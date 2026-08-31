#!/bin/bash
# VeritX: build ASTRA-sim with our BookSim2 fork as the network backend.
#
# Reproducibility (bbe3): BOOKSIM2_SRC_DIR now defaults to the VENDORED fork
# in-tree. The old default (/var/tmp/r1work/booksim2-embed) was deleted and
# broke every build. Override with BOOKSIM2_SRC_DIR=<path> only if you have a
# local fork checkout.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# repairs/booksim2-fork lives under the repo (third_party/booksim2). Resolve
# relative to the repo root from this file: serving/astra-sim/build/astra_booksim2
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEFAULT_BOOKSIM2="${BOOKSIM2_SRC_DIR:-${REPO_ROOT}/third_party/booksim2}"
BUILD_DIR="${SCRIPT_DIR}/build"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"
echo "BOOKSIM2_SRC_DIR = ${DEFAULT_BOOKSIM2}"
cmake .. -DBOOKSIM2_SRC_DIR="${DEFAULT_BOOKSIM2}"
cmake --build . -j "${JOBS:-2}"
