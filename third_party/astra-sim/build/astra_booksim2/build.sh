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
# relative to the repo root from this file:
# third_party/astra-sim/build/astra_booksim2 (four levels up).
# NOTE: a previous revision used ../../.. (correct only under the old
# serving/astra-sim layout) which silently pointed BOOKSIM2_SRC_DIR at a
# nonexistent path. Do not regress this when moving the script.
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
DEFAULT_BOOKSIM2="${BOOKSIM2_SRC_DIR:-${REPO_ROOT}/third_party/booksim2}"
BUILD_DIR="${SCRIPT_DIR}/build"
mkdir -p "${BUILD_DIR}"

# Generate the chakra protobuf C++ sources if absent. chakra's CMake globs
# them at configure time, so they must exist BEFORE cmake runs; without this
# step the link fails on ChakraProtoMsg symbols.
PROTO_DIR="${REPO_ROOT}/third_party/astra-sim/extern/graph_frontend/chakra/schema/protobuf"
if [ ! -f "${PROTO_DIR}/et_def.pb.cc" ]; then
  echo "Generating chakra protobuf sources in ${PROTO_DIR}"
  ( cd "${PROTO_DIR}" && protoc --cpp_out=. ./*.proto )
fi

cd "${BUILD_DIR}"
echo "BOOKSIM2_SRC_DIR = ${DEFAULT_BOOKSIM2}"
cmake .. -DBOOKSIM2_SRC_DIR="${DEFAULT_BOOKSIM2}"
cmake --build . -j "${JOBS:-2}"
