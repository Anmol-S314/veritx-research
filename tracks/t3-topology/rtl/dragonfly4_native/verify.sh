#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
SCRATCH_ROOT="${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$SCRATCH_ROOT"
SCRATCH="$(mktemp -d "$SCRATCH_ROOT/dragonfly4_native.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
verilator --binary --timing --assert -Wall -Wno-fatal --top-module tb_dragonfly4_native \
  --Mdir "$SCRATCH/obj_dir" \
  "$ROOT/tracks/t3-topology/rtl/dragonfly4_native/dragonfly4_native.sv" \
  "$ROOT/tracks/t3-topology/rtl/dragonfly4_native/tb_dragonfly4_native.sv"
"$SCRATCH/obj_dir/Vtb_dragonfly4_native"
