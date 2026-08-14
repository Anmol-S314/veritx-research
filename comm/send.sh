#!/bin/bash
# comm/send.sh — send a message to another agent's inbox.
# Usage: bash comm/send.sh <to> "<subject>"
#        bash comm/send.sh <to> "<subject>" <<< "body text"
# Requires FROM env or defaults to "unknown" — set it in your session
# (export FROM=laura) or pass -f: bash comm/send.sh -f laura dave "subj"

set -euo pipefail

FROM="unknown"
if [ "$1" = "-f" ]; then FROM="$2"; shift 2; fi
TO="${1:?usage: comm/send.sh [-f from] <to> <subject>}"
SUBJECT="${2:?usage: comm/send.sh [-f from] <to> <subject>}"

case "$TO" in laura|dave|junior|steve) ;; *) echo "unknown recipient: $TO" >&2; exit 1;; esac
case "$FROM" in laura|dave|junior|steve) ;; *) echo "unknown sender: $FROM (use -f)" >&2; exit 1;; esac

DIR="$(cd "$(dirname "$0")" && pwd)"
SLUG="$(echo "$SUBJECT" | tr '[:upper:] ' '[:lower:]_' | tr -cd 'a-z0-9_' | cut -c1-40)"
STAMP="$(date +%Y-%m-%d-%H%M)"
FILE="$DIR/inbox/$TO/$STAMP-$FROM-$SLUG.txt"

{
  echo "Status: NEW"
  echo "From: $FROM"
  echo "To: $TO"
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

echo "sent: $FILE"
