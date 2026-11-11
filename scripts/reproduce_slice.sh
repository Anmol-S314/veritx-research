#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=runs/slice; CLEAN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --clean) CLEAN="--clean"; shift ;;
    -h|--help) echo "usage: scripts/reproduce_slice.sh [--out runs/slice] [--clean]"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
python3 scripts/reproduce_slice.py --out "$OUT" $CLEAN
python3 scripts/verify_slice.py --out "$OUT"
