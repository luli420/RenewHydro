#!/usr/bin/env python3
"""Per-basin ensemble-median change table (basin_table.json) for build_report.js,
from the notebook's figures/summary_changes.csv and aggregates/areas.csv.

Usage: python make_basin_table.py <figures_dir> <aggregates_dir>
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

fig, agg = Path(sys.argv[1]), Path(sys.argv[2])
w = pd.read_csv(fig / "summary_changes.csv")
areas = pd.read_csv(agg / "areas.csv").set_index("basin")["area_km2"]


def med(text):
    return float(re.match(r"([+-]?[\d.]+)", str(text)).group(1)) if pd.notna(text) else None


rows = []
for basin, g in w.groupby("basin"):
    r = {"basin": basin, "area": round(float(areas[basin]), 1)}
    for _, x in g.iterrows():
        key = f"{x.scenario}|{x.period.split()[0]}"
        r[key] = med(x["annual_%"])
        r[key + "|DJF"] = med(x["DJF_%"])
        r[key + "|JJA"] = med(x["JJA_%"])
    rows.append(r)
order = sorted(b for b in areas.index if b != "EVANGER_TOTAL") + ["EVANGER_TOTAL"]
rows.sort(key=lambda r: order.index(r["basin"]))
json.dump(rows, open(fig / "basin_table.json", "w"), indent=1)
print("wrote", fig / "basin_table.json")
