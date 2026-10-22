#!/usr/bin/env python3
"""
Split the long-format runoff CSV from extract_basin_runoff.py into small
per-basin inputs for the analysis_*.py scripts, and add an area-weighted
total over all basins.

Why: analysis_seasonal_redistribution.py and analysis_dry_year_risk.py assign
Near-future/Far-future without looking at the scenario, so a CSV holding
rcp26 + rcp45 + ssp370 would pool all three into one period. Each output
"<basin>__<scenario>.csv" therefore holds hist + ONE future scenario.
"<basin>__all.csv" holds every scenario, for
analysis_uncertainty_decomposition.py (which separates scenarios itself).

The total series (default name EVANGER_TOTAL) is the area-weighted mean of
mrro_mm over all basins, weights = the `areal_km2` column of the catchment
file (NVE's own areas), so total volume = mean mm/day x summed area.

Also writes areas.csv (basin, area_km2) for the --area-km2 argument.

Usage:
    python split_runoff_csv.py \\
        --runoff-csv .../basin_mrro_full/evanger_basin_mrro.csv \\
        --catchments Evanger_system/evanger_local_subcatchments.gpkg \\
        --out-dir .../projections/input -v
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logger = logging.getLogger("split_runoff_csv")

REFERENCE_SCENARIO = "hist"
CATEGORY_COLUMNS = ["basin", "scenario", "model", "method"]


def load_runoff(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={c: "category" for c in CATEGORY_COLUMNS})


def load_areas(catchments: Path, id_col: str, area_col: str) -> pd.Series:
    gdf = gpd.read_file(catchments)
    return gdf.set_index(id_col)[area_col].astype(float)


def add_total(df: pd.DataFrame, areas: pd.Series, total_name: str) -> pd.DataFrame:
    missing = set(df["basin"].unique()) - set(areas.index)
    if missing:
        raise ValueError(f"No area for basins {sorted(missing)} in the catchment file")
    w = df["basin"].map(areas).astype(float)
    weighted = df.assign(wv=df["mrro_mm"] * w, w=w)
    total = (
        weighted.groupby(["scenario", "model", "method", "date"], observed=True)[["wv", "w"]]
        .sum()
        .reset_index()
    )
    total["mrro_mm"] = total["wv"] / total["w"]
    total["basin"] = total_name
    out = pd.concat(
        [df.astype({"basin": str}), total[["basin", "scenario", "model", "method", "date", "mrro_mm"]]],
        ignore_index=True,
    )
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runoff-csv", type=Path, required=True)
    parser.add_argument("--catchments", type=Path, required=True, help="Catchment file with basin IDs and areas")
    parser.add_argument("--id-col", default="basin")
    parser.add_argument("--area-col", default="areal_km2", help="Area column, km2 (NVE's areal_km2 by default)")
    parser.add_argument("--total-name", default="EVANGER_TOTAL", help="Name of the area-weighted total series")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    df = load_runoff(args.runoff_csv)
    logger.info("Loaded %d rows, %d basins", len(df), df["basin"].nunique())
    areas = load_areas(args.catchments, args.id_col, args.area_col)
    df = add_total(df, areas, args.total_name)

    area_table = areas.rename("area_km2").rename_axis("basin").reset_index()
    area_table = pd.concat(
        [area_table, pd.DataFrame({"basin": [args.total_name], "area_km2": [areas.sum()]})], ignore_index=True
    )
    area_table.to_csv(args.out_dir / "areas.csv", index=False)
    logger.info("Total area %.1f km2 -> %s", areas.sum(), args.out_dir / "areas.csv")

    futures = sorted(s for s in df["scenario"].unique() if s != REFERENCE_SCENARIO)
    for basin, g in df.groupby("basin", observed=True):
        g.to_csv(args.out_dir / f"{basin}__all.csv", index=False)
        hist = g[g["scenario"] == REFERENCE_SCENARIO]
        for scen in futures:
            pd.concat([hist, g[g["scenario"] == scen]]).to_csv(args.out_dir / f"{basin}__{scen}.csv", index=False)
        logger.info("Wrote %s (all + %s)", basin, ", ".join(futures))


if __name__ == "__main__":
    main()
