#!/usr/bin/env bash
# =============================================================================
# T3 Topology — Environment bootstrap
# Source this file from the "run" directory before any script or make target:
#
#   cd tracks/t3-topology/run
#   source env.sh          # sets up all T3_* variables
#   t3 help               # list all commands
#   t3 all                # run full analysis pipeline
#
# This file lives in  tracks/t3-topology/run/
# T3_DIR is resolved as the parent:  tracks/t3-topology/
# It works from any working directory.
# =============================================================================

# --------------------------------------------------------------------------
# 1.  Resolve this file's own location (works whether sourced or executed)
# --------------------------------------------------------------------------
if [ -n "${BASH_SOURCE[0]}" ]; then
    _T3_ENV_SH="${BASH_SOURCE[0]}"
else
    _T3_ENV_SH="$0"
fi
_T3_RUN_DIR="$(cd "$(dirname "$_T3_ENV_SH")" && pwd)"   # .../run/
T3_DIR="$(cd "$_T3_RUN_DIR/.." && pwd)"                  # .../t3-topology/
export T3_DIR

# --------------------------------------------------------------------------
# 2.  Repo root (two levels up from tracks/t3-topology/)
# --------------------------------------------------------------------------
export REPO_ROOT="$(cd "$T3_DIR/../.." && pwd)"

# --------------------------------------------------------------------------
# 3.  Python — prefer the repo venv, fall back to system python3
# --------------------------------------------------------------------------
if [ -x "$REPO_ROOT/venv/bin/python3" ]; then
    export T3_PYTHON="$REPO_ROOT/venv/bin/python3"
elif command -v python3 &>/dev/null; then
    export T3_PYTHON="$(command -v python3)"
else
    echo "  [env.sh] ✗ python3 not found — install Python 3.9+ or create venv" >&2
fi

# --------------------------------------------------------------------------
# 4.  Booksim binary  (override: BOOKSIM_BIN=/path/to/booksim source env.sh)
# --------------------------------------------------------------------------
export BOOKSIM_BIN="${BOOKSIM_BIN:-booksim}"

# --------------------------------------------------------------------------
# 5.  Project directories  (all anchored to T3_DIR — zero hardcoded paths)
# --------------------------------------------------------------------------
export T3_SCRIPTS="$T3_DIR/scripts"
export T3_RESULTS="$T3_DIR/results"
export T3_CONFIGS="$T3_DIR/configs"

# --------------------------------------------------------------------------
# 6.  Analysis tunables (override any of these before sourcing if needed)
# --------------------------------------------------------------------------
export PACKET_SIZE_BITS="${PACKET_SIZE_BITS:-128}"   # energy_proxy = hops × this
export SAT_K="${SAT_K:-2.0}"                         # saturation threshold multiplier
export RATES="${RATES:-0.002,0.005,0.01,0.02,0.03}"  # injection rate sweep

# Optional: point to a traffic matrix file (skips uniform traffic)
# export TRAFFIC_MATRIX="$T3_RESULTS/traffic_matrix.txt"

# --------------------------------------------------------------------------
# 7.  Matplotlib (suppress GUI pop-ups when running headless)
# --------------------------------------------------------------------------
export MPLBACKEND="${MPLBACKEND:-Agg}"

# --------------------------------------------------------------------------
# 8.  PATH — make 't3' top-level script callable without a path prefix
# --------------------------------------------------------------------------
export PATH="$T3_DIR:$PATH"

# --------------------------------------------------------------------------
# 9.  Pretty summary
# --------------------------------------------------------------------------
echo "  [T3 env]  T3_DIR     → $T3_DIR"
echo "  [T3 env]  REPO_ROOT  → $REPO_ROOT"
echo "  [T3 env]  T3_PYTHON  → $T3_PYTHON"
echo "  [T3 env]  BOOKSIM    → $BOOKSIM_BIN"
echo "  [T3 env]  T3_RESULTS → $T3_RESULTS"
echo "  [T3 env]  Run 't3 help' to see available commands."
