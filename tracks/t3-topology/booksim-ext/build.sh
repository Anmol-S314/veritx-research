#!/usr/bin/env bash
# Rebuild Booksim with everything under src/ here, install it, and verify nothing
# broke. Run INSIDE the tools image (`make shell`):
#
#   ./tracks/t3-topology/booksim-ext/build.sh
#
# src/ mirrors Booksim's own src/ tree, so a file's path decides what it does:
#   src/foo.cpp             -> NEW file, compiled in (Booksim's Makefile globs)
#   src/routers/iq_router.cpp -> OVERLAY, replaces upstream's copy wholesale
#
# Edit here (the repo survives the container), re-run, repeat. The rebuild is
# incremental, so a one-file change is seconds.
set -euo pipefail

EXT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC=/opt/booksim2/src

[ -d "$SRC" ] || {
  echo "✗ $SRC not found. Run inside the tools image:  make shell"
  exit 1
}

# --------------------------------------------------------------------------
# Guard: veritx_hooks.patch edits traffic.cpp and routefunc.cpp. Overlaying
# either would be clobbered by (or fight) that patch. Adding a pattern or
# routing function never requires it -- that's what veritx_ext.cpp is for.
# --------------------------------------------------------------------------
for f in traffic.cpp routefunc.cpp; do
  if [ -e "$EXT/src/$f" ]; then
    echo "✗ src/$f overlays a file that veritx_hooks.patch already edits."
    echo "  Register patterns/routing in src/veritx_ext.cpp instead."
    exit 1
  fi
done

echo "→ sync   booksim-ext/src → $SRC"
# Report overlays explicitly. An overlay pins that file at the version you copied:
# bump the Booksim commit in the Dockerfile and your stale copy silently shadows
# upstream's new one. Additions carry no such risk.
( cd "$EXT/src" && find . -name '*.cpp' -o -name '*.hpp' ) | sed 's|^\./||' | while read -r f; do
  if [ -e "$SRC/$f" ]; then
    echo "   OVERLAY  $f  (shadows upstream — recheck when the pinned commit moves)"
  else
    echo "   new      $f"
  fi
done
cp -r "$EXT/src/." "$SRC/"

echo "→ build"
make -C "$SRC" -j"$(nproc)"

echo "→ install /usr/local/bin/booksim"
# Install rather than exporting BOOKSIM_BIN: `make setup` and the sanity tests
# resolve `booksim` on PATH (tracks/common.mk), so the env var would cover only
# run_experiments.py and silently leave the other paths on the stale binary.
cp "$SRC/booksim" /usr/local/bin/booksim

# --------------------------------------------------------------------------
# Verify. A Booksim that builds but silently drops your extension is exactly
# the failure this exists to catch, so every check fails loudly.
# --------------------------------------------------------------------------
CFG="$SRC/examples/mesh88_lat"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Booksim exits 255 even on a fully successful run, so its exit code is
# meaningless -- `|| true` stops set -e/pipefail tripping on it. Success is read
# from stdout instead, same as run_experiments.py does.
latency() {
  # Lines read "Packet latency average = 57.8681 (1 samples)": take the field
  # after '=', not the last one. Keep the final match (the overall average).
  { booksim "$CFG" "$@" sim_count=1 2>&1 || true; } \
    | awk -F'=' '/Packet latency average/ { split($2, a, " "); v = a[1] } END { print v+0 }'
}

check() { # check <label> <booksim-args...>
  local label="$1"; shift
  local v; v="$(latency "$@")"
  if ! awk -v v="$v" 'BEGIN { exit !(v > 0) }'; then
    echo "  ✗ $label — no latency reported (booksim rejected it, or it deadlocked)"
    { booksim "$CFG" "$@" sim_count=1 2>&1 || true; } | tail -3 | sed 's/^/      /'
    exit 1
  fi
  printf '  ✓ %-34s latency %s\n' "$label" "$v"
}

echo "→ verify: upstream Booksim still behaves"
check "baseline dim_order (upstream)" routing_function=dim_order

echo "→ verify: VeritX routing functions are registered"
check "yx_mesh" routing_function=yx

echo "→ verify: VeritX traffic patterns are registered"
# mesh88_lat is 8x8, and a matrix must be N×N with N = node count.
python3 - "$TMP/m.txt" <<'PY'
import sys
n = 64
with open(sys.argv[1], "w") as f:
    for i in range(n):
        f.write(" ".join("0" if j == i else "1" for j in range(n)) + "\n")
PY
check "matrix(<file>)" "traffic=matrix($TMP/m.txt)"

echo
echo "✓ booksim rebuilt and installed — $(command -v booksim)"
