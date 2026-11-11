#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
build_dir="$(mktemp -d "${TMPDIR:-/tmp/opencode}/srota-route-sim.XXXXXX")"
trap 'rm -rf -- "$build_dir"' EXIT

verilator --binary --timing --timescale 1ns/1ps -Wno-fatal --top-module tb_srota_route_compute \
  --Mdir "$build_dir/obj_dir" \
  "$script_dir/srota_route_pkg.sv" \
  "$script_dir/srota_route_compute.sv" \
  "$script_dir/srota_drop_cell.sv" \
  "$script_dir/tb_srota_route_compute.sv"

"$build_dir/obj_dir/Vtb_srota_route_compute"
