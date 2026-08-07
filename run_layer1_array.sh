#!/bin/bash
# SLURM array job skeleton for Layer 1 extraction on Olivia (handoff notes §6
# "Job setup"). One array task per (scenario, member) combination -- ~50-60
# tasks total, each touching its own set of yearly files exactly once.
#
# Not tuned/tested against Olivia (no HPC access from this environment) --
# adjust #SBATCH values, the container-wrapper invocation, and paths for
# your actual account/allocation before submitting. Run the single-member
# test sequence from handoff notes §6 first:
#   1. one member end-to-end
#   2. confirm mrro units from file attrs (extract_layer1_timeseries.py
#      logs this)
#   3. plot the weight mask once (see build_weight_matrix.py) and confirm
#      it lands on the right cells
#   4. check extracted mean annual runoff against QNormalDelfelt9120_Mm3Aar
# before submitting the full array.
#
# Usage:
#   sbatch run_layer1_array.sh

#SBATCH --job-name=kin2025-layer1
#SBATCH --account=nn10014k
#SBATCH --partition=normal          # CPU partition only -- GPU partition adds queue time for no benefit here
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --array=0-59                 # match the line count of member_manifest.csv - 1
#SBATCH --output=logs/layer1_%A_%a.out
#SBATCH --error=logs/layer1_%A_%a.err

set -euo pipefail

# --- paths: adjust to your NIRD project area, not $HOME ---
PROJECT_DIR="/nird/datapeak/NS10014K/WP6/luli/Klima_i_Norge_2025"
REPO_DIR="${PROJECT_DIR}/RenewHydro"
ARCHIVE_LOCAL_DIR="${PROJECT_DIR}/mrro"          # only if download_mrro_full_archive.sh already ran; else drop --local-dir below
WEIGHTS="${PROJECT_DIR}/weights/delfelt_weights.npz"
OUT_DIR="${PROJECT_DIR}/layer1"
MANIFEST="${REPO_DIR}/member_manifest.csv"       # scenario,method,model -- generate once, see note below

mkdir -p "${REPO_DIR}/logs" "${OUT_DIR}"

# Generate the manifest once (outside the array, or as a pre-step) with:
#   python -c "
#   import csv
#   from kin2025_config import scenario_member_combos
#   with open('member_manifest.csv', 'w', newline='') as f:
#       w = csv.writer(f)
#       w.writerow(['scenario', 'method', 'model'])
#       for scenario, member in scenario_member_combos():
#           w.writerow([scenario, member.method, member.model])
#   "

LINE=$(sed -n "$((SLURM_ARRAY_TASK_ID + 2))p" "${MANIFEST}")   # +2: skip header, 1-index
SCENARIO=$(echo "${LINE}" | cut -d',' -f1)
METHOD=$(echo "${LINE}" | cut -d',' -f2)
MODEL=$(echo "${LINE}" | cut -d',' -f3)

echo "Task ${SLURM_ARRAY_TASK_ID}: scenario=${SCENARIO} method=${METHOD} model=${MODEL}"

# --- wrap the conda/pip env with HPC-container-wrapper (per handoff §6) ---
# module load HPC-container-wrapper (adjust module name to whatever `module
# avail` shows on Olivia) and build the wrapper once beforehand, e.g.:
#   create-hpc-container-wrapper --prefix "${PROJECT_DIR}/evanger-env" \
#       --requirement "${REPO_DIR}/requirements.txt"
# then invoke it below instead of a bare `python`.

cd "${REPO_DIR}"

python extract_layer1_timeseries.py \
    --method "${METHOD}" \
    --model "${MODEL}" \
    --scenario "${SCENARIO}" \
    --weights "${WEIGHTS}" \
    --local-dir "${ARCHIVE_LOCAL_DIR}" \
    --out-dir "${OUT_DIR}" \
    -v
