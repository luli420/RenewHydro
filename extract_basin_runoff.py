#!/usr/bin/env python3
"""
Extract basin-averaged KiN2025 mrro (runoff) daily time series for one basin
polygon, from a LOCAL copy of the archive already staged on disk (as
produced by download_mrro_full_archive.sh) -- no OPeNDAP/network access
needed at run time.

Test case: Evangervatn (Bulken/Evanger intake), on Olivia:
    python extract_basin_runoff.py \\
        --catchments /cluster/work/projects/nn10014k/luli/evangervatn/zipfolder/NedbfeltF_v4.shp \\
        --basin-name Evangervatn \\
        --archive-dir /cluster/work/projects/nn10014k/luli/kin2025 \\
        --out-dir /cluster/work/projects/nn10014k/luli/evangervatn/basin_mrro/

This is the single/few-basin counterpart of the full NVE-delfelt pipeline
(fetch_nve_subcatchments.py -> build_weight_matrix.py ->
extract_layer1_timeseries.py -> merge_layer1_outputs.py) for cases where
you already have your own basin shapefile rather than NVE's delfelt layer.
It reuses that pipeline's tested building blocks (build_weight_matrix's
sparse-coverage-weight computation, extract_layer1_timeseries's per-member
extraction loop) rather than reimplementing them -- see CLAUDE.md.

Per handoff notes' "test sequence before the full run": start with a
narrow --scenarios/--methods/--models filter (e.g. one hist member) to
confirm the mrro units attribute, weight mask, and output look right
before running the full ensemble. This has NOT been executed against real
data in this session (no Olivia/filesystem access) -- verify each of those
checks on the real archive.

Output: one long-format CSV under --out-dir with columns
(basin, scenario, model, method, date, mrro_mm), plus the computed weight
matrix (for the "plot the mask" sanity check) under --out-dir/weights/.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import scipy.sparse as sp
import xarray as xr

from build_weight_matrix import build_weight_matrix, get_grid_crs, get_transform
from extract_layer1_timeseries import extract_member
from kin2025_config import SCENARIOS, scenario_member_combos

logger = logging.getLogger("extract_basin_runoff")

GRID_INDEX_BUFFER_CELLS = 5  # pad the auto-detected window around the basin, in grid cells


# ---------------------------------------------------------------------------
# Basin polygon loading
# ---------------------------------------------------------------------------


def load_basin(catchments_path: Path, id_col: str | None, basin_name: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(catchments_path)
    if gdf.crs is None:
        raise ValueError(f"{catchments_path} has no CRS set")

    if id_col and id_col in gdf.columns:
        out = gdf[[id_col, "geometry"]].rename(columns={id_col: "basin"})
        out["basin"] = out["basin"].astype(str)
        return out

    # No usable id column (or none given): treat the whole file as one basin,
    # dissolving multi-part shapefiles into a single polygon/multipolygon.
    dissolved = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.unary_union
    return gpd.GeoDataFrame({"basin": [basin_name]}, geometry=[dissolved], crs=gdf.crs)


# ---------------------------------------------------------------------------
# Grid window auto-detection (avoid reading the full ~1195x1550 Norway grid)
# ---------------------------------------------------------------------------


def find_sample_file(archive_dir: Path, method: str | None, scenario: str | None, model: str | None) -> tuple[str, str, str, Path]:
    """Return (method, scenario, model, path) for one file to inspect the
    grid from -- either the requested combo, or the first one found on disk."""
    if method and scenario and model:
        year0 = SCENARIOS[scenario][1]
        candidate = archive_dir / method / scenario / model / f"{model}_{scenario}_{method}-estobs_disthbv_norway_1km_mrro_daily_{year0}.nc4"
        if candidate.exists():
            return method, scenario, model, candidate
        logger.warning("Requested sample file not found (%s); searching archive-dir for any file instead", candidate)

    matches = sorted(archive_dir.glob("*/*/*/*.nc4"))
    if not matches:
        raise FileNotFoundError(f"No .nc4 files found anywhere under {archive_dir}")
    path = matches[0]
    found_method, found_scenario, found_model = path.parts[-4], path.parts[-3], path.parts[-2]
    logger.info("Using discovered sample file: %s", path)
    return found_method, found_scenario, found_model, path


def find_grid_window(ds: xr.Dataset, basin_geom_wgs84, crs, buffer_cells: int = GRID_INDEX_BUFFER_CELLS) -> tuple[slice, slice]:
    """Locate the Yc/Xc index window (+ buffer) covering the basin's bounds.

    Prefers the file's own projected X/Y coordinate variables if present.
    Otherwise -- the layout CONFIRMED on the real archive on Olivia: only
    Xc/Yc index dims plus 2D lon/lat auxiliary coordinates, no projected
    X/Y -- masks directly on lon/lat against the basin's bounds in WGS84."""
    ny_full = ds.sizes["Yc"]
    nx_full = ds.sizes["Xc"]

    x_name = next((n for n in ("X", "x") if n in ds.variables), None)
    y_name = next((n for n in ("Y", "y") if n in ds.variables), None)
    if x_name is not None and y_name is not None:
        x = ds[x_name].values
        y = ds[y_name].values
        x1d = x[0, :] if x.ndim == 2 else x
        y1d = y[:, 0] if y.ndim == 2 else y
        minx, miny, maxx, maxy = gpd.GeoSeries([basin_geom_wgs84], crs="EPSG:4326").to_crs(crs).iloc[0].bounds
        xc_idx = np.where((x1d >= minx) & (x1d <= maxx))[0]
        yc_idx = np.where((y1d >= miny) & (y1d <= maxy))[0]
    else:
        lat_name = next((n for n in ("lat", "latitude") if n in ds.variables), None)
        lon_name = next((n for n in ("lon", "longitude") if n in ds.variables), None)
        if lat_name is None or lon_name is None:
            raise KeyError(
                "Could not find projected X/Y or 2D lon/lat coordinate variables in the "
                f"sample file needed to locate the basin on the grid. Available variables: {list(ds.variables)}"
            )
        lat = ds[lat_name].values
        lon = ds[lon_name].values
        minx, miny, maxx, maxy = basin_geom_wgs84.bounds
        mask = (lat >= miny) & (lat <= maxy) & (lon >= minx) & (lon <= maxx)
        if not mask.any():
            raise ValueError(
                "Basin bounding box does not overlap the grid's lon/lat coordinates -- "
                "check the basin shapefile's CRS/extent against the sample file."
            )
        yc_idx, xc_idx = np.where(mask)

    if xc_idx.size == 0 or yc_idx.size == 0:
        raise ValueError(
            "Basin bounding box does not overlap the grid -- "
            "check the basin shapefile's CRS/extent against the sample file."
        )

    xc_slice = slice(max(int(xc_idx.min()) - buffer_cells, 0), min(int(xc_idx.max()) + 1 + buffer_cells, nx_full))
    yc_slice = slice(max(int(yc_idx.min()) - buffer_cells, 0), min(int(yc_idx.max()) + 1 + buffer_cells, ny_full))
    logger.info("Grid window: Yc %s, Xc %s (%d x %d cells)", yc_slice, xc_slice, yc_slice.stop - yc_slice.start, xc_slice.stop - xc_slice.start)
    return yc_slice, xc_slice


