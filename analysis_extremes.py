#!/usr/bin/env python3
"""
Flow analysis 4/5: extremes, in flow terms (handoff notes §7.5).

Computes, per period (Reference/Near-future/Far-future), pooling annual
extrema across all ensemble members within the period (caveat: members are
NOT fully independent -- 10 GCM-RCMs x 2 bias-adjustment methods -- so
treat the GEV confidence band as indicative, not a rigorous i.i.d. interval;
see CLAUDE.md):
  - Annual maximum 1-day and 3-day mean inflow (m3/s), with a GEV fit and
    return levels for standard return periods, plus a percentile bootstrap
    confidence band
  - Summer (Jun-Sep) 7-day minimum flow (m3/s)
  - Days per year below a minimum-flow threshold (minstevannforing),
    supplied via --min-flow-m3s -- plant/concession-specific, not guessed

Output: one 2-panel figure (GEV return-level plot for 1-day annual maxima,
and summer 7-day minimum flow by period) plus a summary CSV.

Usage:
    python analysis_extremes.py \\
        --runoff-csv evangervatn_basin_mrro.csv --basin Evangervatn \\
        --area-km2 150 --min-flow-m3s 0.5 --out-dir figures/extremes/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from plot_style import PERIOD_COLORS, PERIOD_ORDER, SINGLE_COL_SIZE, add_panel_label, new_figure, save_figure, set_categorical_xticks
from runoff_analysis_common import assign_period, load_runoff_csv, mm_day_to_m3s, rolling_mean_by_member

logger = logging.getLogger("analysis_extremes")

RETURN_PERIODS = np.array([2, 5, 10, 20, 50, 100])
SUMMER_MONTHS = {6, 7, 8, 9}
N_BOOTSTRAP = 500
RNG_SEED = 0


def annual_max_nday(df: pd.DataFrame, area_km2: float, window: int) -> pd.DataFrame:
    df = df.copy()
    df["flow_m3s"] = mm_day_to_m3s(df["mrro_mm"], area_km2)
    col = f"roll{window}_m3s"
    df[col] = rolling_mean_by_member(df, "flow_m3s", window)
    out = df.dropna(subset=["period", col]).groupby(["period", "member", "year"], observed=True)[col].max().reset_index(name="annual_max_m3s")
    return out


def fit_gev(annual_maxima: np.ndarray) -> tuple[float, float, float]:
    """Returns (shape, loc, scale) in scipy.stats.genextreme's own
    parameterization (its shape c = -xi in the usual GEV convention) --
    used consistently with genextreme.ppf below, so the sign convention
    never needs to be interpreted directly."""
    c, loc, scale = stats.genextreme.fit(annual_maxima)
    return c, loc, scale


def return_levels(shape: float, loc: float, scale: float, return_periods: np.ndarray = RETURN_PERIODS) -> np.ndarray:
    return stats.genextreme.ppf(1 - 1 / return_periods, shape, loc=loc, scale=scale)


def bootstrap_return_levels(annual_maxima: np.ndarray, return_periods: np.ndarray = RETURN_PERIODS, n_boot: int = N_BOOTSTRAP, seed: int = RNG_SEED) -> np.ndarray:
    """Percentile bootstrap: resample annual maxima with replacement, refit,
    recompute return levels. Returns array shape (n_boot, len(return_periods))."""
    rng = np.random.default_rng(seed)
    n = len(annual_maxima)
    out = np.full((n_boot, len(return_periods)), np.nan)
    for i in range(n_boot):
        sample = rng.choice(annual_maxima, size=n, replace=True)
        try:
            c, loc, scale = fit_gev(sample)
            out[i] = return_levels(c, loc, scale, return_periods)
        except Exception:  # noqa: BLE001 -- occasional fit failure on a degenerate resample
            continue
    return out


def summer_7day_min(df: pd.DataFrame, area_km2: float) -> pd.DataFrame:
    df = df.copy()
    df["flow_m3s"] = mm_day_to_m3s(df["mrro_mm"], area_km2)
    df["roll7_m3s"] = rolling_mean_by_member(df, "flow_m3s", 7)
    summer = df[df["month"].isin(SUMMER_MONTHS)].dropna(subset=["period", "roll7_m3s"])
    out = summer.groupby(["period", "member", "year"], observed=True)["roll7_m3s"].min().reset_index(name="summer_7day_min_m3s")
    return out


def days_below_threshold(df: pd.DataFrame, area_km2: float, threshold_m3s: float) -> pd.DataFrame:
    df = df.copy()
    df["flow_m3s"] = mm_day_to_m3s(df["mrro_mm"], area_km2)
    out = (
        df.dropna(subset=["period"])
        .assign(below=lambda d: d["flow_m3s"] < threshold_m3s)
        .groupby(["period", "member", "year"], observed=True)["below"]
        .sum()
        .reset_index(name="days_below_min_flow")
    )
    return out


def make_figure(annual_max_1d: pd.DataFrame, summer_min: pd.DataFrame, out_dir: Path, basin_label: str) -> None:
    fig, axes = new_figure(size=SINGLE_COL_SIZE, ncols=2, nrows=1)
    ax_gev, ax_summer = axes

    for period in PERIOD_ORDER:
        maxima = annual_max_1d.loc[annual_max_1d["period"] == period, "annual_max_m3s"].values
        if len(maxima) < 10:
            continue
        color = PERIOD_COLORS[period]

        n = len(maxima)
        sorted_maxima = np.sort(maxima)
        empirical_T = (n + 1) / (n - np.arange(n))  # Weibull plotting position
        ax_gev.scatter(empirical_T, sorted_maxima, s=6, color=color, alpha=0.5)

        c, loc, scale = fit_gev(maxima)
        fitted = return_levels(c, loc, scale)
        ax_gev.plot(RETURN_PERIODS, fitted, color=color, label=period)

        boot = bootstrap_return_levels(maxima)
        lo = np.nanpercentile(boot, 5, axis=0)
        hi = np.nanpercentile(boot, 95, axis=0)
        ax_gev.fill_between(RETURN_PERIODS, lo, hi, color=color, alpha=0.15, linewidth=0)

    ax_gev.set_xscale("log")
    ax_gev.set_xlabel("Return period (years)")
    ax_gev.set_ylabel("Annual max 1-day flow (m3/s)")
    ax_gev.legend(loc="upper left", fontsize=6)
    add_panel_label(ax_gev, "a")

    data = [summer_min.loc[summer_min["period"] == p, "summer_7day_min_m3s"].values for p in PERIOD_ORDER]
    # positions/set_categorical_xticks (0-indexed) rather than the boxplot
    # labels=/tick_labels= kwarg, whose name changed across matplotlib versions
    bp = ax_summer.boxplot(data, positions=range(len(PERIOD_ORDER)), showfliers=False, patch_artist=True, widths=0.6)
    for patch, period in zip(bp["boxes"], PERIOD_ORDER):
        patch.set_facecolor(PERIOD_COLORS[period])
        patch.set_alpha(0.35)
        patch.set_edgecolor(PERIOD_COLORS[period])
    ax_summer.set_ylabel("Summer 7-day min flow (m3/s)")
    set_categorical_xticks(ax_summer, PERIOD_ORDER)
    add_panel_label(ax_summer, "b")

    fig.suptitle(f"Extremes -- {basin_label}", fontsize=9, y=1.04)
    fig.tight_layout()
    save_figure(fig, out_dir / "extremes")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runoff-csv", type=Path, required=True)
    parser.add_argument("--basin", default=None)
    parser.add_argument("--area-km2", type=float, required=True)
    parser.add_argument("--min-flow-m3s", type=float, required=True, help="Minstevannforing / concession minimum release threshold, m3/s")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    df = assign_period(load_runoff_csv(args.runoff_csv, basin=args.basin))
    basin_label = args.basin or (df["basin"].iloc[0] if not df.empty else "basin")

    max1d = annual_max_nday(df, args.area_km2, window=1)
    max3d = annual_max_nday(df, args.area_km2, window=3)
    summer_min = summer_7day_min(df, args.area_km2)
    below = days_below_threshold(df, args.area_km2, args.min_flow_m3s)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    make_figure(max1d, summer_min, args.out_dir, basin_label)

    rows = []
    for period in PERIOD_ORDER:
        maxima1 = max1d.loc[max1d["period"] == period, "annual_max_m3s"].values
        maxima3 = max3d.loc[max3d["period"] == period, "annual_max_m3s"].values
        row = {"period": period}
        if len(maxima1) >= 10:
            c, loc, scale = fit_gev(maxima1)
            for T, rl in zip(RETURN_PERIODS, return_levels(c, loc, scale)):
                row[f"return_level_1day_T{T}_m3s"] = rl
        if len(maxima3) >= 10:
            c, loc, scale = fit_gev(maxima3)
            for T, rl in zip(RETURN_PERIODS, return_levels(c, loc, scale)):
                row[f"return_level_3day_T{T}_m3s"] = rl
        row["summer_7day_min_mean_m3s"] = summer_min.loc[summer_min["period"] == period, "summer_7day_min_m3s"].mean()
        row["days_below_min_flow_mean_per_yr"] = below.loc[below["period"] == period, "days_below_min_flow"].mean()
        rows.append(row)

    summary_path = args.out_dir / "extremes_summary.csv"
    pd.DataFrame(rows).set_index("period").reindex(PERIOD_ORDER).to_csv(summary_path)
    logger.info("Wrote figure + %s", summary_path)


if __name__ == "__main__":
    main()
