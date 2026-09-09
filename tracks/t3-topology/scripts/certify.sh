#!/bin/bash
# certify.sh — production certification matrix for R10 NoC fabric.
#
# Usage: certify.sh <build_dir> [quick|full] [extra env pairs...]
#   build_dir: dir containing obj_dir/Vnoc_top built from R10 template
#   quick: patterns {uniform,hotspot} x IR {0.08,0.32} x seed {42,99}
#   full : all patterns x IR {0.04,0.16,0.20,0.24,0.32,0.48,0.64,0.99} x seeds {42,43,44}
#
# Checks per run:
#   P1 liveness      : "outstanding:   0 OK"
#   P2 routing       : wrong_dst == 0
#   P4 pair-order    : zero P4-ORDER-VIOLATION lines
# Any violation -> FAIL recorded, run continues (full report), exit 1 at end.

BUILD=${1:?usage: certify.sh <build_dir> [quick|full]}
TIER=${2:-quick}
shift 2 2>/dev/null
EXTRA_ENV="$@"

BIN=$BUILD/obj_dir/Vnoc_top
[ -x "$BIN" ] || { echo "FATAL: $BIN missing"; exit 2; }

if [ "$TIER" = full ]; then
  PATTERNS="uniform hotspot transpose tornado neighbor bitrev"
  IRS="0.04 0.16 0.20 0.24 0.32 0.48 0.64 0.99"
  SEEDS="42 43 44"
else
  PATTERNS="uniform hotspot transpose tornado neighbor bitrev"
  IRS="0.08 0.32"
  SEEDS="42 99"
fi

PASS=0; FAIL=0; FAILED_RUNS=""

for pat in $PATTERNS; do
  for ir in $IRS; do
    for seed in $SEEDS; do
      # L6: timeout scales with router count (64n needs ~5x mesh_4x4)
      TMO=$(( 180 * ${NOC_CERT_TMO_SCALE:-1} ))
      OUT=$(env NOC_PATTERN=$pat NOC_IR=$ir NOC_SEED=$seed $EXTRA_ENV \
            timeout $TMO "$BIN" 2>/dev/null)
      STUCK=$(echo "$OUT" | grep "^outstanding" | grep -o '[0-9]*' | head -1)
      WD=$(echo "$OUT" | grep "^wrong_dst" | grep -o '[0-9]*' | head -1)
      ORD=$(echo "$OUT" | grep -c "P4-ORDER-VIOLATION")
      # H6 P3: conservation must be OK (every pkt completes exactly once)
      CONS=$(echo "$OUT" | grep "^conservation" | grep -o "OK\\|FAIL" | head -1)
      # H7: trace-player overflow = TB artifact, reported separately
      OVF=$(echo "$OUT" | grep -c "TRACE-OVERFLOW")

      REASON=""
      [ "$STUCK" != "0" ] && REASON="$REASON stuck=$STUCK"
      [ "$WD" != "0" ] && REASON="$REASON wrong_dst=$WD"
      [ "$ORD" != "0" ] && REASON="$REASON order_viol=$ORD"
      [ "$CONS" = "FAIL" ] && REASON="$REASON conservation=FAIL"
      [ "$OVF" != "0" ] && echo "WARN pat=$pat ir=$ir seed=$seed: $OVF TRACE-OVERFLOWs (TB cap)"

      if [ -z "$REASON" ]; then
        PASS=$((PASS+1))
        echo "PASS pat=$pat ir=$ir seed=$seed"
      else
        FAIL=$((FAIL+1))
        FAILED_RUNS="$FAILED_RUNS
FAIL pat=$pat ir=$ir seed=$seed:$REASON"
        echo "FAIL pat=$pat ir=$ir seed=$seed:$REASON"
      fi
    done
  done
done

echo ""
echo "=== CERTIFICATION SUMMARY ($TIER) ==="
echo "PASS: $PASS  FAIL: $FAIL"
[ -n "$FAILED_RUNS" ] && echo "$FAILED_RUNS"
[ "$FAIL" = "0" ]
