#!/usr/bin/env bash
# Drive the frozen Windows sidecar through the real gateway suite under Wine.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
image=${SROTA_WINDOWS_GWTEST_IMAGE:-localhost/srota-windows-gwtest:acceptance}
# Prefer the one-dir tree the installer actually ships, so the gate exercises
# the same artifact users get; the legacy one-file build is only a fallback.
one_dir="$repo/apps/studio/prototype/src-tauri/binaries/gateway/srota-gateway.exe"
one_file="$repo/apps/studio/prototype/src-tauri/binaries/srota-gateway-x86_64-pc-windows-msvc.exe"
if [ -f "$one_dir" ]; then
    sidecar="$one_dir"
elif [ -f "$one_file" ]; then
    sidecar="$one_file"
else
    echo "missing Windows sidecar (run freeze_backend.sh first)" >&2
    exit 1
fi
echo "sidecar: $sidecar"
podman build -f "$here/Containerfile.gwtest" -t "$image" "$here"
sidecar_rel=${sidecar#"$repo/"}
podman run --rm --shm-size=1g -e sidecar_rel="$sidecar_rel" -v "$repo:/repo:ro" "$image" bash -euc '
    mkdir -p /home/builder/windows-temp
    export TEMP="Z:\\home\\builder\\windows-temp" TMP="Z:\\home\\builder\\windows-temp"
    export WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
    wine_bin=$(command -v /usr/lib/wine/wine64 || command -v wine64 || command -v wine)
    # Wine prints a one-off configuration-directory line on its
    # first run in a fresh HOME. Create the prefix up front so the sidecar
    # first stdout line is the readiness announcement, as the suite expects.
    WINEDLLOVERRIDES="mscoree,mshtml=" timeout 180 "$wine_bin" wineboot --init >/dev/null 2>&1 || true
    cat > /tmp/sidecar <<EOF
#!/bin/sh
exec xvfb-run -a "$wine_bin" "Z:\\repo\\${sidecar_rel}" "\$@"
EOF
    chmod +x /tmp/sidecar
    SROTA_SIDECAR=/tmp/sidecar python3 /repo/apps/studio/prototype/desktop/test_gateway.py
'
