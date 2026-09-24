"""F-0003 intervention gate: completion must track the injection horizon."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tracks" / "t3-topology" / "dse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validation.harness.intervention import (  # noqa: E402
    intervention_verdict, run_schedule_intervention,
)
from validation.harness.run import _binary  # noqa: E402


def test_completion_tracks_the_injection_horizon(tmp_path):
    rows = run_schedule_intervention(_binary(), tmp_path)
    verdict = intervention_verdict(rows)
    assert verdict["supported"], verdict
