#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
verilator --lint-only --Wall -Wno-fatal --top-module qtree_native_fabric qtree_native_fabric.sv
scratch=${JCODE_SCRATCH_DIR:-$HOME/.jcode/scratch}
mkdir -p "$scratch"
tmpdir=$(mktemp -d "$scratch/qtree-native-verify.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_qtree_native \
  qtree_native_fabric.sv tb_qtree_native.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_qtree_native"
