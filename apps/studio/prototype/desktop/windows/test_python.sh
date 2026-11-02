#!/usr/bin/env bash
# Real Windows CPython under Wine. Not native Windows acceptance evidence.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
python_prefix="${SROTA_WINDOWS_PYTHON_PREFIX:-$(cd "$here/../.." && pwd)/.desktop-build/windows/pywin}"
bash "$here/setup_python.sh"
podman run --rm --network=none -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 \
    --userns=keep-id:uid=1001,gid=1001 \
    -v "$repo:/repo:ro" -v "$python_prefix:/home/builder/python:ro" \
    ${SROTA_WINDOWS_IMAGE:-localhost/srota-windows-python:acceptance} bash -euc '
    mkdir -p /home/builder/windows-temp
    export TEMP="Z:\\home\\builder\\windows-temp"
    export TMP="Z:\\home\\builder\\windows-temp"
    export WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
    for test in test_windows_job.py test_store_portability.py test_build_backend.py test_windows_files.py test_process_supervision.py; do
        wine_bin=$(command -v /usr/lib/wine/wine64 || command -v wine64 || command -v wine)
        timeout 100s xvfb-run -a "$wine_bin" /home/builder/python/python.exe \
            "Z:\\repo\\apps\\studio\\prototype\\desktop\\$test"
    done
'
