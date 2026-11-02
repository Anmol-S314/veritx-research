#!/usr/bin/env bash
# Seed tauri's NSIS toolset cache so cross-building the installer never depends
# on a GitHub release download at bundle time.
#
# Why this exists: tauri-bundler's cross-compile path cannot satisfy its own
# "NSIS.exe is present and hashed" check (that file only arrives via the
# Windows-only zip extraction), so every bundle run deletes the toolset and
# re-downloads nsis_tauri_utils.dll. From this builder the container reaches
# release-assets.githubusercontent.com at ~1.5 KB/s (34 KB in 23 s, IPv6 dead),
# and tauri aborts with `failed to bundle project: timeout: global`. The host
# fetches the same files in under a second, so the host seeds the cache and the
# bundler then finds everything already valid.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
prototype="$repo/apps/studio/prototype"
cache="$prototype/.desktop-build/windows/tauri-cache/tauri"
toolset="$cache/NSIS"
plugin="$toolset/Plugins/x86-unicode/additional/nsis_tauri_utils.dll"

# Hashes are the constants in tauri-bundler's
# src/bundle/windows/nsis/mod.rs for this bundler version (NSIS 3.13, utils 0.5.3).
NSIS_ZIP_SHA1=db14f8af2ea346b786c6ae19343f61aaf5e09b8e
NSIS_EXE_SHA1=6d45d4e8ccf18fe1fdac9164058f356102a2ecf2
PLUGIN_SHA1=75197fee3c6a814fe035788d1c34ead39349b860
NSIS_ZIP_URL=https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.13/nsis-3.13.zip
PLUGIN_URL=https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll

verify() { # file expected-sha1 label
    local actual
    actual=$(sha1sum "$1" | cut -d' ' -f1)
    if [ "$actual" != "$2" ]; then
        echo "$3 hash mismatch: $actual != $2" >&2
        exit 1
    fi
}

if [ -f "$toolset/NSIS.exe" ] && [ -f "$plugin" ] \
    && [ "$(sha1sum "$toolset/NSIS.exe" | cut -d' ' -f1)" = "$NSIS_EXE_SHA1" ] \
    && [ "$(sha1sum "$plugin" | cut -d' ' -f1)" = "$PLUGIN_SHA1" ]; then
    echo "NSIS toolset already seeded: $toolset"
    exit 0
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl --fail --silent --show-error --location --retry 3 --max-time 900 \
    -o "$work/nsis.zip" "$NSIS_ZIP_URL"
verify "$work/nsis.zip" "$NSIS_ZIP_SHA1" "nsis-3.13.zip"

curl --fail --silent --show-error --location --retry 3 --max-time 300 \
    -o "$work/nsis_tauri_utils.dll" "$PLUGIN_URL"
verify "$work/nsis_tauri_utils.dll" "$PLUGIN_SHA1" "nsis_tauri_utils.dll"

unzip -q "$work/nsis.zip" -d "$work/extract"
rm -rf "$toolset"
mkdir -p "$cache"
mv "$work/extract/nsis-3.13" "$toolset"
mkdir -p "$(dirname "$plugin")"
cp "$work/nsis_tauri_utils.dll" "$plugin"

verify "$toolset/NSIS.exe" "$NSIS_EXE_SHA1" "NSIS.exe"
verify "$plugin" "$PLUGIN_SHA1" "nsis_tauri_utils.dll"
echo "NSIS toolset seeded (no bundle-time download needed): $toolset"
