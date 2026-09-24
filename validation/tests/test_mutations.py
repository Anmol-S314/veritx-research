"""Layer 5 gate: every deliberate corruption must be refused.

A mutation that slips through is a finding, so this test fails loudly on
any missed mutation.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tracks" / "t3-topology" / "dse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validation.harness.mutations import run_mutations  # noqa: E402
from validation.harness.run import _binary  # noqa: E402


def test_all_mutations_are_caught(tmp_path):
    results = run_mutations(_binary(), tmp_path)
    missed = [m for m in results if not m.caught]
    assert not missed, [(m.name, m.detail) for m in missed]
