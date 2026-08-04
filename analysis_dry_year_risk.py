#!/usr/bin/env python3
"""
Flow analysis 3/5: dry-year and multi-year deficit risk, in flow/volume
terms (handoff notes §7.4).

Uses annual inflow volume (Mm3/yr) per (scenario, member, period, year).
A "dry year" is defined as annual volume below a FIXED threshold taken from
the Reference period (the 20th percentile, i.e. a historical 1-in-5-dry-year
level) -- applied consistently to Near-future/Far-future so the analysis
shows whether years that would have counted as dry historically become more
or less frequent, rather than redefining "dry" separately in each period.

Computes, per period:
  - 1-in-10 and 1-in-20 driest-year volumes (10th/5th percentile, pooled
    across member-years within the period)
  - Longest run of consecutive dry years (< Reference-period threshold),
    per member, within that period's ~30-year window
  - Interannual coefficient of variation (std/mean of annual volume),
    computed per member then averaged across members (keeps single-
    realization interannual variability from being conflated with
    member-to-member spread)

Output: one 2-panel figure (annual volume distribution by period with dry
thresholds marked, and interannual CV by period) plus a summary CSV.

Usage:
    python analysis_dry_year_risk.py \\
        --runoff-csv evangervatn_basin_mrro.csv --basin Evangervatn \\
        --area-km2 150 --out-dir figures/dry_year/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from plot_style import PERIOD_COLORS, PERIOD_ORDER, SINGLE_COL_SIZE, add_panel_label, new_figure, save_figure, set_categorical_xticks
from runoff_analysis_common import annual_volume_Mm3, assign_period, load_runoff_csv

logger = logging.getLogger("analysis_dry_year_risk")


def dry_year_quantiles(annual_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for period, g in annual_df.groupby("period", observed=True):
        rows.append(
            {
                "period": period,
                "p10_1in10_Mm3": np.percentile(g["vol_Mm3"], 10),
                "p05_1in20_Mm3": np.percentile(g["vol_Mm3"], 5),
                "median_Mm3": np.median(g["vol_Mm3"]),
            }
        )
    return pd.DataFrame(rows).set_index("period").reindex(PERIOD_ORDER)


def reference_dry_threshold(annual_df: pd.DataFrame) -> float:
    ref = annual_df[annual_df["period"] == "Reference"]
    if ref.empty:
        raise ValueError("No Reference-period rows found; cannot define the dry-year threshold")
    return float(np.percentile(ref["vol_Mm3"], 20))


def longest_dry_run(years: np.ndarray, values: np.ndarray, threshold: float) -> int:
    """Longest run of consecutive years (by calendar year, gaps break the
    run) where values < threshold."""
    order = np.argsort(years)
    years = years[order]
    values = values[order]
    best = cur = 0
    prev_year = None
    for y, v in zip(years, values):
        if prev_year is not None and y != prev_year + 1:
            cur = 0
        if v < threshold:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
        prev_year = y
    return best


def dry_run_and_cv_by_period(annual_df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    rows = []
    for (period, member), g in annual_df.groupby(["period", "member"], observed=True):
        run = longest_dry_run(g["year"].values, g["vol_Mm3"].values, threshold)
        cv = g["vol_Mm3"].std(ddof=1) / g["vol_Mm3"].mean()
        rows.append({"period": period, "member": member, "longest_dry_run_years": run, "cv": cv})
    return pd.DataFrame(rows)


def make_figure(annual_df: pd.DataFrame, threshold: float, cv_df: pd.DataFrame, out_dir: Path, basin_label: str) -> None:
    fig, axes = new_figure(size=SINGLE_COL_SIZE, ncols=2, nrows=1)
    ax_box, ax_cv = axes

    data = [annual_df.loc[annual_df["period"] == p, "vol_Mm3"].values for p in PERIOD_ORDER]
    # positions/set_categorical_xticks (0-indexed) rather than the boxplot
    # labels=/tick_labels= kwarg, whose name changed across matplotlib versions
    bp = ax_box.boxplot(data, positions=range(len(PERIOD_ORDER)), showfliers=False, patch_artist=True, widths=0.6)
    for patch, period in zip(bp["boxes"], PERIOD_ORDER):
        patch.set_facecolor(PERIOD_COLORS[period])
        patch.set_alpha(0.35)
        patch.set_edgecolor(PERIOD_COLORS[period])
    for median in bp["medians"]:
        median.set_color("black")
    ax_box.axhline(threshold, color="black", linestyle="--", linewidth=0.8, label="Reference 1-in-5 dry threshold")
    ax_box.set_ylabel("Annual volume (Mm3/yr)")
    set_categorical_xticks(ax_box, PERIOD_ORDER)
    ax_box.legend(loc="best", fontsize=6)
    add_panel_label(ax_box, "a")

    means = cv_df.groupby("period", observed=True)["cv"].mean().reindex(PERIOD_ORDER)
    stds = cv_df.groupby("period", observed=True)["cv"].std().reindex(PERIOD_ORDER)
    colors = [PERIOD_COLORS[p] for p in PERIOD_ORDER]
    ax_cv.bar(PERIOD_ORDER, means.values, yerr=stds.values, color=colors, capsize=3)
    ax_cv.set_ylabel("Interannual CV of annual volume")
    set_categorical_xticks(ax_cv, PERIOD_ORDER)
    add_panel_label(ax_cv, "b")

    fig.suptitle(f"Dry-year and deficit risk -- {basin_label}", fontsize=9, y=1.04)
    fig.tight_layout()
    save_figure(fig, out_dir / "dry_year_risk")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runoff-csv", type=Path, required=True)
    parser.add_argument("--basin", default=None)
    parser.add_argument("--area-km2", type=float, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    df = assign_period(load_runoff_csv(args.runoff_csv, basin=args.basin))
    basin_label = args.basin or (df["basin"].iloc[0] if not df.empty else "basin")

    annual_df = annual_volume_Mm3(df, args.area_km2)
    threshold = reference_dry_threshold(annual_df)
    quantiles = dry_year_quantiles(annual_df)
    dry_runs = dry_run_and_cv_by_period(annual_df, threshold)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    make_figure(annual_df, threshold, dry_runs, args.out_dir, basin_label)

    dry_runs_summary = dry_runs.groupby("period", observed=True)[["longest_dry_run_years", "cv"]].agg(["mean", "max", "std"])
    dry_runs_summary.columns = ["_".join(c) for c in dry_runs_summary.columns]
    summary = pd.concat([quantiles, dry_runs_summary], axis=1)
    summary["reference_dry_threshold_Mm3"] = threshold
    summary_path = args.out_dir / "dry_year_risk_summary.csv"
    summary.to_csv(summary_path)
    logger.info("Wrote figure + %s", summary_path)


if __name__ == "__main__":
    main()
