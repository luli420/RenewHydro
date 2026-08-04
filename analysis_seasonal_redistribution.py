#!/usr/bin/env python3
"""
Flow analysis 1/5: seasonal redistribution (handoff notes §7.2).

Consumes the long-format runoff CSV from extract_basin_runoff.py
(basin, scenario, model, method, date, mrro_mm) -- no GWh conversion here,
this stays in flow terms (mm/day) so it can be checked before the energy
step is added on top (mrro_to_gwh.py / a later analysis pass).

Computes, per period (Reference/Near-future/Far-future) and pooled across
ensemble members within each period:
  - Monthly climatology with an ensemble spread band
  - Centre-of-volume date (day-of-year at which 50% of the annual total has
    passed), per member-year, summarized per period
  - Oct-Mar share of annual inflow, per member-year, summarized per period
  - Spring flood magnitude (peak monthly mean in Mar-Jun) and a duration
    proxy (days in Mar-Jun above that year's 75th percentile daily flow)

Output: one 2-panel figure (monthly climatology + Oct-Mar share by period)
and a summary CSV with the per-period statistics.

Usage:
    python analysis_seasonal_redistribution.py \\
        --runoff-csv evangervatn_basin_mrro.csv --basin Evangervatn \\
        --out-dir figures/seasonal/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from plot_style import PERIOD_COLORS, PERIOD_ORDER, SINGLE_COL_SIZE, add_panel_label, new_figure, save_figure, set_categorical_xticks
from runoff_analysis_common import assign_period, load_runoff_csv

logger = logging.getLogger("analysis_seasonal_redistribution")

SPRING_MONTHS = (3, 4, 5, 6)
WINTER_MONTHS = {10, 11, 12, 1, 2, 3}  # Oct-Mar


def monthly_climatology(df: pd.DataFrame) -> pd.DataFrame:
    """Per (period, member, month): mean daily mrro_mm that month, then
    summarized (mean, p10, p90) across member-years within each period."""
    per_member_month = (
        df.dropna(subset=["period"])
        .groupby(["period", "member", "year", "month"], observed=True)["mrro_mm"]
        .mean()
        .reset_index()
    )
    summary = (
        per_member_month.groupby(["period", "month"], observed=True)["mrro_mm"]
        .agg(mean="mean", p10=lambda s: np.percentile(s, 10), p90=lambda s: np.percentile(s, 90))
        .reset_index()
    )
    return summary


def _annual_group(df: pd.DataFrame) -> pd.core.groupby.DataFrameGroupBy:
    return df.dropna(subset=["period"]).groupby(["period", "member", "year"], observed=True)


def centre_of_volume_doy(df: pd.DataFrame) -> pd.DataFrame:
    """Per (period, member, year): DOY at which cumulative mrro first
    reaches 50% of that year's total."""
    rows = []
    for (period, member, year), g in _annual_group(df):
        g = g.sort_values("doy")
        cum = g["mrro_mm"].cumsum()
        total = cum.iloc[-1]
        if total <= 0:
            continue
        doy50 = g["doy"].values[np.searchsorted(cum.values, 0.5 * total)]
        rows.append({"period": period, "member": member, "year": year, "cov_doy": doy50})
    return pd.DataFrame(rows)


def oct_mar_share(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (period, member, year), g in _annual_group(df):
        total = g["mrro_mm"].sum()
        if total <= 0:
            continue
        winter = g.loc[g["month"].isin(WINTER_MONTHS), "mrro_mm"].sum()
        rows.append({"period": period, "member": member, "year": year, "oct_mar_share": winter / total})
    return pd.DataFrame(rows)


def spring_flood_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (period, member, year), g in _annual_group(df):
        spring = g[g["month"].isin(SPRING_MONTHS)]
        if spring.empty:
            continue
        by_month = spring.groupby("month")["mrro_mm"].mean()
        magnitude = by_month.max()
        threshold = g["mrro_mm"].quantile(0.75)
        duration_days = int((spring["mrro_mm"] > threshold).sum())
        rows.append({"period": period, "member": member, "year": year, "spring_peak_month_mean_mm": magnitude, "spring_duration_days": duration_days})
    return pd.DataFrame(rows)


def make_figure(clim: pd.DataFrame, oct_mar: pd.DataFrame, out_dir: Path, basin_label: str) -> None:
    fig, axes = new_figure(size=SINGLE_COL_SIZE, ncols=2, nrows=1)
    ax_clim, ax_share = axes

    for period in PERIOD_ORDER:
        sub = clim[clim["period"] == period].sort_values("month")
        if sub.empty:
            continue
        color = PERIOD_COLORS[period]
        ax_clim.plot(sub["month"], sub["mean"], color=color, label=period)
        ax_clim.fill_between(sub["month"], sub["p10"], sub["p90"], color=color, alpha=0.15, linewidth=0)

    ax_clim.set_xticks(range(1, 13))
    ax_clim.set_xticklabels(list("JFMAMJJASOND"))
    ax_clim.set_xlabel("Month")
    ax_clim.set_ylabel("Runoff (mm/day)")
    ax_clim.legend(loc="upper left")
    add_panel_label(ax_clim, "a")

    means = oct_mar.groupby("period", observed=True)["oct_mar_share"].mean().reindex(PERIOD_ORDER)
    stds = oct_mar.groupby("period", observed=True)["oct_mar_share"].std().reindex(PERIOD_ORDER)
    colors = [PERIOD_COLORS[p] for p in PERIOD_ORDER]
    ax_share.bar(PERIOD_ORDER, means.values * 100, yerr=stds.values * 100, color=colors, capsize=3)
    ax_share.set_ylabel("Oct-Mar share of annual inflow (%)")
    set_categorical_xticks(ax_share, PERIOD_ORDER)
    add_panel_label(ax_share, "b")

    fig.suptitle(f"Seasonal redistribution -- {basin_label}", fontsize=9, y=1.04)
    fig.tight_layout()
    save_figure(fig, out_dir / "seasonal_redistribution")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runoff-csv", type=Path, required=True)
    parser.add_argument("--basin", default=None, help="Filter to one basin if the CSV has multiple")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    df = assign_period(load_runoff_csv(args.runoff_csv, basin=args.basin))
    basin_label = args.basin or (df["basin"].iloc[0] if not df.empty else "basin")

    clim = monthly_climatology(df)
    cov = centre_of_volume_doy(df)
    oct_mar = oct_mar_share(df)
    spring = spring_flood_stats(df)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    make_figure(clim, oct_mar, args.out_dir, basin_label)

    cov_summary = cov.groupby("period", observed=True)["cov_doy"].agg(["mean", "std"])
    cov_summary.columns = [f"cov_doy_{c}" for c in cov_summary.columns]

    oct_mar_summary = oct_mar.groupby("period", observed=True)["oct_mar_share"].agg(["mean", "std"])
    oct_mar_summary.columns = [f"oct_mar_share_{c}" for c in oct_mar_summary.columns]

    spring_summary = spring.groupby("period", observed=True)[["spring_peak_month_mean_mm", "spring_duration_days"]].agg(["mean", "std"])
    spring_summary.columns = ["_".join(c) for c in spring_summary.columns]

    summary = pd.concat([cov_summary, oct_mar_summary, spring_summary], axis=1).reindex(PERIOD_ORDER)
    summary_path = args.out_dir / "seasonal_redistribution_summary.csv"
    summary.to_csv(summary_path)
    logger.info("Wrote figure + %s", summary_path)


if __name__ == "__main__":
    main()
