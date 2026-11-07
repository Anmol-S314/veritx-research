#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scratch_root="${JCODE_SCRATCH_DIR:-${TMPDIR:-$HOME/.jcode/scratch}}"
mkdir -p "$scratch_root"
tmpdir="$(mktemp -d "$scratch_root/gec-mecs-native.XXXXXXXX")"
trap 'rm -rf -- "$tmpdir"' EXIT HUP INT TERM
iverilog -g2012 -s tb_gec_mecs_channel -o "$tmpdir/tb.out" \
  "$here/gec_mecs_channel.sv" "$here/tb_gec_mecs_channel.sv"
vvp "$tmpdir/tb.out"
verilator --lint-only --timing -Wall -Wno-fatal --top-module gec_mecs_channel \
  "$here/gec_mecs_channel.sv"
