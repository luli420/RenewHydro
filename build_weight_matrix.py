#!/usr/bin/env python3
"""
Precompute the sparse area-weight matrix W (n_delfelt x n_cells) used to
turn a flattened daily mrro grid into per-delfelt area-weighted means via a
single matrix multiply, instead of re-running zonal stats on every one of
the ~47,500 daily timesteps in the archive (see handoff notes §6).

W is built ONCE from the delfelt polygons and reused for every
(scenario, member, year) file in extract_layer1_timeseries.py -- the
polygon geometry is never touched again after this step.

Two ways of computing fractional cell coverage per polygon are provided:

  1. exactextract's per-cell "cell_id"/"coverage" output (preferred: exact
     partial-cell weighting). The precise output schema depends on the
     installed exactextract version and has NOT been verified in this
     sandbox (no network to test against real data) -- if it doesn't match,
     this path raises and falls back to (2).
  2. A supersampled `rasterio.features.rasterize` fallback (10x oversample
     by default, block-averaged down to grid resolution). Always works,
     slightly approximate for the smallest polygons -- fine per handoff
     notes ("centroid-in-polygon ... can be off by ~10% for small [basins];
     exactextract is cleanest" -- 10x supersampling is much finer than
     centroid-in-polygon).

IMPORTANT: per handoff notes §6 "Test sequence before launching the array",
plot the resulting mask for at least one delfelt and confirm it lands on
the right cells before trusting W in the full extraction run.

Usage:
    python build_weight_matrix.py \\
        --catchments delfelt_subcatchments.gpkg \\
        --sample-method eqm --sample-model cnrm-r1i1p1-aladin \\
        --sample-scenario hist --sample-year 1991 \\
        --yc-slice 1165 1291 --xc-slice 45 176 \\
        --out weights/delfelt_weights.npz
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import scipy.sparse as sp
import xarray as xr
from affine import Affine
from pyproj import CRS, Transformer

from kin2025_config import OPENDAP_BASE, build_url

logger = logging.getLogger("build_weight_matrix")

GRID_CRS_FALLBACK = "EPSG:25833"


def get_grid_crs(ds: xr.Dataset, var_name: str) -> CRS:
    grid_mapping_name = ds[var_name].attrs.get("grid_mapping")
    if grid_mapping_name and grid_mapping_name in ds.variables:
        try:
            return CRS.from_cf(ds[grid_mapping_name].attrs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse grid_mapping '%s': %s", grid_mapping_name, exc)
    logger.warning("No usable grid_mapping on '%s'; falling back to %s", var_name, GRID_CRS_FALLBACK)
    return CRS.from_user_input(GRID_CRS_FALLBACK)


def get_transform(ds: xr.Dataset, yc_slice: slice, xc_slice: slice, crs: CRS) -> Affine:
    """Build an affine transform (grid-index -> projected meters) for the
    sliced region.

    Prefers the file's own projected X/Y coordinate variables if present.
    Otherwise -- the layout CONFIRMED on the real archive on Olivia: only
    Xc/Yc index dims plus 2D lon/lat auxiliary coordinates in degrees, no
    projected X/Y -- derive it by reprojecting the sliced lon/lat window
    into `crs` and reading off the (regular UTM grid) spacing."""
    x_name = next((n for n in ("X", "x") if n in ds.variables), None)
    y_name = next((n for n in ("Y", "y") if n in ds.variables), None)
    if x_name is not None and y_name is not None:
        x = ds[x_name].values
        y = ds[y_name].values
        if x.ndim == 2:  # some seNorge files carry X/Y as 2D fields matching (Yc, Xc)
            x = x[0, xc_slice]
            y = y[yc_slice, 0]
        else:
            x = x[xc_slice]
            y = y[yc_slice]
        res_x = float(np.median(np.diff(x)))
        res_y = float(np.median(np.diff(y)))
        return Affine.translation(x[0] - res_x / 2, y[0] - res_y / 2) * Affine.scale(res_x, res_y)

    lat_name = next((n for n in ("lat", "latitude") if n in ds.variables), None)
    lon_name = next((n for n in ("lon", "longitude") if n in ds.variables), None)
    if lat_name is None or lon_name is None:
        raise KeyError(
            "Could not find projected X/Y or 2D lon/lat coordinate variables needed to "
            f"build an affine transform. Available variables: {list(ds.variables)}"
        )
    lat = ds[lat_name].values[yc_slice, xc_slice]
    lon = ds[lon_name].values[yc_slice, xc_slice]
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x_proj, y_proj = transformer.transform(lon, lat)
    x1d = x_proj[0, :]
    y1d = y_proj[:, 0]
    res_x = float(np.median(np.diff(x1d)))
    res_y = float(np.median(np.diff(y1d)))
    return Affine.translation(x1d[0] - res_x / 2, y1d[0] - res_y / 2) * Affine.scale(res_x, res_y)


def open_sample_grid(
    method: str, model: str, scenario: str, year: int, yc_slice: slice, xc_slice: slice, base: str
) -> tuple[Affine, CRS, tuple[int, int]]:
    url, _ = build_url(method=method, scenario=scenario, model=model, year=year, base=base)
    logger.info("Opening sample grid %s", url)
    ds = xr.open_dataset(url)
    var = "mrro"
    crs = get_grid_crs(ds, var)
    transform = get_transform(ds, yc_slice, xc_slice, crs)
    shape = (yc_slice.stop - yc_slice.start, xc_slice.stop - xc_slice.start)
    return transform, crs, shape


# ---------------------------------------------------------------------------
# Weight computation
# ---------------------------------------------------------------------------


def _weights_via_exactextract(
    gdf: gpd.GeoDataFrame, shape: tuple[int, int], transform: Affine, crs: CRS
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    import rioxarray  # noqa: F401 -- registers .rio accessor
    from exactextract import exact_extract

    ny, nx = shape
    dummy = xr.DataArray(np.zeros((ny, nx), dtype="float32"), dims=("y", "x"))
    dummy = dummy.rio.write_transform(transform, inplace=False)
    dummy = dummy.rio.write_crs(crs, inplace=False)

    result = exact_extract(dummy, gdf, ["cell_id", "coverage"], output="pandas")

    rows_all, cols_all, vals_all, feat_all = [], [], [], []
    for i, row in enumerate(result.itertuples(index=False)):
        cell_ids = np.asarray(row.cell_id)
        coverage = np.asarray(row.coverage)
        r, c = np.divmod(cell_ids, nx)
        rows_all.append(r)
        cols_all.append(c)
        vals_all.append(coverage)
        feat_all.append(np.full(len(cell_ids), i))

    if not rows_all:
        raise RuntimeError("exactextract returned no per-cell coverage rows")

    return (
        np.concatenate(rows_all),
        np.concatenate(cols_all),
        np.concatenate(vals_all),
        np.concatenate(feat_all),
    )


def _weights_via_supersample(
    gdf: gpd.GeoDataFrame, shape: tuple[int, int], transform: Affine, factor: int = 10
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    from rasterio.features import rasterize

    ny, nx = shape
    rows_all, cols_all, vals_all, feat_all = [], [], [], []
    inv_transform = ~transform

    for i, geom in enumerate(gdf.geometry):
        if geom is None or geom.is_empty:
            continue
        minx, miny, maxx, maxy = geom.bounds
        col0f, row0f = inv_transform * (minx, maxy)
        col1f, row1f = inv_transform * (maxx, miny)
        r0 = max(int(np.floor(min(row0f, row1f))) - 1, 0)
        r1 = min(int(np.ceil(max(row0f, row1f))) + 1, ny)
        c0 = max(int(np.floor(min(col0f, col1f))) - 1, 0)
        c1 = min(int(np.ceil(max(col0f, col1f))) + 1, nx)
        if r1 <= r0 or c1 <= c0:
            continue

        window_transform = transform * Affine.translation(c0, r0)
        fine_transform = window_transform * Affine.scale(1.0 / factor, 1.0 / factor)
        fine_shape = ((r1 - r0) * factor, (c1 - c0) * factor)

        mask = rasterize([(geom, 1)], out_shape=fine_shape, transform=fine_transform, fill=0, dtype="uint8")
        frac = mask.reshape(r1 - r0, factor, c1 - c0, factor).mean(axis=(1, 3))
        rr, cc = np.nonzero(frac)
        if rr.size == 0:
            continue
        rows_all.append(rr + r0)
        cols_all.append(cc + c0)
        vals_all.append(frac[rr, cc])
        feat_all.append(np.full(rr.size, i))

    return (
        np.concatenate(rows_all) if rows_all else np.array([], dtype=int),
        np.concatenate(cols_all) if cols_all else np.array([], dtype=int),
        np.concatenate(vals_all) if vals_all else np.array([], dtype=float),
        np.concatenate(feat_all) if feat_all else np.array([], dtype=int),
    )


def build_weight_matrix(
    gdf: gpd.GeoDataFrame, shape: tuple[int, int], transform: Affine, crs: CRS
) -> tuple[sp.csr_matrix, str]:
    ny, nx = shape
    try:
        rows, cols, vals, feat_idx = _weights_via_exactextract(gdf, shape, transform, crs)
        method_used = "exactextract"
    except Exception as exc:  # noqa: BLE001
        logger.warning("exactextract per-cell coverage path failed (%s); using supersampled rasterize", exc)
        rows, cols, vals, feat_idx = _weights_via_supersample(gdf, shape, transform)
        method_used = "supersample"

    n_features = len(gdf)
    W_raw = sp.csr_matrix((vals, (feat_idx, rows * nx + cols)), shape=(n_features, ny * nx))

    row_sums = np.asarray(W_raw.sum(axis=1)).ravel()
    zero_mask = row_sums == 0
    if zero_mask.any():
        logger.warning("%d delfelt have zero grid overlap (outside the sliced region?)", zero_mask.sum())
    safe_sums = np.where(zero_mask, 1.0, row_sums)
    W = sp.diags(1.0 / safe_sums) @ W_raw
    return W.tocsr(), method_used


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catchments", type=Path, required=True, help="delfelt GeoPackage (from fetch_nve_subcatchments.py)")
    parser.add_argument("--id-col", default="delfeltNr")
    parser.add_argument("--sample-method", default="eqm")
    parser.add_argument("--sample-model", default="cnrm-r1i1p1-aladin")
    parser.add_argument("--sample-scenario", default="hist")
    parser.add_argument("--sample-year", type=int, default=1991)
    parser.add_argument("--opendap-base", default=OPENDAP_BASE)
    parser.add_argument("--yc-slice", type=int, nargs=2, required=True, metavar=("START", "STOP"))
    parser.add_argument("--xc-slice", type=int, nargs=2, required=True, metavar=("START", "STOP"))
    parser.add_argument("--out", type=Path, default=Path("weights/delfelt_weights.npz"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    gdf = gpd.read_file(args.catchments)
    if args.id_col not in gdf.columns:
        raise ValueError(f"Expected '{args.id_col}' column in {args.catchments}, got {list(gdf.columns)}")

    yc_slice = slice(*args.yc_slice)
    xc_slice = slice(*args.xc_slice)
    transform, grid_crs, shape = open_sample_grid(
        method=args.sample_method,
        model=args.sample_model,
        scenario=args.sample_scenario,
        year=args.sample_year,
        yc_slice=yc_slice,
        xc_slice=xc_slice,
        base=args.opendap_base,
    )
    gdf_proj = gdf if gdf.crs == grid_crs else gdf.to_crs(grid_crs)

    W, method_used = build_weight_matrix(gdf_proj, shape, transform, grid_crs)
    logger.info("Built %s weight matrix using %s (nnz=%d)", W.shape, method_used, W.nnz)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sp.save_npz(args.out, W)

    meta = {
        "id_col": args.id_col,
        "delfelt_ids": gdf[args.id_col].tolist(),
        "grid_shape": list(shape),
        "yc_slice": list(args.yc_slice),
        "xc_slice": list(args.xc_slice),
        "crs": grid_crs.to_string(),
        "transform": list(transform)[:6],
        "coverage_method": method_used,
    }
    meta_path = args.out.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2))
    logger.info("Wrote %s and %s", args.out, meta_path)


if __name__ == "__main__":
    main()
