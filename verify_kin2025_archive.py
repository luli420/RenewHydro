#!/usr/bin/env python3
"""
Verify the local KiN2025 mrro archive by reading every file completely, and
optionally re-download the files that fail.

Why: a file can have the correct size and still be damaged. Confirmed on
Olivia (2026-10-08): .../eqm/hist/noresm-r1i1p1f1-hclim/..._1999.nc4 had the
server's exact size but differed from the server copy from byte 122,257,409,
and every read failed with "NetCDF: HDF error". The size check in
download_mrro_full_archive.sh cannot find this, so run this script after
each download.

Each file is opened and the whole `mrro` variable is read (every compressed
chunk is decoded), in parallel worker processes. With --redownload, each bad
file is fetched again from the THREDDS fileServer (kin2025_config.build_url),
written to a temporary name, verified, and only then moved over the bad file.

Do NOT run this on files that a download job is still writing.

Usage:
    python verify_kin2025_archive.py --archive-dir /cluster/work/projects/nn10014k/luli/kin2025/mrro \\
        --scenarios hist --workers 16 --redownload --report logs/verify_hist.csv -v
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import shutil
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import netCDF4

from kin2025_config import FILESERVER_BASE, METHODS, SCENARIOS, build_url

logger = logging.getLogger("verify_kin2025_archive")


def check_file(path: Path) -> str | None:
    """Return None if the whole mrro variable can be read, else an error message."""
    try:
        with netCDF4.Dataset(path) as nc:
            var = nc.variables["mrro"]
            # Read one time step at a time: decodes every chunk without
            # holding a whole year (~1 GB uncompressed) in memory.
            for t in range(var.shape[0]):
                var[t]
        return None
    except Exception as exc:  # noqa: BLE001 -- any failure means the file is bad
        return f"{type(exc).__name__}: {exc}"


def redownload(path: Path, archive_dir: Path) -> str | None:
    """Fetch `path` again into a temporary file; replace the bad file only if
    the new copy reads cleanly. Return None on success, else an error."""
    method, scenario, model = path.relative_to(archive_dir).parts[:3]
    year = int(path.stem.rsplit("_", 1)[1])
    url, _ = build_url(method, scenario, model, year, base=FILESERVER_BASE)
    tmp = path.with_name(path.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, length=16 * 1024 * 1024)
        err = check_file(tmp)
        if err:
            return f"new copy also bad: {err}"
        os.replace(tmp, path)
        return None
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    finally:
        tmp.unlink(missing_ok=True)


def list_files(archive_dir: Path, scenarios: list[str], methods: list[str]) -> list[Path]:
    files: list[Path] = []
    for method in methods:
        for scenario in scenarios:
            files.extend(sorted((archive_dir / method / scenario).glob("*/*.nc4")))
    return files


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive-dir", type=Path, required=True, help="Archive root (method/scenario/model/*.nc4)")
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS.keys()), choices=list(SCENARIOS.keys()))
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=METHODS)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "4")))
    parser.add_argument("--redownload", action="store_true", help="Fetch bad files again and verify the new copy")
    parser.add_argument("--report", type=Path, default=None, help="CSV of bad files (path, error, redownload result)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    files = list_files(args.archive_dir, args.scenarios, args.methods)
    logger.info("Checking %d files with %d workers", len(files), args.workers)

    bad: dict[Path, str] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_file, f): f for f in files}
        for i, fut in enumerate(as_completed(futures), 1):
            err = fut.result()
            if err:
                bad[futures[fut]] = err
                logger.warning("BAD %s -- %s", futures[fut], err)
            if i % 200 == 0:
                logger.info("%d/%d checked, %d bad so far", i, len(files), len(bad))
    logger.info("Check done: %d of %d files bad", len(bad), len(files))

    results: dict[Path, str] = {}
    if args.redownload:
        for path in sorted(bad):
            res = redownload(path, args.archive_dir)
            results[path] = "fixed" if res is None else f"FAILED: {res}"
            logger.info("Redownload %s: %s", path.name, results[path])

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["path", "error", "redownload"])
            for path in sorted(bad):
                w.writerow([path, bad[path], results.get(path, "not attempted")])
        logger.info("Wrote %s", args.report)

    unresolved = [p for p in bad if results.get(p) != "fixed"]
    if unresolved:
        raise SystemExit(f"{len(unresolved)} bad file(s) remain -- see the log/report")


if __name__ == "__main__":
    main()
