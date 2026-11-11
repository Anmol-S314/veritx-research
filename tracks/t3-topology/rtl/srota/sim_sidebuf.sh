#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
verilator=${VERILATOR:-verilator}

if ! command -v "$verilator" >/dev/null 2>&1; then
  printf 'error: Verilator not found: %s\n' "$verilator" >&2
  exit 127
fi

build_dir=$(mktemp -d "${TMPDIR:-/tmp/opencode}/srota-sidebuf.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT

"$verilator" --binary --timing --assert --Mdir "$build_dir/obj" \
  --top-module tb_srota_sidebuf -Wno-TIMESCALEMOD \
  "$script_dir/srota_sidebuf.sv" "$script_dir/tb_srota_sidebuf.sv"
"$build_dir/obj/Vtb_srota_sidebuf"
