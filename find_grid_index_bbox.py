#!/usr/bin/env python3
"""
Turn a lon/lat bounding box into an Xc/Yc grid-index slice on the KiN2025
seNorge grid, by opening one sample file over OPeNDAP and searching its 2D
lat/lon auxiliary coordinates.

Why: the archive is indexed by Xc/Yc (grid cell index), not lon/lat or a
projected x/y -- see download_mrro_vestlandet_subset.py, which already
hardcodes a Vestlandet slice (Xc 45:175, Yc 1165:1290). Handoff notes §8
flag that the region must be re-derived/extended to also cover Driva
(Oppdal, central Norway) -- this script operationalizes that check instead
of guessing indices by hand.

Usage:
    python find_grid_index_bbox.py --lon-min 4.0 --lat-min 58.5 \\
        --lon-max 12.5 --lat-max 64.0 \\
        --sample-year 1991 --model cnrm-r1i1p1-aladin --method eqm

Prints the Xc/Yc slice to use, plus how many grid cells it covers, so the
result can be sanity-checked before being pasted into an extraction config.
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import xarray as xr

from kin2025_config import OPENDAP_BASE, build_url

logger = logging.getLogger("find_grid_index_bbox")


def find_index_bbox(
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    method: str,
    model: str,
    scenario: str,
    year: int,
    base: str = OPENDAP_BASE,
) -> tuple[slice, slice]:
    url, _ = build_url(method=method, scenario=scenario, model=model, year=year, base=base)
    logger.info("Opening sample file %s", url)
    ds = xr.open_dataset(url)

    lat_name = next((n for n in ("lat", "latitude") if n in ds.coords or n in ds.variables), None)
    lon_name = next((n for n in ("lon", "longitude") if n in ds.coords or n in ds.variables), None)
    if lat_name is None or lon_name is None:
        raise KeyError(
            f"Could not find lat/lon auxiliary coordinates in {url}. "
            f"Available variables: {list(ds.variables)}"
        )

    lat = ds[lat_name].values
    lon = ds[lon_name].values
    if lat.ndim != 2 or lon.ndim != 2:
        raise ValueError(f"Expected 2D lat/lon arrays (Yc, Xc); got shapes {lat.shape}, {lon.shape}")

    mask = (lat >= lat_min) & (lat <= lat_max) & (lon >= lon_min) & (lon <= lon_max)
    if not mask.any():
        raise ValueError("No grid cells fall inside the requested lon/lat box")

    yc_idx, xc_idx = np.where(mask)
    yc_slice = slice(int(yc_idx.min()), int(yc_idx.max()) + 1)
    xc_slice = slice(int(xc_idx.min()), int(xc_idx.max()) + 1)

    logger.info(
        "Xc %d:%d (%d cells), Yc %d:%d (%d cells)",
        xc_slice.start, xc_slice.stop, xc_slice.stop - xc_slice.start,
        yc_slice.start, yc_slice.stop, yc_slice.stop - yc_slice.start,
    )
    return yc_slice, xc_slice


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lon-min", type=float, required=True)
    parser.add_argument("--lat-min", type=float, required=True)
    parser.add_argument("--lon-max", type=float, required=True)
    parser.add_argument("--lat-max", type=float, required=True)
    parser.add_argument("--method", default="eqm")
    parser.add_argument("--model", default="cnrm-r1i1p1-aladin")
    parser.add_argument("--scenario", default="hist")
    parser.add_argument("--sample-year", type=int, default=1991)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    yc_slice, xc_slice = find_index_bbox(
        lon_min=args.lon_min,
        lat_min=args.lat_min,
        lon_max=args.lon_max,
        lat_max=args.lat_max,
        method=args.method,
        model=args.model,
        scenario=args.scenario,
        year=args.sample_year,
    )
    print(f"Yc slice: {yc_slice.start}:{yc_slice.stop}")
    print(f"Xc slice: {xc_slice.start}:{xc_slice.stop}")


if __name__ == "__main__":
    main()
