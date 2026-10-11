"""Run the real shared gate against bounded stubs, never the full suites."""
import os
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("missing,deps,npm_status,npx_status,expected", [
    ("node", True, 0, 0, 1),
    ("npx", True, 0, 0, 1),
    ("npm", False, 0, 0, 1),
    (None, False, 1, 0, 1),
    (None, True, 0, 1, 1),
    (None, False, 0, 0, 0),
    (None, True, 0, 0, 0),
])
def test_required_stages_cannot_skip_to_green(
        tmp_path, missing, deps, npm_status, npx_status, expected):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    gate = scripts / "ci_gate.sh"
    gate.write_text((REPO / "scripts/ci_gate.sh").read_text())
    studio = tmp_path / "apps/studio"
    studio.mkdir(parents=True)
    if deps:
        (studio / "node_modules").mkdir()
    bins = tmp_path / "bin"
    bins.mkdir()
    for name in ("bash", "dirname", "env", "mkdir"):
        (bins / name).symlink_to(Path("/usr/bin") / name)
    for name in ("make", "python3", "node", "npx", "npm"):
        if name == missing:
            continue
        status = npm_status if name == "npm" else npx_status if name == "npx" else 0
        body = '#!/bin/bash\nprintf "%s\\n" "' + name + ' $*" >> "$CALLS"\n'
        if name == "npm" and status == 0:
            body += 'mkdir -p apps/studio/node_modules\n'
        body += f"exit {status}\n"
        (bins / name).write_text(body)
        (bins / name).chmod(0o755)
    calls = tmp_path / "calls"
    run = subprocess.run(
        ["/bin/bash", str(gate)], cwd=tmp_path,
        env={**os.environ, "PATH": str(bins), "CALLS": str(calls)},
        capture_output=True, text=True, timeout=5)
    assert run.returncode == expected, run.stdout + run.stderr
    assert ("CI GATE GREEN" in run.stdout) == (expected == 0)
    assert "SKIP=0" in run.stdout
    # Even a missing required prerequisite must not suppress later stages.
    assert "python3 -m pytest apps/studio/tests" in calls.read_text()
    if expected:
        assert "FAIL ---" in run.stdout
