#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/dragonflynew-native.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
python3 "$HERE/check_topology.py"
verilator --binary --timing --assert -Wno-fatal --top-module tb_dragonflynew_native \
  --Mdir "$SCRATCH/obj_dir" \
  "$HERE/dragonflynew_native.sv" "$HERE/tb_dragonflynew_native.sv"
timeout 90 "$SCRATCH/obj_dir/Vtb_dragonflynew_native"
