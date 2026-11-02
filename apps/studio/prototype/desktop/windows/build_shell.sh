#!/usr/bin/env bash
# Cross-build the Tauri shell for Windows (MSVC target) and bundle an NSIS
# installer. Requires the frozen Windows sidecar from freeze_backend.sh and a
# built frontend in apps/studio/prototype/dist.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
prototype="$repo/apps/studio/prototype"
image=${SROTA_WINDOWS_SHELL_IMAGE:-localhost/srota-windows-shell:acceptance}
sidecar="$prototype/src-tauri/binaries/gateway/srota-gateway.exe"
if [ ! -f "$sidecar" ]; then
    echo "missing Windows gateway tree: $sidecar (run freeze_backend.sh first)" >&2
    exit 1
fi
if [ ! -f "$prototype/dist/index.html" ]; then
    echo "missing frontend build: $prototype/dist (run npm run build first)" >&2
    exit 1
fi
# Tauri downloads its NSIS helper DLL at bundle time. Keep that cache on the
# host: the download is flaky inside the container and a rebuild must not
# depend on GitHub reachability.
cache="$prototype/.desktop-build/windows/tauri-cache"
mkdir -p "$cache"
# Seed NSIS locally: the bundler otherwise deletes and re-downloads its plugin
# through a container link that is too slow for its global timeout.
bash "$here/seed_nsis_toolset.sh"
podman run --rm --userns=keep-id:uid=1001,gid=1001 \
    -e HOME=/home/builder -e XWIN_CACHE_DIR=/home/builder/xwin-cache \
    -e XDG_CACHE_HOME=/home/builder/cache \
    -v "$repo:/repo:rw" \
    -v "$cache:/home/builder/cache" \
    "$image" bash -euc '
    cd /repo/apps/studio/prototype
    export PATH=/home/builder/.cargo/bin:$PATH
    ls -l src-tauri/binaries/
    cargo tauri build --runner cargo-xwin --target x86_64-pc-windows-msvc \
        --bundles nsis \
        --config "{\"build\":{\"beforeBuildCommand\":\"\"}}"
'
ls -l "$prototype/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/" 2>/dev/null || true
