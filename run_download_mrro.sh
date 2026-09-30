#!/bin/bash
# SLURM batch job: download the full KiN2025 mrro archive from thredds.met.no
# via download_mrro_full_archive.sh. Submit with:
#
#   sbatch run_download_mrro.sh
#
# IMPORTANT -- verify before relying on this: compute nodes on some HPC
# clusters have no outbound internet access (only login nodes do). If that
# is true on Olivia's small/large partitions, every wget inside
# download_mrro_full_archive.sh will fail to connect and this job will burn
# its walltime doing nothing. Test first with one file from a login node:
#   wget -c "https://thredds.met.no/thredds/fileServer/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro/eqm/hist/cnrm-r1i1p1-aladin/cnrm-r1i1p1-aladin_hist_eqm-estobs_disthbv_norway_1km_mrro_daily_1971.nc4"
# then srun/salloc a compute node and repeat the same wget to see if it
# still connects. If compute nodes can't reach the internet, run the
# download directly on the login node inside tmux instead (see the tmux
# alternative), not via sbatch.
#
# download_mrro_full_archive.sh uses `wget -c` (resumable) and re-checks
# every file, so this script is safe to re-submit if it runs out of
# walltime before finishing -- it picks up where it left off rather than
# re-downloading completed files.
#
# --time is a first guess: the archive is ~6800 files with a 1-second
# politeness delay between each (~1.9 hours of sleep alone, before any
# actual transfer time) -- raise this or just re-submit if it times out.

#SBATCH --job-name=download_kin2025
#SBATCH --account=nn10014k
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=3-00:00:00
#SBATCH --output=logs/download_mrro_%j.out
#SBATCH --error=logs/download_mrro_%j.err

set -euo pipefail

REPO_DIR="/cluster/work/projects/nn10014k/luli/RenewHydro"
mkdir -p "${REPO_DIR}/logs"
cd "${REPO_DIR}"

bash download_mrro_full_archive.sh

exit $?
