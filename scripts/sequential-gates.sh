#!/usr/bin/env bash
# Sequential hardware gates: run ONE stage at a time, in order, with full
# logs, stopping at the first failure. No parallelism — this host's swap
# saturates and concurrent Verilator builds starve the box.
#
# Usage: scripts/sequential-gates.sh [stage ...]
#   no args:  run every stage in order
#   stages:   any of: dse-pytest slice-family parameterized families-lint \
#               release-matrix playwright reproduce verify frontend-tsc
#   e.g.  scripts/sequential-gates.sh slice-family
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
DSE=tracks/t3-topology/dse
export PYTHONPATH="$REPO/$DSE:$REPO/$DSE/tests"
OUT="$REPO/runs/sequential-gates-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"

# Scratch must live OUTSIDE the repository: the BookSim source-verification
# gate refuses any output directory that is an ancestor of, or inside, the
# source tree (a repo-local TMPDIR makes that gate fail for the wrong reason).
SCRATCH="${VERITX_SCRATCH:-/home/datavex/veritx-tmp}"
mkdir -p "$SCRATCH"
export TMPDIR="$SCRATCH"

free_mb=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
if [ "${free_mb:-0}" -lt 4096 ]; then
  echo "REFUSING TO START: only ${free_mb} MiB available; real runs (builds, sims) need ~4 GiB headroom."
  echo "Wait for current builds to finish, or free memory first."
  exit 3
fi
swap_use_mb=$(awk '/^SwapFree:/ {print int($2/1024)}' /proc/meminfo)
if [ "${swap_use_mb:-0}" -lt 1024 ]; then
  echo "REFUSING TO START: swap nearly exhausted (${swap_use_mb} MiB free); heavy jobs will thrash."
  exit 3
fi

declare -A RC=()

stage() {
  local name="$1"; shift
  echo "=== stage $name → $OUT/$name.log"
  local rc=0
  ( "$@" ) > "$OUT/$name.log" 2>&1 || rc=$?
  RC[$name]=$rc
  echo "=== $name exit=$rc"
  bash "$REPO/scripts/cleanup_runs.sh" 2>&1 | tail -1 || true
  if [ "$rc" -ne 0 ]; then
    echo "STOP at $name; see $OUT/$name.log"
    printf '{\n  "stage": "%s",\n  "exit_code": %d,\n  "log": "%s"\n}\n' "$name" "$rc" "$OUT/$name.log" > "$OUT/failed.json"
    exit "$rc"
  fi
}

run_selected() {
  if [ "$#" -eq 0 ]; then set -- dse-pytest slice-family parameterized families-lint release-matrix playwright reproduce verify frontend-tsc; fi
  for stage_name in "$@"; do
    case "$stage_name" in
      frontend-tsc) stage frontend-tsc npx --prefix apps/studio/prototype tsc --noEmit ;;
      dse-pytest)   stage dse-pytest python3 -m pytest "$DSE/tests" -q -p no:randomly ;;
      slice-family) stage slice-family python3 -m pytest "$DSE/tests/test_project_top_slice.py" "$DSE/tests/test_project_top_shared.py" "$DSE/tests/test_project_top_parameterized.py" -q --tb=short ;;
      parameterized) stage parameterized python3 -m pytest "$DSE/tests/test_project_top_parameterized.py" -q --tb=short ;;
      families-lint) stage families-lint python3 -m pytest "$DSE/tests/test_project_top_slice.py::test_composed_family_lints_and_sims" "$DSE/tests/test_project_top_shared.py" -q --tb=short ;;
      release-matrix) stage release-matrix python3 scripts/complete_design.py --release --out "$OUT/release-matrix" ;;
      playwright)   stage playwright npm --prefix apps/studio/prototype run test:e2e ;;
      reproduce)    stage reproduce bash scripts/reproduce_slice.sh --out "$OUT/slice" --clean ;;
      verify)       stage verify bash scripts/verify_slice.sh ;;
      *) echo "unknown stage: $stage_name" >&2; return 2 ;;
    esac
  done
  echo "ALL SELECTED STAGES PASS"
  printf '{\n  "result": "PASS",\n  "stages": {\n' > "$OUT/manifest.json"
  local first=1
  for key in "${!RC[@]}"; do
    if [ $first -eq 0 ]; then printf ',\n' >> "$OUT/manifest.json"; fi
    first=0
    printf '    "%s": %d' "$key" "${RC[$key]}" >> "$OUT/manifest.json"
  done
  printf '\n  }\n}\n' >> "$OUT/manifest.json"
  echo "manifest: $OUT/manifest.json"
}

run_selected "$@"
