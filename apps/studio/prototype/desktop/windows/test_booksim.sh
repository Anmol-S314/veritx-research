#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
out="$repo/apps/studio/prototype/.desktop-build/windows/booksim"
podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/srota-home -e WINEPREFIX=/tmp/srota-home/wine -v "$here:/fixtures:ro" \
    -v "$repo/third_party/booksim2/src/booksim:/linux-booksim:ro" \
    -v "$out:/output" localhost/srota-windows-tools:acceptance bash -euc '
    mkdir -m 700 -p "$HOME"
    cd "$HOME"
    timeout 90s xvfb-run -a /usr/lib/wine/wine64 /output/booksim.exe \
        "Z:\\fixtures\\booksim-smoke.cfg" > /output/windows-smoke.log 2>&1 \
        || { code=$?; tail -n 80 /output/windows-smoke.log; exit "$code"; }
    timeout 30s /linux-booksim /fixtures/booksim-smoke.cfg > /output/linux-smoke.log 2>&1 \
        || { code=$?; tail -n 80 /output/linux-smoke.log; exit "$code"; }
'
python - "$out" <<'PY'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])

def metrics(name):
    text = (root / name).read_text()
    assert '====== Overall Traffic Statistics ======' in text, f'Missing completed simulation statistics in {name}'
    summary = text.split('====== Overall Traffic Statistics ======', 1)[1]
    pairs = re.findall(r"^([A-Za-z][^=\n]+? average)\s*=\s*([-+0-9.eE]+)", summary, re.MULTILINE)
    assert pairs, f"No measured metrics in {name}:\n{text[-3000:]}"
    return {key.strip(): float(value) for key, value in pairs}

windows = metrics('windows-smoke.log')
linux = metrics('linux-smoke.log')
assert windows == linux, f"Measured simulation parity failure:\nWindows: {windows}\nLinux: {linux}"
print('PASS: Windows PE/Wine and Linux measured simulation metrics match:', windows)
PY
