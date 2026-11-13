#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 check_graph.py
tmp=$(mktemp "${TMPDIR:-/tmp}/srota64-native.XXXXXX.vvp")
trap 'rm -f "$tmp"' EXIT
iverilog -g2012 -s tb -o "$tmp" srota64_native.sv tb.sv
vvp "$tmp"
tmp2=$(mktemp "${TMPDIR:-/tmp}/srota64-reset.XXXXXX.vvp")
trap 'rm -f "$tmp" "$tmp2"' EXIT
iverilog -g2012 -s tb_reset -o "$tmp2" srota64_native.sv tb_reset.sv
vvp "$tmp2"
python3 replay_workload.py \
  --trace ../../dse/inputs/traces/test_dynamic.trace
# AXI5 transactions through the fabric (Verilator; Icarus is ~20 ms/cycle here)
python3 run_axi5_fabric.py
