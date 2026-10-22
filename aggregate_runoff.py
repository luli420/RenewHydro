#!/usr/bin/env python3
"""
Reduce the daily long-format runoff CSV (extract_basin_runoff.py) to small
tables for interactive analysis (notebooks/evanger_runoff_projections.ipynb):

  monthly.csv   basin, scenario, model, method, year, month, mrro_mm
                (monthly mean of daily runoff, mm/day)
  annual.csv    basin, scenario, model, method, year,
                total_mm        annual sum, mm/yr
                max1d_mm        annual maximum daily runoff, mm/day
                max3d_mm        annual maximum 3-day mean runoff, mm/day
                min7d_summer_mm minimum 7-day mean runoff in Jun-Sep, mm/day
                cov_doy         centre-of-volume day of year (50% of the
                                annual total has passed)
  areas.csv     basin, area_km2 (NVE areal_km2), incl. the total series

Adds the area-weighted total series (default EVANGER_TOTAL), same as
split_runoff_csv.py. No plant-specific numbers are needed: extremes are
reported as values per basin and compared in relative terms in the notebook.

Usage:
    python aggregate_runoff.py \\
        --runoff-csv .../basin_mrro_full/evanger_basin_mrro.csv \\
        --catchments Evanger_system/evanger_local_subcatchments.gpkg \\
        --out-dir .../projections/aggregates -v
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from split_runoff_csv import add_total, load_areas, load_runoff

logger = logging.getLogger("aggregate_runoff")

KEYS = ["basin", "scenario", "model", "method"]


def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Trailing n-day mean; first n-1 values are NaN."""
    out = np.full(x.shape, np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def annual_stats(g: pd.DataFrame) -> pd.DataFrame:
    """g: one (basin, scenario, model, method) daily series, sorted by date."""
    v = g["mrro_mm"].to_numpy(dtype=float)
    d = g["date"]
    r3 = rolling_mean(v, 3)
    r7 = rolling_mean(v, 7)
    tmp = pd.DataFrame({
        "year": d.dt.year.to_numpy(),
        "doy": d.dt.dayofyear.to_numpy(),
        "summer": d.dt.month.between(6, 9).to_numpy(),
        "v": v, "r3": r3, "r7": r7,
    })
    rows = []
    for year, y in tmp.groupby("year", sort=True):
        cum = np.cumsum(y["v"].to_numpy())
        total = cum[-1]
        cov = int(y["doy"].to_numpy()[np.searchsorted(cum, 0.5 * total)]) if total > 0 else np.nan
        s = y.loc[y["summer"], "r7"]
        rows.append((year, total, y["v"].max(), y["r3"].max(), s.min() if len(s) else np.nan, cov))
    return pd.DataFrame(rows, columns=["year", "total_mm", "max1d_mm", "max3d_mm", "min7d_summer_mm", "cov_doy"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runoff-csv", type=Path, required=True)
    parser.add_argument("--catchments", type=Path, required=True)
    parser.add_argument("--id-col", default="basin")
    parser.add_argument("--area-col", default="areal_km2")
    parser.add_argument("--total-name", default="EVANGER_TOTAL")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    df = load_runoff(args.runoff_csv)
    areas = load_areas(args.catchments, args.id_col, args.area_col)
    df = add_total(df, areas, args.total_name)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(KEYS + ["date"]).reset_index(drop=True)
    logger.info("Loaded %d rows incl. %s", len(df), args.total_name)

    pd.concat(
        [areas.rename("area_km2").rename_axis("basin").reset_index(),
         pd.DataFrame({"basin": [args.total_name], "area_km2": [areas.sum()]})],
        ignore_index=True,
    ).to_csv(args.out_dir / "areas.csv", index=False)

    monthly = (
        df.assign(year=df["date"].dt.year, month=df["date"].dt.month)
        .groupby(KEYS + ["year", "month"], observed=True)["mrro_mm"].mean()
        .reset_index()
    )
    monthly.to_csv(args.out_dir / "monthly.csv", index=False, float_format="%.5g")
    logger.info("Wrote monthly.csv (%d rows)", len(monthly))

    parts = []
    for i, (key, g) in enumerate(df.groupby(KEYS, observed=True, sort=False)):
        a = annual_stats(g)
        for k, val in zip(KEYS, key):
            a.insert(KEYS.index(k), k, val)
        parts.append(a)
        if (i + 1) % 200 == 0:
            logger.info("%d series done", i + 1)
    annual = pd.concat(parts, ignore_index=True)
    annual.to_csv(args.out_dir / "annual.csv", index=False, float_format="%.5g")
    logger.info("Wrote annual.csv (%d rows)", len(annual))


if __name__ == "__main__":
    main()
