"""Build notebooks/evanger_runoff_projections.ipynb (stdlib only)."""
import json
import sys

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "id": f"c{len(cells):02d}", "metadata": {}, "source": s.strip("\n").splitlines(keepends=True)})


def code(s):
    cells.append({"cell_type": "code", "id": f"c{len(cells):02d}", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": s.strip("\n").splitlines(keepends=True)})


md(r"""
# Evanger runoff projections (KiN2025, 21 local sub-catchments)

Daily runoff (`mrro`, distHBV) from **Klima i Norge 2025**, averaged over each of the 21 local Evanger
sub-catchments, plus **EVANGER_TOTAL** (area-weighted over all 21, 187.9 km²).

| Item | Value |
|---|---|
| Reference | `hist` 1991–2020 |
| Future periods | Near 2041–2070, Far 2071–2100 |
| Scenarios | `rcp26`, `rcp45` (10 CMIP5 GCM-RCMs), `ssp370` (10 CMIP6 GCM-RCMs) |
| Members | each GCM-RCM × 2 bias adjustments (`eqm`, `3dbc-eqm`) = 20 per scenario |

**Method notes**
- Changes are computed **member by member**: each future member is compared with the *same* model and
  bias adjustment in `hist`, then the ensemble is summarised (median, 10–90 % range). This removes most
  of the constant model bias.
- KiN2025 reference runoff is ~0.80 × NVE's `QN9120` normals (Figure 1). Use the **relative changes**,
  not the absolute values, for planning (delta-change).
- The 20 members are 10 models × 2 bias adjustments, **not 20 independent** members; read ranges as indicative.
- No plant data (minimum flow, reservoir volume, Qmax) is used. Extremes are shown as relative changes.

**Input:** small tables from `aggregate_runoff.py` (`monthly.csv`, `annual.csv`, `areas.csv`) and
`nve_normals.csv`. Set `DATA_DIR` below.
""")

code(r"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

DATA_DIR = Path(os.environ.get("EVANGER_AGG_DIR", "aggregates"))   # folder with monthly.csv, annual.csv, ...
FIG_DIR = Path(os.environ.get("EVANGER_FIG_DIR", "figures"))
FIG_DIR.mkdir(parents=True, exist_ok=True)

TOTAL = "EVANGER_TOTAL"
REF = (1991, 2020)
PERIODS = {"Near 2041–2070": (2041, 2070), "Far 2071–2100": (2071, 2100)}
SCENARIOS = ["rcp26", "rcp45", "ssp370"]
# Okabe & Ito palette, same as plot_style.py
SCEN_COLORS = {"hist": "#000000", "rcp26": "#0072B2", "rcp45": "#E69F00", "ssp370": "#D55E00"}
MONTHS = list("JFMAMJJASOND")

plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 200, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.3, "font.size": 10})


def save(fig, name):
    fig.savefig(FIG_DIR / f"{name}.png", bbox_inches="tight")


def q(s, p):
    return s.quantile(p)
""")

code(r"""
monthly = pd.read_csv(DATA_DIR / "monthly.csv")
annual = pd.read_csv(DATA_DIR / "annual.csv")
areas = pd.read_csv(DATA_DIR / "areas.csv").set_index("basin")["area_km2"]
nve = pd.read_csv(DATA_DIR / "nve_normals.csv").set_index("basin")
for d in (monthly, annual):
    d["member"] = d["model"] + "_" + d["method"]

BASINS = sorted(b for b in annual["basin"].unique() if b != TOTAL) + [TOTAL]
print(f"{len(BASINS)} series, {annual.groupby('scenario')['member'].nunique().to_dict()} members per scenario")
hist_years = annual.loc[annual.scenario == "hist", "year"].agg(["min", "max"]).tolist()
fut_years = annual.loc[annual.scenario != "hist", "year"].agg(["min", "max"]).tolist()
print(f"years: hist {hist_years}, future {fut_years}")
""")

md(r"""
## Helper: member-wise change

`ref_mean` = mean of a variable over 1991–2020 in `hist` for each (basin, member).
`fut_mean` = mean over a future period in a scenario for the same (basin, member).
Change in % = 100 × (fut / ref − 1). For timing variables (days) the change is the difference.
""")

code(r"""
def period_stat(df, var, scen, years, agg="mean"):
    sub = df[(df.scenario == scen) & df.year.between(*years)]
    return sub.groupby(["basin", "member"])[var].agg(agg)


def member_change(df, var, agg="mean", kind="pct"):
    # One row per (basin, scenario, period, member) with the change against the member's own reference.
    ref = period_stat(df, var, "hist", REF, agg).rename("ref")
    out = []
    for scen in SCENARIOS:
        for pname, years in PERIODS.items():
            fut = period_stat(df, var, scen, years, agg).rename("fut")
            j = pd.concat([ref, fut], axis=1, join="inner").reset_index()
            j["change"] = 100 * (j.fut / j.ref - 1) if kind == "pct" else j.fut - j.ref
            j["scenario"], j["period"] = scen, pname
            out.append(j)
    return pd.concat(out, ignore_index=True)


def ens_summary(ch):
    return ch.groupby(["basin", "scenario", "period"])["change"].agg(
        median="median", p10=lambda s: q(s, 0.1), p90=lambda s: q(s, 0.9), n="count").reset_index()


COLS = [(s, p) for s in SCENARIOS for p in PERIODS]
COL_LABELS = [f"{s}\n{p.split()[0]}" for s, p in COLS]


def heatmap(ax, table, title, fmt="{:+.0f}", vmax=None, cmap="BrBG", unit="%"):
    # table: index = basin, columns = (scenario, period)
    data = table.reindex(index=BASINS, columns=COLS).to_numpy(dtype=float)
    vmax = vmax or np.nanmax(np.abs(data))
    im = ax.imshow(data, cmap=cmap, norm=mcolors.TwoSlopeNorm(0, -vmax, vmax), aspect="auto")
    ax.set_xticks(range(len(COLS)), COL_LABELS, fontsize=8)
    ax.set_yticks(range(len(BASINS)), BASINS, fontsize=8)
    ax.axhline(len(BASINS) - 1.5, color="k", lw=1)
    for i in range(data.shape[0]):
        for k in range(data.shape[1]):
            if np.isfinite(data[i, k]):
                ax.text(k, i, fmt.format(data[i, k]), ha="center", va="center", fontsize=7)
    ax.grid(False)
    ax.set_title(title)
    plt.colorbar(im, ax=ax, shrink=0.6, label=unit)
""")

md(r"""
## 1. Reference check against NVE normals

KiN2025 `hist` 1991–2020 mean annual runoff (ensemble median and 10–90 % range over 40 members)
against NVE's `QN9120_mmA` from the catchment reports.
""")

code(r"""
ref_ann = period_stat(annual, "total_mm", "hist", REF).groupby("basin").agg(
    median="median", p10=lambda s: q(s, .1), p90=lambda s: q(s, .9)).join(nve, how="inner")

fig, ax = plt.subplots(figsize=(5.5, 5))
ax.errorbar(ref_ann.QN9120_mm, ref_ann["median"], yerr=[ref_ann["median"] - ref_ann.p10, ref_ann.p90 - ref_ann["median"]],
            fmt="o", ms=4, color="k", ecolor="0.6", capsize=2)
lim = [1800, 3800]
ax.plot(lim, lim, "k--", lw=1, label="1:1")
ax.plot(lim, [0.8 * v for v in lim], color="#D55E00", lw=1, label="0.8 × NVE")
ax.set(xlim=lim, ylim=lim, xlabel="NVE QN9120 (mm/yr)", ylabel="KiN2025 hist 1991–2020 (mm/yr)",
       title="Reference runoff: KiN2025 vs NVE")
ax.legend()
save(fig, "01_reference_vs_nve")
ratio = ref_ann["median"] / ref_ann.QN9120_mm
print(f"ratio KiN2025/NVE: median {ratio.median():.2f}, range {ratio.min():.2f}–{ratio.max():.2f}")
""")

md(r"""
## 2. Annual runoff over time (EVANGER_TOTAL)

Annual runoff of each member as % of its own 1991–2020 mean, smoothed with a 10-year running mean;
line = ensemble median, band = 10–90 %.
""")

code(r"""
def rel_series(df, basin):
    d = df[df.basin == basin]
    ref = d[(d.scenario == "hist") & d.year.between(*REF)].groupby("member")["total_mm"].mean()
    d = d.assign(rel=100 * d.total_mm / d.member.map(ref)).dropna(subset=["rel"])
    d = d.sort_values("year")
    d["rel10"] = d.groupby(["scenario", "member"])["rel"].transform(lambda s: s.rolling(10, center=True, min_periods=10).mean())
    return d

d = rel_series(annual, TOTAL)
fig, ax = plt.subplots(figsize=(9, 4.5))
for scen in ["hist"] + SCENARIOS:
    g = d[d.scenario == scen].groupby("year")["rel10"]
    med, lo, hi = g.median(), g.quantile(.1), g.quantile(.9)
    ax.fill_between(med.index, lo, hi, color=SCEN_COLORS[scen], alpha=0.15, lw=0)
    ax.plot(med.index, med, color=SCEN_COLORS[scen], lw=2, label=scen)
ax.axhline(100, color="k", lw=0.8)
ax.axvspan(*REF, color="0.9", zorder=0)
ax.set(ylabel="% of 1991–2020", title="EVANGER_TOTAL annual runoff (10-yr running mean)")
ax.legend(ncol=4)
save(fig, "02_annual_timeseries_total")
""")

md(r"""
## 3. Change in mean annual runoff, all basins

Ensemble median of the member-wise change (%). Bottom row = EVANGER_TOTAL.
""")

code(r"""
ch_ann = member_change(annual, "total_mm")
s_ann = ens_summary(ch_ann)
tab = s_ann.pivot_table(index="basin", columns=["scenario", "period"], values="median")
fig, ax = plt.subplots(figsize=(8, 8))
heatmap(ax, tab, "Change in mean annual runoff (ensemble median, %)", vmax=15)
save(fig, "03_annual_change_heatmap")

s_ann[s_ann.basin == TOTAL].round(1)
""")

md(r"""
## 4. Seasonal cycle (EVANGER_TOTAL)

Monthly mean runoff (mm/day): reference (black) and future periods, ensemble median with 10–90 % band
of member climatologies.
""")

code(r"""
def member_clim(df, basin, scen, years):
    sub = df[(df.basin == basin) & (df.scenario == scen) & df.year.between(*years)]
    return sub.groupby(["member", "month"])["mrro_mm"].mean().unstack()

fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
ref_c = member_clim(monthly, TOTAL, "hist", REF)
for ax, scen in zip(axes, SCENARIOS):
    for label, (scen_i, years, color, ls) in {"Ref 1991–2020": ("hist", REF, "k", "-"),
                                             "Near": (scen, PERIODS["Near 2041–2070"], SCEN_COLORS[scen], "--"),
                                             "Far": (scen, PERIODS["Far 2071–2100"], SCEN_COLORS[scen], "-")}.items():
        c = member_clim(monthly, TOTAL, scen_i, years)
        if scen_i == "hist":   # same members as the scenario only
            c = c.loc[c.index.intersection(member_clim(monthly, TOTAL, scen, PERIODS["Far 2071–2100"]).index)]
        ax.fill_between(range(1, 13), c.quantile(.1), c.quantile(.9), color=color, alpha=0.12, lw=0)
        ax.plot(range(1, 13), c.median(), color=color, ls=ls, lw=2, label=label)
    ax.set_xticks(range(1, 13), MONTHS)
    ax.set_title(scen)
axes[0].set_ylabel("runoff (mm/day)")
axes[0].legend()
fig.suptitle("EVANGER_TOTAL monthly runoff")
save(fig, "04_seasonal_cycle_total")
""")

code(r"""
# Monthly change (%) for EVANGER_TOTAL, member-wise, ensemble median
rows = []
for m in range(1, 13):
    sub = monthly[(monthly.basin == TOTAL) & (monthly.month == m)].rename(columns={"mrro_mm": "v"})
    ch = member_change(sub, "v")
    ch["month"] = m
    rows.append(ch)
ch_mon = pd.concat(rows)
tab_m = ch_mon.groupby(["scenario", "period", "month"])["change"].median().unstack()
tab_m = tab_m.reindex(COLS)

fig, ax = plt.subplots(figsize=(10, 3.8))
v = tab_m.to_numpy(dtype=float)
vmax = np.nanmax(np.abs(v))
im = ax.imshow(v, cmap="BrBG", norm=mcolors.TwoSlopeNorm(0, -vmax, vmax), aspect="auto")
ax.set_xticks(range(12), MONTHS)
ax.set_yticks(range(len(COLS)), [f"{s} {p.split()[0]}" for s, p in COLS])
for i in range(v.shape[0]):
    for k in range(12):
        ax.text(k, i, f"{v[i, k]:+.0f}", ha="center", va="center", fontsize=8)
ax.grid(False)
plt.colorbar(im, ax=ax, label="%")
ax.set_title("EVANGER_TOTAL: change in monthly runoff (ensemble median, %)")
save(fig, "05_monthly_change_total")
""")

md(r"""
## 5. Timing and winter share

- **Centre-of-volume date**: day of year when 50 % of the year's runoff has passed (shift in days; negative = earlier).
- **Oct–Mar share**: share of the calendar-year runoff that falls in Jan–Mar + Oct–Dec (change in %-points).
""")

code(r"""
win = monthly[monthly.month.isin([1, 2, 3, 10, 11, 12])].groupby(["basin", "scenario", "member", "year"])["mrro_mm"].sum()
allm = monthly.groupby(["basin", "scenario", "member", "year"])["mrro_mm"].sum()
share = (100 * win / allm).rename("winter_share").reset_index()

ch_cov = member_change(annual, "cov_doy", kind="diff")
ch_win = member_change(share, "winter_share", kind="diff")

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, ch, ylab, title in [(axes[0], ch_cov, "days", "Centre-of-volume date shift"),
                            (axes[1], ch_win, "%-points", "Change in Oct–Mar share")]:
    sub = ch[ch.basin == TOTAL]
    data = [sub[(sub.scenario == s) & (sub.period == p)]["change"] for s, p in COLS]
    bp = ax.boxplot(data, patch_artist=True, widths=0.6)
    for patch, (s, p) in zip(bp["boxes"], COLS):
        patch.set_facecolor(SCEN_COLORS[s]); patch.set_alpha(0.4 if p.startswith("Near") else 0.8)
    ax.set_xticks(range(1, len(COLS) + 1), COL_LABELS, fontsize=8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set(ylabel=ylab, title=f"EVANGER_TOTAL: {title}")
save(fig, "06_timing_winter_share_total")

fig, axes = plt.subplots(1, 2, figsize=(14, 8))
heatmap(axes[0], ens_summary(ch_cov).pivot_table(index="basin", columns=["scenario", "period"], values="median"),
        "Centre-of-volume shift (days)", fmt="{:+.0f}", cmap="RdBu", unit="days")
heatmap(axes[1], ens_summary(ch_win).pivot_table(index="basin", columns=["scenario", "period"], values="median"),
        "Oct–Mar share change (%-points)", fmt="{:+.1f}", cmap="PuOr", unit="%-points")
fig.tight_layout()
save(fig, "07_timing_winter_share_basins")
""")

md(r"""
## 6. High and low flows (no plant thresholds)

Per member and period: the **median of annual maxima** (1-day and 3-day mean runoff) and the median of the
**summer (Jun–Sep) 7-day minimum**; change in % against the member's own reference.
""")

code(r"""
ch_max1 = member_change(annual, "max1d_mm", agg="median")
ch_max3 = member_change(annual, "max3d_mm", agg="median")
ch_min7 = member_change(annual, "min7d_summer_mm", agg="median")

fig, axes = plt.subplots(1, 3, figsize=(15, 4), sharey=False)
for ax, ch, title in [(axes[0], ch_max1, "Annual max 1-day"), (axes[1], ch_max3, "Annual max 3-day"),
                      (axes[2], ch_min7, "Summer 7-day minimum")]:
    sub = ch[ch.basin == TOTAL]
    data = [sub[(sub.scenario == s) & (sub.period == p)]["change"] for s, p in COLS]
    bp = ax.boxplot(data, patch_artist=True, widths=0.6)
    for patch, (s, p) in zip(bp["boxes"], COLS):
        patch.set_facecolor(SCEN_COLORS[s]); patch.set_alpha(0.4 if p.startswith("Near") else 0.8)
    ax.set_xticks(range(1, len(COLS) + 1), COL_LABELS, fontsize=8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set(ylabel="% change", title=f"EVANGER_TOTAL: {title}")
save(fig, "08_extremes_total")

fig, axes = plt.subplots(1, 2, figsize=(14, 8))
heatmap(axes[0], ens_summary(ch_max1).pivot_table(index="basin", columns=["scenario", "period"], values="median"),
        "Annual max 1-day runoff (%)")
heatmap(axes[1], ens_summary(ch_min7).pivot_table(index="basin", columns=["scenario", "period"], values="median"),
        "Summer 7-day minimum (%)")
fig.tight_layout()
save(fig, "09_extremes_basins")
""")

md(r"""
## 7. Dry years (EVANGER_TOTAL)

A year is **dry** if its annual runoff is below the member's own 1991–2020 **20th percentile**
(so 20 % of reference years are dry by definition). Also shown: change in the 1-in-10 dry-year runoff
(10th percentile of annual totals).
""")

code(r"""
def dry_frequency(df, basin):
    d = df[df.basin == basin]
    thr = d[(d.scenario == "hist") & d.year.between(*REF)].groupby("member")["total_mm"].quantile(0.2)
    rows = []
    for scen in SCENARIOS:
        for pname, years in PERIODS.items():
            sub = d[(d.scenario == scen) & d.year.between(*years)]
            f = sub.groupby("member").apply(lambda g: 100 * (g.total_mm < thr.get(g.name, np.nan)).mean())
            rows += [dict(scenario=scen, period=pname, member=m, dry_pct=v) for m, v in f.items()]
    return pd.DataFrame(rows)

dry = dry_frequency(annual, TOTAL)
ch_p10 = member_change(annual, "total_mm", agg=lambda s: s.quantile(0.1))

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, (df_, col, ylab, title, ref_line) in zip(axes, [
        (dry, "dry_pct", "% of years", "Frequency of reference-dry years (ref = 20 %)", 20),
        (ch_p10[ch_p10.basin == TOTAL], "change", "% change", "1-in-10 dry-year runoff", 0)]):
    data = [df_[(df_.scenario == s) & (df_.period == p)][col] for s, p in COLS]
    bp = ax.boxplot(data, patch_artist=True, widths=0.6)
    for patch, (s, p) in zip(bp["boxes"], COLS):
        patch.set_facecolor(SCEN_COLORS[s]); patch.set_alpha(0.4 if p.startswith("Near") else 0.8)
    ax.axhline(ref_line, color="k", lw=0.8)
    ax.set_xticks(range(1, len(COLS) + 1), COL_LABELS, fontsize=8)
    ax.set(ylabel=ylab, title=f"EVANGER_TOTAL: {title}")
save(fig, "10_dry_years_total")
""")

md(r"""
## 8. Sources of uncertainty (EVANGER_TOTAL)

Simplified Hawkins & Sutton (2009) split of the variance of the **10-year mean** annual runoff
(as % of each member's reference):
- **scenario**: variance of the three scenario ensemble means;
- **model × bias adjustment**: mean within-scenario variance across members;
- **internal variability**: variance of the 10-year means around each member's smooth (30-yr) trend, averaged.

Not a full ANOVA: the rcp and ssp ensembles use different models (CMIP5 vs CMIP6).
""")

code(r"""
d = rel_series(annual, TOTAL)
fut = d[d.scenario.isin(SCENARIOS)].copy()
fut["smooth"] = fut.groupby(["scenario", "member"])["rel"].transform(lambda s: s.rolling(30, center=True, min_periods=20).mean())
internal = (fut["rel10"] - fut["smooth"]).groupby(fut.year).var()
by = fut.groupby(["year", "scenario"])["smooth"]
scen_var = by.mean().groupby("year").var()
model_var = by.var().groupby("year").mean()
comp = pd.DataFrame({"scenario": scen_var, "model × bias adj.": model_var, "internal": internal}).dropna()
frac = comp.div(comp.sum(axis=1), axis=0) * 100

fig, ax = plt.subplots(figsize=(8, 4))
ax.stackplot(frac.index, frac.T.values, labels=frac.columns, colors=["#009E73", "#56B4E9", "#CC79A7"], alpha=0.85)
ax.set(xlim=(frac.index.min(), frac.index.max()), ylim=(0, 100), ylabel="% of total variance",
       title="EVANGER_TOTAL: sources of uncertainty, 10-yr mean annual runoff")
ax.legend(loc="lower left")
save(fig, "11_uncertainty_total")
frac.loc[[y for y in (2030, 2050, 2070, 2085) if y in frac.index]].round(0)
""")

md(r"""
## 9. Summary table

Ensemble median (p10–p90) of the member-wise change, for every basin, scenario and period.
Saved as `figures/summary_changes.csv`.
""")

code(r"""
seasons = {"DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]}
pieces = {"annual_%": ch_ann, "max1d_%": ch_max1, "min7d_summer_%": ch_min7,
          "cov_shift_days": ch_cov, "octmar_share_pp": ch_win}
for sname, months in seasons.items():
    sub = monthly[monthly.month.isin(months)].groupby(["basin", "scenario", "member", "year"])["mrro_mm"].mean()
    pieces[f"{sname}_%"] = member_change(sub.rename("v").reset_index(), "v")

summary = []
for name, ch in pieces.items():
    s = ens_summary(ch)
    s["metric"] = name
    summary.append(s)
summary = pd.concat(summary)
summary["text"] = summary.apply(lambda r: f"{r['median']:+.1f} ({r.p10:+.1f} to {r.p90:+.1f})", axis=1)
wide = summary.pivot_table(index=["basin", "scenario", "period"], columns="metric", values="text", aggfunc="first")
wide.to_csv(FIG_DIR / "summary_changes.csv")
wide.loc[TOTAL]
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
json.dump(nb, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print("wrote", sys.argv[1], len(cells), "cells")
