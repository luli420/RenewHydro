# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

## Current state on Olivia (checked 2026-10-05, read this first)

Verified directly on Olivia (`uan02`) on 2026-10-05. Where this section
disagrees with older text further down, this section wins; update the
older text when you fix the underlying issue.

- **No working Python environment.** None of the `conda.sh` paths that
  `run_extract_basin_runoff.sh` searches exist, there is no `conda` on
  `PATH`, and `module avail` lists no conda/python module. The intended env
  prefix `/cluster/work/projects/nn10014k/luli/envs/evanger/` looks like an
  unfinished HPC-container-wrapper build: it has `bin/` (empty), `_bin/`, and
  `share/`. Only the system `/usr/bin/python3` exists, without the
  dependencies. **Rebuild the env before running any Python script on
  Olivia,** then replace the conda block in `run_extract_basin_runoff.sh`
  (`export PATH=<prefix>/bin:$PATH` for a container-wrapper env).
- **Archive is partly downloaded** (`/cluster/work/projects/nn10014k/luli/kin2025/mrro`,
  ~1.2 TB, 2,616 non-empty files of ~6,784 expected):
  - `eqm/hist` and `3dbc-eqm/hist`: complete (20 models x 50 years each).
  - `eqm/rcp26`: 8 of 10 models; `hadgem-r1i1p1-remo` stops at 2078.
  - `rcp45`, `ssp370`, and all `3dbc-eqm` future scenarios: not downloaded.
  - `eqm/rcp26/hadgem-r1i1p1-remo/..._2079.nc4` is a **0-byte file** left by
    a job killed mid-transfer. `wget -c` on the next download run repairs it.
  - The last two download jobs (2399434, 4 h; 2409312, 24 h) both ended in
    `TIMEOUT`. Resubmit to continue; `run_download_mrro.sh` asks for 3 days.
  - `extract_basin_runoff.py` skips a missing *member folder* with a
    warning, but `extract_layer1_timeseries.extract_member()` raises
    `FileNotFoundError` on a missing *year file* in an existing folder, and a
    0-byte file fails on open. So run only `--scenarios hist` until the
    download is complete.
- **Evanger catchment shapefiles** are untracked, in the repo working
  copy: `Evanger_system/<NN_name>/_ags_data/zipfolder/NedbfeltF_v4.shp`
  (exception: `12_eitro/_ags_data1/...`). There are 24 folders, each with
  **one polygon** (NVE Nedbørfelt export, ~280 attribute fields including
  `areal_km2` and `vassdragNr`). The `-nevina` variants of 03, 12 and 15
  have the same `vassdragNr` but much larger areas (03: 4.0 vs 50.4 km²;
  15: 21.6 vs 75.9 km²), so they are probably the full upstream catchment
  rather than the local area.
  - **Decision (2026-10-05):** extract **one series per sub-catchment for
    the 21 local polygons** (use `03_eide_fanndal`, `12_eitro`,
    `15_askjelldalsvatn`; exclude the three `-nevina` variants). Do this
    in a single pass: merge the 21 polygons into one file with an ID column
    (folder name) and pass `--id-col`, rather than running the job 21 times
    over the archive.
  - The path in `run_extract_basin_runoff.sh` and the docstring of
    `extract_basin_runoff.py`
    (`/cluster/work/projects/nn10014k/luli/evangervatn/zipfolder/NedbfeltF_v4.shp`)
    **does not exist**.
- **`/cluster/work` gives intermittent `Input/output error`s** on small
  files: the same `.prj` files failed in one run and read fine in the next.
  Retry before you conclude that a file is corrupt.
- **SLURM partitions on Olivia** (`sinfo`): `small` (default), `large`,
  `accel` (GPU, do not use). `run_layer1_array.sh` asks for
  `--partition=normal`, **which does not exist** and must be changed
  before you submit it.
- **`run_SBATCH.sh`** is the job script the user actually submits. It has its
  own `#SBATCH` header and calls another script with `bash`, so the
  `#SBATCH` lines inside the called script are ignored. As of 2026-10-05, it
  runs `download_mrro_full_archive.sh`; the `run_extract_basin_runoff.sh`
  line is commented out.
- **Git:** the working branch is `claude/evanger-kin2025`. Claude Code web
  sessions also push to it, so run `git pull --rebase` on Olivia before you
  commit there. Never force-push this branch. Untracked local data on Olivia
  (`Evanger_system/`, `download_mrro_full.log`, `slurm-*.out`) must not be
  committed.

