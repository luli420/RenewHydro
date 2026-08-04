#!/usr/bin/env python3
"""
Merge all per-(scenario, member) Layer 1 files produced by
extract_layer1_timeseries.py into a single store with dims
(delfelt, time, member, scenario).

Keeps `model` and `method` (bias-adjustment) as separate coordinates on
`member`, not just a flat member label -- the 20 members are 10 GCM-RCM
pairs x 2 bias-adjustment methods, not independent draws, and this pairing
is needed for the variance decomposition in handoff notes §7.6.

Different scenarios cover different, only partly-overlapping members and
time ranges (rcp26/rcp45 = 10 CMIP5 members, ssp370 = 10 CMIP6 members,
hist = all 20; a handful of HadGEM-driven runs stop at 2098) -- this is
handled by outer-joining on time and member, leaving NaN where a given
scenario/member/date combination doesn't exist in the archive.

Usage:
    python merge_layer1_outputs.py --layer1-dir layer1/ --out layer1_merged.zarr
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import xarray as xr

logger = logging.getLogger("merge_layer1_outputs")


def merge(layer1_dir: Path) -> xr.Dataset:
    files = sorted(layer1_dir.glob("layer1_*.nc"))
    if not files:
        raise FileNotFoundError(f"No layer1_*.nc files found under {layer1_dir}")

    per_scenario: dict[str, list[xr.Dataset]] = {}
    for f in files:
        ds = xr.open_dataset(f)
        member_id = ds.attrs["member_id"]
        scenario = ds.attrs["scenario"]
        ds = ds.expand_dims(member=[member_id])
        ds = ds.assign_coords(
            model=("member", [ds.attrs["model"]]),
            method=("member", [ds.attrs["method"]]),
        )
        per_scenario.setdefault(scenario, []).append(ds)

    scenario_datasets = []
    for scenario, ds_list in per_scenario.items():
        merged = xr.concat(ds_list, dim="member", join="outer")
        merged = merged.expand_dims(scenario=[scenario])
        scenario_datasets.append(merged)
        logger.info("scenario=%s: %d members merged", scenario, len(ds_list))

    combined = xr.concat(scenario_datasets, dim="scenario", join="outer")
    combined.attrs.update(
        {
            "source": "NCCS Klima i Norge 2025 (KiN2025), distHBV-COR-BA-2025, mrro",
            "note": "member dimension = model x method (bias-adjustment); keep paired for variance decomposition",
        }
    )
    return combined


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layer1-dir", type=Path, default=Path("layer1"))
    parser.add_argument("--out", type=Path, default=Path("layer1_merged.zarr"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    combined = merge(args.layer1_dir)
    logger.info("Combined dataset dims: %s", dict(combined.sizes))
    combined.to_zarr(args.out, mode="w")
    logger.info("Wrote %s", args.out)


if __name__ == "__main__":
    main()
