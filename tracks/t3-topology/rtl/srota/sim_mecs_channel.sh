#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
verilator=${VERILATOR:-verilator}
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/srota-mecs-channel.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT

"$verilator" --binary --timing --assert --timescale 1ns/1ps -Wno-fatal \
  --top-module tb_srota_mecs_channel --Mdir "$build_dir/obj_dir" \
  "$script_dir/srota_drop_cell.sv" \
  "$script_dir/srota_mecs_row.sv" \
  "$script_dir/srota_mecs_col.sv" \
  "$script_dir/tb_srota_mecs_channel.sv"

"$build_dir/obj_dir/Vtb_srota_mecs_channel"