## Commands

There is no build step, no package (`requirements.txt` only, no
`pyproject.toml`/`setup.py`), and no committed test suite, linter config, or
CI. Every module is a standalone CLI script run with `python <script>.py`
from the repo root, sharing an identical shape: `parse_args(argv)` ->
`main(argv)` -> `if __name__ == "__main__"`, `-v/--verbose` switching
logging to DEBUG, `pathlib.Path` for every path argument. Follow that shape
when adding a script.

```bash
pip install -r requirements.txt          # or: conda activate evanger (on Olivia)
python <script>.py --help                # every script self-documents its flags
```

### Pipeline order (Layer 1, the many-basin path)

Each step's output is the next step's input; steps 1-3 run once, step 4 runs
per (scenario, member).

```bash
# 1. delfelt polygons  -> delfelt_subcatchments.gpkg   (needs NVE network access)
python fetch_nve_subcatchments.py --bbox 4.0 58.5 12.5 64.0 --out delfelt_subcatchments.gpkg -v

# 2. lon/lat box -> the Yc/Xc index slice every later step needs
python find_grid_index_bbox.py --lon-min 4.0 --lat-min 58.5 --lon-max 12.5 --lat-max 64.0 -v

# 3. sparse coverage weights (delfelt x grid cell) -- computed ONCE, reused for every year
python build_weight_matrix.py --catchments delfelt_subcatchments.gpkg \
    --yc-slice <START> <STOP> --xc-slice <START> <STOP> --out weights/delfelt_weights.npz -v

# 4. one member (drop --local-dir to read over OPeNDAP instead of staged files)
python extract_layer1_timeseries.py --method eqm --model cnrm-r1i1p1-aladin --scenario hist \
    --weights weights/delfelt_weights.npz --local-dir <archive>/mrro --out-dir layer1 -v

# 5. merge per-member files -> (delfelt, time, member, scenario) Zarr store
python merge_layer1_outputs.py --layer1-dir layer1 --out layer1_merged.zarr -v

# 6. energy equivalents, then GWh + the free validation cross-check
python energy_equivalents.py --catchments delfelt_subcatchments.gpkg --out delfelt_energy_equivalents.csv -v
python mrro_to_gwh.py --layer1 layer1_merged.zarr --catchments delfelt_subcatchments.gpkg \
    --energy-equivalents delfelt_energy_equivalents.csv \
    --basin Bulken:<OUTLET_DELFELTNR> --validate -v
```

### Single-basin quick path (own shapefile, local archive)

Bypasses steps 1-5 entirely — see "Single-basin quick extraction" below for
the full Evangervatn invocation and what it reuses.

### Flow analyses (items 2-6)

All five consume the same long-format CSV from `extract_basin_runoff.py` and
write a figure (PNG + PDF) plus a summary CSV to `--out-dir`. `--area-km2` is
required by all but `analysis_seasonal_redistribution.py`; the
plant-specific numbers (`--capacity-mm3`, `--qmax-m3s`, `--min-flow-m3s`) are
required with no defaults, deliberately — do not invent values.

```bash
python analysis_seasonal_redistribution.py  --runoff-csv <csv> --out-dir figs -v
python analysis_dry_year_risk.py            --runoff-csv <csv> --area-km2 <A> --out-dir figs -v
python analysis_uncertainty_decomposition.py --runoff-csv <csv> --area-km2 <A> --out-dir figs -v
python analysis_reservoir_constrained.py    --runoff-csv <csv> --area-km2 <A> --capacity-mm3 <V> --qmax-m3s <Q> --out-dir figs -v
python analysis_extremes.py                 --runoff-csv <csv> --area-km2 <A> --min-flow-m3s <Q> --out-dir figs -v
```

### SLURM (Olivia)

```bash
sbatch run_layer1_array.sh            # array, one task per (scenario, member); needs member_manifest.csv
sbatch run_extract_basin_runoff.sh    # single serial job, loops all combos internally (Evangervatn)
```

`member_manifest.csv` is generated once outside the array from
`kin2025_config.scenario_member_combos()` — the snippet is commented inside
`run_layer1_array.sh`. Both scripts use `--account=nn10014k`. Partitions on
Olivia (`sinfo`): `small` (default), `large`, `accel` (GPU — never use it
here). `run_layer1_array.sh` currently asks for `--partition=normal`, which
does not exist on Olivia — change it to `small`; `run_extract_basin_runoff.sh`
sets no partition and gets `small`.

