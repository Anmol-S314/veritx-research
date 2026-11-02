#!/usr/bin/env bash
# First gate: Windows Ramulator core DLL. Python bindings are a separate gate.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
out="$repo/apps/studio/prototype/.desktop-build/windows/ramulator"
mkdir -p "$out"
podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -v "$repo/third_party/ramulator2:/source:ro" \
    -v "$out:/output" localhost/srota-windows-simulators:acceptance bash -euc '
    mkdir -p /tmp/ramulator
    tar -C /source --exclude="./build" --exclude="*.so" --exclude="*.o" \
        --exclude="*.a" --exclude=".git" --exclude="__pycache__" -cf - . \
        | tar -C /tmp/ramulator -xf -
    cmake -S /tmp/ramulator -B /tmp/ramulator-build -G Ninja \
        -DCMAKE_SYSTEM_NAME=Windows \
        -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc \
        -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \
        -DCMAKE_BUILD_TYPE=Release -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
        -DRAMULATOR_PYTHON_BINDINGS=OFF -DCMAKE_WINDOWS_EXPORT_ALL_SYMBOLS=ON \
        -DCMAKE_SHARED_LINKER_FLAGS="-static -static-libgcc -static-libstdc++"
    cmake --build /tmp/ramulator-build -j2
    cp /tmp/ramulator-build/libramulator.dll /output/
    cp /tmp/ramulator-build/libramulator.dll.a /output/
    x86_64-w64-mingw32-objdump -p /output/libramulator.dll | grep "DLL Name:"
    if x86_64-w64-mingw32-objdump -p /output/libramulator.dll | grep -q "libwinpthread"; then
        echo "FAIL: libramulator.dll requires an unbundled runtime DLL"; exit 1
    fi
    sha256sum /output/libramulator.dll
'
