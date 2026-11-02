#!/usr/bin/env bash
# Install the Windows build requirements into the Wine CPython prefix with uv.
#
# pip running inside Wine has produced distribution records without the
# packages: .desktop-build/windows/pywin gained scikit_learn-1.9.1.dist-info and
# scikit_optimize-0.10.2.dist-info while sklearn/ and skopt/ were absent, so the
# frozen Windows gateway raised ModuleNotFoundError for both and its
# Bayesian-optimization synthesis path could not run. uv resolves wheels for the
# Windows target from this Linux host, and the assert below refuses to leave a
# recorded-but-missing package in place.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
prototype="$repo/apps/studio/prototype"
prefix="$prototype/.desktop-build/windows/pywin"
site="$prefix/Lib/site-packages"

if [ ! -f "$prefix/python.exe" ]; then
    echo "no Windows CPython at $prefix; run desktop/windows/setup_python.sh first" >&2
    exit 1
fi
command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
mkdir -p "$site"

# --target rather than a prefix install: the Wine prefix is populated directly,
# and no Windows interpreter has to run during dependency resolution. --reinstall
# matters, because the corrupted prefix already carries dist-info records for
# packages whose files are missing and uv would otherwise trust them.
uv pip install --reinstall --python-platform x86_64-pc-windows-msvc \
    --python-version 3.14 --only-binary :all: --target "$site" \
    -r "$prototype/desktop/requirements-build.txt"

# threadpoolctl is a single module, not a package, so accept either form.
for package in numpy scipy sklearn skopt joblib threadpoolctl PyInstaller; do
    if [ ! -d "$site/$package" ] && [ ! -f "$site/$package.py" ]; then
        echo "build environment is incomplete: $site/$package is missing" >&2
        exit 1
    fi
done
echo "Windows build requirements installed into $site"