```bash
sbatch run_download_mrro.sh           # resumable full-archive download (wget -c), 3-day limit
sbatch run_SBATCH.sh                  # the user's own generic wrapper: runs whichever script is uncommented in it
```

### On testing

**No tests are committed to this repo.** Claims elsewhere in this file that
something was "unit-tested" or "verified against synthetic data" refer to
throwaway checks run in earlier sessions that were never persisted — they
are not reproducible from a clean clone, and should be re-established rather
than trusted. If you add tests, `pytest` is not currently a dependency.

## Data source

- Dataset: NCCS "Klima i Norge 2025" (KiN2025) / CiN-2025 hydrological
  projections, `distHBV-COR-BA-2025`, variable `mrro` (runoff, mm/day --
  **confirm the units attribute on the actual file**, don't just assume).
  Dyrrdal et al. 2025, NVE + MET Norway, served on `thredds.met.no`.
- **Confirmed OPeNDAP base and dims** (used successfully by
  `download_mrro_full_archive.sh` and `download_mrro_vestlandet_subset.py`
  -- these are no longer guesses, unlike the old `ReferenceIndices`/
  `ClimateStatistics` paths in `legacy/nevina_runoff_v1.py`):
  ```
  https://thredds.met.no/thredds/dodsC/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro/<method>/<scenario>/<model>/<model>_<scenario>_<method>-estobs_disthbv_norway_1km_mrro_daily_<year>.nc4
  ```
  - Grid is indexed by **`Yc`/`Xc`** (grid cell index), not `x`/`y` or
    lon/lat directly -- use `find_grid_index_bbox.py` to turn a lon/lat box
    into an `Yc`/`Xc` slice (2D `lat`/`lon` auxiliary coordinates are
    present on the grid for this).
  - **Confirmed on the real archive on Olivia (2026-08)**: files carry
    *only* `Xc`/`Yc` index dims plus 2D `lat`/`lon` in degrees -- there is
    **no** projected `X`/`Y` in meters. `build_weight_matrix.get_transform()`
    and `extract_basin_runoff.find_grid_window()` derive the affine
    transform / grid window by reprojecting the (sliced) `lat`/`lon` into
    the grid's CRS via `pyproj`, rather than assuming projected coordinate
    variables exist (they still prefer `X`/`Y` if present, for
    portability, but that path is unverified against any real file).
  - Real archive on Olivia was found nested one level deeper than
    `download_mrro_full_archive.sh`'s `OUT_DIR` might suggest at a glance:
    `<archive_root>/mrro/<method>/<scenario>/<model>/*.nc4` -- pass the
    `mrro/` level itself as `--archive-dir`/`--local-dir`.
  - **One file per (bias-adjustment method, GCM-RCM model, scenario,
    year)** -- confirms handoff notes §8 open item on chunking.
  - Grid/CRS: KliNoGrid/seNorge, UTM33N (EPSG:25833) unless a file's own
    `grid_mapping` says otherwise (read that first; see `get_grid_crs()` in
    `build_weight_matrix.py`). On the real archive the `grid_mapping`
    variable is named `projection_utm`; parsing it via `pyproj`'s
    `CRS.from_cf()` has been observed to log a benign PROJ debug message
    ("several objects matching this name...Greenwich") -- didn't block
    execution in testing, but not yet double-checked that the resolved CRS
    is bit-exact EPSG:25833 vs. a numerically-equivalent alternate
    definition; revisit if downstream areas/volumes look subtly off.
- `fileServer` (bulk download, used by `download_mrro_full_archive.sh` to
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
- **Two storage roots are in play and the scripts disagree** -- check which
  one you actually want before copying paths:
  - **NIRD** `/nird/datapeak/NS10014K/WP6/luli/Klima_i_Norge_2025/` --
    still hardcoded in `run_layer1_array.sh`; intended as the project
    storage area for weight matrices and Layer 1/2 outputs.
  - **Olivia work area** `/cluster/work/projects/nn10014k/luli/` --
    hardcoded in `run_extract_basin_runoff.sh`, `run_download_mrro.sh`,
    `run_SBATCH.sh`, and (since commit `9c2e5a2`) in
    `download_mrro_full_archive.sh`'s `OUT_DIR`. The archive is staged here
    (`.../kin2025/mrro`); see "Current state on Olivia" for how much.

  Write to either, not `$HOME`. **Check the project quota before staging
  the full archive**: ~350 GB/member uncompressed, multi-TB across all
  scenario-member combinations.
- SLURM: embarrassingly parallel, one array task per (scenario, member)
  (`run_layer1_array.sh`), **CPU partition only** (`accel` is the Grace
  Hopper GPU partition -- queue time for no benefit here). The single-basin
  path has its own non-array job, `run_extract_basin_runoff.sh`. Neither
  script's `--time`/`--mem` has been tuned against a real measurement;
  extrapolate from the per-year INFO timestamps of a small test run before
  trusting them.

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

## Analyses to build on Layer 1 (roughly in priority order)

By explicit request, items 2-6 are implemented in FLOW terms first (mm/day,
m3/s, Mm3), each as its own `analysis_*.py` script with its own figure(s)
and summary CSV, so results can be sanity-checked before energy conversion
is layered on top. `mrro_to_gwh.py` (item 1) already does the conversion
itself; wiring GWh into the analysis scripts is a deliberate later step,
not done yet.

1. Everything in GWh (done: `mrro_to_gwh.py`; not yet wired into items 2-6).
2. **Seasonal redistribution** -- `analysis_seasonal_redistribution.py`:
   monthly climatology with ensemble bands, centre-of-volume date, Oct-Mar
   share of annual inflow, spring flood magnitude/duration.
3. **Reservoir-constrained flow** -- `analysis_reservoir_constrained.py`:
   daily bucket model with reservoir volume `V` (`--capacity-mm3`) and max
   turbine discharge `Qmax` (`--qmax-m3s`, both plant-specific, not
   guessed); spilled volume, days above `Qmax`, filling degree at end of
   filling season, firm flow (Q90).
4. **Dry-year and multi-year deficit risk** -- `analysis_dry_year_risk.py`:
   1-in-10/1-in-20 driest years, consecutive dry-year runs against a fixed
   Reference-period threshold, change in interannual CV.
5. **Extremes** -- `analysis_extremes.py`: annual max 1-/3-day inflow with
   GEV return levels + bootstrap CI (dam safety); summer 7-day minimum and
   days below a minstevannforing threshold (`--min-flow-m3s`, not guessed).
6. **Uncertainty decomposition** -- `analysis_uncertainty_decomposition.py`:
   variance across scenario / GCM-RCM+method / interannual variability
   (simplified Hawkins & Sutton-style cascade, not a full orthogonal
   ANOVA); time of emergence vs. the Reference-period band.
7. Baseline credibility -- if residual bias remains after step 6's
   validation, apply results as delta-change factors on the company's
   observed inflow series rather than absolutes. Not yet implemented.
8. Portfolio view (if multiple plants) -- cross-basin correlation of
   annual inflow, erosion of geographic diversification in dry years. Not
   yet implemented.

### Flow analysis scripts (items 2-6) -- shared conventions

- Input: the long-format CSV from `extract_basin_runoff.py`
  (`basin, scenario, model, method, date, mrro_mm`) via `--runoff-csv`
  (`--basin NAME` to filter if the CSV holds more than one).
- Period convention (`runoff_analysis_common.py`): **Reference**
  (`hist`, 1991-2020), **Near-future** (2041-2070), **Far-future**
  (2071-2100), evaluated within whichever future scenario is present in
  the CSV -- matches the diff-mrro periods used elsewhere in this project.
- Figures: `plot_style.py` provides shared journal-figure conventions --
  single/double-column widths, embedded editable vector text
  (`pdf.fonttype`/`ps.fonttype` 42) for PDF export alongside a 300 dpi PNG,
  panel labels via `ax.set_title(loc="left")` (a dedicated layout slot, so
  it can't collide with a long/rotated y-axis label the way a manually
  positioned `ax.text` can), and a fixed-order colorblind-safe Okabe & Ito
  (2008) palette assigned by identity (`PERIOD_COLORS`/`SCENARIO_COLORS`),
  never by rank.
- Every script also writes a summary CSV of the underlying per-period
  statistics next to its figure.
- Caveat carried through every script's docstring: the 20 ensemble members
  are 10 GCM-RCM pairs x 2 bias-adjustment methods, not fully independent
  -- confidence bands/decompositions that pool across members (GEV
  bootstrap in `analysis_extremes.py`, the uncertainty cascade in
  `analysis_uncertainty_decomposition.py`) should be read as indicative,
  not rigorous i.i.d. intervals.
- All 5 scripts' core numeric functions (containment/topology aside) were
  verified against a synthetic archive with a known seasonal cycle,
  warming trend, and dry-year injections in this session -- e.g. the
  reservoir bucket model's spilled volume and the GEV return levels moved
  in the expected direction under the injected trend, and the uncertainty
  decomposition correctly attributed ~0% of variance to "scenario" when
  only one future scenario was present in the test data. Real KiN2025
  output has not been run through them yet.

## Open items / next steps

Blocking the Evanger run on Olivia (see "Current state on Olivia"):

- **Rebuild the `evanger` env** and update the activation block in
  `run_extract_basin_runoff.sh`.
- **Finish the archive download** (resubmit `run_download_mrro.sh`).
- **Merge the 21 local Evanger sub-catchment polygons** into one file with
  an ID column, point `CATCHMENTS` in `run_extract_basin_runoff.sh` at it,
  and pass `--id-col`.
- **First real test:** `--scenarios hist --methods eqm --models <one>`;
  confirm the `mrro` units and plot the weight mask before the full run.

Pipeline-wide:

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
- Four modules are shared infrastructure, imported rather than duplicated --
  reach for these before writing new code:
  - `kin2025_config.py` -- the single source of truth for OPeNDAP/fileServer
    bases, the model/method/scenario lists, HadGEM's 2098 truncation, and
    URL/year construction (`build_url()`, `years_for()`,
    `scenario_member_combos()`). Never hardcode a model list or a filename
    pattern anywhere else. Note `download_mrro_full_archive.sh` duplicates
    these lists in Bash; keep the two in sync if either changes.
  - `runoff_analysis_common.py` -- CSV loading, the Reference /
    Near-future / Far-future period assignment, and the mm/day ->
    m3/s / Mm3 unit conversions used by all five `analysis_*.py` scripts.
  - `plot_style.py` -- journal figure conventions; call
    `apply_journal_style()` then `new_figure()`/`save_figure()` rather than
    touching `matplotlib.rcParams` directly.
  - `build_weight_matrix.py` -- `get_grid_crs()`, `get_transform()`, and the
    exactextract/supersample coverage pair are imported by
    `extract_basin_runoff.py`; geometry handling lives here only.
- Geometry and I/O stay separated: weights are computed once from polygons,
  then every read is a `W @ R.T` matmul. Never re-touch geometry inside a
  per-year or per-member loop.
- Physical parameters that belong to a specific plant (reservoir capacity,
  `Qmax`, minstevannforing) are required CLI arguments with no defaults, on
  purpose. Keep it that way -- a plausible-looking default is worse than a
  crash here.
- Comments and docstrings carry provenance: they state whether a fact was
  confirmed against the real archive/API or is still a guess. Preserve that
  distinction when editing, and downgrade a claim rather than delete it if
  it turns out to be unverified.

## Single-basin quick extraction (extract_basin_runoff.py)

For a one-off basin with its own shapefile (not NVE's delfelt layer) and an
archive already staged locally -- e.g. one Evanger sub-catchment on Olivia,
with the archive at `/cluster/work/projects/nn10014k/luli/kin2025/mrro` and
the polygons under `Evanger_system/` in the repo working copy (see "Current
state on Olivia"; the older `.../luli/evangervatn/zipfolder/` path does not
exist):

```
python extract_basin_runoff.py \
    --catchments Evanger_system/10_groendalsvatn/_ags_data/zipfolder/NedbfeltF_v4.shp \
    --basin-name Evangervatn \
    --archive-dir /cluster/work/projects/nn10014k/luli/kin2025/mrro \
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
unnecessary for the many-basin case) -- `extract_basin_runoff.py` itself
has since been rewritten (see "Single-basin quick extraction" above) rather
than kept as dead code. A frozen copy of the original NEVINA-era version is
kept at **`legacy/nevina_runoff_v1.py`** for historical reference (renamed
there from its original filename, `extract_evanger_runoff.py`, to keep
"current active code" and "historical reference" from sharing a
directory); it is not part of the active pipeline and duplicates none of
the fixes made since.
