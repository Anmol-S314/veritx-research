#!/usr/bin/env bash
# Prove what the built Windows installer actually does about WebView2.
#
# The mode is a documented size/offline trade: offlineInstaller embeds ~205 MiB
# of runtime, embedBootstrapper embeds a ~2 MiB stub that fetches the runtime
# where it is absent. Read the generated NSIS script rather than the config we
# wrote, because only the script decides what ends up in the exe.
#
# Paths inside that script are container paths (/home/builder/cache/...), so map
# them back onto the host cache mount before trusting them.
set -euo pipefail
prototype=${1:-$(cd "$(dirname "$0")/../.." && pwd)}
want=${SROTA_WEBVIEW2_MODE:-embedBootstrapper}
target="$prototype/src-tauri/target/x86_64-pc-windows-msvc/release"
nsi="$target/nsis/x64/installer.nsi"
cache="$prototype/.desktop-build/windows/tauri-cache"

[ -f "$nsi" ] || { echo "missing NSIS script: $nsi (build first)" >&2; exit 1; }

define() { sed -n "s/^!define $1 \"\\(.*\\)\"\$/\\1/p" "$nsi" | tr -d '\r'; }
hostpath() { case "$1" in /home/builder/cache/*) printf '%s/%s' "$cache" "${1#/home/builder/cache/}";; *) printf '%s' "$1";; esac; }

mode=$(define INSTALLWEBVIEW2MODE)
[ "$mode" = "$want" ] || { echo "webview2 install mode is '$mode', expected '$want'" >&2; exit 1; }

offline=$(define WEBVIEW2INSTALLERPATH)
if [ -n "$offline" ] && [ -f "$(hostpath "$offline")" ]; then
    echo "offline WebView2 runtime is still embedded: $offline" >&2
    exit 1
fi

stub=$(hostpath "$(define WEBVIEW2BOOTSTRAPPERPATH)")
[ -f "$stub" ] || { echo "embedded WebView2 bootstrapper is missing: $stub" >&2; exit 1; }
stub_kib=$(( $(stat -c %s "$stub") / 1024 ))
[ "$stub_kib" -lt 10240 ] || { echo "bootstrapper is ${stub_kib} KiB, expected a small stub" >&2; exit 1; }

# Pick the installer for the version this tree declares. A stale exe from an
# earlier version sits in the same directory, and "the first one" once selected
# a 269 MiB 0.1.0 build while the current one was 33 MiB.
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
    "$prototype/src-tauri/tauri.conf.json")
installer="$target/bundle/nsis/Srota Studio_${version}_x64-setup.exe"
[ -f "$installer" ] || { echo "no installer for declared version $version: $installer" >&2; exit 1; }
awk -v m="$mode" -v s="$stub_kib" -v n="$(basename "$installer")" -v b="$(stat -c %s "$installer")" \
    'BEGIN { printf "webview2: mode=%s stub=%d KiB  installer: %s (%.2f MiB)\n", m, s, n, b/1048576 }' /dev/null
