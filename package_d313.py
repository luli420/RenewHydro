#!/usr/bin/env python3
"""
Build the RenewHydro deliverable D3.1.3 data package: projected daily runoff
(KiN2025) for the Evanger sub-basins, documented and ready to share.

Input: the per-basin "<basin>__all.csv" files from split_runoff_csv.py (all
scenarios incl. hist, plus the area-weighted EVANGER_TOTAL), the catchment
GeoPackage, and nve_normals.csv.

Output (--out-dir):
  daily_csv/<basin>.csv.gz      date, scenario, model, method, member,
                                runoff_mm_day, discharge_m3s
  netcdf/evanger_kin2025_runoff_<scenario>.nc
                                runoff(basin, member, time) in mm/day, with
                                area_km2(basin); CF-style attributes
  basins/                       GeoPackage (UTM 33N), GeoJSON (WGS84),
                                basin_attributes.csv
  members.csv                   scenario, model, GCM, ensemble, RCM, method, years
  README.md                     copied from --readme
  checksums.md5

Usage:
    python package_d313.py --input-dir .../projections/input \\
        --catchments Evanger_system/evanger_local_subcatchments.gpkg \\
        --nve-normals .../projections/aggregates/nve_normals.csv \\
        --readme docs/D3.1.3_README.md --out-dir .../D3.1.3_KiN2025_Evanger_runoff -v
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

from kin2025_config import SCENARIOS

logger = logging.getLogger("package_d313")

TOTAL = "EVANGER_TOTAL"


def split_model(model: str) -> tuple[str, str, str]:
    """'cnrm-r1i1p1f2-hclim' -> ('cnrm', 'r1i1p1f2', 'hclim')."""
    gcm, ens, rcm = model.split("-")
    return gcm, ens, rcm


def write_csvs(input_dir: Path, basins: list[str], areas: pd.Series, out: Path) -> dict[str, pd.DataFrame]:
    out.mkdir(parents=True, exist_ok=True)
    frames = {}
    for b in basins:
        df = pd.read_csv(input_dir / f"{b}__all.csv")
        df["member"] = df["model"] + "_" + df["method"]
        df = df.rename(columns={"mrro_mm": "runoff_mm_day"})
        df["discharge_m3s"] = df["runoff_mm_day"] * areas[b] * 1000.0 / 86400.0
        df = df.sort_values(["scenario", "model", "method", "date"])
        cols = ["date", "scenario", "model", "method", "member", "runoff_mm_day", "discharge_m3s"]
        df[cols].to_csv(out / f"{b}.csv.gz", index=False, float_format="%.5g", compression="gzip")
        frames[b] = df[cols].astype({c: "category" for c in ["date", "scenario", "model", "method", "member"]})
        logger.info("CSV %s: %d rows", b, len(df))
    return frames


def read_csvs(out: Path, basins: list[str]) -> dict[str, pd.DataFrame]:
    """Reload already written daily CSVs (for --skip-csv)."""
    cats = {c: "category" for c in ["date", "scenario", "model", "method", "member"]}
    return {b: pd.read_csv(out / f"{b}.csv.gz", dtype=cats) for b in basins}


def write_netcdf(frames: dict[str, pd.DataFrame], basins: list[str], areas: pd.Series, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for scen in SCENARIOS:
        parts = []
        for b in basins:
            d = frames[b][frames[b]["scenario"] == scen]
            # NetCDF cannot store pandas categoricals: use plain strings for the index
            d = d.astype({"member": str, "date": str})
            parts.append(d.assign(basin=b).set_index(["basin", "member", "date"])["runoff_mm_day"])
        s = pd.concat(parts)
        da = s.to_xarray().astype("float32")
        da = da.assign_coords(time=("date", pd.to_datetime(da["date"].values))).swap_dims(date="time").drop_vars("date")
        members = da["member"].values
        ds = xr.Dataset({"runoff": da.transpose("basin", "member", "time")})
        ds = ds.assign_coords(
            area_km2=("basin", areas.reindex(ds["basin"].values).to_numpy()),
            model=("member", [m.rsplit("_", 1)[0] for m in members]),
            method=("member", [m.rsplit("_", 1)[1] for m in members]),
        )
        ds["runoff"].attrs = {
            "long_name": "basin-mean daily runoff (local, unrouted)",
            "units": "mm day-1",
            "source_variable": "mrro (kg m-2 s-1) x 86400",
            "cell_methods": "area: mean (coverage-weighted over basin) time: mean (daily)",
        }
        ds["area_km2"].attrs = {"long_name": "basin area (NVE areal_km2)", "units": "km2"}
        ds.attrs = {
            "title": f"KiN2025 projected runoff for Evanger sub-basins, scenario {scen}",
            "project": "RenewHydro (FME), deliverable D3.1.3",
            "institution": "NORCE Norwegian Research Centre",
            "source": "Klima i Norge 2025 (KiN2025), distHBV-COR-BA-2025 mrro, 1 km, NVE/MET Norway/NCCS",
            "scenario": scen,
            "basins": f"21 local sub-catchments of the Evanger system + {TOTAL} (area-weighted mean)",
            "note": "Natural (unregulated) local runoff, no routing. Use changes relative to hist, not absolute values: "
                    "1991-2020 hist runoff is ~0.80 x NVE QN9120 normals for these basins.",
            "Conventions": "CF-1.8",
        }
        enc = {"runoff": {"zlib": True, "complevel": 4, "dtype": "float32"}}
        path = out / f"evanger_kin2025_runoff_{scen}.nc"
        ds.to_netcdf(path, encoding=enc)
        logger.info("NetCDF %s: %s", path.name, dict(ds.sizes))


def write_basins(catchments: Path, nve: Path, frames: dict[str, pd.DataFrame], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    g = gpd.read_file(catchments)
    g.to_file(out / "evanger_local_subcatchments_utm33.gpkg", driver="GPKG")
    g.to_crs("EPSG:4326").to_file(out / "evanger_local_subcatchments_wgs84.geojson", driver="GeoJSON")
    attrs = pd.read_csv(nve)
    ref = {}
    for b, df in frames.items():
        h = df[(df["scenario"] == "hist") & pd.to_datetime(df["date"]).dt.year.between(1991, 2020)]
        ref[b] = h.groupby("member")["runoff_mm_day"].mean().median() * 365.25
    attrs["kin2025_hist_1991_2020_mm_yr"] = attrs["basin"].map(ref).round(0)
    attrs.to_csv(out / "basin_attributes.csv", index=False)


def write_members(frames: dict[str, pd.DataFrame], out: Path) -> None:
    d = frames[TOTAL].assign(year=lambda x: pd.to_datetime(x["date"]).dt.year)
    d = d.astype({"scenario": str, "model": str, "method": str})
    m = d.groupby(["scenario", "model", "method"])["year"].agg(["min", "max"]).reset_index()
    m[["gcm", "ensemble", "rcm"]] = pd.DataFrame([split_model(x) for x in m["model"]], index=m.index)
    m["cmip"] = np.where(m["ensemble"].str.contains("f"), "CMIP6", "CMIP5")
    m = m.rename(columns={"min": "first_year", "max": "last_year"})
    m[["scenario", "model", "gcm", "ensemble", "rcm", "cmip", "method", "first_year", "last_year"]].to_csv(out / "members.csv", index=False)


def write_checksums(out: Path) -> None:
    lines = []
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "checksums.md5"):
        h = hashlib.md5()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {f.relative_to(out)}")
    (out / "checksums.md5").write_text("\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--catchments", type=Path, required=True)
    parser.add_argument("--nve-normals", type=Path, required=True)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--skip-csv", action="store_true", help="Reuse daily_csv/ from an earlier run")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    areas = pd.read_csv(args.input_dir / "areas.csv").set_index("basin")["area_km2"]
    basins = sorted(b for b in areas.index if b != TOTAL) + [TOTAL]

    if args.skip_csv:
        frames = read_csvs(out / "daily_csv", basins)
    else:
        frames = write_csvs(args.input_dir, basins, areas, out / "daily_csv")
    write_netcdf(frames, basins, areas, out / "netcdf")
    write_basins(args.catchments, args.nve_normals, frames, out / "basins")
    write_members(frames, out)
    shutil.copy(args.readme, out / "README.md")
    write_checksums(out)
    logger.info("Package ready: %s", out)


if __name__ == "__main__":
    main()
