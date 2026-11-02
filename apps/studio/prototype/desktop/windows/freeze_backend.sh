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

# The frozen tree must NOT carry the numeric stack, and asking for an engine
# that needs it must refuse with a typed error. Both halves matter: the 0.1.0
# packages shipped a stack that could not import (scipy/_external was never
# collected, which took down sklearn and skopt), and the 0.1.1 decision is to
# stop shipping it at all. Checking only one half lets the other regress
# silently — a re-added numpy would pass a refusal-only check, and a deleted
# refusal path would pass an absence-only check.
GUARD='
import importlib.util
for name in ("numpy", "scipy", "sklearn", "skopt"):
    if importlib.util.find_spec(name) is not None:
        raise SystemExit(f"numeric stack leaked into the desktop build: {name}")
import chakra
from veritx_dse.application.errors import EngineUnavailable
from veritx_dse.product import vnext
if any(r["available"] for r in vnext.engine_availability().values()):
    raise SystemExit("engines claimed available without their libraries")
for engine in ("milp_tmcf", "bo_gp", "rho_iterative"):
    try:
        vnext.require_engine(engine)
    except EngineUnavailable as exc:
        assert exc.code == "ENGINE_UNAVAILABLE"
    else:
        raise SystemExit(f"{engine} accepted in a build without its libraries")
print("windows frozen gateway: numeric stack absent, engines refuse typed")
from veritx_dse.gateway import ablations as _ablations
_depths = _ablations.ablation_catalog()["knob_dimensions"]["vc_buf_size"]["values"]
if not _depths:
    raise SystemExit("ablation catalog carries no buffer depths: design_sensitivity.json not shipped")
from veritx_dse.gateway.sweeps import latest_topology_sweep as _sweep
try:
    _sweep(_ablations.REPO)
except Exception as exc:
    raise SystemExit(f"supported-topology sweep evidence is not shipped: {exc}")
print(f"windows frozen gateway: buffer depths {_depths}, sweep evidence readable")
# The fabric search runs this as a subprocess, so prove the subprocess contract
# inside the package: bare python puts the script directory on sys.path and the
# runner imports a sibling module from it. Shipping the runner without its
# siblings, or running it without that path entry, produced a 500 saying the
# runner produced no ablation.json, which reads like a simulator failure.
import subprocess as _sp, sys as _sys
_run = _sp.run([_sys.executable, str(_ablations.SCRIPT), "--help"],
               cwd=str(_ablations.REPO), capture_output=True, text=True, timeout=300)
if _run.returncode != 0:
    raise SystemExit("ablation runner cannot start inside the package: "
                     + (_run.stderr or _run.stdout)[-1500:])
'
podman run --rm --network=none --userns=keep-id:uid=1001,gid=1001 \
    -e HOME=/home/builder -e WINEDLLOVERRIDES="mscoree,mshtml=" -e WINEDEBUG=-all \
    -e SROTA_GUARD="$GUARD" \
    -v "$prototype/src-tauri/binaries/gateway:/gw:ro" \
    ${SROTA_WINDOWS_IMAGE:-localhost/srota-windows-python:acceptance} bash -euc '
    mkdir -p /home/builder/windows-temp
    export TEMP="Z:\\home\\builder\\windows-temp" TMP="Z:\\home\\builder\\windows-temp"
    wine_bin=$(command -v /usr/lib/wine/wine64 || command -v wine64 || command -v wine)
    xvfb-run -a "$wine_bin" Z:\\gw\\srota-gateway.exe -c "$SROTA_GUARD" \
        || { echo "frozen Windows gateway failed its engine-availability guard" >&2; exit 1; }
'
echo "frozen Windows gateway: numeric stack absent, synthesis engines refuse typed"
ls -lh "$prototype/src-tauri/binaries/gateway/srota-gateway.exe"
