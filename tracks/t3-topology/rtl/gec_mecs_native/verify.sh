#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scratch_root="${JCODE_SCRATCH_DIR:-${TMPDIR:-$HOME/.jcode/scratch}}"
mkdir -p "$scratch_root"
tmpdir="$(mktemp -d "$scratch_root/gec-mecs-native.XXXXXXXX")"
trap 'rm -rf -- "$tmpdir"' EXIT HUP INT TERM

python3 "$here/check_gec_mecs16.py"

iverilog -g2012 -s tb_gec_mecs_channel -o "$tmpdir/channel.out" \
  "$here/gec_mecs_channel.sv" "$here/tb_gec_mecs_channel.sv"
vvp "$tmpdir/channel.out"
verilator --lint-only --timing -Wall -Wno-fatal -Wno-DECLFILENAME \
  --top-module gec_mecs_channel "$here/gec_mecs_channel.sv"

verilator --binary --timing -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-BLKSEQ \
  --top-module tb_gec_mecs16_fabric --Mdir "$tmpdir/obj" \
  "$here/gec_mecs_fabric.sv" "$here/tb_gec_mecs16_fabric.sv"
timeout 90 "$tmpdir/obj/Vtb_gec_mecs16_fabric"
