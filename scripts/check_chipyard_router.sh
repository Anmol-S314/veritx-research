#!/usr/bin/env bash
# Run the repo-owned Chisel router/policy checks with the pinned toolchain.
set -euo pipefail
cd "$(dirname "$0")/.."

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
cd tracks/t3-topology/rtl/chipyard/standalone-check
exec "$SBT_BIN" -batch test
