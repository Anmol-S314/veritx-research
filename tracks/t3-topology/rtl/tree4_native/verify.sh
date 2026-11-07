#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
scratch=${JCODE_SCRATCH_DIR:-$HOME/.jcode/scratch}
mkdir -p "$scratch"
tmpdir=$(mktemp -d "$scratch/tree4-native-verify.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT
verilator --lint-only --Wall -Wno-fatal --top-module tree4_native_fabric tree4_native_fabric.sv
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_tree4_native \
  tree4_native_fabric.sv tb_tree4_native.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_tree4_native"
