#!/bin/bash
# SLURM batch job: run extract_basin_runoff.py for the Evangervatn test case
# against the full local KiN2025 archive on Olivia. Not an array -- this is
# one serial job that loops every (scenario, member) combination internally
# (see extract_basin_runoff.py); submit with:
#
#   sbatch run_extract_basin_runoff.sh
#
# Defaults to the FULL archive (all scenarios/methods/models). To repeat a
# narrower test instead, edit SCENARIOS/METHODS/MODELS below.
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
CATCHMENTS="/cluster/work/projects/nn10014k/luli/evangervatn/zipfolder/NedbfeltF_v4.shp"
ARCHIVE_DIR="/cluster/work/projects/nn10014k/luli/kin2025/mrro"
OUT_DIR="/cluster/work/projects/nn10014k/luli/evangervatn/basin_mrro"

# Full archive by default. To repeat a narrower test, uncomment and edit:
# SCENARIOS="hist rcp45"
# METHODS="eqm"
# MODELS="cnrm-r1i1p1-aladin"
SCENARIOS=""   # empty -> extract_basin_runoff.py's own default (all scenarios)
METHODS=""     # empty -> all methods
MODELS=""      # empty -> all models

mkdir -p "${REPO_DIR}/logs" "${OUT_DIR}"
cd "${REPO_DIR}"

# Locate and initialize conda. SLURM batch scripts don't source ~/.bashrc,
# so `conda activate` fails with "command not found" unless conda.sh is
# sourced explicitly first. Olivia has no loadable conda module (confirmed
# via `module spider conda` -- only an unrelated Lustre filesystem module
# showed up), so this searches common self-installed Miniconda/Anaconda
# locations instead of `module load`. Add your real path to the front of
# CONDA_SH_CANDIDATES if none of these match (check with
# `grep -A2 "conda initialize" ~/.bashrc` to find where your install put it).
CONDA_SH_CANDIDATES=(
    "$HOME/miniconda3/etc/profile.d/conda.sh"
    "$HOME/anaconda3/etc/profile.d/conda.sh"
    "$HOME/miniforge3/etc/profile.d/conda.sh"
    "/cluster/work/projects/nn10014k/luli/miniconda3/etc/profile.d/conda.sh"
)
CONDA_SH=""
for candidate in "${CONDA_SH_CANDIDATES[@]}"; do
    if [[ -f "${candidate}" ]]; then
        CONDA_SH="${candidate}"
        break
    fi
done
if [[ -z "${CONDA_SH}" ]]; then
    echo "ERROR: could not find conda.sh in any of: ${CONDA_SH_CANDIDATES[*]}" >&2
    echo "Add your real Miniconda/Anaconda path to CONDA_SH_CANDIDATES in this script." >&2
    exit 1
fi
source "${CONDA_SH}"
conda activate evanger  # adjust to your actual env name if different

EXTRA_ARGS=()
[[ -n "${SCENARIOS}" ]] && EXTRA_ARGS+=(--scenarios ${SCENARIOS})
[[ -n "${METHODS}" ]] && EXTRA_ARGS+=(--methods ${METHODS})
[[ -n "${MODELS}" ]] && EXTRA_ARGS+=(--models ${MODELS})

python extract_basin_runoff.py \
    --catchments "${CATCHMENTS}" \
    --basin-name Evangervatn \
    --archive-dir "${ARCHIVE_DIR}" \
    --out-dir "${OUT_DIR}" \
    "${EXTRA_ARGS[@]}" \
    -v
