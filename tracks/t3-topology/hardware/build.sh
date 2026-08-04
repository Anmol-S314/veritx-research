#!/usr/bin/env bash
# Build the T3 NoC multicast microbenchmark against the tt-metal SDK, ON A TENSTORRENT BOARD.
# NOT run in CI (no SDK in the tools image; `make hw` is not wired into setup/lint/test).
# Run on a Wormhole board (e.g. Koyeb n300) after installing tt-metal:
#
#   git clone https://github.com/tenstorrent/tt-metal --recurse-submodules
#   cd tt-metal && ./build_metal.sh && export TT_METAL_HOME=$PWD
#   cd - && ./build.sh && ./noc_multicast_bw
#
# Grounded in the tt-metal main build flow (see programming_examples CMakeLists + the
# eltwise_binary example): the example dir must be added via add_subdirectory() and the
# target built by name. This script symlinks the repo dir into tt-metal, patch-registers
# the subdirectory once, and builds the single target.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EX_DIR="$TT_METAL_HOME/tt_metal/programming_examples/noc_multicast_bw"
EX_CMAKE="$TT_METAL_HOME/tt_metal/programming_examples/CMakeLists.txt"

if [ -z "${TT_METAL_HOME:-}" ] || [ ! -d "$TT_METAL_HOME" ]; then
  echo "✗ TT_METAL_HOME not set / not found — this target needs the SDK + a board."
  echo "    git clone https://github.com/tenstorrent/tt-metal --recurse-submodules"
  echo "    cd tt-metal && ./build_metal.sh && export TT_METAL_HOME=\$PWD"
  exit 1
fi

# 1. Register the example: symlink the repo dir into tt-metal's programming_examples tree
#    (kernels are resolved relative to it via OVERRIDE_KERNEL_PREFIX = "noc_multicast_bw/...").
ln -sfn "$HERE" "$EX_DIR"
echo "→ linked $HERE → $EX_DIR"

# 2. Register the subdir in the parent CMakeLists. Idempotent; must persist as long as the
#    symlink does (tt-metal configure re-runs when this file changes).
if ! grep -q "add_subdirectory(\${CMAKE_CURRENT_SOURCE_DIR}/noc_multicast_bw)" "$EX_CMAKE"; then
  LINE="add_subdirectory(\${CMAKE_CURRENT_SOURCE_DIR}/noc_multicast_bw)"
  # insert after the NoC_tile_transfer entry (alphabetical neighbours in the file)
  sed -i "/add_subdirectory(\${CMAKE_CURRENT_SOURCE_DIR}\/NoC_tile_transfer)/a\\$LINE" "$EX_CMAKE"
  echo "→ registered noc_multicast_bw in $EX_CMAKE"
else
  echo "→ noc_multicast_bw already registered"
fi

# 3. Build just this target. cmake auto-reruns configure because the CMakeLists touched.
( cd "$TT_METAL_HOME" && cmake --build build --target noc_multicast_bw )

# 4. Copy the binary beside the sources (CMAKE_RUNTIME_OUTPUT_DIRECTORY = build/programming_examples).
BIN="$TT_METAL_HOME/build/programming_examples/noc_multicast_bw"
if [ -x "$BIN" ]; then
  cp "$BIN" "$HERE/"
  echo "✓ built — run ./noc_multicast_bw on the board"
else
  echo "  binary not at $BIN — check \$TT_METAL_HOME/build/programming_examples/…; see README punch-list"
  exit 1
fi