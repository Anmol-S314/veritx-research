#!/usr/bin/env bash
# Rebuild the vendored BookSim after editing its source, and install it on PATH.
# Run inside the tools image (`make shell`), from anywhere:
#
#   third_party/booksim2/veritx-rebuild.sh
#
# You edit the REAL files under third_party/booksim2/src/ (full LSP; `git diff` shows
# exactly our delta vs the pinned upstream). This syncs them into the image's build
# tree at /opt/booksim2, compiles incrementally (~seconds for a one-file change),
# installs /usr/local/bin/booksim, and verifies the flit-fork multicast still forks --
# a booksim without our edits delivers 1:1 and fails the check, which is the point.
#
# See VERITX.md for the full workflow (edit / rebuild / bump upstream).
set -euo pipefail

VEN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC=/opt/booksim2
[ -d "$SRC/src" ] || { echo "✗ $SRC/src not found — run inside the tools image (make shell)"; exit 1; }

echo "→ sync   third_party/booksim2/src → $SRC/src"
cp -r "$VEN/src/." "$SRC/src/"

echo "→ build"
make -C "$SRC/src" -j"$(nproc)"

echo "→ install /usr/local/bin/booksim"
cp "$SRC/src/booksim" /usr/local/bin/booksim

# Verify: a rebuilt binary that silently dropped our edits is exactly the failure this
# guards. mcast_k=8 on the 8x8 example must fork ~7 deliveries per injection.
echo "→ verify flit-fork multicast (accepted ≫ injected)"
CFG="$SRC/src/examples/mesh88_lat"
ratio="$({ booksim "$CFG" mcast_k=8 packet_size=1 injection_rate=0.02 sim_count=1 2>&1 || true; } \
  | awk -F= '/Injected packet rate average/{split($2,a," ");i=a[1]}
             /Accepted packet rate average/{split($2,a," ");x=a[1]} END{print (i>0)?x/i:0}')"
if awk -v r="$ratio" 'BEGIN{exit !(r>5)}'; then
  printf '✓ booksim rebuilt — multicast forks (accepted/injected %.2f ≈ 7): %s\n' "$ratio" "$(command -v booksim)"
else
  echo "✗ multicast did NOT fork (accepted/injected $ratio) — vendored edits missing from the build."
  exit 1
fi
