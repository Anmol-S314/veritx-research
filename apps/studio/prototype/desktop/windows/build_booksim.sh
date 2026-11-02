#!/usr/bin/env bash
# Compile in an isolated source copy; never replace the working Linux simulator.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
out="$repo/apps/studio/prototype/.desktop-build/windows/booksim"
mkdir -p "$out"
snapshot=$(python "$here/snapshot_sources.py" "$repo" "$out" booksim)
printf '%s\n' "$snapshot" > "$out/source-snapshot.txt"
podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -v "$snapshot/third_party/booksim2/src:/source:ro" \
    -v "$out:/output" localhost/srota-windows-tools:acceptance bash -euc '
    mkdir /tmp/booksim
    tar -C /source --exclude="*.o" --exclude="*.d" --exclude=booksim \
        --exclude=libveritx_embed.a -cf - . | tar -C /tmp/booksim -xf -
    cd /tmp/booksim
    make -j2 CXX=x86_64-w64-mingw32-g++ CC=x86_64-w64-mingw32-gcc \
        PROG=booksim.exe LFLAGS="-static -static-libgcc -static-libstdc++"
    cp booksim.exe /output/booksim.exe
    x86_64-w64-mingw32-objdump -p /output/booksim.exe | grep "DLL Name:"
    sha256sum /output/booksim.exe
    x86_64-w64-mingw32-g++ --version > /output/compiler-version.txt
'
PYTHONPATH="$repo/tracks/t3-topology/dse" python - "$snapshot" "$out" <<'PY'
from pathlib import Path
import sys
from veritx_dse.core.build_manifest import write_build_manifest, load_and_verify_manifest
repo, out = map(Path, sys.argv[1:])
binary = out / 'booksim.exe'
write_build_manifest(binary, repo_root=repo, recipe_version='booksim2-fork/v2',
    compiler='x86_64-w64-mingw32-g++',
    compiler_version=(out / 'compiler-version.txt').read_text().splitlines()[0],
    build_config='Release Windows x86-64 static MinGW runtime',
    compile_flags=('-O3', '-g', '-static', '-static-libgcc', '-static-libstdc++'),
    source_paths=('third_party/booksim2', 'apps/studio/prototype/desktop/windows/build_booksim.sh'))
manifest = load_and_verify_manifest(binary)
assert manifest is not None and manifest.source_revision and not manifest.source_dirty
print('Windows BookSim committed-snapshot build manifest verified')
PY
