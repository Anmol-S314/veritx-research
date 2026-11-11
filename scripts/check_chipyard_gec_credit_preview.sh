#!/usr/bin/env bash
# Elaborate the compiled GEC *credit* preview for a contract and report the
# emitted artifact.
#
# This is the emitter the selected-project RTL preview depends on.  It is the
# Chisel CreditRouter path: per-input-port-per-VC queues, VC allocation,
# switch allocation and credit ownership, as opposed to the topology-only
# preview emitted by check_chipyard_gec_preview.sh.
#
# Usage:
#   bash scripts/check_chipyard_gec_credit_preview.sh <contract-dir> <out-dir>
#
# <contract-dir> must contain SelectedGec.scala, contract.json and
# resources/selected-gec.bin from veritx_dse.product.chipyard_gec.export_contract.
#
# The heap cap is the repo's standard SBT_OPTS cap.  The emitted size and the
# elaboration dimensions are printed so a run can be compared against another
# without re-reading the artifact.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <contract-dir> <out-dir>" >&2
  exit 2
fi
CONTRACT="$1"
OUT="$2"
if [[ "$CONTRACT" = /* ]]; then ABS_CONTRACT="$CONTRACT"; else ABS_CONTRACT="$REPO/$CONTRACT"; fi
if [[ "$OUT" = /* ]]; then ABS_OUT="$OUT"; else ABS_OUT="$REPO/$OUT"; fi

if [[ ! -f "$ABS_CONTRACT/SelectedGec.scala" ]]; then
  echo "contract dir must contain SelectedGec.scala: $ABS_CONTRACT" >&2
  exit 2
fi

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

export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
export SBT_OPTS="${SBT_OPTS:--Xmx3G -XX:ActiveProcessorCount=1}"

mkdir -p "$ABS_OUT"
# The Scala/Chisel build writes large temporary files; keep them off tmpfs.
export TMPDIR="${TMPDIR_OVERRIDE:-$ABS_OUT/tmp}"
mkdir -p "$TMPDIR"

echo "contract: $ABS_CONTRACT"
echo "out:      $ABS_OUT"
echo "heap:     ${SBT_OPTS}"

(
  cd tracks/t3-topology/rtl/chipyard/standalone-check-gec
  GEC_CONTRACT_DIR="$ABS_CONTRACT" "$SBT_BIN" -batch \
    "runMain veritx.chipyard.EmitCompiledGecCreditPreview $ABS_OUT/rtl"
)

emitted="$ABS_OUT/rtl/CompiledGecCreditPreview.v"
if [[ ! -f "$emitted" ]]; then
  echo "credit preview was not emitted" >&2
  exit 1
fi
bytes="$(wc -c < "$emitted")"
sha="$(sha256sum "$emitted" | cut -d' ' -f1)"
echo "EMITTED credit preview: $emitted"
echo "bytes: $bytes"
echo "sha256: $sha"

# The hierarchical emitter writes the distinct router bodies in one companion
# file and the top instantiates them.  A module name defined in two files (for
# example `Queue` from both the top and the bodies) cannot be compiled, so the
# artifact set is checked here rather than discovered by the next simulator.
python3 - "$ABS_OUT/rtl" <<'PY'
import collections
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
files = sorted(root.glob("*.v"))
if not files:
    raise SystemExit("no Verilog artifacts emitted")

defs = collections.defaultdict(list)
for path in files:
    text = path.read_text(errors="replace")
    for m in re.finditer(r"(?m)^module\s+(\w+)", text):
        defs[m.group(1)].append(path.name)

duplicates = {name: where for name, where in defs.items() if len(where) > 1}
if duplicates:
    print("DUPLICATE MODULE DEFINITIONS: %r" % duplicates, file=sys.stderr)
    raise SystemExit(1)

print("artifacts:")
for path in sorted(files, key=lambda p: -p.stat().st_size):
    print("  %12d  %s" % (path.stat().st_size, path.name))
print("unique modules across %d files: %d" % (len(files), len(defs)))
PY
