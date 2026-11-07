#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/fattree-native-nca.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT
verilator --lint-only --sv -Wall -Wno-fatal --top-module fattree_native_nca_fabric "$here/fattree_native_nca.sv"
verilator --binary --timing --assert -j 4 -Wno-fatal --sv --top-module tb_fattree_native_nca \
  "$here/fattree_native_nca.sv" "$here/tb_fattree_native_nca.sv" --Mdir "$tmpdir/obj"
"$tmpdir/obj/Vtb_fattree_native_nca"
