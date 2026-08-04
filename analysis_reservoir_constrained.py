#!/usr/bin/env python3
"""
Flow analysis 2/5: reservoir-constrained production, in FLOW terms only
(handoff notes §7.3) -- no energy conversion here, that comes later once
this stage is confirmed. "Production" below means water actually released
through the turbine intake (bounded by Qmax), not GWh.

Simple daily bucket model per (scenario, member):
    storage_t = clip(storage_{t-1} + inflow_t - release_t, 0, V)
    release_t = min(Qmax, storage_{t-1} + inflow_t)
    spill_t   = max(0, storage_{t-1} + inflow_t - release_t - V)

Reservoir capacity V and max turbine discharge Qmax are plant-specific and
NOT guessed here -- pass them via --capacity-mm3/--qmax-m3s.

Computes, per period (Reference/Near-future/Far-future):
  - Spilled volume (Mm3/yr)
  - Days/year where raw inflow alone exceeds Qmax (a storage-independent
    spill-risk proxy)
  - Filling degree at the end of the filling season (--fill-season-end-month,
    default September -- typical for Norwegian snowmelt-fed reservoirs)
  - Firm flow: Q90 of the released series (exceeded 90% of days)

Output: one 2-panel figure (flow-duration curve of inflow vs. release, and
spilled volume by period) plus a summary CSV.

Usage:
    python analysis_reservoir_constrained.py \\
        --runoff-csv evangervatn_basin_mrro.csv --basin Evangervatn \\
        --area-km2 150 --capacity-mm3 20 --qmax-m3s 15 \\
        --out-dir figures/reservoir/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from plot_style import PERIOD_COLORS, PERIOD_ORDER, SINGLE_COL_SIZE, add_panel_label, new_figure, save_figure, set_categorical_xticks
from runoff_analysis_common import assign_period, load_runoff_csv, mm_day_to_Mm3

logger = logging.getLogger("analysis_reservoir_constrained")


def simulate_reservoir(inflow_Mm3: np.ndarray, capacity_Mm3: float, qmax_Mm3_day: float, initial_frac: float = 0.5) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Daily bucket simulation. Returns (storage, release, spill), all Mm3."""
    n = len(inflow_Mm3)
    storage = np.empty(n)
    release = np.empty(n)
    spill = np.empty(n)
    prev = capacity_Mm3 * initial_frac
    for t in range(n):
        available = prev + inflow_Mm3[t]
        rel = min(qmax_Mm3_day, available)
        after_release = available - rel
        if after_release > capacity_Mm3:
            spill[t] = after_release - capacity_Mm3
            after_release = capacity_Mm3
        else:
            spill[t] = 0.0
        storage[t] = after_release
        release[t] = rel
        prev = after_release
    return storage, release, spill


def run_simulation_by_member(df: pd.DataFrame, area_km2: float, capacity_Mm3: float, qmax_m3s: float, initial_frac: float) -> pd.DataFrame:
    qmax_Mm3_day = qmax_m3s * 86400.0 / 1e6
    out_frames = []
    for (scenario, member), g in df.dropna(subset=["period"]).groupby(["scenario", "member"], observed=True):
        g = g.sort_values("date").copy()
        g["inflow_Mm3"] = mm_day_to_Mm3(g["mrro_mm"], area_km2)
        storage, release, spill = simulate_reservoir(g["inflow_Mm3"].values, capacity_Mm3, qmax_Mm3_day, initial_frac)
        g["storage_Mm3"] = storage
        g["release_Mm3"] = release
        g["spill_Mm3"] = spill
        out_frames.append(g)
    return pd.concat(out_frames, ignore_index=True)


