"""§13/§17: execution readiness must never imply numerical qualification.

A backend that executes successfully is not automatically a qualified
number. These tests pin the independent dimensions for each certified
backend and refuse a fabricated envelope for an unknown one.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.qualification_envelopes import (  # noqa: E402
    ESTABLISHED, LIMITED, NOT_ESTABLISHED, qualification_envelope,
)


def test_astra_is_not_numerically_established_absolute():
    env = qualification_envelope("ASTRA2_EMBEDDED_BOOKSIM")
    assert env is not None
    assert env["numerical_qualification"] == LIMITED
    assert "NOT_ESTABLISHED" in env["basis"]
    assert env["calibration"] == NOT_ESTABLISHED


def test_every_certified_backend_declares_calibration():
    for backend in ("BOOKSIM_STANDALONE", "ASTRA2_EMBEDDED_BOOKSIM",
                    "RAMULATOR2_HBM3_V1", "CANONICAL_SERVING"):
        env = qualification_envelope(backend)
        assert env is not None, backend
        assert env["numerical_qualification"] in (
            ESTABLISHED, LIMITED, "PARTIAL")
        assert env["calibration"] == NOT_ESTABLISHED, backend
        assert env["basis"]


def test_unknown_backend_has_no_fabricated_envelope():
    assert qualification_envelope(None) is None
    assert qualification_envelope("MADE_UP_BACKEND") is None
