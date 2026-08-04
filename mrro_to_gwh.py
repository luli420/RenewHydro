#!/usr/bin/env python3
"""
Convert Layer 1 delfelt runoff (mm/day) to energy inflow (GWh/day), and roll
individual delfelt up into named basins (handoff notes §5).

Unit chain:
    mrro [mm/day] x area [km^2] x 1000        -> m^3/day
    m^3/day x EnEkv [kWh/m^3] / 1e6            -> GWh/day

Basin rollup uses the delfelt's own upstream list (oppstromDelfeltListe) --
no polygon geometry needed. Because each delfelt's EnEkv already accounts
for every plant its water passes through on the way to the sea
(energy_equivalents.py), summing GWh across a basin's delfelt set gives the
correct total generation from that basin.

Also includes a free validation check (handoff §4, §6 test-sequence item 4):
compares extracted 1991-2020 mean annual volume against NVE's own
QNormalDelfelt9120_Mm3Aar reference for the same period.

Usage:
    python mrro_to_gwh.py \\
        --layer1 layer1_merged.zarr \\
        --catchments delfelt_subcatchments.gpkg \\
        --energy-equivalents delfelt_energy_equivalents.csv \\
        --validate --out-validation validation_1991-2020.csv \\
        --basin "Evanger:12345" --basin "Driva:67890" \\
        --out-dir gwh/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger("mrro_to_gwh")


def _parse_id_list(raw) -> set[str]:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {str(x) for x in raw}
    return {p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()}


def load_layer1(path: Path) -> xr.Dataset:
    return xr.open_zarr(path) if path.suffix == ".zarr" else xr.open_dataset(path)


def mrro_to_gwh(ds: xr.Dataset, area_km2: pd.Series, energy_equiv: pd.Series) -> xr.DataArray:
    """ds['mrro'] must have a 'delfelt' dim matching the index of area_km2/energy_equiv."""
    area_da = xr.DataArray(area_km2.reindex(ds["delfelt"].values).values, dims=("delfelt",), coords={"delfelt": ds["delfelt"]})
    enekv_da = xr.DataArray(
        energy_equiv.reindex(ds["delfelt"].values).fillna(0.0).values, dims=("delfelt",), coords={"delfelt": ds["delfelt"]}
    )
    m3_per_day = ds["mrro"] * area_da * 1000.0
    gwh_per_day = m3_per_day * enekv_da / 1e6
    gwh_per_day.name = "gwh_per_day"
    gwh_per_day.attrs["units"] = "GWh/day"
    return gwh_per_day


def basin_delfelt_set(subcatch_df: pd.DataFrame, outlet_delfelt: str, id_col: str, upstream_col: str) -> set[str]:
    row = subcatch_df.loc[subcatch_df[id_col].astype(str) == str(outlet_delfelt)]
    if row.empty:
        raise KeyError(f"delfeltNr '{outlet_delfelt}' not found in catchments layer")
    upstream = _parse_id_list(row.iloc[0].get(upstream_col))
    return upstream | {str(outlet_delfelt)}


def rollup_basin(data: xr.DataArray, delfelt_ids: set[str]) -> xr.DataArray:
    present = [d for d in delfelt_ids if d in set(data["delfelt"].values.astype(str))]
    missing = delfelt_ids - set(present)
    if missing:
        logger.warning("%d/%d basin delfelt not present in Layer 1 store (outside sliced region?)", len(missing), len(delfelt_ids))
    return data.sel(delfelt=present).sum(dim="delfelt", skipna=True)


def validate_against_normal(
    ds: xr.Dataset,
    subcatch_df: pd.DataFrame,
    area_km2: pd.Series,
    id_col: str = "delfeltNr",
    ref_col: str = "QNormalDelfelt9120_Mm3Aar",
    scenario: str = "hist",
) -> pd.DataFrame:
    """Compare extracted 1991-2020 mean annual volume (Mm3/yr) per delfelt
    against NVE's own reference for the same period -- a free validation
    baseline (handoff §4) that costs nothing to check before showing anyone
    a projection."""
    hist = ds["mrro"].sel(scenario=scenario) if "scenario" in ds["mrro"].dims else ds["mrro"]
    hist = hist.sel(time=slice("1991-01-01", "2020-12-31"))
    if "member" in hist.dims:
        hist = hist.mean(dim="member", skipna=True)

    annual_mm = hist.groupby("time.year").sum(dim="time", skipna=True).mean(dim="year", skipna=True)
    area_da = xr.DataArray(area_km2.reindex(annual_mm["delfelt"].values).values, dims=("delfelt",), coords={"delfelt": annual_mm["delfelt"]})
    annual_volume_Mm3 = annual_mm * area_da / 1000.0  # mm * km2 / 1000 = Mm3

    df = annual_volume_Mm3.to_dataframe(name="extracted_Mm3Aar").reset_index()
    ref = subcatch_df[[id_col, ref_col]].copy()
    ref[id_col] = ref[id_col].astype(str)
    df["delfelt"] = df["delfelt"].astype(str)

    merged = df.merge(ref, left_on="delfelt", right_on=id_col, how="left")
    merged["pct_diff"] = 100.0 * (merged["extracted_Mm3Aar"] - merged[ref_col]) / merged[ref_col]
    return merged


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layer1", type=Path, required=True, help="layer1_merged.zarr or a single layer1_*.nc")
    parser.add_argument("--catchments", type=Path, required=True)
    parser.add_argument("--energy-equivalents", type=Path, required=True)
    parser.add_argument("--id-col", default="delfeltNr")
    parser.add_argument("--area-col", default="delfeltAreal_km2")
    parser.add_argument("--upstream-col", default="oppstromDelfeltListe")
    parser.add_argument(
        "--basin",
        action="append",
        default=[],
        metavar="NAME:OUTLET_DELFELTNR",
        help="Repeatable. e.g. --basin Evanger:12345 --basin Driva:67890",
    )
    parser.add_argument("--validate", action="store_true", help="Run the QNormalDelfelt9120_Mm3Aar cross-check")
    parser.add_argument("--out-validation", type=Path, default=Path("validation_1991-2020.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("gwh"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    ds = load_layer1(args.layer1)
    subcatch_df = gpd.read_file(args.catchments)
    subcatch_df[args.id_col] = subcatch_df[args.id_col].astype(str)
    area_km2 = subcatch_df.set_index(args.id_col)[args.area_col]

    energy_df = pd.read_csv(args.energy_equivalents, dtype={args.id_col: str})
    energy_equiv = energy_df.set_index(args.id_col)["EnEkv_kWh_per_m3"]

    gwh = mrro_to_gwh(ds, area_km2, energy_equiv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    gwh.to_dataset().to_netcdf(args.out_dir / "delfelt_gwh_per_day.nc")
    logger.info("Wrote %s", args.out_dir / "delfelt_gwh_per_day.nc")

    for spec in args.basin:
        name, outlet = spec.split(":", 1)
        delfelt_ids = basin_delfelt_set(subcatch_df, outlet, args.id_col, args.upstream_col)
        basin_gwh = rollup_basin(gwh, delfelt_ids)
        out_path = args.out_dir / f"basin_gwh_{name}.nc"
        basin_gwh.to_dataset(name="gwh_per_day").to_netcdf(out_path)
        logger.info("Basin '%s': %d delfelt, wrote %s", name, len(delfelt_ids), out_path)

    if args.validate:
        report = validate_against_normal(ds, subcatch_df, area_km2, id_col=args.id_col)
        report.to_csv(args.out_validation, index=False)
        logger.info(
            "Validation vs QNormalDelfelt9120_Mm3Aar: median |pct_diff| = %.1f%%, wrote %s",
            report["pct_diff"].abs().median(),
            args.out_validation,
        )


if __name__ == "__main__":
    main()
