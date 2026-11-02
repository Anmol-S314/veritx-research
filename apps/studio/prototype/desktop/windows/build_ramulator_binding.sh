#!/usr/bin/env bash
# Link genuine Windows CPython/nanobind bindings against the Windows core DLL.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
base="$repo/apps/studio/prototype/.desktop-build/windows"
out="$base/ramulator-binding"
test -f "$base/ramulator/libramulator.dll"
test -f "$base/cpython/tools/libs/python314.lib"
mkdir -p "$out"
podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" \
    -v "$repo/third_party/ramulator2:/ramulator:ro" \
    -v "$base/cpython:/cpython:ro" -v "$base/ramulator:/core:ro" \
    -v "$out:/output" localhost/srota-windows-tools:acceptance bash -euc '
    flags=(-std=c++20 -DNDEBUG -DNB_COMPACT_ASSERTIONS \
        -I/cpython/tools/include -I/ramulator/ext/nanobind/include \
        -I/ramulator/ext/nanobind/ext/robin_map/include -I/ramulator/src \
        -I/ramulator/ext/fmt/include -I/ramulator/ext/yaml-cpp/include)
    x86_64-w64-mingw32-g++ "${flags[@]}" -O2 -fno-strict-aliasing \
        -c /ramulator/ext/nanobind/src/nb_combined.cpp -o /output/nanobind.o
    x86_64-w64-mingw32-g++ "${flags[@]}" -Os \
        -c /ramulator/src/ramulator/python/bindings.cpp -o /output/bindings.o
    mkdir -p /output/ramulator
    tar -C /ramulator/python/ramulator --exclude="*.so" --exclude="*.pyd" \
        --exclude="*.build-manifest.json" --exclude="__pycache__" -cf - . \
        | tar -C /output/ramulator -xf -
    x86_64-w64-mingw32-g++ -shared -static -static-libgcc -static-libstdc++ \
        -Wl,--exclude-libs,ALL \
        /output/bindings.o /output/nanobind.o /core/libramulator.dll \
        /cpython/tools/libs/python314.lib \
        -o /output/ramulator/_ramulator.cp314-win_amd64.pyd
    if x86_64-w64-mingw32-objdump -p /output/ramulator/_ramulator.cp314-win_amd64.pyd | grep -q libwinpthread; then
        echo "FAIL: .pyd requires an unbundled runtime DLL"; exit 1
    fi
    cp /core/libramulator.dll /output/ramulator/
    x86_64-w64-mingw32-objdump -p /output/ramulator/_ramulator.cp314-win_amd64.pyd | grep "DLL Name:"
    x86_64-w64-mingw32-g++ --version > /output/compiler-version.txt
'
PYTHONPATH="$repo/tracks/t3-topology/dse" python - "$repo" "$out" <<'PY'
from pathlib import Path
import sys
from veritx_dse.core.build_manifest import write_build_manifest, load_and_verify_manifest
repo, out = map(Path, sys.argv[1:])
binary = out / 'ramulator/_ramulator.cp314-win_amd64.pyd'
write_build_manifest(binary, repo_root=repo, recipe_version='ramulator-windows-cp314/v1',
    compiler='x86_64-w64-mingw32-g++',
    compiler_version=(out / 'compiler-version.txt').read_text().splitlines()[0],
    build_config='Windows x86-64 CPython 3.14 nanobind with Windows Ramulator DLL',
    compile_flags=('-std=c++20', '-DNDEBUG', '-DNB_COMPACT_ASSERTIONS', '-O2', '-Os',
                   '-fno-strict-aliasing', '-shared', '-static-libgcc', '-static-libstdc++'),
    source_paths=('third_party/ramulator2',
                  'apps/studio/prototype/desktop/windows/build_ramulator_binding.sh'))
assert load_and_verify_manifest(binary) is not None
print('Windows Ramulator binding build manifest verified')
PY
