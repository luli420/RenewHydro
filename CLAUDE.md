# RenewHydro — KiN2025 runoff -> GWh pipeline

Context for whoever (human or Claude Code) picks this project up next.
Supersedes the earlier NEVINA-polygon-based approach (see "History" at the
bottom) with an NVE-delfelt-based architecture per the project handoff
notes.

## Goal

Extract basin-averaged runoff projections from KiN2025 for Norwegian
catchments, convert them to energy inflow (GWh), and produce
decision-relevant analyses for a hydropower company operating a plant
downstream.

Case studies: **Evanger** (Bulken, Mestad, Mertesgrova), Voss/Vaksdal,
western Norway -- primary. **Driva** (Oppdal), central Norway -- possible
second site. Driva is NOT in western Norway, so any spatial subsetting
must be extended to cover it (see "Region bounding box" below).

## Data source

- Dataset: NCCS "Klima i Norge 2025" (KiN2025) / CiN-2025 hydrological
  projections, `distHBV-COR-BA-2025`, variable `mrro` (runoff, mm/day --
  **confirm the units attribute on the actual file**, don't just assume).
  Dyrrdal et al. 2025, NVE + MET Norway, served on `thredds.met.no`.
- **Confirmed OPeNDAP base and dims** (used successfully by
  `download_mrro_KlimaiNorge.sh` and `download_mrro_VN_sKlimaiNorge2025.py`
  -- these are no longer guesses, unlike the old `ReferenceIndices`/
  `ClimateStatistics` paths in the deprecated NEVINA-era script):
  ```
  https://thredds.met.no/thredds/dodsC/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro/<method>/<scenario>/<model>/<model>_<scenario>_<method>-estobs_disthbv_norway_1km_mrro_daily_<year>.nc4
  ```
  - Grid is indexed by **`Yc`/`Xc`** (grid cell index), not `x`/`y` or
    lon/lat directly -- use `find_grid_index_bbox.py` to turn a lon/lat box
    into an `Yc`/`Xc` slice (2D `lat`/`lon` auxiliary coordinates are
    present on the grid for this).
  - **One file per (bias-adjustment method, GCM-RCM model, scenario,
    year)** -- confirms handoff notes §8 open item on chunking.
  - Grid/CRS: KliNoGrid/seNorge, UTM33N (EPSG:25833) unless a file's own
    `grid_mapping` says otherwise (read that first; see `get_grid_crs()` in
    `build_weight_matrix.py`).
- `fileServer` (bulk download, used by `download_mrro_KlimaiNorge.sh` to
  stage the raw archive onto NIRD) vs. `dodsC`/OPeNDAP (used by the Layer 1
  pipeline scripts below to read only the sliced region needed, without
  downloading full-Norway grids) -- both are legitimate depending on
  whether you're staging data onto NIRD for repeated local reads or reading
  once directly. See "Deployment" below.
- Ensemble: **20 members = 10 GCM-RCM pairs x 2 bias-adjustment methods**
  (EQM, 3DBC) -- see `kin2025_config.py`. **Members are not independent**;
  every script that carries a `member` dimension keeps `model` and `method`
  as separate coordinates so variance can be decomposed by source later.
- Scenarios: `hist` (1971-2020, all 20 members), `rcp26`/`rcp45` (2021-2100,
  10 CMIP5-driven members), `ssp370` (2021-2100, 10 CMIP6-driven members).
  A few HadGEM-driven rcp26/rcp45 runs stop at 2098 (`kin2025_config.py`
  handles this).
- Reference period for validation: **1991-2020**.
- `mrro` is **locally generated runoff per cell, not routed discharge** --
  naturalized (unregulated) inflow, no reservoir operation represented.
  Basin aggregation is a simple area-weighted sum, which is what makes the
  Layer 1 architecture below work. No routing means daily peak timing is
  slightly early/sharp for larger basins -- fine at daily-to-weekly
  reservoir timescales, but don't over-read single-day extremes on large
  basins.

## Architecture: two layers, one pass over the archive

Basin aggregation is linear, so small units can be summed exactly into
larger basins -- the archive should be read **once**, producing both
layers together.

### Layer 1 -- every delfelt's time series (do this first)

Pipeline: `fetch_nve_subcatchments.py` -> `build_weight_matrix.py` ->
`extract_layer1_timeseries.py` (one SLURM array task per scenario/member,
see `run_layer1_array.sh`) -> `merge_layer1_outputs.py`.

- Extracts area-weighted daily `mrro` for **every NVE delfelt** in the
  region of interest, not just Evanger/Driva -- any future basin is just
  the sum of the delfelt in its `oppstromDelfeltListe` (see
  `mrro_to_gwh.py`'s `rollup_basin()`), so a new basin never needs the
  archive re-read.
- The sparse weight matrix `W` (delfelt x grid cell, fractional coverage)
  is computed **once** from the delfelt polygons and reused for every
  (scenario, member, year) file -- `basin_means = (W @ R.T)` per year,
  never re-touching geometry inside the loop.
- Output: one compact file per (scenario, member) with dims
  `(delfelt, time)`, merged into a single store with dims
  `(delfelt, time, member, scenario)`.
- Indexed by **`delfeltNr`**, joining directly to NVE's plant database and
  the energy-equivalent conversion.

### Layer 2 -- regional gridded cache (optional, quota permitting)

Only needed for gridded fields (spatial maps, SWE patterns, figures). Not
yet implemented as a standalone script -- `extract_layer1_timeseries.py`
already reads the correctly-sliced regional subset per year, so a Layer 2
cache-write can be added into that same loop rather than a second archive
pass. Guidance if/when built:
- Extend the region south to ~64degN or include Vestland + Rogaland +
  More og Romsdal + southern Trondelag so Driva is covered.
- Index-slice only on the native `Yc`/`Xc` grid -- no reprojection, no
  regridding, so masks/weights stay valid.
- Keep daily resolution and all members; aggregating here will be
  regretted for extremes/drought-sequence analysis later.
- Rechunk for time-series access (e.g. `time: 3650, y: 150, x: 150`) --
  source files are chunked for whole-domain map access, the wrong shape
  for per-catchment time series.

## Region bounding box -- still open

`fetch_nve_subcatchments.py --bbox` and any `Yc`/`Xc` slice used by
`build_weight_matrix.py`/`extract_layer1_timeseries.py` currently use a
**first-guess** bbox (lon 4.0-12.5, lat 58.5-64.0) meant to cover both
Evanger and Driva. This has **not** been visually verified (no NVE/map
access in the sandbox this was written in) -- confirm both catchments fall
inside it (e.g. plot the fetched delfelt polygons) before relying on it,
per handoff notes §4/§8. Use `find_grid_index_bbox.py` to convert a
confirmed lon/lat box into the `Yc`/`Xc` slice these scripts need.

## Subcatchment polygons (NVE delfelt)

`fetch_nve_subcatchments.py` -- fixes three bugs in NVE/API's reference
script (`hydropower/hydropower_gis_subcatchments.py`):

1. **Geometry bug (critical, fixed)**: the reference script flattened Esri
   JSON `rings` into a `MultiPoint`, discarding the polygon interior.
   `rings_to_polygon()` rebuilds proper `Polygon`/`MultiPolygon` geometry,
   honoring Esri's ring-winding convention (clockwise = exterior,
   counter-clockwise = hole) -- unit-tested against synthetic rings.
2. **Export format (fixed)**: GeoPackage, not `.xlsx` (which drops
   geometry).
3. **CRS (fixed)**: `outSR=25833` requested explicitly.

Endpoint: `https://gis3.nve.no/map/rest/services/Mapservices/VassdragsreguleringVannkraft/MapServer/8/query`
-- **not reachable from the Claude Code sandbox** this was written in
(network allowlist covers GitHub/PyPI/npm only); run on Olivia or any
machine with open outbound access, and has not been executed against the
live service yet.

Key fields: `delfeltNr` (join key for everything downstream),
`vannkraftverkNr` (plant at this delfelt, if any), `oppstromDelfeltListe`
(accumulated upstream delfelt -- the topology, no polygon geometry needed
for basin rollup), `delfeltAreal_km2`, `QNormalDelfelt9120_Mm3Aar` /
`QNormalDelfelt6190_Mm3Aar` (free 1991-2020 / 1961-90 normal-runoff
validation baseline, same reference period as KiN2025 -- see
`mrro_to_gwh.py --validate`).

## Runoff -> GWh conversion

`energy_equivalents.py` builds a `delfeltNr -> EnEkv (kWh/m^3)` mapping: for
each delfelt, sum the energy equivalents of every plant its water passes
through on the way to the sea (plant topology from `oppstromDelfeltListe`,
plus a downstream plant-chain walk to catch delfelt separated from a plant
by another plant with no subcatchment in between -- unit-tested against a
synthetic cascade). Plant attributes (`EnEkv` etc.) come from
`https://api.nve.no/web/Powerplant/GetHydroPowerPlantsInOperation` --
also not reachable from the sandbox, not yet run against the live API. The
exact field name for the downstream plant chain
(`nedstromvannkraftverknr_liste` per handoff notes) is unconfirmed;
`DOWNSTREAM_FIELD_CANDIDATES` in `energy_equivalents.py` lists guesses to
verify against the real API response.

`mrro_to_gwh.py` applies the unit chain and rolls delfelt up into named
basins:
```
mrro [mm/day] x area [km^2] x 1000    -> m^3/day
m^3/day x EnEkv [kWh/m^3] / 1e6       -> GWh/day
```
Basin totals for Evanger (Bulken/Mestad/Mertesgrova) and Driva need their
outlet `delfeltNr` values (from the fetched delfelt layer) passed via
`--basin NAME:OUTLET_DELFELTNR` -- not hardcoded here since they can't be
looked up without live NVE access.

## Natural vs. regulated Bulken -- still open

Bulken has an Evanger intake dam:

- **Natural**: direct from the grid, accumulated over Bulken's delfelt set
  -- what this pipeline computes (KiN2025 `mrro` has no reservoir
  operation represented).
- **Regulated**: NOT in the grid. Two options proposed, **not yet chosen**:
  (a) NVE observed regulated series + delta-change (apply the projected %
  change onto Bulken's actual regulated flow record), or (b) explicit
  routing/water-balance using the diversion topology and operating rules of
  the Bulken intake. Decide before adding a regulated-Bulken module.

## Deployment

- **GitHub** is the source of truth for code. NetCDF/large data files,
  weight matrices, and fetched polygons are not committed (`.gitignore`).
- **Claude Code GitHub App** (`@claude` in issues/PRs) is for code
  review/edits -- GitHub-hosted runners, no HPC/NVE/NIRD network access,
  so it produces code, not executed/verified results. Every script above
  that talks to `thredds.met.no`, `gis3.nve.no`, or `api.nve.no` has been
  written against documented/observed behavior but **not executed** in
  this environment -- run the "Test sequence before the full run" below
  first.
- **Olivia (HPC, Sigma2)** does the actual execution: `git pull` on the
  login node (compute nodes lack the internet access OPeNDAP needs),
  `conda activate evanger` (or the HPC-container-wrapper equivalent -- a
  bare env with `xarray`/`geopandas`/`rioxarray`/`exactextract` is tens of
  thousands of small files and hostile to the parallel filesystem), run
  the pipeline there. No automated push-to-HPC CI -- syncing is a manual
  `git pull`.
- **NIRD** (`/nird/datapeak/NS10014K/WP6/luli/Klima_i_Norge_2025/`) is the
  project storage area for the staged archive
  (`download_mrro_KlimaiNorge.sh`), weight matrices, and Layer 1/2 outputs
  -- write there, not `$HOME`. **Check the project quota before staging
  the full archive**: ~350 GB/member uncompressed, multi-TB across all
  scenario-member combinations.
- SLURM: embarrassingly parallel, one array task per (scenario, member)
  (`run_layer1_array.sh`), **CPU partition only** (the Grace Hopper GPU
  partition adds queue time for no benefit here).

## Test sequence before the full run (handoff notes §6)

1. Run one member end to end (`extract_layer1_timeseries.py` for a single
   `--method`/`--model`/`--scenario`).
2. Confirm the `mrro` units attribute logged by that run matches
   expectations (mm/day) -- don't assume.
3. Plot the weight mask for at least one delfelt (from
   `build_weight_matrix.py`'s output) and confirm it lands on the right
   grid cells.
4. Run `mrro_to_gwh.py --validate` and check the extracted 1991-2020 mean
   annual volume against `QNormalDelfelt9120_Mm3Aar` -- a free validation
   baseline that costs nothing to check.

Only then submit the full `run_layer1_array.sh` array.

## Analyses to build on Layer 1 (not yet implemented, roughly in priority order)

1. Everything in GWh (done: `mrro_to_gwh.py`).
2. Seasonal redistribution -- monthly climatology with ensemble bands,
   centre-of-volume date, Oct-Mar share of annual inflow, spring flood
   magnitude/duration.
3. Reservoir-constrained production -- bucket model with reservoir volume
   `V` and max turbine discharge `Qmax`; spilled energy, days above `Qmax`,
   firm energy (90% exceedance).
4. Dry-year and multi-year deficit risk -- 1-in-10/1-in-20 driest years,
   consecutive dry-year runs, change in interannual CV.
5. Extremes -- annual max 1-/3-day inflow with GEV return levels (dam
   safety); summer 7-day minimum and days below minstevannforing.
6. Uncertainty decomposition -- variance across scenario/GCM-RCM/
   bias-adjustment using the 10x2 design; time of emergence.
7. Baseline credibility -- if residual bias remains after step 6's
   validation, apply results as delta-change factors on the company's
   observed inflow series rather than absolutes.
8. Portfolio view (if multiple plants) -- cross-basin correlation of
   annual inflow, erosion of geographic diversification in dry years.

## Open items / next steps

1. **Verify the region bounding box** covers both Evanger and Driva (see
   "Region bounding box" above).
2. **Run `fetch_nve_subcatchments.py` on a machine with NVE access**
   (Olivia, or any non-sandboxed machine) and sanity-check the geometry
   fix visually.
3. **Verify field names** against the live NVE API responses: the
   downstream-plant-chain field in `energy_equivalents.py`
   (`DOWNSTREAM_FIELD_CANDIDATES`), and the exact schema of the
   Powerplant API response.
4. **Verify `build_weight_matrix.py`'s exactextract path** (the
   `["cell_id", "coverage"]` per-cell output) against the installed
   exactextract version -- it has a tested, always-working supersampled-
   rasterize fallback, but the exactextract path is preferred for accuracy
   and hasn't been confirmed against real data.
5. **Decide natural-vs-regulated Bulken approach** (a or b above).
6. **Check NIRD project storage quota** before staging the full archive or
   committing to a Layer 2 gridded cache.
7. Once Layer 1 is validated, build the analyses in priority order above.

## Conventions

- CRS handling: always prefer the CF `grid_mapping` attribute over
  assuming EPSG:25833; only fall back when it's missing or unparseable.
- Prefer OPeNDAP subsetting over downloading full grids when reading once;
  bulk `fileServer` staging onto NIRD is fine when the archive will be read
  repeatedly from local disk (see "Deployment").
- Keep `model`/`method` as separate coordinates wherever a `member`
  dimension appears -- the 20 members are paired, not independent.
- Long-format / dimensioned outputs over wide tables, so downstream
  analysis doesn't need to know the scenario/period list in advance.

## Single-basin quick extraction (extract_evanger_runoff.py)

For a one-off basin with its own shapefile (not NVE's delfelt layer) and an
archive already staged locally -- e.g. testing against Evangervatn on
Olivia at `/cluster/work/projects/nn10014k/luli/kin2025` with the basin
polygon at `/cluster/work/projects/nn10014k/luli/evangervatn/zipfolder/NedbfeltF_v4.shp`:

```
python extract_evanger_runoff.py \
    --catchments /cluster/work/projects/nn10014k/luli/evangervatn/zipfolder/NedbfeltF_v4.shp \
    --basin-name Evangervatn \
    --archive-dir /cluster/work/projects/nn10014k/luli/kin2025 \
    --out-dir /cluster/work/projects/nn10014k/luli/evangervatn/basin_mrro/ \
    --scenarios hist --methods eqm --models cnrm-r1i1p1-aladin -v
```

Start with a single-model/single-scenario run like the one above (per the
"Test sequence" above) before dropping the `--scenarios`/`--methods`/
`--models` filters to run the full local archive. It auto-detects a small
grid window around the basin (so it never reads the full ~1195x1550 Norway
grid), reuses `build_weight_matrix`'s tested coverage-weighting and
`extract_layer1_timeseries`'s tested extraction loop, and writes one
long-format CSV (`basin, scenario, model, method, date, mrro_mm`) plus the
weight matrix (for the "plot the mask" check) to `--out-dir`. The
grid-window detection, weight matrix, and matmul extraction were verified
against an independently hand-computed area-weighted mean on synthetic
data in this session -- the parts that still need a real first run are the
same as elsewhere: confirm the `mrro` units attribute and the archive's
actual directory layout on Olivia.

## History

The very first version of this script delineated catchments manually in
NEVINA (nevina.nve.no) and derived local/incremental subcatchments by
polygon-containment differencing, reading `ReferenceIndices`/
`ClimateStatistics` OPeNDAP paths that were unverified guesses. That
approach is superseded by the delfelt-based Layer 1 pipeline above (NVE's
own `oppstromDelfeltListe` topology makes the containment-differencing step
unnecessary for the many-basin case) -- `extract_evanger_runoff.py` itself
has since been rewritten (see "Single-basin quick extraction" above) rather
than kept as dead code. A frozen copy of the original NEVINA-era version
was saved by request as `Evanger_runoff_analysis.py` before the rewrite;
it is not part of the active pipeline and duplicates none of the fixes
made since.
