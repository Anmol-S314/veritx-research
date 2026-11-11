#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 check_graph.py
tmp=$(mktemp "${TMPDIR:-/tmp}/srota64-native.XXXXXX.vvp")
trap 'rm -f "$tmp"' EXIT
iverilog -g2012 -s tb -o "$tmp" srota64_native.sv tb.sv
vvp "$tmp"
