#!/usr/bin/env bash
# Run a command against this repo and decide afterwards whether the tree held
# still long enough for the result to mean anything.
#
# Why: item 11 of docs/product/REMAINING-WORK.md was measured three times and
# none of the three is a green gate. The 2h14m single-process run caught the
# tree mid-rework; the 58-failure follow-up ran in a worktree with none of the
# built producers. In both cases the *number* was reported without the fact
# that would have made it meaningless. This wrapper records the tree before and
# after and refuses to let a moved tree pass as a clean measurement.
#
# What it proves: HEAD and a digest of the porcelain status plus the tracked
# (staged and unstaged) diff were identical before and after, and no second run
# overlapped it (exclusive lock).
# What it does NOT prove: it cannot see a writer changing an *ignored* file
# (`.gitignore` rules apply, e.g. `*.tmp`), nor the content of a file that was
# already untracked before the run. It also says nothing about whether the
# tests measured the right thing. It fences the tree, it does not audit the
# test.
#
# WARNING for negative controls. To prove this script detects a moving tree you
# must let a writer leave a trace. Do NOT pick a file another session has open
# as the probe. On 2026-11-12 exactly that cost ~297 bytes of another session's
# uncommitted work: this script's author appended to
# apps/studio/prototype/PROTOTYPE-PAGES.md, then cleaned up with
# `git checkout -- <path>`, which restores from the index and therefore
# discarded that session's edits instead of reverting only the probe. Create a
# file you own (a name git does not ignore), let it survive to the after-snapshot,
# then delete it with `rm`. Never use `git checkout --` to undo a probe.
#
# Usage:
#   scripts/fenced-run.sh --out DIR -- <command...>
#   scripts/fenced-run.sh --out DIR -- python -m pytest -q tests/test_env_gates.py
#
# Exit codes:
#   <command's own code>   the tree held still; $OUT/verdict says
#                          VALID_CLEAN_TREE or VALID_BUT_DIRTY_AT_START (the
#                          latter still measures uncommitted code, and says so)
#   90                     tree moved: the run is INVALID as a measurement
#   91                     another fenced run holds the lock
#   92                     usage error / not a git checkout
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT=""
LOCK="${TMPDIR:-/tmp}/veritx-fenced-run.lock"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:-}"; shift 2 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "fenced-run: unknown argument \`$1' (separate the command with --)" >&2
       exit 92 ;;
  esac
done

if [ $# -eq 0 ]; then
  echo "fenced-run: no command given; put it after --" >&2
  exit 92
fi

git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || {
  echo "fenced-run: $REPO is not a git checkout" >&2; exit 92; }

[ -n "$OUT" ] || OUT="$REPO/runs/fenced-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT" || exit 92

# Exclusive lock: two fenced runs cannot overlap, so a second writer cannot be
# the thing that moved the tree underneath the first.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "fenced-run: another fenced run holds $LOCK; refusing to overlap" >&2
  exit 91
fi

snapshot() {
  # HEAD plus a digest of every tracked and untracked path git can see, AND
  # the content of the tracked diff. The diff is not optional: a file that is
  # already modified before the run keeps the same porcelain line when a second
  # writer edits it further, so a name-only digest reports "unchanged" for the
  # mid-rework case that actually broke the earlier suite runs. Staged content
  # is included for the same reason.
  {
    echo "head=$(git -C "$REPO" rev-parse HEAD)"
    echo "status_sha256=$(
      { git -C "$REPO" status --porcelain
        git -C "$REPO" diff
        git -C "$REPO" diff --cached
      } | sha256sum | cut -d' ' -f1)"
    echo "status_line_count=$(git -C "$REPO" status --porcelain | wc -l)"
  }
}

snapshot > "$OUT/before.txt"
git -C "$REPO" status --porcelain > "$OUT/status-before.txt"
echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT/before.txt"
printf 'command=%s\n' "$*" > "$OUT/command.txt"

echo "fenced-run: out=$OUT"
echo "fenced-run: $(grep '^head=' "$OUT/before.txt") line_count=$(git -C "$REPO" status --porcelain | wc -l)"

# Run the command with its output teed so a failure can still be read later.
( cd "$REPO" && "$@" ) > >(tee "$OUT/output.log") 2> >(tee -a "$OUT/output.log" >&2)
rc=$?

wait  # let the tee process substitutions finish before comparing

snapshot > "$OUT/after.txt"
git -C "$REPO" status --porcelain > "$OUT/status-after.txt"
echo "ended_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT/after.txt"
echo "command_exit=$rc" >> "$OUT/after.txt"

head_before=$(sed -n 's/^head=//p' "$OUT/before.txt")
head_after=$(sed -n 's/^head=//p' "$OUT/after.txt")
digest_before=$(grep '^status_sha256=' "$OUT/before.txt")
digest_after=$(grep '^status_sha256=' "$OUT/after.txt")
lines_before=$(grep '^status_line_count=' "$OUT/before.txt" | cut -d= -f2)
tracked_before=$(git -C "$REPO" status --porcelain --untracked-files=no | wc -l)

if [ "$head_before" != "$head_after" ]; then
  verdict="INVALID_TREE_MOVED head $head_before -> $head_after"
  status=90
elif [ "$digest_before" != "$digest_after" ]; then
  verdict="INVALID_TREE_DIRT_CHANGED (status digest moved during the run)"
  status=90
elif [ "$lines_before" -gt 0 ]; then
  # The tree held still, so the run is reproducible -- but it measured
  # uncommitted code, which is exactly what made the earlier suite numbers
  # uncitable. Say so instead of printing a bare VALID.
  verdict="VALID_BUT_DIRTY_AT_START head=$head_before dirty=$lines_before tracked_modified=$tracked_before (command_exit=$rc)"
  status=$rc
else
  verdict="VALID_CLEAN_TREE head=$head_before (command_exit=$rc)"
  status=$rc
fi

{
  echo "verdict=$verdict"
  echo "command_exit=$rc"
} > "$OUT/verdict"
cat "$OUT/verdict"

if [ "$status" -eq 90 ]; then
  echo "fenced-run: the tree changed during the run; do not cite this result." >&2
  echo "fenced-run: diff of git status before/after:" >&2
  diff "$OUT/status-before.txt" "$OUT/status-after.txt" >&2 || true
fi

exit "$status"
