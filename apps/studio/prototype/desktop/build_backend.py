"""Freeze the gateway as a one-dir tree for this build host."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

PROTOTYPE = Path(__file__).resolve().parents[1]
REPO = PROTOTYPE.parents[2]

# Tauri copies this directory into the app resources as `gateway/`, and the
# shell launches `gateway/srota-gateway`. The name carries no target triple:
# the bundle config would otherwise need a host-specific path.
STAGED = Path("src-tauri/binaries/gateway")


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
    shutil.rmtree(staged, ignore_errors=True)
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
    # A frozen tree can look complete and still fail on first use: the shipped
    # 0.1.0 Linux package could not import scipy.optimize (its vendored
    # scipy/_external tree was never collected), which also broke sklearn and
    # skopt. Prove the numeric stack resolves in the frozen interpreter instead
    # of discovering it in a user's synthesis run.
    check = subprocess.run(
        [str(launcher), "-c", "import scipy.optimize, scipy.sparse, sklearn, skopt"],
        capture_output=True, text=True, timeout=300,
    )
    if check.returncode:
        raise SystemExit(
            "Frozen gateway cannot import its numeric stack "
            f"(scipy.optimize, scipy.sparse, sklearn, skopt):\n{check.stderr[-2000:]}"
        )
    size = sum(path.stat().st_size for path in staged.rglob("*") if path.is_file())
    print(f"Backend ready for {target} ({size // (1024 * 1024)} MiB one-dir tree)")


if __name__ == "__main__":
    main()
