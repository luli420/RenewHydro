#!/bin/bash
# SLURM batch job: run extract_basin_runoff.py for the 21 local Evanger
# sub-catchments (one series each, one pass over the archive) against the
# local KiN2025 archive on Olivia. Not an array -- this is one serial job
# that loops every (scenario, member) combination internally (see
# extract_basin_runoff.py); submit with:
#
#   sbatch run_extract_basin_runoff.sh
#
# The catchment GeoPackage is built once with merge_catchment_shapefiles.py
# (see CATCHMENTS below).
#
# Defaults to the FULL archive (all scenarios/methods/models). For a narrower
# test, override from the command line instead of editing this file, e.g.:
#
#   sbatch --time=02:00:00 --export=ALL,SCENARIOS=hist,METHODS=eqm,MODELS=cnrm-r1i1p1-aladin run_extract_basin_runoff.sh
#
# NOT tuned against a real timing measurement -- estimate your own runtime
# from the small hist+rcp45/1-model/1-method test you already ran: check
# the per-year INFO log lines' timestamps (extract_basin_runoff.py logs one
# per year processed) and extrapolate to ~6800 (scenario,model,method,year)
# files for the full archive (20 models x 2 methods x ~50-80 years x 4
# scenario groups, roughly). Adjust --time below accordingly before relying
# on this -- the value here is a first guess, not a measurement.
#
# --account below is a guess (matches run_layer1_array.sh's NIRD project
# code) -- replace with your actual Olivia SLURM account if different
# (check with `sacctmgr show associations user=$USER` or similar).

#SBATCH --job-name=basin_runoff
#SBATCH --account=nn10014k
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=24:00:00              # first guess -- see note above, raise if the small test extrapolates higher
#SBATCH --output=logs/extract_basin_runoff_%j.out
#SBATCH --error=logs/extract_basin_runoff_%j.err

set -euo pipefail

REPO_DIR="/cluster/work/projects/nn10014k/luli/RenewHydro"
# 21 local Evanger sub-catchments (the -nevina upstream variants excluded),
# built with:
#   python merge_catchment_shapefiles.py --root Evanger_system \
#       --exclude 'nevina$' --out Evanger_system/evanger_local_subcatchments.gpkg -v
CATCHMENTS="${REPO_DIR}/Evanger_system/evanger_local_subcatchments.gpkg"
ID_COL="basin"          # one output series per catchment folder name
BASIN_NAME="Evanger"    # used only for the output filename (evanger_basin_mrro.csv)
ARCHIVE_DIR="/cluster/work/projects/nn10014k/luli/kin2025/mrro"
OUT_DIR="/cluster/work/projects/nn10014k/luli/evangervatn/basin_mrro"

# Full archive by default; override via the environment (see header), e.g.
# SCENARIOS="hist rcp45" METHODS="eqm" MODELS="cnrm-r1i1p1-aladin".
SCENARIOS="${SCENARIOS:-}"   # empty -> extract_basin_runoff.py's own default (all scenarios)
METHODS="${METHODS:-}"       # empty -> all methods
MODELS="${MODELS:-}"         # empty -> all models

mkdir -p "${REPO_DIR}/logs" "${OUT_DIR}"
cd "${REPO_DIR}"

# Python env: an HPC-container-wrapper (Tykky) env built from
# requirements.txt (spec: /cluster/projects/nn10014k/Luli/envs/evanger-env.yml).
# Tykky envs are activated by putting their bin/ first on PATH -- no conda
# needed (Olivia has no conda module). It lives on /cluster/projects, not
# /cluster/work, because the previous env's image on /cluster/work vanished.
ENV_PREFIX="/cluster/projects/nn10014k/Luli/envs/evanger"
if [[ ! -x "${ENV_PREFIX}/bin/python" ]]; then
    echo "ERROR: no python in ${ENV_PREFIX}/bin -- rebuild the env (see CLAUDE.md)" >&2
    exit 1
fi
export PATH="${ENV_PREFIX}/bin:${PATH}"

EXTRA_ARGS=()
[[ -n "${SCENARIOS}" ]] && EXTRA_ARGS+=(--scenarios ${SCENARIOS})
[[ -n "${METHODS}" ]] && EXTRA_ARGS+=(--methods ${METHODS})
[[ -n "${MODELS}" ]] && EXTRA_ARGS+=(--models ${MODELS})

python extract_basin_runoff.py \
    --catchments "${CATCHMENTS}" \
    --id-col "${ID_COL}" \
    --basin-name "${BASIN_NAME}" \
    --archive-dir "${ARCHIVE_DIR}" \
    --out-dir "${OUT_DIR}" \
    "${EXTRA_ARGS[@]}" \
    -v
