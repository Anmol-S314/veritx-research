#!/bin/bash
# comm/read.sh — read a shared topic (pub-sub).
# Usage: bash comm/read.sh <topic> [--all]

TOPIC="${1:?usage: comm/read.sh <topic> [--all]}"
DIR="$(cd "$(dirname "$0")" && pwd)/topics/$TOPIC"
[ -d "$DIR" ] || { echo "no such topic: $TOPIC (status|decisions|alerts|questions)" >&1; exit 1; }

for f in "$DIR"/*.txt; do
  [ -f "$f" ] || continue
  status="$(grep -m1 '^Status:' "$f" | cut -d' ' -f2-)"
  from="$(grep -m1 '^From:' "$f" | cut -d' ' -f2-)"
  subj="$(grep -m1 '^Subject:' "$f" | cut -d' ' -f2-)"
  if [ "$status" = "NEW" ] || [ "${2:-}" = "--all" ]; then
    echo "=== [$status] $from: $subj ==="
    sed -n '/^$/,$p' "$f" | head -20
    echo
  fi
done
