#!/usr/bin/env python3
"""
Layer 1 extraction (handoff notes §3, §6): for ONE ensemble member
(method + model) and ONE scenario, read every year's daily mrro file once,
apply the precomputed sparse weight matrix W (build_weight_matrix.py) to
get area-weighted daily runoff for every delfelt in a single matrix
multiply per year, and write one compact per-member output file.

This is the unit of work for one SLURM array task (see run_layer1_array.sh)
-- designed to be embarrassingly parallel across the ~50-60
(scenario, member) combinations in the archive, touching each source file
exactly once.

A Layer 2 gridded cache-write (handoff §3) could be added into this same
per-year loop later, so the archive genuinely only gets read once -- not
implemented yet, see CLAUDE.md.

Reads from a local directory (if the archive was already pulled to NIRD via
download_mrro_full_archive.sh -- pass --local-dir) or straight over OPeNDAP
otherwise.

Usage:
    python extract_layer1_timeseries.py \\
        --method eqm --model cnrm-r1i1p1-aladin --scenario hist \\
        --weights weights/delfelt_weights.npz \\
        --out-dir layer1/
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
import xarray as xr

from kin2025_config import OPENDAP_BASE, build_url, years_for

logger = logging.getLogger("extract_layer1_timeseries")


def load_weights(weights_path: Path) -> tuple[sp.csr_matrix, dict]:
    W = sp.load_npz(weights_path)
    meta = json.loads(weights_path.with_suffix(".json").read_text())
    return W, meta


def open_year(
    method: str, model: str, scenario: str, year: int, yc_slice: slice, xc_slice: slice,
    local_dir: Path | None, opendap_base: str,
) -> xr.DataArray:
    if local_dir is not None:
        fname = f"{model}_{scenario}_{method}-estobs_disthbv_norway_1km_mrro_daily_{year}.nc4"
        path = local_dir / method / scenario / model / fname
        if not path.exists():
            raise FileNotFoundError(f"Expected local file not found: {path}")
        ds = xr.open_dataset(path)
    else:
        url, _ = build_url(method=method, scenario=scenario, model=model, year=year, base=opendap_base)
        ds = xr.open_dataset(url)

    da = ds["mrro"].isel(Yc=yc_slice, Xc=xc_slice)
    return da


_UNITS_LOGGED = False

# Source `units` attribute -> factor that converts the values to mm/day.
# CONFIRMED on the real archive on Olivia (2026-10-07, hist/eqm/cnrm-r1i1p1-aladin):
# KiN2025 mrro is stored as a flux in "kg m-2 s-1" (1 kg m-2 = 1 mm of water),
# so x86400 gives mm/day. After the conversion, Evanger's 1991-2020 annual
# totals are 2,000-3,060 mm, the same order as NVE's QN9120 normals (2,675-3,570 mm).
# Unknown units raise an error rather than pass through silently.
UNIT_TO_MM_PER_DAY = {
    "kg m-2 s-1": 86400.0,
    "kg m**-2 s**-1": 86400.0,
    "kg/m2/s": 86400.0,
    "mm s-1": 86400.0,
    "mm/s": 86400.0,
    "mm day-1": 1.0,
    "mm/day": 1.0,
    "mm d-1": 1.0,
}


def _log_units_once(da: xr.DataArray) -> None:
    global _UNITS_LOGGED
    if not _UNITS_LOGGED:
        units = da.attrs.get("units", "<missing units attribute>")
        logger.info("mrro units attribute: %s -- converted to mm/day with factor %s", units, UNIT_TO_MM_PER_DAY.get(units.strip(), "<unknown>"))
        _UNITS_LOGGED = True


def mm_per_day_factor(da: xr.DataArray) -> float:
    units = str(da.attrs.get("units", "")).strip()
    if units not in UNIT_TO_MM_PER_DAY:
        raise ValueError(
            f"Unknown mrro units {units!r} -- add the correct mm/day factor to "
            "UNIT_TO_MM_PER_DAY in extract_layer1_timeseries.py after checking the source file"
        )
    return UNIT_TO_MM_PER_DAY[units]


def extract_member(
    method: str,
    model: str,
    scenario: str,
    W: sp.csr_matrix,
    meta: dict,
    local_dir: Path | None,
    opendap_base: str,
) -> xr.Dataset:
    yc_slice = slice(*meta["yc_slice"])
    xc_slice = slice(*meta["xc_slice"])
    ny, nx = meta["grid_shape"]

    all_times: list[np.ndarray] = []
    all_values: list[np.ndarray] = []

    for year in years_for(scenario, model):
        logger.info("member=%s_%s scenario=%s year=%d", model, method, scenario, year)
        da = open_year(method, model, scenario, year, yc_slice, xc_slice, local_dir, opendap_base)
        _log_units_once(da)

        if da.shape[-2:] != (ny, nx):
            raise ValueError(
                f"Grid shape mismatch for {model}/{method}/{scenario}/{year}: "
                f"got {da.shape[-2:]}, weight matrix built for {(ny, nx)}"
            )

        ntime = da.sizes["time"]
        R = da.values.reshape(ntime, ny * nx)  # row-major: matches W's flat = Yc_idx*nx + Xc_idx
        R = np.nan_to_num(R, nan=0.0)  # cells outside the archive's land mask; W already excludes zero-overlap delfelt

        basin_means = (W @ R.T).T * mm_per_day_factor(da)  # (ntime, n_delfelt), mm/day

        all_times.append(da["time"].values)
        all_values.append(basin_means)
        da.close()

    time = np.concatenate(all_times)
    values = np.concatenate(all_values, axis=0)

    ds_out = xr.Dataset(
        {"mrro": (("time", "delfelt"), values)},
        coords={"time": time, "delfelt": meta["delfelt_ids"]},
        attrs={
            "method": method,
            "model": model,
            "scenario": scenario,
            "member_id": f"{model}_{method}",
            "units": "mm/day",
            "coverage_weighting": meta.get("coverage_method", "unknown"),
            "source": "NCCS Klima i Norge 2025 (KiN2025), distHBV-COR-BA-2025, mrro",
        },
    )
    return ds_out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--method", required=True, choices=["eqm", "3dbc-eqm"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--scenario", required=True, choices=["hist", "rcp26", "rcp45", "ssp370"])
    parser.add_argument("--weights", type=Path, required=True, help="Path to weights .npz from build_weight_matrix.py")
    parser.add_argument("--local-dir", type=Path, default=None, help="Local archive root (as populated by download_mrro_full_archive.sh); omit to read over OPeNDAP")
    parser.add_argument("--opendap-base", default=OPENDAP_BASE)
    parser.add_argument("--out-dir", type=Path, default=Path("layer1"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    W, meta = load_weights(args.weights)
    ds_out = extract_member(
        method=args.method,
        model=args.model,
        scenario=args.scenario,
        W=W,
        meta=meta,
        local_dir=args.local_dir,
        opendap_base=args.opendap_base,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"layer1_{args.model}_{args.method}_{args.scenario}.nc"
    ds_out.to_netcdf(out_path)
    logger.info("Wrote %s (%d timesteps x %d delfelt)", out_path, ds_out.sizes["time"], ds_out.sizes["delfelt"])


if __name__ == "__main__":
    main()
