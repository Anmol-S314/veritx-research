#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build_dir=$(mktemp -d "${TMPDIR:-/tmp/opencode}/srota-router-stall.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT

mapfile -t sources < <(
  find "$script_dir" -maxdepth 1 -type f -name 'srota_*.sv' \
    ! -name 'srota_route_pkg.sv' -print | sort
)

verilator --binary --timing --assert --timescale 1ns/1ps -Wno-fatal \
  --top-module tb_srota_router_stall --Mdir "$build_dir/obj_dir" \
  "$script_dir/srota_route_pkg.sv" "${sources[@]}" \
  "$script_dir/tb_srota_router_stall.sv"

"$build_dir/obj_dir/Vtb_srota_router_stall"