def summarize_by_period(sim_df: pd.DataFrame, qmax_m3s: float, area_km2: float, fill_season_end_month: int) -> pd.DataFrame:
    qmax_mm_day = qmax_m3s * 86400.0 / 1000.0 / area_km2  # m3/s -> mm/day, for the raw-inflow comparison

    rows = []
    for (period, member, year), g in sim_df.groupby(["period", "member", "year"], observed=True):
        spilled = g["spill_Mm3"].sum()
        days_above_qmax = int((g["mrro_mm"] > qmax_mm_day).sum())
        eom = g[g["month"] == fill_season_end_month]
        filling_degree = float(eom["storage_Mm3"].iloc[-1]) if not eom.empty else np.nan
        rows.append({"period": period, "member": member, "year": year, "spilled_Mm3": spilled, "days_above_qmax": days_above_qmax, "storage_at_fill_season_end_Mm3": filling_degree})
    per_year = pd.DataFrame(rows)

    q90 = sim_df.groupby(["period"], observed=True)["release_Mm3"].quantile(0.10).rename("firm_release_Mm3_day_q90").to_frame()
    summary = per_year.groupby("period", observed=True)[["spilled_Mm3", "days_above_qmax", "storage_at_fill_season_end_Mm3"]].agg(["mean", "std"])
    summary.columns = ["_".join(c) for c in summary.columns]
    summary = pd.concat([summary, q90], axis=1)
    return summary.reindex(PERIOD_ORDER)


def make_figure(sim_df: pd.DataFrame, per_period_spill: pd.Series, out_dir: Path, basin_label: str, capacity_Mm3: float) -> None:
    fig, axes = new_figure(size=SINGLE_COL_SIZE, ncols=2, nrows=1)
    ax_fdc, ax_spill = axes

    for period in PERIOD_ORDER:
        sub = sim_df[sim_df["period"] == period]
        if sub.empty:
            continue
        color = PERIOD_COLORS[period]
        inflow_sorted = np.sort(sub["inflow_Mm3"].values)[::-1]
        exceed = 100.0 * (np.arange(1, len(inflow_sorted) + 1) / len(inflow_sorted))
        ax_fdc.plot(exceed, inflow_sorted, color=color, label=period, linewidth=0.8)

    ax_fdc.set_yscale("log")
    ax_fdc.set_xlabel("Exceedance probability (%)")
    ax_fdc.set_ylabel("Inflow (Mm3/day)")
    ax_fdc.legend(loc="best")
    add_panel_label(ax_fdc, "a")

    colors = [PERIOD_COLORS[p] for p in PERIOD_ORDER]
    ax_spill.bar(PERIOD_ORDER, per_period_spill.values, color=colors)
    ax_spill.set_ylabel("Mean spilled volume (Mm3/yr)")
    set_categorical_xticks(ax_spill, PERIOD_ORDER)
    add_panel_label(ax_spill, "b")

    fig.suptitle(f"Reservoir-constrained flow (V={capacity_Mm3:g} Mm3) -- {basin_label}", fontsize=9, y=1.04)
    fig.tight_layout()
    save_figure(fig, out_dir / "reservoir_constrained")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runoff-csv", type=Path, required=True)
    parser.add_argument("--basin", default=None)
    parser.add_argument("--area-km2", type=float, required=True)
    parser.add_argument("--capacity-mm3", type=float, required=True, help="Reservoir capacity V, Mm3")
    parser.add_argument("--qmax-m3s", type=float, required=True, help="Max turbine discharge, m3/s")
    parser.add_argument("--initial-storage-frac", type=float, default=0.5)
    parser.add_argument("--fill-season-end-month", type=int, default=9, help="Month (1-12) to evaluate filling degree; default September")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    df = assign_period(load_runoff_csv(args.runoff_csv, basin=args.basin))
    basin_label = args.basin or (df["basin"].iloc[0] if not df.empty else "basin")

    sim_df = run_simulation_by_member(df, args.area_km2, args.capacity_mm3, args.qmax_m3s, args.initial_storage_frac)
    summary = summarize_by_period(sim_df, args.qmax_m3s, args.area_km2, args.fill_season_end_month)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    make_figure(sim_df.dropna(subset=["period"]), summary["spilled_Mm3_mean"], args.out_dir, basin_label, args.capacity_mm3)

    summary_path = args.out_dir / "reservoir_constrained_summary.csv"
    summary.to_csv(summary_path)
    logger.info("Wrote figure + %s", summary_path)


if __name__ == "__main__":
    main()
