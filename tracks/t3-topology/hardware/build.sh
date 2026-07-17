#!/usr/bin/env bash
# Build the T3 NoC multicast microbenchmark against the tt-metal SDK, ON A TENSTORRENT BOARD.
# NOT run in CI (no SDK in the tools image; `make hw` is not wired into setup/lint/test).
# Run on a Koyeb n300 after installing tt-metal:
#
#   git clone https://github.com/tenstorrent/tt-metal --recurse-submodules
#   cd tt-metal && ./build_metal.sh && export TT_METAL_HOME=$PWD
#   cd - && ./build.sh && ./noc_multicast_bw
#
# DRAFT: the custom-example build wiring + binary path are not yet verified on hardware
# (see ../README.md punch-list). `# VERIFY:` marks the spots to confirm.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${TT_METAL_HOME:-}" ] || [ ! -d "$TT_METAL_HOME" ]; then
  echo "✗ TT_METAL_HOME not set / not found — this target needs the SDK + a board."
  echo "    git clone https://github.com/tenstorrent/tt-metal --recurse-submodules"
  echo "    cd tt-metal && ./build_metal.sh && export TT_METAL_HOME=\$PWD"
  exit 1
fi

# tt-metal's cmake globs tt_metal/programming_examples/*, so a symlinked dir is the simplest
# supported build path for a custom example (avoids reinventing its build).  # VERIFY: glob still current
EX="$TT_METAL_HOME/tt_metal/programming_examples/noc_multicast_bw"
ln -sfn "$HERE" "$EX"
echo "→ linked $HERE → $EX"

echo "→ build via tt-metal"
( cd "$TT_METAL_HOME" && cmake --build build --target programming_examples )   # VERIFY: target name

BIN="$TT_METAL_HOME/build/programming_examples/noc_multicast_bw"               # VERIFY: output path
if [ -x "$BIN" ]; then
  cp "$BIN" "$HERE/"
  echo "✓ built — run ./noc_multicast_bw on the board"
else
  echo "  binary not at $BIN — check \$TT_METAL_HOME/build/…; see README punch-list"
  exit 1
fi
