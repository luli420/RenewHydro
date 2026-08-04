#!/usr/bin/env python3
"""
Flow analysis 5/5: uncertainty decomposition and time of emergence, in flow
terms (handoff notes §7.6).

Metric: mean annual inflow volume (Mm3/yr) per (scenario, model, method).

Variance decomposition (simplified, Hawkins & Sutton (2009)-style additive
cascade -- NOT a full orthogonal ANOVA with interaction terms, since the
design is not fully balanced across scenarios; documented as an
approximation):
  - Scenario uncertainty: variance across the per-scenario ensemble-mean
    metric values
  - GCM-RCM x bias-adjustment uncertainty: variance across the 20 member
    metric values within a scenario, averaged across scenarios
  - Internal (interannual) variability: within-member year-to-year variance
    of annual volume, averaged across all (scenario, member)
Reported as each component's share of their sum.

Time of emergence: per scenario, the ensemble-mean of a 10-year rolling
annual volume, and the first year after which it stays outside the
Reference-period band (ensemble-mean +/- 2 x interannual std) for the rest
of the record.

Output: one 2-panel figure (variance decomposition bars for Near-future and
Far-future, and time-of-emergence trajectories) plus a summary CSV.

Usage:
    python analysis_uncertainty_decomposition.py \\
        --runoff-csv evangervatn_basin_mrro.csv --basin Evangervatn \\
        --area-km2 150 --out-dir figures/uncertainty/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from plot_style import PERIOD_COLORS, PERIOD_ORDER, SCENARIO_COLORS, SINGLE_COL_SIZE, add_panel_label, new_figure, save_figure
from runoff_analysis_common import assign_period, load_runoff_csv, mm_day_to_Mm3

logger = logging.getLogger("analysis_uncertainty_decomposition")

ROLLING_WINDOW_YEARS = 10
TOE_BAND_K = 2.0


def annual_volume_all_years(df: pd.DataFrame, area_km2: float) -> pd.DataFrame:
    """Like runoff_analysis_common.annual_volume_Mm3, but over the FULL
    record (not restricted to the Reference/Near-future/Far-future windows)
    -- needed for the continuous time-of-emergence trajectory."""
    d = df.copy()
    d["vol_Mm3"] = mm_day_to_Mm3(d["mrro_mm"], area_km2)
    return d.groupby(["scenario", "member", "year"], observed=True)["vol_Mm3"].sum().reset_index()


def variance_decomposition(annual_df: pd.DataFrame, period: str) -> dict:
    """annual_df must already carry a 'period' column (see assign_period)."""
    sub = annual_df[annual_df["period"] == period]
    member_period_mean = sub.groupby(["scenario", "member"], observed=True)["vol_Mm3"].mean().reset_index()

    scenario_means = member_period_mean.groupby("scenario", observed=True)["vol_Mm3"].mean()
    scenario_var = float(scenario_means.var(ddof=1)) if len(scenario_means) > 1 else 0.0

    within_scenario_vars = member_period_mean.groupby("scenario", observed=True)["vol_Mm3"].var(ddof=1)
    model_method_var = float(within_scenario_vars.mean()) if not within_scenario_vars.empty else 0.0

    interannual_vars = sub.groupby(["scenario", "member"], observed=True)["vol_Mm3"].var(ddof=1)
    internal_var = float(interannual_vars.mean()) if not interannual_vars.empty else 0.0

    total = scenario_var + model_method_var + internal_var
    if total <= 0:
        return {"scenario_frac": np.nan, "model_method_frac": np.nan, "internal_frac": np.nan, "total_var": 0.0}
    return {
        "scenario_frac": scenario_var / total,
        "model_method_frac": model_method_var / total,
        "internal_frac": internal_var / total,
        "total_var": total,
    }


def rolling_ensemble_mean_by_scenario(annual_df: pd.DataFrame, window: int = ROLLING_WINDOW_YEARS) -> dict[str, pd.Series]:
    """Per scenario: ensemble-mean annual volume by year, then a trailing
    rolling mean over `window` years. Returned as {scenario: Series indexed
    by year}."""
    out = {}
    for scenario, g in annual_df.groupby("scenario", observed=True):
        ens_mean = g.groupby("year")["vol_Mm3"].mean().sort_index()
        out[scenario] = ens_mean.rolling(window, min_periods=window).mean()
    return out


def time_of_emergence(smoothed: pd.Series, ref_mean: float, ref_std: float, k: float = TOE_BAND_K) -> float:
    """First year after which `smoothed` stays outside [ref_mean +/- k*ref_std]
    for the rest of the record. NaN if it never permanently emerges."""
    lower, upper = ref_mean - k * ref_std, ref_mean + k * ref_std
    values = smoothed.values
    years = smoothed.index.values
    valid = ~np.isnan(values)
    inside = valid & (values >= lower) & (values <= upper)
    inside_idx = np.where(inside)[0]
    last_inside = inside_idx.max() if inside_idx.size else -1
    candidate = last_inside + 1
    if candidate >= len(years) or not valid[candidate:].all():
        return np.nan
    return float(years[candidate])


def make_figure(decomp: dict[str, dict], rolling: dict[str, pd.Series], ref_mean: float, ref_std: float, toe: dict[str, float], out_dir: Path, basin_label: str) -> None:
    fig, axes = new_figure(size=SINGLE_COL_SIZE, ncols=2, nrows=1)
    ax_decomp, ax_toe = axes

    components = ["scenario_frac", "model_method_frac", "internal_frac"]
    comp_labels = ["Scenario", "GCM-RCM x method", "Internal (interannual)"]
    comp_colors = ["#0072B2", "#E69F00", "#999999"]
    periods = [p for p in ("Near-future", "Far-future") if p in decomp]
    bottom = np.zeros(len(periods))
    for comp, label, color in zip(components, comp_labels, comp_colors):
        vals = np.array([decomp[p][comp] * 100 if not np.isnan(decomp[p][comp]) else 0 for p in periods])
        ax_decomp.bar(periods, vals, bottom=bottom, color=color, label=label)
        bottom += vals
    ax_decomp.set_ylabel("Share of total variance (%)")
    ax_decomp.legend(loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=1, fontsize=6)
    add_panel_label(ax_decomp, "a")

    lower, upper = ref_mean - TOE_BAND_K * ref_std, ref_mean + TOE_BAND_K * ref_std
    ax_toe.axhspan(lower, upper, color="black", alpha=0.1, linewidth=0, label="Reference band (+/-2 sd)")
    for scenario, series in rolling.items():
        color = SCENARIO_COLORS.get(scenario, "#333333")
        ax_toe.plot(series.index, series.values, color=color, label=scenario)
        t = toe.get(scenario)
        if t is not None and not np.isnan(t):
            ax_toe.axvline(t, color=color, linestyle=":", linewidth=0.8)
    ax_toe.set_xlabel("Year")
    ax_toe.set_ylabel(f"{ROLLING_WINDOW_YEARS}-yr mean annual volume (Mm3/yr)")
    ax_toe.legend(loc="upper left", fontsize=6)
    add_panel_label(ax_toe, "b")

    fig.suptitle(f"Uncertainty decomposition -- {basin_label}", fontsize=9, y=1.04)
    fig.tight_layout()
    save_figure(fig, out_dir / "uncertainty_decomposition")


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

    annual_full = annual_volume_all_years(df, args.area_km2)
    annual_full = annual_full.merge(df[["scenario", "member", "year", "period"]].drop_duplicates(), on=["scenario", "member", "year"], how="left")

    decomp = {p: variance_decomposition(annual_full, p) for p in ("Near-future", "Far-future") if (annual_full["period"] == p).any()}

    ref = annual_full[annual_full["period"] == "Reference"]
    ref_ens_mean_by_year = ref.groupby("year")["vol_Mm3"].mean()
    ref_mean = float(ref_ens_mean_by_year.mean())
    ref_std = float(ref_ens_mean_by_year.std(ddof=1))

    rolling = rolling_ensemble_mean_by_scenario(annual_full)
    toe = {scenario: time_of_emergence(series, ref_mean, ref_std) for scenario, series in rolling.items() if scenario != "hist"}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    make_figure(decomp, rolling, ref_mean, ref_std, toe, args.out_dir, basin_label)

    rows = []
    for period, d in decomp.items():
        rows.append({"period": period, **d})
    decomp_df = pd.DataFrame(rows).set_index("period")
    toe_df = pd.Series(toe, name="time_of_emergence_year").rename_axis("scenario").reset_index()

    decomp_path = args.out_dir / "uncertainty_decomposition_summary.csv"
    toe_path = args.out_dir / "time_of_emergence_summary.csv"
    decomp_df.to_csv(decomp_path)
    toe_df.to_csv(toe_path, index=False)
    logger.info("Wrote figure + %s + %s", decomp_path, toe_path)


if __name__ == "__main__":
    main()
