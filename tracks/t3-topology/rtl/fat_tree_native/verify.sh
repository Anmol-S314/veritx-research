#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
scratch_root=${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}
tmpdir=$(mktemp -d "$scratch_root/fat-tree-native-verify.XXXXXX")
trap 'rm -rf -- "$tmpdir"' EXIT
verilator --lint-only --Wall -Wno-fatal --top-module fat_tree_native_fabric fat_tree_native_fabric.sv
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_fat_tree_native \
  fat_tree_native_fabric.sv tb_fat_tree_native.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_fat_tree_native"
