#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
verilator --lint-only --Wall -Wno-fatal --top-module structured_qtree_fabric structured_qtree_fabric.sv
scratch=${JCODE_SCRATCH_DIR:-$HOME/.jcode/scratch}
mkdir -p "$scratch"
tmpdir=$(mktemp -d "$scratch/structured-qtree-verify.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT
verilator --binary --timing -j 4 -Wno-fatal --top-module tb_structured_qtree \
  structured_qtree_fabric.sv tb_structured_qtree.sv --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_structured_qtree"
