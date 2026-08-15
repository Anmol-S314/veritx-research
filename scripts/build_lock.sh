#!/usr/bin/env bash
# build_lock.sh — exclusive build lock for the shared 14GB box.
# ONE build at a time is rule 4 (GATE-R1-COORD §3.1); concurrent -j1 builds
# OOM this box even at -j1 (vbuild_col0 killed 23:20, RAM hit 1GB — seed
# 8c7b family). This makes the rule structural instead of a convention.
#
# Usage:
#   bash scripts/build_lock.sh <cmd...>              # run cmd under the lock (waits up to 300s)
#   BUILD_LOCK_TIMEOUT=60 bash scripts/build_lock.sh <cmd...>   # shorter wait
#
# The lock is a flock on /var/tmp/r1work/.build.lock (real disk — NOT /tmp,
# the tmpfs is wiped). Holder info (pid + time + command) is written to the
# lock file so contenders can see WHO holds it.
set -euo pipefail

LOCK="/var/tmp/r1work/.build.lock"
LOCK_TIMEOUT="${BUILD_LOCK_TIMEOUT:-300}"

# belt + suspenders: even non-script builds must not run concurrently.
# Covers all build phases: verilator_bin (parse/elab), make (any Mdir — the
# old pattern only matched Vnoc_tb.mk and MISSED `make -C dave_d3`, killing
# dave's build 2026-08-15 21:45), and g++/cc1plus (the g++ phase is where OOM
# kills happen and has NO verilator_bin process running).
if pgrep -x verilator_bin >/dev/null 2>&1 \
   || pgrep -f 'make -C' >/dev/null 2>&1 \
   || pgrep -x cc1plus >/dev/null 2>&1 \
   || pgrep -x g++ >/dev/null 2>&1; then
    echo "build_lock: verilator/make/g++ already running — one build at a time (rule 4)." >&2
    echo "build_lock:   ps aux | grep -E '[v]erilator|[g]++|[m]ake -C'  to see it" >&2
    exit 1
fi

exec 9>"$LOCK"
if ! flock -w "$LOCK_TIMEOUT" 9; then
    echo "build_lock: lock held >${LOCK_TIMEOUT}s by: $(cat "$LOCK" 2>/dev/null || echo unknown)" >&2
    exit 1
fi
# fd 9 holds the flock for the duration of this script; record the holder
echo "$$ $(date '+%H:%M:%S') $*" > "$LOCK"
echo "build_lock: acquired $(date '+%H:%M:%S') — $*"
"$@"
rc=$?
echo "build_lock: released $(date '+%H:%M:%S') (rc=$rc)"
exit $rc
