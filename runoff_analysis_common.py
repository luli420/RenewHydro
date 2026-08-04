"""
Shared loading, period-assignment, and unit-conversion helpers reused by all
5 flow (runoff) analysis scripts (analysis_*.py). Consumes the long-format
CSV produced by extract_basin_runoff.py
(basin, scenario, model, method, date, mrro_mm).

Period convention matches the diff-mrro periods used elsewhere in this
project (legacy/nevina_runoff_v1.py, the original handoff notes): a
1991-2020 Reference baseline (from the hist scenario) plus Near-future
(2041-2070) and Far-future (2071-2100) windows, evaluated within whichever
future scenario a given analysis is looking at.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REFERENCE_SCENARIO = "hist"
REFERENCE_YEARS = (1991, 2020)
NEAR_FUTURE_YEARS = (2041, 2070)
FAR_FUTURE_YEARS = (2071, 2100)

PERIOD_ORDER = ["Reference", "Near-future", "Far-future"]


def load_runoff_csv(path: Path, basin: str | None = None) -> pd.DataFrame:
    """Load an extract_basin_runoff.py / extract_layer1_timeseries.py-style
    long-format runoff CSV (basin, scenario, model, method, date, mrro_mm)."""
    df = pd.read_csv(path, parse_dates=["date"])
    if basin is not None:
        df = df[df["basin"] == basin].copy()
        if df.empty:
            raise ValueError(f"No rows for basin='{basin}' in {path}; available: {sorted(pd.read_csv(path)['basin'].unique())}")
    df["member"] = df["model"].astype(str) + "_" + df["method"].astype(str)
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["doy"] = df["date"].dt.dayofyear
    return df.sort_values(["scenario", "member", "date"]).reset_index(drop=True)


def assign_period(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'period' column (Reference/Near-future/Far-future/NA) per the
    convention above. Rows outside all three windows get NA and are dropped
    by period-based analyses (e.g. hist years before 1991 or after 2020)."""
    df = df.copy()
    df["period"] = pd.array([pd.NA] * len(df), dtype="string")

    ref_mask = (df["scenario"] == REFERENCE_SCENARIO) & df["year"].between(*REFERENCE_YEARS)
    df.loc[ref_mask, "period"] = "Reference"

    future_mask = df["scenario"] != REFERENCE_SCENARIO
    near_mask = future_mask & df["year"].between(*NEAR_FUTURE_YEARS)
    far_mask = future_mask & df["year"].between(*FAR_FUTURE_YEARS)
    df.loc[near_mask, "period"] = "Near-future"
    df.loc[far_mask, "period"] = "Far-future"
    return df


def mm_day_to_m3s(mrro_mm, area_km2: float):
    """mm/day -> m^3/s: mm/day * km^2 * 1000 m^3/(mm.km^2) / 86400 s/day."""
    return mrro_mm * area_km2 * 1000.0 / 86400.0


def mm_day_to_Mm3(mrro_mm, area_km2: float):
    """mm/day -> Mm^3/day: 1 mm over 1 km^2 = 1000 m^3 = 0.001 Mm^3."""
    return mrro_mm * area_km2 / 1000.0


def annual_volume_Mm3(df: pd.DataFrame, area_km2: float) -> pd.DataFrame:
    """Per (scenario, member, period, year): total annual volume in Mm^3."""
    df = df.copy()
    df["vol_Mm3"] = mm_day_to_Mm3(df["mrro_mm"], area_km2)
    out = (
        df.dropna(subset=["period"])
        .groupby(["scenario", "member", "period", "year"], observed=True)["vol_Mm3"]
        .sum()
        .reset_index()
    )
    return out


def rolling_mean_by_member(df: pd.DataFrame, value_col: str, window: int) -> pd.Series:
    """Centered-enough (trailing) rolling mean of value_col, computed
    independently within each (scenario, member) group, in date order."""
    return df.groupby(["scenario", "member"], observed=True)[value_col].transform(
        lambda s: s.rolling(window, min_periods=window).mean()
    )
