#!/usr/bin/env bash
# Rebuild the Linux ASTRA/BookSim binary from the qualified producer revision.
#
# Unpatched HEAD's BookSim EmbedTM refuses injection until SetHostFlitLimit() is
# called and the HEAD ASTRA fabric wrapper never called it, so every HEAD build
# aborted with "BookSim host flit limit must be set before injection" and
# reported no per-rank results. The patch that fixes this is committed as
# c0b41679; that commit is the producer this script builds. See
# docs/reports/ASTRA-PRODUCER-RECOVERY-20261012.md for the earlier v1 pin.
#
# The build must run in an isolated worktree at that revision: the manifest is
# written against that worktree so provenance stays clean and verifiable, and
# never against an edited checkout.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../.." && pwd)
out="$repo/apps/studio/prototype/.desktop-build/linux/astra"
mkdir -p "$out"

producer_revision=c0b41679a9984b3b663443b2dd3928771d8ad0a0
worktree=$(mktemp -d)/astra-patched
build_dir=$(mktemp -d)
trap 'git -C "$repo" worktree remove --force "$worktree" >/dev/null 2>&1 || true; rm -rf "$(dirname "$worktree")" "$build_dir"' EXIT

git -C "$repo" worktree add --detach "$worktree" "$producer_revision" >"$out/worktree.log" 2>&1
printf '%s\n' "$producer_revision" > "$out/producer-revision.txt"

# BookSim's flex/bison parser sources are generated, and chakra's protobuf
# sources must exist before CMake's globs run; both are absent in a fresh tree.
make -C "$worktree/third_party/booksim2/src" -j "${JOBS:-6}" >"$out/booksim.log" 2>&1

PROTO_DIR="$worktree/third_party/astra-sim/extern/graph_frontend/chakra/schema/protobuf"
if [ ! -f "$PROTO_DIR/et_def.pb.cc" ]; then
    ( cd "$PROTO_DIR" && protoc --cpp_out=. ./*.proto ) >>"$out/booksim.log" 2>&1
fi

# A reused build directory caches the previous temporary source path and then
# refuses to configure, so every run gets its own.
cmake -S "$worktree/third_party/astra-sim/build/astra_booksim2" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBOOKSIM2_SRC_DIR="$worktree/third_party/booksim2" >"$out/cmake.log" 2>&1
cmake --build "$build_dir" -j "${JOBS:-6}" >"$out/build.log" 2>&1

built="$worktree/third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2"
test -x "$built"
target="$repo/third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2"
cp "$built" "$target"
PYTHONPATH="$repo/tracks/t3-topology/dse" python - "$worktree" "$target" <<'PY'
from pathlib import Path
import subprocess
import sys
from veritx_dse.core.build_manifest import load_and_verify_manifest, write_build_manifest
snapshot, binary = map(Path, sys.argv[1:])
compiler = subprocess.run(["g++", "--version"], capture_output=True, text=True,
                          check=True).stdout.splitlines()[0]
write_build_manifest(binary, repo_root=snapshot,
                     recipe_version="astra-sim+booksim2/v1",
                     compiler="g++", compiler_version=compiler,
                     source_paths=("third_party/astra-sim", "third_party/booksim2"))
manifest = load_and_verify_manifest(binary)
print(f"verified manifest: {manifest.source_revision} dirty={manifest.source_dirty}")
if manifest.source_dirty:
    raise SystemExit("pinned-revision builds must be clean")
PY
ls -l "$target" "$target.build-manifest.json"
