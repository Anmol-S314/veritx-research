"""Energy fidelity tests: six separate, MECS excluded, never merged."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.reports import energy_fidelity as E  # noqa: E402


def test_six_estimators_with_distinct_fidelity():
    assert len(E.ESTIMATORS) == 6
    assert len({e["fidelity"] for e in E.ESTIMATORS}) == 6
    assert len({e["id"] for e in E.ESTIMATORS}) == 6


def test_bridge_coefficient_placeholder():
    assert E.BRIDGE_PJ_PER_HOP == pytest.approx(2.5 + 0.8 + 0.9 + 1.2)
    assert E.BRIDGE_ERT_STATUS == "PLACEHOLDER"


def test_mecs_power_invalid():
    for fam in ("gec", "gec_mecs", "mecs", "multidrop", "tapped",
                "hybrid", "GEC-MECS"):
        verdict, reason = E.booksim_native_verdict(fam)
        assert verdict == "INVALID", fam
        assert "_md_chan" in reason


def test_p2p_scope_valid():
    for fam in ("mesh", "cmesh", "flatfly", "torus"):
        verdict, _ = E.booksim_native_verdict(fam)
        assert verdict == "VALID_SCOPE", fam


def test_unknown_refused():
    verdict, _ = E.booksim_native_verdict("")
    assert verdict == "REFUSED"


def test_combine_always_raises():
    with pytest.raises(ValueError, match="never be merged"):
        E.combine_estimates(1.0, 2.0)
