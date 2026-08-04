#!/usr/bin/env python3
"""
Build a delfeltNr -> energy-equivalent (kWh/m^3) mapping, so Layer 1 runoff
volumes can be converted to GWh (handoff notes §5).

Logic: for each delfelt, sum the energy equivalents (EnEkv) of every plant
its water passes through on the way to the sea.

  1. From the subcatchment layer (fetch_nve_subcatchments.py output), read
     delfeltNr, vannkraftverkNr, oppstromDelfeltListe.
  2. Build a plant -> delfelt topology: each plant's own delfelt plus every
     delfelt in its oppstromDelfeltListe (oppstromDelfeltListe is already
     the accumulated upstream set, same semantics as NEVINA's total
     catchments used previously -- see CLAUDE.md).
  3. Walk the downstream plant chain to also catch delfelt separated from a
     plant by another plant with no subcatchment in between (broken links).
  4. Fetch plant attributes (EnEkv etc.) from
     https://api.nve.no/web/Powerplant/GetHydroPowerPlantsInOperation.
  5. Invert (2)+(3) and sum EnEkv per delfeltNr.

NOTE: api.nve.no is not reachable from the Claude Code sandbox this script
was written in -- NOT executed against the live API. The exact field name
for the downstream plant chain ("nedstromvannkraftverknr_liste" per handoff
notes) is unconfirmed; DOWNSTREAM_FIELD_CANDIDATES lists guesses to try.
Verify against the real API response (e.g. `print(plants_df.columns)`) on
Olivia before trusting output.

Usage:
    python energy_equivalents.py --catchments delfelt_subcatchments.gpkg \\
        --out delfelt_energy_equivalents.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

logger = logging.getLogger("energy_equivalents")

PLANT_API_URL = "https://api.nve.no/web/Powerplant/GetHydroPowerPlantsInOperation"
PLANT_ID_COL = "VannKraftverkID"
PLANT_FIELDS = [PLANT_ID_COL, "Navn", "MaksYtelse", "MidProd_91_20", "EnEkv"]

# Unconfirmed -- see module docstring.
DOWNSTREAM_FIELD_CANDIDATES = [
    "nedstromvannkraftverknr_liste",
    "nedstromVannkraftverkNrListe",
    "NedstromsVannkraftverkNrListe",
]


def _parse_id_list(raw) -> set:
    """NVE typically returns these accumulation lists as delimited strings;
    handle that, plain lists, and missing values uniformly."""
    if raw is None:
        return set()
    if isinstance(raw, float) and np.isnan(raw):
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {str(x) for x in raw}
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]
    return set(parts)


def fetch_plant_attributes() -> pd.DataFrame:
    resp = requests.get(PLANT_API_URL, timeout=60)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    missing = [c for c in PLANT_FIELDS if c not in df.columns]
    if missing:
        logger.warning("Plant API response missing expected fields %s; available: %s", missing, list(df.columns))
    df[PLANT_ID_COL] = df[PLANT_ID_COL].astype(str)
    return df


def build_plant_upstream_delfelt(
    subcatch_df: pd.DataFrame, id_col: str, plant_col: str, upstream_col: str
) -> dict[str, set]:
    plant_delfelt: dict[str, set] = {}
    for _, row in subcatch_df.dropna(subset=[plant_col]).iterrows():
        plant = str(row[plant_col])
        own = _parse_id_list(row.get(upstream_col)) | {str(row[id_col])}
        plant_delfelt.setdefault(plant, set()).update(own)
    return plant_delfelt


def build_downstream_plant_graph(plants_df: pd.DataFrame) -> dict[str, set]:
    field = next((c for c in DOWNSTREAM_FIELD_CANDIDATES if c in plants_df.columns), None)
    if field is None:
        logger.warning(
            "No downstream-plant-chain field found (tried %s); cascade linking for "
            "plants separated by no subcatchment will be skipped -- see module docstring",
            DOWNSTREAM_FIELD_CANDIDATES,
        )
        return {}
    graph = {}
    for _, row in plants_df.iterrows():
        graph[str(row[PLANT_ID_COL])] = _parse_id_list(row.get(field))
    return graph


def propagate_downstream(plant_delfelt: dict[str, set], downstream_graph: dict[str, set]) -> dict[str, set]:
    """Fixed-point propagation: a downstream plant's reach must include
    everything upstream of any plant chained directly above it."""
    changed = True
    while changed:
        changed = False
        for plant, downstream_plants in downstream_graph.items():
            upstream_set = plant_delfelt.get(plant, set())
            if not upstream_set:
                continue
            for dnp in downstream_plants:
                if dnp not in plant_delfelt:
                    continue
                before = len(plant_delfelt[dnp])
                plant_delfelt[dnp] |= upstream_set
                if len(plant_delfelt[dnp]) != before:
                    changed = True
    return plant_delfelt


def invert_to_delfelt_plants(plant_delfelt: dict[str, set]) -> dict[str, set]:
    delfelt_plants: dict[str, set] = {}
    for plant, delfelt_set in plant_delfelt.items():
        for d in delfelt_set:
            delfelt_plants.setdefault(d, set()).add(plant)
    return delfelt_plants


def compute_delfelt_energy_equivalents(
    subcatch_df: pd.DataFrame,
    plants_df: pd.DataFrame,
    id_col: str = "delfeltNr",
    plant_col: str = "vannkraftverkNr",
    upstream_col: str = "oppstromDelfeltListe",
) -> pd.DataFrame:
    plant_delfelt = build_plant_upstream_delfelt(subcatch_df, id_col=id_col, plant_col=plant_col, upstream_col=upstream_col)
    downstream_graph = build_downstream_plant_graph(plants_df)
    plant_delfelt = propagate_downstream(plant_delfelt, downstream_graph)
    delfelt_plants = invert_to_delfelt_plants(plant_delfelt)

    en_ekv = plants_df.set_index(PLANT_ID_COL)["EnEkv"] if "EnEkv" in plants_df.columns else pd.Series(dtype=float)

    rows = []
    for delfelt, plants in delfelt_plants.items():
        total = sum(float(en_ekv.get(p, 0.0) or 0.0) for p in plants)
        rows.append({id_col: delfelt, "EnEkv_kWh_per_m3": total, "n_plants_downstream": len(plants)})
    result = pd.DataFrame(rows)

    all_delfelt = {str(x) for x in subcatch_df[id_col]}
    missing = all_delfelt - set(result[id_col]) if not result.empty else all_delfelt
    if missing:
        filler = pd.DataFrame({id_col: sorted(missing), "EnEkv_kWh_per_m3": 0.0, "n_plants_downstream": 0})
        result = pd.concat([result, filler], ignore_index=True)

    return result.sort_values(id_col).reset_index(drop=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catchments", type=Path, required=True)
    parser.add_argument("--id-col", default="delfeltNr")
    parser.add_argument("--plant-col", default="vannkraftverkNr")
    parser.add_argument("--upstream-col", default="oppstromDelfeltListe")
    parser.add_argument("--out", type=Path, default=Path("delfelt_energy_equivalents.csv"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    subcatch_df = gpd.read_file(args.catchments)
    plants_df = fetch_plant_attributes()
    result = compute_delfelt_energy_equivalents(
        subcatch_df, plants_df, id_col=args.id_col, plant_col=args.plant_col, upstream_col=args.upstream_col
    )
    result.to_csv(args.out, index=False)
    logger.info("Wrote %s (%d delfelt)", args.out, len(result))


if __name__ == "__main__":
    main()
