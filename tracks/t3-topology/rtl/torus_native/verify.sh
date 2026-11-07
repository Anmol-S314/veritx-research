#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
SCRATCH_ROOT="${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$SCRATCH_ROOT"
SCRATCH="$(mktemp -d "$SCRATCH_ROOT/torus_native_verilator.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
verilator --binary --timing --assert -Wall -Wno-fatal --top-module tb_torus_native \
  --Mdir "$SCRATCH/obj_dir" \
  "$ROOT/tracks/t3-topology/rtl/torus_native/torus_native_fabric.sv" \
  "$ROOT/tracks/t3-topology/rtl/torus_native/tb_torus_native.sv"
"$SCRATCH/obj_dir/Vtb_torus_native"
