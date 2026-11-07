#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SCRATCH_ROOT=${JCODE_SCRATCH_DIR:-${TMPDIR:-$HOME/.jcode/scratch}}
mkdir -p "$SCRATCH_ROOT"
SCRATCH=$(mktemp -d "$SCRATCH_ROOT/fly-native-verify.XXXXXX")
trap 'rm -rf "$SCRATCH"' EXIT
verilator --binary --timing --assert -Wall -Wno-fatal -Wno-DECLFILENAME --top-module tb_fly_native \
  --Mdir "$SCRATCH/obj_dir" "$HERE/fly_native_fabric.sv" "$HERE/tb_fly_native.sv"
"$SCRATCH/obj_dir/Vtb_fly_native"
