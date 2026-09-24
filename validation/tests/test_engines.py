"""Engine gates: independent engines must be available and self-consistent."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tracks" / "t3-topology" / "dse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validation.harness.engines import run_engines  # noqa: E402


def test_independent_engines_pass(tmp_path):
    results = run_engines(_ROOT, tmp_path)
    failed = [e for e in results if not e.passed]
    assert not failed, [(e.name, e.detail) for e in failed]
