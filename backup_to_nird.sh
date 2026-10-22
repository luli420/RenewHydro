#!/bin/bash
# Back up results and the staged KiN2025 archive from Olivia /cluster/work
# (auto-deleted after ~21 days) to NIRD Data Peak, with rsync.
#
# NIRD needs password + one-time code and is not mounted on Olivia, so first
# open a shared NIRD connection ON OLIVIA (lasts 24 h):
#   ssh -M -S ~/.ssh/nird-cm -o ControlPersist=24h luli@login.nird.sigma2.no
# then run this on the same Olivia login node, detached:
#   setsid nohup bash backup_to_nird.sh > logs/nird_backup.log 2>&1 < /dev/null &
#
# rsync only sends new or changed files, so re-running it is cheap.
# Measured 2026-10-22: ~200 MB/s, i.e. ~4-5 h for the 3.1 TB archive.
set -u

SRC="${SRC:-/cluster/work/projects/nn10014k/luli}"
DST="${DST:-luli@login.nird.sigma2.no:/nird/datapeak/NS10014K/WP6/luli/RenewHydro_data}"
SOCKET="${SOCKET:-$HOME/.ssh/nird-cm}"
E="ssh -S ${SOCKET} -o BatchMode=yes"

if ! ssh -S "${SOCKET}" -O check luli@login.nird.sigma2.no 2>/dev/null; then
    echo "ERROR: no NIRD connection at ${SOCKET} -- open it first (see header)" >&2
    exit 1
fi

echo "$(date "+%F %T") start results"
rsync -a --partial -e "$E" "$SRC"/evangervatn/basin_mrro* "$SRC"/evangervatn/projections "$DST/results/" \
    && echo "$(date "+%F %T") results OK" || echo "$(date "+%F %T") results FAILED"

echo "$(date "+%F %T") start archive"
rsync -a --partial --info=progress2 -e "$E" "$SRC"/kin2025/mrro "$DST/kin2025/" \
    && echo "$(date "+%F %T") archive OK" || echo "$(date "+%F %T") archive FAILED rc=$?"
