"""RT-final Worker B — B5/B6: production gates survive ``python3 -O``.

The identity precondition and the evidence-authentication gate must be
explicit conditionals (never ``assert``), because ``-O`` removes asserts
from production code. The probe subprocess runs both gates under ``-O``;
the static audit pins that ``fabric_evaluator.py`` carries no assert.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]


class TestPythonOInvariants:
    def test_identity_and_evidence_gates_survive_optimization(self):
        probe = DSE / "tests" / "rt_identity_probe_o.py"
        env = dict(os.environ)
        pypath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(DSE) + (os.pathsep + pypath if pypath
                                        else "")
        proc = subprocess.run(
            [sys.executable, "-O", str(probe)], cwd=str(DSE),
            capture_output=True, text=True, timeout=300, env=env)
        assert proc.returncode == 0, proc.stderr
        verdict = json.loads(proc.stdout)
        assert verdict == {"ok": True, "transplant_refused": True,
                           "evidence_refused": True}

    def test_fabric_evaluator_has_no_assert_gates(self):
        """Static audit: the evaluator's seal-critical module must not
        rely on ``assert`` (which ``-O`` removes)."""
        source = (DSE / "veritx_dse" / "application" /
                  "fabric_evaluator.py").read_text()
        tree = ast.parse(source)
        asserts = [node.lineno for node in ast.walk(tree)
                   if isinstance(node, ast.Assert)]
        assert asserts == [], (
            f"fabric_evaluator.py carries assert statement(s) at "
            f"line(s) {asserts}; production invariants must use explicit "
            f"conditionals + typed exceptions")
