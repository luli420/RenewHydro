#!/usr/bin/env python3
"""
Fetch NVE subcatchment ("delfelt") polygons for hydropower basin analysis
from the ArcGIS REST endpoint:

    https://gis3.nve.no/map/rest/services/Mapservices/VassdragsreguleringVannkraft/MapServer/8/query

This replaces the NEVINA-polygon approach used previously (see CLAUDE.md):
NVE's delfelt layer already ships the accumulation topology
(`oppstromDelfeltListe`, `nesteDelfeltNr`), so no polygon-containment
differencing is needed -- delfelt ARE the local/incremental units, and any
larger basin is just the sum of the delfelt in its upstream list.

Fixes three bugs found in NVE/API's reference script
(`hydropower/hydropower_gis_subcatchments.py`):

  1. Geometry (critical). The reference script flattens each polygon's
     Esri-JSON `rings` into a MultiPoint of vertices, discarding the
     interior entirely -- unusable for masking/zonal stats. Here we
     rebuild proper Polygon/MultiPolygon geometry from the rings, honoring
     Esri's ring-winding convention (clockwise = exterior/new part,
     counter-clockwise = hole in the preceding exterior).
  2. Export format: writes GeoPackage (preserves geometry), not .xlsx.
  3. CRS: requests `outSR=25833` explicitly (UTM33N, NVE's standard)
     instead of inheriting the service default.

NOTE: gis3.nve.no is not reachable from the Claude Code sandbox this script
was written in (network allowlist covers GitHub/PyPI/npm only) -- it has
NOT been executed against the live service. Run and verify on Olivia or any
machine with open outbound access before trusting the output (see CLAUDE.md
"Open items"), and visually check that both Evanger and Driva catchments
land inside --bbox before using it for extraction.

Usage:
    python fetch_nve_subcatchments.py --out delfelt_subcatchments.gpkg \\
        --bbox 4.0 58.5 12.5 64.0
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import MultiPolygon, Polygon

logger = logging.getLogger("fetch_nve_subcatchments")

ENDPOINT = (
    "https://gis3.nve.no/map/rest/services/Mapservices/"
    "VassdragsreguleringVannkraft/MapServer/8/query"
)

OUT_SR = 25833  # UTM33N, NVE's standard -- fix #3

FIELDS = [
    "OBJECTID",
    "objektType",
    "delfeltNr",
    "delfeltNavn",
    "delfeltAreal_km2",
    "vannkraftverkNr",
    "vannkraftverkNavn",
    "magasinNr",
    "magasinNavn",
    "nesteDelfeltNr",
    "delfeltFormal",
    "vassdragsomradeNr",
    "oppstromDelfeltListe",
    "QNormalDelfelt6190_Mm3Aar",
    "QNormalDelfelt9120_Mm3Aar",
]

PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60
SLEEP_BETWEEN_PAGES = 0.5

# First-guess bounding box (lon/lat, WGS84) meant to cover both case
# studies: Evanger (Vestland, ~60.6N 6.3E) and Driva/Oppdal (Trondelag,
# ~62.6N 9.7E). Per handoff notes: "verify visually that Driva's catchment
# is inside the box before committing" -- this has NOT been visually
# checked (no NVE/map access in this environment).
DEFAULT_BBOX_WGS84 = (4.0, 58.5, 12.5, 64.0)  # xmin, ymin, xmax, ymax


# ---------------------------------------------------------------------------
# Esri-JSON ring -> shapely Polygon/MultiPolygon (fix #1)
# ---------------------------------------------------------------------------


def _ring_is_clockwise(ring: list[list[float]]) -> bool:
    """Esri JSON convention: exterior rings are clockwise, holes are
    counter-clockwise, via the shoelace-sum test used by ArcGIS's own
    JSON<->geometry converters."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        total += (x2 - x1) * (y2 + y1)
    return total >= 0.0


def rings_to_polygon(rings: list[list[list[float]]]) -> Polygon | MultiPolygon:
    """Rebuild a proper polygon geometry from Esri JSON rings, handling
    multiple exterior parts (MultiPolygon) and interior rings (holes)."""
    parts: list[tuple[list, list]] = []  # (exterior, [holes])
    for ring in rings:
        if len(ring) < 4:
            continue
        if _ring_is_clockwise(ring):
            parts.append((ring, []))
        else:
            if not parts:
                logger.warning("Hole ring with no preceding exterior; skipping")
                continue
            parts[-1][1].append(ring)

    polygons = [Polygon(shell=ext, holes=holes) for ext, holes in parts]
    if not polygons:
        return Polygon()
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_page(bbox: tuple[float, float, float, float], offset: int) -> dict:
    xmin, ymin, xmax, ymax = bbox
    params = {
        "where": "1=1",
        "outFields": ",".join(FIELDS),
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": 4326,
        "outSR": OUT_SR,
        "returnGeometry": "true",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "f": "pjson",
    }
    resp = requests.get(ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"NVE API error: {payload['error']}")
    return payload


def fetch_all(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    records = []
    geometries = []
    offset = 0
    while True:
        logger.info("Fetching offset=%d", offset)
        payload = fetch_page(bbox, offset)
        features = payload.get("features", [])
        if not features:
            break
        for feat in features:
            attrs = feat["attributes"]
            geom = feat.get("geometry")
            rings = (geom or {}).get("rings", [])
            records.append({k: attrs.get(k) for k in FIELDS})
            geometries.append(rings_to_polygon(rings) if rings else Polygon())

        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(SLEEP_BETWEEN_PAGES)

    gdf = gpd.GeoDataFrame(pd.DataFrame.from_records(records), geometry=geometries, crs=f"EPSG:{OUT_SR}")
    return gdf


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("delfelt_subcatchments.gpkg"))
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        default=DEFAULT_BBOX_WGS84,
        help="Query bbox in lon/lat (WGS84). Default is a first-guess covering both "
        "Evanger and Driva -- verify visually before trusting it.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    gdf = fetch_all(tuple(args.bbox))
    logger.info("Fetched %d subcatchments", len(gdf))
    gdf.to_file(args.out, driver="GPKG")
    logger.info("Wrote %s", args.out)


if __name__ == "__main__":
    main()
