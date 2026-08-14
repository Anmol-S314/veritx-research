#!/bin/bash
# comm/publish.sh — publish to a shared topic (pub-sub).
# Usage: bash comm/publish.sh <topic> "<subject>"
#        bash comm/publish.sh <topic> "<subject>" <<< "body"
# Topics: status (live state), decisions (made calls), alerts (blockers,
# build hazards), questions (open to anyone). Topic dirs under comm/topics/.
# Anyone may read a topic; publishing stamps From. Read topics with:
#   comm/read.sh <topic> [--all]

set -euo pipefail

FROM="unknown"
if [ "$1" = "-f" ]; then FROM="$2"; shift 2; fi
TOPIC="${1:?usage: comm/publish.sh [-f from] <topic> <subject>}"
SUBJECT="${2:?usage: comm/publish.sh [-f from] <topic> <subject>}"

case "$FROM" in laura|dave|junior|steve) ;; *) echo "unknown sender: $FROM" >&2; exit 1;; esac

DIR="$(cd "$(dirname "$0")" && pwd)"
[ -d "$DIR/topics/$TOPIC" ] || { echo "no such topic: $TOPIC (status|decisions|alerts|questions)" >&2; exit 1; }

SLUG="$(echo "$SUBJECT" | tr '[:upper:] ' '[:lower:]_' | tr -cd 'a-z0-9_' | cut -c1-40)"
STAMP="$(date +%Y-%m-%d-%H%M)"
FILE="$DIR/topics/$TOPIC/$STAMP-$FROM-$SLUG.txt"

{
  echo "Status: NEW"
  echo "From: $FROM"
  echo "Topic: $TOPIC"
  echo "Date: $(date '+%Y-%m-%d %H:%M %Z')"
  echo "Subject: $SUBJECT"
  echo
  if [ -t 0 ]; then
    echo "(no body — type it below, Ctrl-D when done)"
    cat
  else
    cat
  fi
} > "$FILE"

echo "published: $FILE"
