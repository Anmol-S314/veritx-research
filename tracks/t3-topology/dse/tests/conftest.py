"""Test-session configuration.

Subprocess coverage: when the suite itself runs under `coverage run`, make
every spawned `python -m veritx_dse.cli ...` subprocess report its own
coverage (COVERAGE_PROCESS_START recipe, see scripts/_cov_sitecustomize.py).
Without measurement this installs nothing and tests run exactly as before.

Measured workflow (from dse/):

    COVERAGE_FILE=$PWD/.coverage COVERAGE_PROCESS_START=$PWD/pyproject.toml \
        python3 -m coverage run -m pytest tests/ -q
    python3 -m coverage combine && python3 -m coverage report

The hook dir (<rootdir>/.cov-hook/) holds a copy of the startup module named
`sitecustomize.py`, prepended to PYTHONPATH for spawned processes only when
measurement is active. It shadows the system sitecustomize *inside measured
subprocesses only* (the system one only installs the apport crash hook, which
test runs don't need); with COVERAGE_PROCESS_START unset the copy is inert
and nothing is installed at all.
"""
import os
import shutil
from pathlib import Path

import pytest

_DSE = Path(__file__).resolve().parent.parent
_HOOK = _DSE / "scripts" / "_cov_sitecustomize.py"


def pytest_configure(config):
    if not os.environ.get("COVERAGE_PROCESS_START"):
        return
    hook_dir = Path(config.rootdir) / ".cov-hook"
    hook_dir.mkdir(exist_ok=True)
    shutil.copy(_HOOK, hook_dir / "sitecustomize.py")
    pyd = str(_DSE)
    pypath = os.environ.get("PYTHONPATH", "")
    if pyd not in pypath.split(os.pathsep):
        os.environ["PYTHONPATH"] = (
            f"{hook_dir}{os.pathsep}{pyd}" + (f"{os.pathsep}{pypath}" if pypath else "")
        )
    # parallel-mode data files from subprocesses, combined afterwards
    os.environ.setdefault("COVERAGE_RUN", "true")


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("COVERAGE_PROCESS_START"):
        print("\n[subprocess coverage armed]")
