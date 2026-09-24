"""Exact clock parsing (§5.13): no binary float for identity-bearing Hz."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.cli.commands_optimize import _parse_clock_hz  # noqa: E402


def test_exact_integer_above_2_53_is_preserved():
    # float("9007199254740993") == 9007199254740992.0 would silently lose 1.
    assert _parse_clock_hz("9007199254740993") == 9007199254740993
    assert _parse_clock_hz(9007199254740993) == 9007199254740993
    assert _parse_clock_hz("18446744073709551617") == 18446744073709551617


def test_integral_scientific_string_is_exact():
    assert _parse_clock_hz("1e9") == 10 ** 9
    assert _parse_clock_hz("2.5e3") == 2500


@pytest.mark.parametrize("bad", ["1.5", "0.1", "nan", "inf", "-inf", True,
                                 "not-a-number", ""])
def test_inexact_or_non_numeric_refuses(bad):
    with pytest.raises(ValueError):
        _parse_clock_hz(bad)


@pytest.mark.parametrize("bad", [0, -1, -10 ** 9])
def test_non_positive_refuses(bad):
    with pytest.raises(ValueError):
        _parse_clock_hz(bad)


def test_none_is_allowed():
    assert _parse_clock_hz(None) is None
