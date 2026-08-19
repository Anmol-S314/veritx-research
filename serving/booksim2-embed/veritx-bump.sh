#!/usr/bin/env bash
# Bump the vendored BookSim to a new upstream commit or tag. One arg: the ref.
#
#   third_party/booksim2/veritx-bump.sh <upstream-commit-or-tag>
#
# Wraps `git subtree pull` with the prefix, upstream URL, and --squash baked in, and
# runs from the repo root for you (subtree pull requires it). Upstream changes merge
# with our edits automatically; if they touched our lines you get a normal merge
# conflict to resolve in your editor. After it lands, rebuild and rerun the gates.
set -euo pipefail

REF="${1:-}"
[ -n "$REF" ] || { echo "usage: $(basename "$0") <upstream-commit-or-tag>" >&2; exit 2; }

PREFIX=third_party/booksim2
URL=https://github.com/booksim/booksim2.git
cd "$(git rev-parse --show-toplevel)"

echo "→ git subtree pull  $PREFIX  ←  booksim2@$REF  (squashed)"
git subtree pull --prefix "$PREFIX" "$URL" "$REF" --squash

echo "✓ pulled booksim2@$REF"
echo "  next:  third_party/booksim2/veritx-rebuild.sh   # rebuild + verify"
echo "         then rerun the T3 gates, and update the pinned commit in $PREFIX/VERITX.md"
