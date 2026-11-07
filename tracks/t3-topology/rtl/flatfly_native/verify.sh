#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
SCRATCH_ROOT="${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$SCRATCH_ROOT"
SCRATCH="$(mktemp -d "$SCRATCH_ROOT/flatfly_native_verilator.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
python3 "$HERE/check_topology.py"
verilator --binary --timing --assert -Wall -Wno-fatal -Wno-DECLFILENAME --top-module tb_flatfly_native \
  --Mdir "$SCRATCH/obj_dir" \
  "$HERE/flatfly_native_fabric.sv" "$HERE/tb_flatfly_native.sv"
"$SCRATCH/obj_dir/Vtb_flatfly_native"
