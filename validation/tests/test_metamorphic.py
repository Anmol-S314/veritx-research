"""Layer 5 gate: metamorphic invariants must hold."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tracks" / "t3-topology" / "dse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validation.harness.metamorphic import run_metamorphic  # noqa: E402
from validation.harness.run import _binary  # noqa: E402


def test_metamorphic_invariants_hold(tmp_path):
    results = run_metamorphic(_binary(), tmp_path)
    failed = [m for m in results if not m.passed]
    assert not failed, [(m.name, m.detail) for m in failed]
