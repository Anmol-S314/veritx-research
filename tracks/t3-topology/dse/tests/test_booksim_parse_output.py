"""BookSim stats parser — reclaimed semantics (PHASE 3.2 / P0).

`simulation.booksim.parse_output` is NOT a legacy CLI helper. It is imported
by the CERTIFIED execution path:

    backend/booksim.py::_execute_prepared  -> parse_output
    backend/meshdor.py                     -> parse_output
    application/presets.py                 -> metric mapping ("mean")

The stronger lineage (p1b/verified-evaluation == integration/p1-product ==
epic/booksim-forward-port) carried three semantics the current tree had lost:

  1. `honest_avg` -> `honest_latency`   (request-time latency; the metric the
     comparison CLI prefers. The certified path parses BOTH keys, requires
     the stock `latency` key and stores the full stats dict — it does not
     itself prefer honest latency. Corrected wording, PHASE 3.2-seal.)
  2. a `NUM` numeric grammar that refuses BookSim's bare `= -` no-sample form
     instead of calling `float("-")`
  3. `max_packet_latency` extracted from the block's `\\tmaximum` line, NaN
     and inf guarded

The later current-side drain/flit evidence is PRESERVED, not replaced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.simulation.booksim import NUM, parse_output


# ══ 1. honest_avg -> honest_latency (THE P0) ═══════════════════════════

def test_honest_avg_is_parsed():
    r = parse_output("Packet latency average = 100.0\n\thonest_avg = 19.5\n")
    assert r["honest_latency"] == 19.5


def test_stock_latency_key_is_never_overwritten():
    """Two latency conventions, two precise names. The stock qtime-based
    plat mean must survive alongside the honest request-time mean."""
    r = parse_output("Packet latency average = 1000.0\n\thonest_avg = 12.0\n")
    assert r["latency"] == 1000.0
    assert r["honest_latency"] == 12.0


def test_honest_latency_and_percentiles_share_one_convention():
    """honest_latency and p50/p95/p99 are all request-time based. A parse
    where the honest mean sits inside [p50, p99] is the sanity property;
    the point of the test is that BOTH come from the same corrected
    semantics and neither is derived from the stock plat mean."""
    stdout = (
        "Packet latency average = 4000.0\n"
        "\tp50 = 10.0\n\tp95 = 20.0\n\tp99 = 30.0\n"
        "\thonest_avg = 15.0\n"
    )
    r = parse_output(stdout)
    assert r["latency"] == 4000.0
    assert (r["p50"], r["p95"], r["p99"]) == (10.0, 20.0, 30.0)
    assert r["p50"] <= r["honest_latency"] <= r["p99"]
    # The honest mean is NOT a function of the stock mean.
    assert r["honest_latency"] != r["latency"]


def test_honest_avg_absent_stays_absent():
    """A stock binary prints no honest_avg — the key must not appear, so
    callers fall back deliberately rather than reading a fabricated 0."""
    r = parse_output("Packet latency average = 5.0\n")
    assert "honest_latency" not in r


def test_honest_avg_scientific_notation():
    assert parse_output("\thonest_avg = 1.25e+02\n")["honest_latency"] == 125.0


# ══ 2. bare "-" / no-sample stats must not crash ═══════════════════════

def test_bare_dash_placeholder_never_reaches_float():
    """BookSim prints "= -" for a stat with no samples (zero packets
    delivered). float("-") used to crash the whole batch."""
    stdout = (
        "Packet latency average = -\n\tp50 = -\n\tp99 = -\n"
        "Hops average = -\nAccepted packet rate average = -\n"
        "\thonest_avg = -\n"
    )
    r = parse_output(stdout)
    for key in ("latency", "p50", "p99", "hops", "throughput",
                "honest_latency"):
        assert key not in r, f"{key} must stay absent for a '-' placeholder"


def test_num_grammar_rejects_non_numeric_forms():
    import re
    for good in ("12", "12.5", ".5", "1e3", "1.5E-2"):
        assert re.fullmatch(NUM, good), f"{good!r} must match NUM"
    for bad in ("-", "--", "", "abc", "-."):
        assert not re.fullmatch(NUM, bad), f"{bad!r} must not match NUM"


def test_zero_packet_stats_are_absent_not_zero():
    r = parse_output("Packet latency average = -\n\tpkt_count = 0\n")
    assert "latency" not in r
    assert r["pkt_count"] == 0


# ══ 3. max_packet_latency (F8) ═════════════════════════════════════════

def test_max_packet_latency_from_the_right_block():
    r = parse_output(
        "Packet latency average = 19.125\n\tmaximum = 26\n"
        "Network latency average = 3.0\n")
    assert r["max_packet_latency"] == 26.0


def test_max_packet_latency_nan_guarded():
    r = parse_output("Packet latency average = -nan\n\tmaximum = -nan\n")
    assert "max_packet_latency" not in r
    assert "latency" not in r


def test_max_packet_latency_ignores_other_blocks():
    """A `\\tmaximum` under a DIFFERENT latency block is not the packet max."""
    r = parse_output("Flit latency average = 3.0\n\tmaximum = 9\n")
    assert "max_packet_latency" not in r


def test_max_packet_latency_absent_when_block_has_no_max():
    r = parse_output("Packet latency average = 4.0\n"
                     "Network latency average = 2.0\n")
    assert "max_packet_latency" not in r


# ══ 4. preserved semantics: completion, drain, flits, unstable ═════════

def test_completion_time_and_time_taken_fallback():
    assert parse_output("Completion time is 1234 cycles")["completion_time"] == 1234
    assert parse_output("Time taken is 99 cycles")["completion_time"] == 99
    # "Completion time" wins when both are present.
    both = parse_output("Time taken is 99 cycles\nCompletion time is 1234 cycles")
    assert both["completion_time"] == 1234


def test_p50_p95_p99_and_pkt_count():
    r = parse_output("\tp50 = 1.5\n\tp95 = 2.5\n\tp99 = 3.5\n\tpkt_count = 42\n")
    assert (r["p50"], r["p95"], r["p99"], r["pkt_count"]) == (1.5, 2.5, 3.5, 42)


def test_hops_and_throughput():
    r = parse_output("Hops average = 2.75\n"
                     "Accepted packet rate average = 0.125\n")
    assert r["hops"] == 2.75 and r["throughput"] == 0.125


def test_drain_verdict_delivered_and_flit_totals_are_preserved():
    """The later current-side drain/flit evidence must survive the merge."""
    stdout = ("Trace replay complete: delivered 24 packets, drain took 9 cycles\n"
              "VeritX: injected flits total = 96\n"
              "VeritX: accepted flits total = 96\n")
    r = parse_output(stdout)
    assert r["delivered"] == 24
    assert r["flits_injected"] == 96 and r["flits_accepted"] == 96
    assert "Trace replay complete" in r["drain_verdict"]


def test_absent_flit_totals_stay_absent():
    r = parse_output("Injected flit rate average = 0.001\n")
    assert "flits_injected" not in r and "flits_accepted" not in r


def test_unstable_detection():
    assert parse_output("Too many sample periods")["unstable"] is True
    assert parse_output("Simulation UNSTABLE")["unstable"] is True
    assert "unstable" not in parse_output("all good\n")


def test_empty_stdout_yields_empty_dict():
    assert parse_output("") == {}


# ══ 5. one BookSimError identity ═══════════════════════════════════════

def test_booksim_error_is_the_core_identity():
    """`simulation.booksim` used to DEFINE a second BookSimError while the
    certified backend raised core.errors.BookSimError. The CLI caught the
    local one, so backend failures fell through to the generic handler."""
    from veritx_dse.core.errors import (
        BookSimError as CoreBookSimError, TimeoutError as CoreTimeout,
        TraceError,
    )
    from veritx_dse.simulation.booksim import (
        BookSimError, TimeoutError,
    )
    assert BookSimError is CoreBookSimError
    assert TimeoutError is CoreTimeout
    assert issubclass(TimeoutError, BookSimError)
    assert issubclass(TraceError, Exception)


# ══ 6. detect_trace_stats: fail loud + max_node ════════════════════════

def test_detect_trace_stats_reports_max_node(tmp_path):
    from veritx_dse.simulation.booksim import detect_trace_stats
    p = tmp_path / "t.trace"
    p.write_text("# c\n0 0 0 3 128\n5 16 0 48 128\n")
    st = detect_trace_stats(str(p))
    assert st.max_node == 48
    assert st.num_packets == 2
    assert st.max_cycle == 5


def test_detect_trace_stats_missing_file_fails_loud():
    from veritx_dse.core.errors import TraceError
    from veritx_dse.simulation.booksim import detect_trace_stats
    with pytest.raises(TraceError):
        detect_trace_stats("/nonexistent/file.trace")


def test_detect_trace_stats_malformed_line_fails_loud(tmp_path):
    from veritx_dse.core.errors import TraceError
    from veritx_dse.simulation.booksim import detect_trace_stats
    p = tmp_path / "bad.trace"
    p.write_text("0 0 0 1 4\n1 x 0 2 4\n")
    with pytest.raises(TraceError):
        detect_trace_stats(str(p))


def test_detect_trace_stats_empty_trace_still_returns_zeros(tmp_path):
    """Existing-but-empty is NOT an error: callers report
    num_packets == 0 themselves."""
    from veritx_dse.simulation.booksim import detect_trace_stats
    p = tmp_path / "e.trace"
    p.write_text("# comments only\n")
    st = detect_trace_stats(str(p))
    assert st.num_packets == 0 and st.max_node == 0


def test_anynet_usability_now_actually_fires_on_oversized_trace(tmp_path):
    """PHASE-3.1 reclaimed the precheck but TraceStats had no max_node, so
    it could never fire. This is the end-to-end proof it does now."""
    from veritx_dse.model.presets import anynet_usability, make_anynet_topo
    from veritx_dse.simulation.booksim import detect_trace_stats

    trace = tmp_path / "big.trace"
    trace.write_text("0 0 0 40 128\n")
    net = tmp_path / "small.anynet"
    net.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
    st = detect_trace_stats(str(trace))
    ok, reason = anynet_usability(make_anynet_topo(str(net)), st.max_node)
    assert not ok and "remap the trace" in reason
