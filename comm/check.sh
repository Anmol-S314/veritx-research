#!/bin/bash
# comm/check.sh — list unread messages for an agent.
# Usage: bash comm/check.sh <name>   (shows subjects + paths)
#        bash comm/check.sh <name> --all   (also read ones)

NAME="${1:?usage: comm/check.sh <name>}"
DIR="$(cd "$(dirname "$0")" && pwd)/inbox/$NAME"
[ -d "$DIR" ] || { echo "no inbox for $NAME"; exit 1; }

for f in "$DIR"/*.txt; do
  [ -f "$f" ] || continue
  status="$(grep -m1 '^Status:' "$f" | cut -d' ' -f2-)"
  from="$(grep -m1 '^From:' "$f" | cut -d' ' -f2-)"
  subj="$(grep -m1 '^Subject:' "$f" | cut -d' ' -f2-)"
  if [ "$status" = "NEW" ] || [ "${2:-}" = "--all" ]; then
    echo "[$status] $from: $subj  ($(basename "$f"))"
  fi
done