def build_local_weights(basin_gdf: gpd.GeoDataFrame, sample_path: Path, buffer_cells: int) -> tuple[sp.csr_matrix, dict]:
    ds = xr.open_dataset(sample_path)
    var = "mrro"
    crs = get_grid_crs(ds, var)
    basin_proj = basin_gdf if basin_gdf.crs == crs else basin_gdf.to_crs(crs)
    basin_wgs84 = basin_gdf.to_crs("EPSG:4326")

    combined_geom_wgs84 = basin_wgs84.geometry.union_all() if hasattr(basin_wgs84.geometry, "union_all") else basin_wgs84.unary_union
    yc_slice, xc_slice = find_grid_window(ds, combined_geom_wgs84, crs, buffer_cells)
    transform = get_transform(ds, yc_slice, xc_slice, crs)
    shape = (yc_slice.stop - yc_slice.start, xc_slice.stop - xc_slice.start)

    W, coverage_method = build_weight_matrix(basin_proj, shape, transform, crs)
    meta = {
        "id_col": "basin",
        "delfelt_ids": basin_proj["basin"].tolist(),
        "grid_shape": list(shape),
        "yc_slice": [yc_slice.start, yc_slice.stop],
        "xc_slice": [xc_slice.start, xc_slice.stop],
        "crs": crs.to_string(),
        "transform": list(transform)[:6],
        "coverage_method": coverage_method,
    }
    return W, meta


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(
    catchments_path: Path,
    id_col: str | None,
    basin_name: str,
    archive_dir: Path,
    out_dir: Path,
    scenarios: list[str],
    methods: list[str],
    models: list[str] | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    weights_dir = out_dir / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)

    basin_gdf = load_basin(catchments_path, id_col, basin_name)
    logger.info("Loaded %d basin(s): %s", len(basin_gdf), basin_gdf["basin"].tolist())

    sample_method, sample_scenario, sample_model, sample_path = find_sample_file(archive_dir, None, None, None)
    W, meta = build_local_weights(basin_gdf, sample_path, GRID_INDEX_BUFFER_CELLS)

    sp.save_npz(weights_dir / "basin_weights.npz", W)
    (weights_dir / "basin_weights.json").write_text(json.dumps(meta, indent=2))
    logger.info("Wrote weight matrix + metadata to %s (coverage_method=%s) -- plot this mask before trusting extraction", weights_dir, meta["coverage_method"])

    combos = [
        (scenario, member)
        for scenario, member in scenario_member_combos()
        if scenario in scenarios
        and member.method in methods
        and (models is None or member.model in models)
    ]
    logger.info("Processing %d (scenario, member) combinations", len(combos))

    all_frames: list[pd.DataFrame] = []
    for scenario, member in combos:
        member_dir = archive_dir / member.method / scenario / member.model
        if not member_dir.exists():
            logger.warning("Skipping %s/%s/%s -- not found under %s", member.method, scenario, member.model, archive_dir)
            continue

        ds_out = extract_member(
            method=member.method,
            model=member.model,
            scenario=scenario,
            W=W,
            meta=meta,
            local_dir=archive_dir,
            opendap_base="",  # unused when local_dir is set
        )
        df = ds_out["mrro"].to_dataframe(name="mrro_mm").reset_index()
        df = df.rename(columns={"delfelt": "basin", "time": "date"})
        df["scenario"] = scenario
        df["model"] = member.model
        df["method"] = member.method
        all_frames.append(df[["basin", "scenario", "model", "method", "date", "mrro_mm"]])

    if not all_frames:
        raise RuntimeError("No (scenario, member) combinations produced output -- check --archive-dir and filters")

    combined = pd.concat(all_frames, ignore_index=True)
    out_csv = out_dir / f"{basin_name.lower()}_basin_mrro.csv"
    combined.to_csv(out_csv, index=False)
    logger.info("Wrote %s (%d rows)", out_csv, len(combined))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catchments", type=Path, required=True, help="Basin shapefile/GeoPackage")
    parser.add_argument("--id-col", default=None, help="Column to use as basin ID; omit to dissolve the whole file into one basin")
    parser.add_argument("--basin-name", default="Evangervatn", help="Basin name used when --id-col is omitted, and for the output filename")
    parser.add_argument("--archive-dir", type=Path, required=True, help="Local KiN2025 archive root (method/scenario/model/*.nc4 layout)")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS.keys()), choices=list(SCENARIOS.keys()))
    parser.add_argument("--methods", nargs="+", default=["eqm", "3dbc-eqm"], choices=["eqm", "3dbc-eqm"])
    parser.add_argument("--models", nargs="+", default=None, help="Restrict to specific GCM-RCM model IDs; omit for all available")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    run(
        catchments_path=args.catchments,
        id_col=args.id_col,
        basin_name=args.basin_name,
        archive_dir=args.archive_dir,
        out_dir=args.out_dir,
        scenarios=args.scenarios,
        methods=args.methods,
        models=args.models,
    )


if __name__ == "__main__":
    main()
