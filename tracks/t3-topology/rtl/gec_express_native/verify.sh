#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scratch="${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}"
mkdir -p -- "$scratch"
tmpdir="$(mktemp -d "$scratch/gec-express-native.XXXXXXXX")"
trap 'rm -rf -- "$tmpdir"' EXIT HUP INT TERM
verilator --lint-only --timing -Wall -Wno-fatal -Wno-DECLFILENAME --top-module gec_express_native_fabric \
  "$here/gec_express_native.sv"
verilator --binary --timing -j 4 -Wno-fatal -Wno-TIMESCALEMOD -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND \
  -Wno-DECLFILENAME --top-module tb_gec_express_native \
  "$here/gec_express_native.sv" "$here/tb_gec_express_native.sv" --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_gec_express_native"
