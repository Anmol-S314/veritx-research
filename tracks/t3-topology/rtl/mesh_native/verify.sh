#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v verilator >/dev/null || { echo "verilator is required" >&2; exit 127; }
scratch_root=${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}
mkdir -p "$scratch_root"
tmpdir=$(mktemp -d "$scratch_root/mesh-native.XXXXXX")
trap 'rm -rf -- "$tmpdir"' EXIT
verilator --lint-only --Wall -Wno-fatal --top-module mesh_native mesh_native.sv
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_mesh_native \
  mesh_native.sv tb_mesh_native.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_mesh_native"
