#!/bin/bash
# SLURM job: split the full runoff CSV per basin/scenario (split_runoff_csv.py),
# then run the flow analyses that need no plant-specific numbers:
#   analysis_seasonal_redistribution.py  per basin x future scenario (with hist)
#   analysis_dry_year_risk.py            per basin x future scenario (with hist)
#   analysis_uncertainty_decomposition.py per basin (all scenarios together)
# analysis_extremes.py and analysis_reservoir_constrained.py need minimum flow,
# reservoir volume and Qmax per plant -- not run here.
#
#   sbatch run_flow_analyses.sh
#   sbatch --export=ALL,SKIP_SPLIT=1 run_flow_analyses.sh   # reuse an earlier split

#SBATCH --job-name=flow_analyses
#SBATCH --account=nn10014k
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=logs/flow_analyses_%j.out
#SBATCH --error=logs/flow_analyses_%j.err

set -euo pipefail

REPO_DIR="/cluster/work/projects/nn10014k/luli/RenewHydro"
RUNOFF_CSV="${RUNOFF_CSV:-/cluster/work/projects/nn10014k/luli/evangervatn/basin_mrro_full/evanger_basin_mrro.csv}"
CATCHMENTS="${REPO_DIR}/Evanger_system/evanger_local_subcatchments.gpkg"
PROJ_DIR="${PROJ_DIR:-/cluster/work/projects/nn10014k/luli/evangervatn/projections}"
INPUT_DIR="${PROJ_DIR}/input"
FUTURES="rcp26 rcp45 ssp370"
NPROC="${SLURM_CPUS_PER_TASK:-8}"

export PATH="/cluster/projects/nn10014k/Luli/envs/evanger/bin:${PATH}"
export PYTHONNOUSERSITE=1
cd "${REPO_DIR}"
mkdir -p logs "${PROJ_DIR}/runlogs"

if [[ -z "${SKIP_SPLIT:-}" ]]; then
    python split_runoff_csv.py --runoff-csv "${RUNOFF_CSV}" --catchments "${CATCHMENTS}" --out-dir "${INPUT_DIR}" -v
fi

# One line per run: <name> <command...>; executed NPROC at a time.
TASKS="${PROJ_DIR}/runlogs/tasks.txt"
: > "${TASKS}"
tail -n +2 "${INPUT_DIR}/areas.csv" | while IFS=, read -r basin area; do
    for scen in ${FUTURES}; do
        echo "seasonal__${basin}__${scen} python analysis_seasonal_redistribution.py --runoff-csv ${INPUT_DIR}/${basin}__${scen}.csv --out-dir ${PROJ_DIR}/seasonal/${basin}/${scen}" >> "${TASKS}"
        echo "dryyear__${basin}__${scen} python analysis_dry_year_risk.py --runoff-csv ${INPUT_DIR}/${basin}__${scen}.csv --area-km2 ${area} --out-dir ${PROJ_DIR}/dry_year/${basin}/${scen}" >> "${TASKS}"
    done
    echo "uncertainty__${basin}__all python analysis_uncertainty_decomposition.py --runoff-csv ${INPUT_DIR}/${basin}__all.csv --area-km2 ${area} --out-dir ${PROJ_DIR}/uncertainty/${basin}" >> "${TASKS}"
done
echo "$(wc -l < "${TASKS}") analysis runs"

run_one() {
    local name=$1; shift
    if "$@" > "${PROJ_DIR}/runlogs/${name}.log" 2>&1; then echo "OK ${name}"; else echo "FAIL ${name}"; fi
}
export -f run_one
export PROJ_DIR
xargs -P "${NPROC}" -L 1 bash -c 'run_one "$@"' _ < "${TASKS}" | tee "${PROJ_DIR}/runlogs/status.txt"

echo "OK: $(grep -c '^OK' "${PROJ_DIR}/runlogs/status.txt")  FAIL: $(grep -c '^FAIL' "${PROJ_DIR}/runlogs/status.txt" || true)"
