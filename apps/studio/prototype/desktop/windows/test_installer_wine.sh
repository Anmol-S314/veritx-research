#!/usr/bin/env bash
# Install the packaged NSIS setup under Wine and run the *installed* sidecar.
# Wine is packaging-integrity evidence only; it is not a Windows machine.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
bundle="$repo/apps/studio/prototype/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis"
image=${SROTA_WINDOWS_GWTEST_IMAGE:-localhost/srota-windows-gwtest:acceptance}
installer=$(ls "$bundle"/*-setup.exe | head -1)
podman run --rm -v "$bundle:/bundle:ro" --userns=keep-id:uid=1001,gid=1001 "$image" bash -euc '
    mkdir -p /home/builder/windows-temp /tmp/inst
    export TEMP="Z:\\home\\builder\\windows-temp" TMP="Z:\\home\\builder\\windows-temp"
    export WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
    wine_bin=$(command -v /usr/lib/wine/wine64 || command -v wine64 || command -v wine)
    export DISPLAY=:96
    Xvfb :96 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
    sleep 2
    timeout 300 "$wine_bin" wineboot --init >/dev/null 2>&1 || true
    setup=$(ls /bundle/*-setup.exe)
    echo "installing $setup"
    # The WebView2 runtime installer cannot run under Wine; its failure is
    # expected and must not be mistaken for a packaging failure.
    timeout 900 "$wine_bin" "$setup" /S || echo "installer exited non-zero (see files below)"
    root="$HOME/.wine/drive_c/users/builder/AppData/Local"
    echo "--- installed tree"
    find "$root" -maxdepth 2 -name "*.exe" -printf "%p %s\n" 2>/dev/null | sed "s|$HOME/.wine/drive_c|C:|"
    gateway=$(find "$root" -name srota-gateway.exe -print -quit 2>/dev/null || true)
    studio=$(find "$root" -name srota-studio.exe -print -quit 2>/dev/null || true)
    [ -n "$gateway" ] || { echo "FAIL: packaged sidecar was not installed"; exit 1; }
    [ -n "$studio" ] || { echo "FAIL: packaged shell was not installed"; exit 1; }
    uninstall=$(find "$root" -iname "uninstall.exe" -print -quit 2>/dev/null || true)
    [ -n "$uninstall" ] || { echo "FAIL: uninstaller missing"; exit 1; }
    echo "PASS: installer placed shell, sidecar and uninstaller"
    echo "--- running the installed sidecar"
    mkdir -p /tmp/data
    (sleep 300) | timeout 240 "$wine_bin" "$(winepath -w "$gateway")" --data-dir "Z:\\tmp\\data" >/tmp/gw.out 2>/tmp/gw.err &
    gw=$!
    for _ in $(seq 1 240); do
        grep -q SROTA_READY /tmp/gw.out 2>/dev/null && break
        sleep 1
    done
    head -3 /tmp/gw.out
    grep -q SROTA_READY /tmp/gw.out || { echo "FAIL: installed sidecar did not start"; tail -20 /tmp/gw.err; exit 1; }
    listen=$(sed -n "s/^SROTA_READY //p" /tmp/gw.out | head -1 | sed "s/.*\"base\": \"//;s/\".*//")
    echo "ready: $listen"
    kill $gw 2>/dev/null || true
    echo "--- installed sidecar runtime surface"
    cat > /tmp/surface.py <<PY
import sys
from veritx_dse.core.paths import REPO
sys.path.insert(0, str(REPO / "third_party/ramulator2/python"))
from ramulator._ramulator import Simulation
from veritx_dse.backend.astra_machine import declared_runtime_config_fields
print("SURFACE_OK", len(declared_runtime_config_fields()))
PY
    timeout 240 "$wine_bin" "$(winepath -w "$gateway")" "$(winepath -w /tmp/surface.py)" >/tmp/surface.out 2>&1 || true
    tail -5 /tmp/surface.out
    # A stale freeze once shipped a gateway that could not read the ASTRA parser
    # surface it validates fabric configs against. Starting up is not enough.
    grep -q SURFACE_OK /tmp/surface.out || { echo "FAIL: installed sidecar cannot load its Ramulator binding or ASTRA parser surface"; exit 1; }
    echo "PASS: installed sidecar loads Ramulator binding and ASTRA parser surface"
    "$wine_bin" cmd /c "dir C:\\\\users\\\\builder\\\\AppData\\\\Local" >/dev/null 2>&1 || true
    echo "PASS: packaged installer produced a runnable standalone sidecar"
'
