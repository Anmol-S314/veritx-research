#!/usr/bin/env bash
# Export a compiled GEC contract, elaborate it, and run the Verilator testbench.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
OUT="${1:-runs/chipyard-gec6}"
if [[ "$OUT" = /* ]]; then ABS="$OUT"; else ABS="$REPO/$OUT"; fi

if [[ -z "${JAVA_HOME:-}" ]]; then
  for candidate in /usr/lib/jvm/java-17-openjdk-amd64 /usr/lib/jvm/java-17-* /opt/java-17; do
    if [[ -x "$candidate/bin/java" ]]; then JAVA_HOME="$candidate"; break; fi
  done
fi
if [[ -z "${JAVA_HOME:-}" || ! -x "$JAVA_HOME/bin/java" ]]; then
  echo "JAVA_HOME must point to a JDK 17 installation (JDK 25 breaks Scala 2.13.10)." >&2
  exit 2
fi
major="$("$JAVA_HOME/bin/java" -version 2>&1 | awk -F'"' '/version/{print $2}' | cut -d. -f1)"
if [[ "$major" != "17" ]]; then
  echo "JDK 17 required, found major $major at $JAVA_HOME." >&2
  exit 2
fi
SBT_BIN="${SBT_BIN:-$(command -v sbt || true)}"
if [[ -z "$SBT_BIN" || ! -x "$SBT_BIN" ]]; then
  echo "sbt 1.10.7 not found; set SBT_BIN or put sbt on PATH." >&2
  exit 2
fi
for tool in verilator python3 g++; do
  command -v "$tool" >/dev/null || { echo "required tool missing: $tool" >&2; exit 2; }
done

export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
export SBT_OPTS="${SBT_OPTS:--Xmx3G -XX:ActiveProcessorCount=1}"

echo "contract: $ABS"
rm -rf "$ABS/rtl" "$ABS/obj"
(
  cd tracks/t3-topology/dse
  PYTHONPATH=tests:. python3 - "$ABS" <<'PY'
import sys
from pathlib import Path
from test_chipyard_gec import request
from veritx_dse.product.chipyard_gec import export_contract
out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
print(export_contract(request(6).to_dict(), out, revision_id='check-gec6'))
PY
)

(
  cd tracks/t3-topology/rtl/chipyard/standalone-check-gec
  GEC_CONTRACT_DIR="$ABS" "$SBT_BIN" -batch \
    "runMain veritx.chipyard.EmitCompiledGecPreview $ABS/rtl"
)

python3 tracks/t3-topology/rtl/chipyard/make_testbench.py \
  "$ABS/contract.json" "$ABS/rtl/tb.sv"

verilator --binary --timing --assert --top-module tb_compiled_gec \
  -Wno-fatal --Mdir "$ABS/obj" \
  "$ABS/rtl/tb.sv" "$ABS/rtl/CompiledGecPreview.v" > "$ABS/verilator.log" 2>&1

(
  cd "$ABS/rtl"
  "$ABS/obj/Vtb_compiled_gec"
) | tee "$ABS/simulation.log"
grep -q '^PASS compiled_gec' "$ABS/simulation.log"
