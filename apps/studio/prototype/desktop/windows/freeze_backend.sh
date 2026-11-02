#!/usr/bin/env bash
# Freeze the real Windows gateway executable under Windows CPython + PyInstaller.
# Output: src-tauri/binaries/gateway/ (one-dir tree with srota-gateway.exe)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
prototype="$repo/apps/studio/prototype"
stage=$(python "$here/stage_resources.py")
chakra=$(python "$here/stage_chakra.py")
python_prefix="$prototype/.desktop-build/windows/pywin"
bash "$here/setup_python.sh"
# pip inside Wine left scikit-learn/scikit-optimize recorded but not installed,
# so the frozen Windows gateway had no sklearn/skopt. uv installs them for the
# Windows target and fails loudly if a package is still missing.
bash "$here/install_build_requirements.sh"
out="$prototype/.desktop-build/windows/dist"
rm -rf "$out"
mkdir -p "$out"
podman run --rm --network=none --userns=keep-id:uid=1001,gid=1001 \
    -e HOME=/home/builder -e SROTA_CHAKRA_ROOT="Z:\\repo\\apps\\studio\\prototype\\.desktop-build\\windows\\chakra\\chakra" \
    -e SROTA_DESKTOP_RESOURCES="Z:\\repo\\apps\\studio\\prototype\\.desktop-build\\windows\\stage" \
    -v "$repo:/repo:ro" -v "$out:/output" -v "$python_prefix:/home/builder/python:ro" \
    -v "$repo/apps/studio/prototype/.desktop-build/windows/chakra:/repo/apps/studio/prototype/.desktop-build/windows/chakra:ro" \
    -v "$repo/apps/studio/prototype/.desktop-build/windows/stage:/repo/apps/studio/prototype/.desktop-build/windows/stage:ro" \
    ${SROTA_WINDOWS_IMAGE:-localhost/srota-windows-python:acceptance} bash -euc '
    mkdir -p /home/builder/windows-temp
    export TEMP="Z:\\home\\builder\\windows-temp"
    export TMP="Z:\\home\\builder\\windows-temp"
    export WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
    cd /output
    wine_bin=$(command -v /usr/lib/wine/wine64 || command -v wine64 || command -v wine)
    xvfb-run -a "$wine_bin" /home/builder/python/python.exe -m PyInstaller \
        --noconfirm --clean --distpath "Z:\\output\\dist" --workpath "Z:\\output\\work" \
        "Z:\\repo\\apps\\studio\\prototype\\desktop\\gateway.spec"
    ls -l /output/dist
'
test -f "$out/dist/srota-gateway/srota-gateway.exe"
rm -rf "$prototype/src-tauri/binaries/gateway"
mkdir -p "$prototype/src-tauri/binaries"
cp -r "$out/dist/srota-gateway" "$prototype/src-tauri/binaries/gateway"
ls -lh "$prototype/src-tauri/binaries/gateway/srota-gateway.exe"
