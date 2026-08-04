#!/usr/bin/env python3
"""
DEPRECATED: superseded by the delfelt-based pipeline (fetch_nve_subcatchments.py
-> build_weight_matrix.py -> extract_layer1_timeseries.py -> merge_layer1_outputs.py
-> mrro_to_gwh.py). Kept for reference only; not part of the active pipeline.
See CLAUDE.md "History" for why (NVE's own oppstromDelfeltListe topology replaces
the containment-differencing this script does, and the OPeNDAP path this script
guesses at is now confirmed to be the DailyTimeSeries/mrro path used elsewhere).

Extract projected runoff (mrro) for Evanger hydropower subcatchments from the
NCCS "Klima i Norge 2025" (KiN2025) dataset (Dyrrdal et al. 2025, NVE + MET
Norway), served as gridded NetCDF-CF on thredds.met.no.

Reads NEVINA-delineated catchment polygons (one per node: Bulken intake dam,
each Inntakspunkt, tributary junctions, downstream outlet), pulls the
1991-2020 reference mrro grid plus the projected diff-mrro grids (per RCP /
GCM-RCM member, 2041-2070 and 2071-2100), and computes area-weighted
zonal statistics per node.

NEVINA polygons are *accumulated* (total upstream) catchments, so nodes
nest automatically. Local/incremental (delfelt) subcatchments are derived
here purely by polygon-containment differencing -- no manual topology input
is required.

IMPORTANT -- open items not resolved in this script (see CLAUDE.md):
  * The exact OPeNDAP path/token for ReferenceIndices/mrro30plt and the
    variable names in both files have not yet been verified against the
    live catalog from this environment (network to thredds.met.no was not
    reachable when this script was written). Verify with `print(ds)` on
    Olivia before trusting output, and adjust the *_CANDIDATES lists below
    if needed.
  * This script computes NATURAL (unregulated) runoff only. The Bulken
    node's regulated flow (post Evanger-intake diversion) is not in the
    grid and is deliberately out of scope here -- see CLAUDE.md for the
    two proposed approaches.

Usage:
    python extract_evanger_runoff.py \\
        --catchments evanger_nevina_catchments.gpkg \\
        --rcps rcp26 rcp45 rcp85 \\
        --members ensemble-mean \\
        --out-dir output/

Outputs (in --out-dir):
    evanger_runoff_nodes.csv  -- accumulated (total upstream) runoff per node
    evanger_runoff_local.csv  -- incremental (local/delfelt) runoff per
                                  subcatchment
Both are long-format: node, rcp, member, period, mrro_mm, area_km2,
volume_Mm3.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray  # noqa: F401 -- registers the .rio accessor on xarray objects
import xarray as xr
from pyproj import CRS
from shapely.ops import unary_union

logger = logging.getLogger("extract_evanger_runoff")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENDAP_BASE_DEFAULT = "https://thredds.met.no/thredds/dodsC/nve/kin2025"

# Candidate relative paths for the 1991-2020 reference mrro grid, tried in
# order. Confirm the real one against the live THREDDS catalog and trim
# this list -- see CLAUDE.md item "Confirm OPeNDAP paths".
REFERENCE_MRRO_CANDIDATES = [
    "ReferenceIndices/mrro30plt/reference_1991-2020_disthbv_norway_1km_mrro30plt.nc",
]

# Template for the projected change (diff-mrro) grid. {member} is e.g.
# "ensemble-mean" or a specific GCM-RCM identifier; {rcp} is rcp26/45/85.
DIFF_MRRO_TEMPLATE = (
    "ClimateStatistics/diff-mrro/{member}_{rcp}_both-bc-estobs_disthbv_norway_1km_diff-mrro.nc"
)

# Candidate variable names inside each file, tried in order.
REFERENCE_VAR_CANDIDATES = ["mrro", "mrro30plt"]
DIFF_VAR_CANDIDATES = ["diff_mrro", "mrro", "mrro_diff"]

# Fallback CRS if a file's grid_mapping variable is missing or unparseable.
GRID_CRS_FALLBACK = "EPSG:25833"  # KliNoGrid/seNorge, UTM33N

RCPS_DEFAULT = ["rcp26", "rcp45", "rcp85"]
MEMBERS_DEFAULT = ["ensemble-mean"]

# Order of the 2 time steps in each diff-mrro file. Verify against the
# file's actual time/period coordinate before trusting this ordering.
PERIOD_LABELS = ["2041-2070", "2071-2100"]
REFERENCE_PERIOD_LABEL = "1991-2020"

# Nodes whose total-upstream catchment area is considered "the same" for
# containment purposes despite small boundary snapping differences between
# separately-delineated NEVINA polygons.
CONTAINMENT_AREA_FRACTION = 0.98


# ---------------------------------------------------------------------------
# OPeNDAP access
# ---------------------------------------------------------------------------


def open_opendap(url: str) -> xr.Dataset:
    """Open a remote NetCDF-CF dataset via OPeNDAP, trying a couple of engines."""
    last_exc: Exception | None = None
    for engine in ("netcdf4", "pydap"):
        try:
            logger.debug("Opening %s with engine=%s", url, engine)
            return xr.open_dataset(url, engine=engine, decode_cf=True)
        except Exception as exc:  # noqa: BLE001 - want to try the next engine
            logger.debug("engine=%s failed for %s: %s", engine, url, exc)
            last_exc = exc
    raise RuntimeError(f"Could not open OPeNDAP dataset: {url}") from last_exc


def _open_first_available(base: str, candidates: list[str]) -> tuple[xr.Dataset, str]:
    last_exc: Exception | None = None
    for rel_path in candidates:
        url = f"{base.rstrip('/')}/{rel_path}"
        try:
            return open_opendap(url), url
        except Exception as exc:  # noqa: BLE001
            logger.warning("Candidate path failed: %s (%s)", url, exc)
            last_exc = exc
    raise RuntimeError(
        f"None of the candidate paths could be opened under {base}: {candidates}"
    ) from last_exc


def _pick_var(ds: xr.Dataset, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.variables:
            return name
    raise KeyError(
        f"None of the candidate variable names {candidates} found in dataset. "
        f"Available variables: {list(ds.data_vars)}"
    )


def get_grid_crs(ds: xr.Dataset, var_name: str) -> CRS:
    """Read the CRS from a variable's CF grid_mapping attribute, falling back
    to the known KliNoGrid/seNorge UTM33N CRS if it can't be determined."""
    grid_mapping_name = ds[var_name].attrs.get("grid_mapping")
    if grid_mapping_name and grid_mapping_name in ds.variables:
        try:
            return CRS.from_cf(ds[grid_mapping_name].attrs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse grid_mapping '%s': %s", grid_mapping_name, exc)
    logger.warning(
        "No usable grid_mapping on '%s'; falling back to %s", var_name, GRID_CRS_FALLBACK
    )
    return CRS.from_user_input(GRID_CRS_FALLBACK)


@dataclass
class GridLayer:
    """A single 2D (y, x) field plus the CRS it's defined in."""

    data: xr.DataArray
    crs: CRS


def load_reference_mrro(base: str) -> GridLayer:
    ds, url = _open_first_available(base, REFERENCE_MRRO_CANDIDATES)
    logger.info("Loaded reference mrro from %s", url)
    var = _pick_var(ds, REFERENCE_VAR_CANDIDATES)
    da = ds[var]
    if "time" in da.dims:
        da = da.isel(time=0, drop=True)
    crs = get_grid_crs(ds, var)
    return GridLayer(data=da, crs=crs)


def load_diff_mrro(base: str, member: str, rcp: str) -> tuple[GridLayer, GridLayer]:
    """Return the two (t0, t1) diff-mrro layers for a given member/rcp."""
    rel_path = DIFF_MRRO_TEMPLATE.format(member=member, rcp=rcp)
    url = f"{base.rstrip('/')}/{rel_path}"
    ds = open_opendap(url)
    logger.info("Loaded diff-mrro from %s", url)
    var = _pick_var(ds, DIFF_VAR_CANDIDATES)
    da = ds[var]

    time_dim = next((d for d in da.dims if d not in ("y", "x")), None)
    if time_dim is None or da.sizes[time_dim] != 2:
        raise ValueError(
            f"Expected a length-2 time-like dimension in diff-mrro variable '{var}' "
            f"(dims={da.dims}); got {dict(da.sizes)}. Verify the file structure."
        )

    crs = get_grid_crs(ds, var)
    t0 = GridLayer(data=da.isel({time_dim: 0}, drop=True), crs=crs)
    t1 = GridLayer(data=da.isel({time_dim: 1}, drop=True), crs=crs)
    return t0, t1


def future_mrro(reference: GridLayer, diff: GridLayer) -> GridLayer:
    """future runoff (mm) = reference mrro + diff-mrro, on the reference grid."""
    combined = reference.data + diff.data.reindex_like(reference.data, method=None)
    return GridLayer(data=combined, crs=reference.crs)


# ---------------------------------------------------------------------------
# Catchment topology: derive local (delfelt) subcatchments from accumulated
# NEVINA polygons purely by geometric containment.
# ---------------------------------------------------------------------------


def load_catchments(gpkg_path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(gpkg_path)
    if "node" not in gdf.columns:
        raise ValueError(f"Expected a 'node' column in {gpkg_path}, got {list(gdf.columns)}")
    if gdf.crs is None:
        raise ValueError(f"{gpkg_path} has no CRS set")
    return gdf


def derive_containment(
    gdf: gpd.GeoDataFrame, area_fraction: float = CONTAINMENT_AREA_FRACTION
) -> dict[str, list[str]]:
    """For each node, list every other node whose total catchment lies
    (almost entirely) inside it -- i.e. every upstream node, not just the
    immediate ones."""
    contains: dict[str, list[str]] = {node: [] for node in gdf["node"]}
    for _, row_i in gdf.iterrows():
        for _, row_j in gdf.iterrows():
            if row_i["node"] == row_j["node"]:
                continue
            area_j = row_j.geometry.area
            if area_j <= 0:
                continue
            inter_area = row_i.geometry.intersection(row_j.geometry).area
            if inter_area / area_j >= area_fraction:
                contains[row_i["node"]].append(row_j["node"])
    return contains


def derive_immediate_children(contains: dict[str, list[str]]) -> dict[str, list[str]]:
    """Reduce each node's full upstream set down to its immediate children
    (drop anything that's also upstream of one of its own siblings)."""
    immediate: dict[str, list[str]] = {}
    for node, contained in contains.items():
        contained_set = set(contained)
        direct = set(contained_set)
        for other in contained_set:
            direct -= set(contains.get(other, [])) & contained_set
        immediate[node] = sorted(direct)
    return immediate


def derive_local_geometries(
    gdf: gpd.GeoDataFrame, immediate_children: dict[str, list[str]]
) -> gpd.GeoDataFrame:
    """local(node) = total_catchment(node) - union(total_catchment(child) for
    each immediate upstream child)."""
    geom_by_node = dict(zip(gdf["node"], gdf.geometry))
    local_geoms = {}
    for node, geom in geom_by_node.items():
        children = immediate_children.get(node, [])
        if children:
            child_union = unary_union([geom_by_node[c] for c in children])
            local_geoms[node] = geom.difference(child_union)
        else:
            local_geoms[node] = geom
    local_gdf = gdf.copy()
    local_gdf["geometry"] = local_gdf["node"].map(local_geoms)
    return local_gdf


# ---------------------------------------------------------------------------
# Zonal statistics
# ---------------------------------------------------------------------------


def zonal_mean_mm(layer: GridLayer, gdf: gpd.GeoDataFrame) -> pd.Series:
    """Area-weighted mean of a gridded mm field over each polygon, using
    exactextract for correct partial-cell coverage weighting."""
    from exactextract import exact_extract

    da = layer.data.rio.write_crs(layer.crs, inplace=False)
    gdf_proj = gdf if gdf.crs == layer.crs else gdf.to_crs(layer.crs)

    result = exact_extract(da, gdf_proj, ["mean"], include_cols=["node"], output="pandas")
    result = result.set_index("node")["mean"]
    return result.reindex(gdf["node"])


def area_km2(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Polygon area in km^2, computed in the (already-projected, UTM33N)
    CRS of the input GeoDataFrame. UTM distortion at this regional scale is
    small and consistent with the grid's own CRS."""
    areas = gdf.set_index("node").geometry.area / 1e6
    return areas


def volume_Mm3(mrro_mm: pd.Series, area_km2_: pd.Series) -> pd.Series:
    # 1 mm over 1 km^2 = 1000 m^3 = 0.001 Mm^3
    return mrro_mm * area_km2_ / 1000.0


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(
    catchments_path: Path,
    rcps: list[str],
    members: list[str],
    opendap_base: str,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes_gdf = load_catchments(catchments_path)
    containment = derive_containment(nodes_gdf)
    immediate_children = derive_immediate_children(containment)
    local_gdf = derive_local_geometries(nodes_gdf, immediate_children)

    node_area = area_km2(nodes_gdf)
    local_area = area_km2(local_gdf)

    reference = load_reference_mrro(opendap_base)

    accumulated_rows: list[dict] = []
    local_rows: list[dict] = []

    def _add_rows(layer: GridLayer, rcp: str, member: str, period: str) -> None:
        acc_mm = zonal_mean_mm(layer, nodes_gdf)
        loc_mm = zonal_mean_mm(layer, local_gdf)
        for node in nodes_gdf["node"]:
            accumulated_rows.append(
                {
                    "node": node,
                    "rcp": rcp,
                    "member": member,
                    "period": period,
                    "mrro_mm": acc_mm.get(node, np.nan),
                    "area_km2": node_area.get(node, np.nan),
                    "volume_Mm3": volume_Mm3(acc_mm, node_area).get(node, np.nan),
                }
            )
            local_rows.append(
                {
                    "node": node,
                    "rcp": rcp,
                    "member": member,
                    "period": period,
                    "mrro_mm": loc_mm.get(node, np.nan),
                    "area_km2": local_area.get(node, np.nan),
                    "volume_Mm3": volume_Mm3(loc_mm, local_area).get(node, np.nan),
                }
            )

    # Reference baseline (1991-2020), same for every rcp/member.
    _add_rows(reference, rcp="reference", member="reference", period=REFERENCE_PERIOD_LABEL)

    for rcp in rcps:
        for member in members:
            logger.info("Processing member=%s rcp=%s", member, rcp)
            t0, t1 = load_diff_mrro(opendap_base, member=member, rcp=rcp)
            for diff_layer, period_label in zip((t0, t1), PERIOD_LABELS):
                fut = future_mrro(reference, diff_layer)
                _add_rows(fut, rcp=rcp, member=member, period=period_label)

    accumulated_df = pd.DataFrame(accumulated_rows)
    local_df = pd.DataFrame(local_rows)

    accumulated_out = out_dir / "evanger_runoff_nodes.csv"
    local_out = out_dir / "evanger_runoff_local.csv"
    accumulated_df.to_csv(accumulated_out, index=False)
    local_df.to_csv(local_out, index=False)
    logger.info("Wrote %s and %s", accumulated_out, local_out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--catchments",
        type=Path,
        required=True,
        help="Path to evanger_nevina_catchments.gpkg (must have a 'node' column)",
    )
    parser.add_argument("--rcps", nargs="+", default=RCPS_DEFAULT, help="RCP scenarios to process")
    parser.add_argument(
        "--members", nargs="+", default=MEMBERS_DEFAULT, help="GCM-RCM members (or 'ensemble-mean')"
    )
    parser.add_argument("--opendap-base", default=OPENDAP_BASE_DEFAULT, help="THREDDS OPeNDAP base URL")
    parser.add_argument("--out-dir", type=Path, default=Path("output"), help="Output directory for CSVs")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run(
        catchments_path=args.catchments,
        rcps=args.rcps,
        members=args.members,
        opendap_base=args.opendap_base,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
