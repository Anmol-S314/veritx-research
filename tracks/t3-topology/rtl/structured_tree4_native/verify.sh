#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
scratch=${JCODE_SCRATCH_DIR:-$HOME/.jcode/scratch}
mkdir -p "$scratch"
tmpdir=$(mktemp -d "$scratch/structured-tree4-verify.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT
verilator --lint-only --Wall -Wno-fatal --top-module structured_tree4_fabric structured_tree4_fabric.sv
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_structured_tree4 \
  structured_tree4_fabric.sv tb_structured_tree4.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_structured_tree4"
