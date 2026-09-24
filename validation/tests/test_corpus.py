"""CI gate for the independent validation corpus.

Runs every experiment in ``validation/experiments`` and asserts every
check is exact. A missing BookSim binary FAILS (the corpus never skips a
differential check silently) — build it with ``make tool-build
TOOL=booksim2`` or set ``VERITX_BOOKSIM_BIN``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tracks" / "t3-topology" / "dse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validation.harness.run import _binary, run_experiment  # noqa: E402
from validation.harness.spec import ExperimentSpec  # noqa: E402

_EXPERIMENTS = sorted((_ROOT / "validation" / "experiments").glob("V*.json"))
assert _EXPERIMENTS, "the validation corpus is empty"


@pytest.mark.parametrize("path", _EXPERIMENTS, ids=lambda p: p.stem)
def test_experiment_all_checks_exact(path, tmp_path):
    binary = _binary()
    spec = ExperimentSpec.load(path)
    report = run_experiment(spec, binary, tmp_path)
    failures = [c for c in report["checks"]
                if c["verdict"] != "exact" and not c.get("quarantined")]
    assert not failures, failures
    assert report["passed"]
