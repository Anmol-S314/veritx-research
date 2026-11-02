#!/usr/bin/env bash
# Install Windows CPython + build requirements into a reusable prefix under
# .desktop-build/windows/pywin. Runs wine at container run time (image-build
# time wine cannot start its prefix). Not native Windows evidence.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
prototype="$repo/apps/studio/prototype"
image=${SROTA_WINDOWS_IMAGE:-localhost/srota-windows-python:acceptance}
prefix="$prototype/.desktop-build/windows/pywin"
if [ "${1:-}" = --force ]; then rm -rf "$prefix"; fi
if [ -f "$prefix/python.exe" ] && [ -d "$prefix/Lib/site-packages/PyInstaller" ]; then
    echo "Windows Python prefix already prepared: $prefix"
    exit 0
fi
mkdir -p "$prefix"
podman run --rm --userns=keep-id:uid=1001,gid=1001 --shm-size=512m \
    -e HOME=/home/builder \
    -v "$repo:/repo:ro" -v "$prefix:/pywin" \
    "$image" bash -euc '
    mkdir -p /home/builder/windows-temp
    export TEMP="Z:\\home\\builder\\windows-temp" TMP="Z:\\home\\builder\\windows-temp"
    # Without this wineboot pops a Mono/Gecko installer dialog and blocks forever.
    export WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
    wine_bin=$(command -v /usr/lib/wine/wine64 || command -v wine64 || command -v wine)
    # Fresh prefix creation is the only flaky step; retry it with diagnostics.
    Xvfb :97 -screen 0 1024x768x24 >/tmp/xvfb.log 2>&1 &
    export DISPLAY=:97
    sleep 2
    wine_ready=no
    for attempt in 1 2 3; do
        rm -rf /home/builder/.wine
        if timeout 120 "$wine_bin" wineboot --init >"/tmp/wineboot-$attempt.log" 2>&1 \
            && timeout 60 "$wine_bin" cmd /c echo wine-ok >/dev/null 2>&1; then
            echo "wine prefix ready on attempt $attempt"; wine_ready=yes; break
        fi
        echo "wine prefix attempt $attempt failed:" >&2
        tail -5 "/tmp/wineboot-$attempt.log" >&2
    done
    [ "$wine_ready" = yes ] || { echo "wine prefix could not be created" >&2; exit 1; }
    if [ ! -f /pywin/python.exe ]; then
        curl --fail --location --retry 3 https://www.python.org/ftp/python/3.14.0/python-3.14.0-embed-amd64.zip -o /tmp/python.zip
        unzip -oq /tmp/python.zip -d /pywin
        printf "python314.zip\n.\nLib/site-packages\nimport site\n" > /pywin/python314._pth
    fi
    if [ ! -f /pywin/Lib/site-packages/pip/__init__.py ]; then
        curl --fail --location --retry 3 https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
        "$wine_bin" /pywin/python.exe "Z:\\tmp\\get-pip.py" --no-warn-script-location
    fi
    "$wine_bin" /pywin/python.exe -m pip install --use-deprecated=legacy-certs \
        --only-binary=:all: --no-warn-script-location \
        -r "Z:\\repo\\apps\\studio\\prototype\\desktop\\requirements-build.txt"
    "$wine_bin" /pywin/python.exe -c "import sys, PyInstaller, numpy; assert sys.platform == \"win32\"; print(sys.version); print(\"Windows PyInstaller\", PyInstaller.__version__)"
'
