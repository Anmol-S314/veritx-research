#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
verilator --lint-only --Wall -Wno-fatal --top-module ring_native_route ring_native_route.sv
verilator --lint-only --Wall -Wno-fatal --top-module ring_native_fabric ring_native_fabric.sv
python3 route_coverage.py
scratch=${JCODE_SCRATCH_DIR:-/home/datavex/.jcode/scratch}
mkdir -p "$scratch"
tmpdir=$(mktemp -d "$scratch/ring-native-verify.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_ring_native_fabric \
  ring_native_fabric.sv tb_ring_native_fabric.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_ring_native_fabric"
