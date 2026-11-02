"""Freeze the gateway as a one-dir tree for this build host."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

PROTOTYPE = Path(__file__).resolve().parents[1]
REPO = PROTOTYPE.parents[2]

# Runs inside the frozen interpreter: the stack must be absent, and asking for
# an engine that needs it must raise a typed refusal (never ModuleNotFoundError).
_GUARD = r'''
import importlib.util
for name in ("numpy", "scipy", "sklearn", "skopt"):
    if importlib.util.find_spec(name) is not None:
        raise SystemExit(f"numeric stack leaked into the desktop build: {name}")
from veritx_dse.application.errors import EngineUnavailable
from veritx_dse.product import vnext
availability = vnext.engine_availability()
if any(row["available"] for row in availability.values()):
    raise SystemExit(f"engines claimed available without their libraries: {availability}")
for engine in ("milp_tmcf", "bo_gp", "rho_iterative"):
    try:
        vnext.require_engine(engine)
    except EngineUnavailable as exc:
        assert exc.code == "ENGINE_UNAVAILABLE", exc.code
        assert exc.missing, exc
    else:
        raise SystemExit(f"{engine} accepted in a build without its libraries")
if vnext.synthesis_engines()["numeric_stack_shipped"]:
    raise SystemExit("synthesis/engines still advertises the numeric stack")
print("frozen gateway: numeric stack absent, engines refuse typed")

# Packaging bugs that only appear once the tree is frozen: code that reads a
# repository path the spec forgot to ship fails silently. The ablation catalog
# lost its buffer depths this way (design_sensitivity.json was absent), which
# left the Studio fabric-search chips empty and its primary action disabled with
# no way forward, and "Refresh sweep evidence" answered 404 while the view still
# rendered a static copy. Both are checked as behaviour, not as file paths.
from veritx_dse.gateway import ablations as _ablations
_catalog = _ablations.ablation_catalog()
_depths = _catalog["knob_dimensions"]["vc_buf_size"]["values"]
if not _depths:
    raise SystemExit(
        "ablation catalog carries no buffer depths: public/data/design_sensitivity.json "
        "is not shipped, so fabric search would offer no buffers")
from veritx_dse.gateway.sweeps import latest_topology_sweep as _sweep
try:
    _sweep(_ablations.REPO)
except Exception as exc:
    raise SystemExit(f"supported-topology sweep evidence is not shipped: {exc}") from exc
print(f"frozen gateway: ablation buffer depths {_depths}, sweep evidence readable")
'''

# Tauri copies this directory into the app resources as `gateway/`, and the
# shell launches `gateway/srota-gateway`. The name carries no target triple:
# the bundle config would otherwise need a host-specific path.
STAGED = Path("src-tauri/binaries/gateway")


def _remove_tree(path: Path) -> None:
    """Clear a staged tree, forcing entries the other lane left read-only.

    Both lanes stage into the same path. The Windows lane's copy can carry
    read-only modes, and rmtree(ignore_errors=True) then leaves a partly
    deleted tree whose only symptom is an opaque PyInstaller COLLECT failure
    later in the build. Fail here, with the path, instead.
    """
    if not path.exists():
        return

    def retry(func, target, _exc):
        try:
            os.chmod(target, 0o755)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onerror=retry)
    if path.exists():
        raise SystemExit(f"cannot clear the staged gateway tree: {path}")


def main():
    if sys.platform not in {"linux", "win32"}:
        raise SystemExit("Desktop packaging supports Linux and Windows build hosts only.")
    windows = sys.platform == "win32"
    local = PROTOTYPE / (".desktop-venv/Scripts/python.exe" if windows else ".desktop-venv/bin/python")
    python = os.environ.get("SROTA_PYTHON", str(local) if local.is_file() else sys.executable)
    if subprocess.run([python, "-c", "import PyInstaller"], capture_output=True).returncode:
        raise SystemExit(
            "Install the build environment first (see desktop/README.md). "
            "PyInstaller is missing from " + python
        )
    target = subprocess.check_output(["rustc", "-vV"], text=True)
    target = next(line.split(": ", 1)[1] for line in target.splitlines() if line.startswith("host:"))
    output = PROTOTYPE / "src-tauri/binaries"
    output.mkdir(exist_ok=True)
    staged = PROTOTYPE / STAGED
    _remove_tree(staged)
    subprocess.run([
        python, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(output), "--workpath", str(PROTOTYPE / ".desktop-build"),
        str(PROTOTYPE / "desktop/gateway.spec"),
    ], cwd=PROTOTYPE, check=True)
    suffix = ".exe" if windows else ""
    produced = output / "srota-gateway"
    # A one-file archive would leave a single file here; refuse it rather than
    # silently shipping a bundle that re-extracts on every launch.
    if not produced.is_dir():
        raise SystemExit(f"Expected a one-dir PyInstaller tree at {produced}")
    staged.parent.mkdir(parents=True, exist_ok=True)
    produced.replace(staged)
    launcher = staged / f"srota-gateway{suffix}"
    if not launcher.is_file():
        raise SystemExit(f"Frozen gateway launcher is missing: {launcher}")
    # Two failure modes have shipped once each, so the guard brackets both: the
    # 0.1.0 packages could not import scipy.optimize at all (broken numeric
    # stack), and the 0.1.1 packages exclude the stack on purpose (bloat). What
    # this build must prove is the pairing — the packages are ABSENT, and asking
    # for an engine that needs them raises a typed refusal rather than
    # ModuleNotFoundError. One check alone cannot hold both: re-adding the stack
    # fails the absence probe, deleting the refusal path fails the second.
    check = subprocess.run(
        [str(launcher), "-c", _GUARD],
        capture_output=True, text=True, timeout=300,
    )
    if check.returncode:
        raise SystemExit(
            "Frozen gateway failed its engine-availability guard:\n"
            f"{check.stdout[-2000:]}{check.stderr[-3000:]}"
        )
    print(check.stdout.strip())
    size = sum(path.stat().st_size for path in staged.rglob("*") if path.is_file())
    print(f"Backend ready for {target} ({size // (1024 * 1024)} MiB one-dir tree)")


if __name__ == "__main__":
    main()
