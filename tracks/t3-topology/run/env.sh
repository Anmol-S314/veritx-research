#!/usr/bin/env bash
# =============================================================================
# T3 Topology — Environment bootstrap
# Source this file from any directory to enable the 't3' CLI command:
#
#   source tracks/t3-topology/run/env.sh
#   t3 help
#   t3 check
#   t3 timeloop
#   t3 exec <command>
#
# Sourcing this file adds 't3' to your PATH and enables transparent container
# execution so commands run inside the veritx-tools-base container seamlessly.
# =============================================================================

# --------------------------------------------------------------------------
# 1. Resolve this file's own location (works whether sourced or executed)
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
# 2. Repo root (two levels up from tracks/t3-topology/)
# --------------------------------------------------------------------------
export REPO_ROOT="$(cd "$T3_DIR/../.." && pwd)"

# --------------------------------------------------------------------------
# 3. Python — select python interpreter
# --------------------------------------------------------------------------
if [ -f /.dockerenv ] || [ -f /run/.containerenv ]; then
    export T3_PYTHON="$(command -v python3)"
elif [ -x "$REPO_ROOT/venv/bin/python3" ] && "$REPO_ROOT/venv/bin/python3" -c "import pandas" &>/dev/null; then
    export T3_PYTHON="$REPO_ROOT/venv/bin/python3"
elif command -v python3 &>/dev/null; then
    export T3_PYTHON="$(command -v python3)"
else
    export T3_PYTHON="python3"
fi

# --------------------------------------------------------------------------
# 4. Booksim binary & Configs
# --------------------------------------------------------------------------
export BOOKSIM_BIN="${BOOKSIM_BIN:-booksim}"
export CONFIG="${CONFIG:-baseline}"
export T3_SCRIPTS="$T3_DIR/scripts"
if [ -z "${T3_RESULTS:-}" ] || [ "$T3_RESULTS" = "$T3_DIR/results" ]; then
    export T3_RESULTS="$T3_DIR/results/$CONFIG"
fi
export T3_CONFIGS="$T3_DIR/configs"

# --------------------------------------------------------------------------
# 5. Analysis tunables
# --------------------------------------------------------------------------
export PACKET_SIZE_BITS="${PACKET_SIZE_BITS:-128}"
export SAT_K="${SAT_K:-2.0}"
export RATES="${RATES:-0.002,0.005,0.01,0.02,0.03}"
export MPLBACKEND="${MPLBACKEND:-Agg}"
export MPLCONFIGDIR="/tmp"
if [ "$HOME" = "/" ] || [ -z "$HOME" ]; then
    export HOME="/tmp"
fi

# --------------------------------------------------------------------------
# 6. PATH — make 't3' top-level script callable without a path prefix
# --------------------------------------------------------------------------
case ":$PATH:" in
    *":$T3_DIR:"*) ;;
    *) export PATH="$T3_DIR:$PATH" ;;
esac

# --------------------------------------------------------------------------
# 7. Summary banner
# --------------------------------------------------------------------------
echo "  [T3 env]  T3_DIR     → $T3_DIR"
echo "  [T3 env]  REPO_ROOT  → $REPO_ROOT"
if [ -f /.dockerenv ] || [ -f /run/.containerenv ]; then
    echo "  [T3 env]  MODE       → Container Environment (native execution)"
else
    echo "  [T3 env]  MODE       → Host Terminal (transparent container execution active)"
fi
echo "  [T3 env]  Run 't3 help' or 't3 check' to get started."
