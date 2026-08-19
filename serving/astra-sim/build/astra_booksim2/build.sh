#!/bin/bash
# VeritX: build ASTRA-sim with our BookSim2 fork as the network backend.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"
cmake .. -DBOOKSIM2_SRC_DIR="${BOOKSIM2_SRC_DIR:-/var/tmp/r1work/booksim2-embed}"
cmake --build . -j "${JOBS:-2}"
