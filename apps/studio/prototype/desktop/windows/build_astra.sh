#!/usr/bin/env bash
# Cross-build ASTRA and canonical BookSim from disposable, read-only inputs.
#
# SOURCE_REPO pins the producer revision through a git worktree (see
# desktop/build_astra_linux.sh for why the v1 revision is pinned). Default: this
# checkout, which is only valid for a tree at the v1 producer revision.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
source_repo=${SOURCE_REPO:-$repo}
out="$repo/apps/studio/prototype/.desktop-build/windows/astra"
mkdir -p "$out"
if [ -n "${SOURCE_REPO:-}" ]; then
    # Pinned producer revision: build the checked-out revision directly. Its own
    # git metadata supplies the revision, and generated files are gitignored, so
    # the manifest still verifies as clean.
    proto="$source_repo/third_party/astra-sim/extern/graph_frontend/chakra/schema/protobuf"
    if [ ! -f "$proto/et_def.pb.cc" ]; then
        ( cd "$proto" && protoc --cpp_out=. ./*.proto ) >"$out/protoc.log" 2>&1
    fi
    snapshot=$(SNAPSHOT_RECIPE_REPO="$repo" python "$here/snapshot_sources.py" \
        "$source_repo" "$out" astra)
else
    snapshot=$(python "$here/snapshot_sources.py" "$source_repo" "$out" astra)
fi
printf '%s\n' "$snapshot" > "$out/source-snapshot.txt"
podman run --rm --userns=keep-id:uid=1001,gid=1001 \
    -e HOME=/tmp -e PROTOBUF_FROM_SOURCE=True \
    -v "$snapshot/third_party/astra-sim:/astra-source:ro" \
    -v "$snapshot/third_party/booksim2/src:/booksim-source:ro" \
    -v "$out:/output" localhost/srota-windows-simulators:acceptance bash -euc '
    mkdir -p /tmp/vendor/astra-sim /tmp/vendor/booksim2/src
    tar -C /astra-source --exclude="*.o" --exclude="*.a" --exclude="*.so" \
        --exclude=".git" --exclude="__pycache__" \
        --exclude="./build/astra_booksim2/build" \
        --exclude="./astra-sim/network_frontend/booksim2/bin" -cf - . \
        | tar -C /tmp/vendor/astra-sim -xf -
    tar -C /booksim-source --exclude="*.o" --exclude="*.d" --exclude=booksim \
        --exclude="*.a" -cf - . | tar -C /tmp/vendor/booksim2/src -xf -
    cmake -S /tmp/vendor/astra-sim/build/astra_booksim2 -B /tmp/astra-build -G Ninja \
        -DCMAKE_SYSTEM_NAME=Windows \
        -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc \
        -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_PREFIX_PATH=/home/builder/windows-libs \
        -DBOOKSIM2_SRC_DIR=/tmp/vendor/booksim2 \
        -DCMAKE_EXE_LINKER_FLAGS="-static -static-libgcc -static-libstdc++"
    cmake --build /tmp/astra-build -j2
    cp /tmp/vendor/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2.exe /output/
    x86_64-w64-mingw32-objdump -p /output/AstraSim_BookSim2.exe | grep "DLL Name:"
    x86_64-w64-mingw32-g++ --version > /output/compiler-version.txt
    sha256sum /output/AstraSim_BookSim2.exe
'
PYTHONPATH="$repo/tracks/t3-topology/dse" python - "$snapshot" "$out" <<'PY'
from pathlib import Path
import sys
from veritx_dse.core.build_manifest import write_build_manifest, load_and_verify_manifest
repo, out = map(Path, sys.argv[1:])
binary = out / 'AstraSim_BookSim2.exe'
# Must be the recipe the gateway qualifies; a platform-specific id here
# makes every Windows ASTRA evaluation refuse as unqualified.
recipe = "astra-sim+booksim2/v1"
write_build_manifest(binary, repo_root=repo, recipe_version=recipe,
    compiler='x86_64-w64-mingw32-g++',
    compiler_version=(out / 'compiler-version.txt').read_text().splitlines()[0],
    build_config='Release Windows x86-64 static MinGW runtime, protobuf 3.21.12',
    compile_flags=('-O3', '-static', '-static-libgcc', '-static-libstdc++'),
    source_paths=('third_party/astra-sim', 'third_party/booksim2',
                  'apps/studio/prototype/desktop/windows/build_astra.sh'))
manifest = load_and_verify_manifest(binary)
assert manifest is not None and manifest.source_revision and not manifest.source_dirty
print('Windows ASTRA committed-snapshot manifest verified')
PY
