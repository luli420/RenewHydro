#!/bin/sh
# USAGE: $ sbatch RUN_XXXX.sh

## project:
#SBATCH --account=nn10014k
#
#  Give the job a name
# 
#SBATCH --job-name="basin_mrro"
## Wall time limit:
#SBATCH --time=4:00:0
## Number of nodes:
#SBATCH --nodes=1
## Number of tasks to start on each node:
#SBATCH --ntasks-per-node=1
#SBATCH --mem-per-cpu=2G

## Recommended safety settings:
set -o errexit # Make bash exit on any error

## module load
module list             # List loaded modules, for easier debugging


# Lu Li 	- July 28, 2026
# ##################################################################################

# directory on /work where the job runs
cd /cluster/work/projects/nn10014k/luli/RenewHydro/

bash run_extract_basin_runoff.sh

exit $?
