#!/usr/bin/env python3
"""
Merge per-catchment NVE Nedbørfelt shapefiles (one polygon each, one folder
per catchment) into a single GeoPackage with a `basin` ID column, so that
extract_basin_runoff.py can extract every catchment in ONE pass over the
archive (`--id-col basin`) instead of one pass per shapefile.

Expected layout (as exported from NVE, e.g. Evanger_system/ on Olivia):
    <root>/<NN_name>/_ags_data*/zipfolder/NedbfeltF_v4.shp
The `basin` ID is the catchment folder name (<NN_name>). `_ags_data*` also
matches folders such as `12_eitro/_ags_data1/`.

Example (Evanger, 21 local sub-catchments, excluding the larger -nevina
upstream variants of 03/12/15 -- decision of 2026-10-05, see CLAUDE.md):
    python merge_catchment_shapefiles.py \\
        --root Evanger_system \\
        --exclude 'nevina$' \\
        --out Evanger_system/evanger_local_subcatchments.gpkg -v
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

logger = logging.getLogger("merge_catchment_shapefiles")

SHAPEFILE_GLOB = "*/_ags_data*/zipfolder/NedbfeltF_v4.shp"
KEEP_COLUMNS = ["vassdragNr", "areal_km2"]  # NVE attributes worth carrying along for sanity checks


def find_shapefiles(root: Path, pattern: str, exclude: list[str]) -> dict[str, Path]:
    """Return {basin_id: shapefile_path}, keyed by the catchment folder name."""
    found: dict[str, Path] = {}
    for path in sorted(root.glob(pattern)):
        basin_id = path.relative_to(root).parts[0]
        if any(re.search(rx, basin_id) for rx in exclude):
            logger.info("Excluding %s (matches --exclude)", basin_id)
            continue
        if basin_id in found:
            raise ValueError(f"More than one shapefile for {basin_id}: {found[basin_id]} and {path}")
        found[basin_id] = path
    return found


def merge_shapefiles(shapefiles: dict[str, Path]) -> gpd.GeoDataFrame:
    frames = []
    target_crs = None
    for basin_id, path in shapefiles.items():
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise ValueError(f"{path} has no CRS set")
        if target_crs is None:
            target_crs = gdf.crs
        elif gdf.crs != target_crs:
            logger.warning("%s has CRS %s; reprojecting to %s", basin_id, gdf.crs, target_crs)
            gdf = gdf.to_crs(target_crs)
        if len(gdf) != 1:
            logger.warning("%s has %d polygons; dissolving them into one", basin_id, len(gdf))
            gdf = gdf.dissolve()
        gdf = gdf[[c for c in KEEP_COLUMNS if c in gdf.columns] + ["geometry"]].copy()
        gdf.insert(0, "basin", basin_id)
        frames.append(gdf)
    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=target_crs)
    merged["area_km2_geom"] = merged.geometry.area / 1e6 if merged.crs.is_projected else float("nan")
    return merged


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="Folder holding one sub-folder per catchment")
    parser.add_argument("--pattern", default=SHAPEFILE_GLOB, help=f"Glob under --root (default: {SHAPEFILE_GLOB})")
    parser.add_argument("--exclude", nargs="*", default=[], help="Regexes; catchment folders matching any are skipped")
    parser.add_argument("--out", type=Path, required=True, help="Output GeoPackage")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    shapefiles = find_shapefiles(args.root, args.pattern, args.exclude)
    if not shapefiles:
        raise FileNotFoundError(f"No shapefiles matching {args.pattern} under {args.root}")
    logger.info("Found %d catchment shapefiles", len(shapefiles))

    merged = merge_shapefiles(shapefiles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_file(args.out, driver="GPKG", layer="catchments")

    for row in merged.itertuples():
        logger.info("%-28s NVE %s km2, geometry %.2f km2", row.basin, getattr(row, "areal_km2", "?"), row.area_km2_geom)
    overlap = merged.geometry.union_all().area if hasattr(merged.geometry, "union_all") else merged.unary_union.area
    logger.info(
        "Wrote %s: %d basins, CRS %s, summed area %.1f km2, union area %.1f km2 (a large difference means overlapping polygons)",
        args.out, len(merged), merged.crs.to_string(), merged.geometry.area.sum() / 1e6, overlap / 1e6,
    )


if __name__ == "__main__":
    main()
