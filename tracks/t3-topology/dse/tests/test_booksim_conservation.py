"""BookSim packet/flit conservation gate (P0.9).

The fork emits delivered-packet and injected/accepted-flit totals. A
supervised execution must carry them and they must conserve; their
absence is now a refusal, not an unexplained ``None``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.booksim_execution import (  # noqa: E402
    BookSimExecutionError, assert_execution_gate, parse_booksim_stats,
)

_HEAD = ("Loaded text trace: 5 packets from workload.trace\n"
         "Completion time is 777 cycles\n")
_TAIL = ("Trace replay complete: delivered {d} packets, drain took 10 "
         "cycles\n"
         "VeritX: injected flits total = {fi}\n"
         "VeritX: accepted flits total = {fa}\n")
_STDERR = "[trace] All 800 cycles, injected=5 — draining\n"


def _stats(d=5, fi=15, fa=15):
    stdout = _HEAD + _TAIL.format(d=d, fi=fi, fa=fa)
    return parse_booksim_stats(stdout, _STDERR)


def test_counters_are_parsed_not_none():
    stats = _stats()
    assert stats["delivered_packets"] == 5
    assert stats["flits_injected"] == 15
    assert stats["flits_accepted"] == 15


def test_conserving_run_passes_the_gate():
    assert_execution_gate(_stats(), expected_packets=5, expected_flits=15,
                          require_conservation=True)


def test_missing_counters_refuse_when_conservation_is_required():
    stdout = _HEAD  # no drain/counter lines
    stats = parse_booksim_stats(stdout, _STDERR)
    assert stats["delivered_packets"] is None
    with pytest.raises(BookSimExecutionError, match="conservation evidence"):
        assert_execution_gate(stats, expected_packets=5, expected_flits=15,
                              require_conservation=True)


def test_delivered_packet_loss_refuses():
    with pytest.raises(BookSimExecutionError, match="packet conservation"):
        assert_execution_gate(_stats(d=4), expected_packets=5,
                              expected_flits=15, require_conservation=True)


def test_flit_loss_refuses():
    with pytest.raises(BookSimExecutionError, match="flit conservation"):
        assert_execution_gate(_stats(fi=15, fa=14), expected_packets=5,
                              expected_flits=15, require_conservation=True)


def test_wrong_declared_flit_total_refuses():
    with pytest.raises(BookSimExecutionError, match="flit conservation"):
        assert_execution_gate(_stats(), expected_packets=5,
                              expected_flits=16, require_conservation=True)


def test_injected_diagnostic_may_omit_counters():
    stats = parse_booksim_stats(_HEAD, _STDERR)
    assert_execution_gate(stats, expected_packets=5)  # no conservation
