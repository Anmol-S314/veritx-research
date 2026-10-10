"""Independent sampled-pointer reference, not production agrees with itself.

This mathematical differential is NOT an independent RTL/CDC qualification.
"""
from fractions import Fraction
from math import lcm

import pytest

from veritx_dse.core.errors import InvalidInput, UnsupportedSemantics
from veritx_dse.model.domain_intent import (
    AsyncFIFOConfig, Crossing, PointerEncoding, assess_crossing,
)
from veritx_dse.simulation.clocked_fifo import clocked_fifo_transfer


def reference(write_hz, read_hz, words, depth, stages, start_s=Fraction(0)):
    ticks_per_s = lcm(write_hz, read_hz)
    write_stride, read_stride = ticks_per_s // write_hz, ticks_per_s // read_hz
    write_pipeline, read_pipeline = [0]*(stages-1), [0]*(stages-1)
    writes = reads = visible_reads = peak = blocked = 0
    completed = None
    for tick in range(100_000):
        # Both receivers sample the pre-edge state. New writes/reads cannot
        # become visible through synchronizers on that same edge.
        before_write, before_read = writes, reads
        if tick % write_stride == 0:
            write_pipeline.append(before_read)
            visible_reads = write_pipeline.pop(0)
        if tick % read_stride == 0:
            read_pipeline.append(before_write)
            visible_writes = read_pipeline.pop(0)
            if reads < visible_writes:
                reads += 1
                if reads == words:
                    completed = Fraction(tick, ticks_per_s) + Fraction(1, read_hz)
        if tick % write_stride == 0:
            if writes < words and Fraction(tick, ticks_per_s) >= start_s:
                if writes - visible_reads < depth:
                    writes += 1
                else:
                    blocked += 1
            if completed is not None and visible_reads == words:
                return completed, max(completed, Fraction(tick, ticks_per_s)), peak, blocked
        peak = max(peak, writes - reads)
    raise AssertionError("reference did not drain")


def test_fractional_start_keeps_both_global_clock_phases():
    config = AsyncFIFOConfig(4, 64, 64, PointerEncoding.GRAY, 2)
    for write_hz in range(1, 8):
        for read_hz in range(1, 8):
            start = Fraction(1, 5)
            actual = clocked_fifo_transfer(config=config, write_hz=write_hz,
                                          read_hz=read_hz, words=16, start_s=start)
            assert (actual.completed_s, actual.reusable_s,
                    actual.peak_occupancy, actual.blocked_write_cycles) == reference(
                        write_hz, read_hz, 16, 4, 2, start)


def test_two_clock_executor_matches_independent_pointer_pipeline():
    for write_hz in range(1, 8):
        for read_hz in range(1, 8):
            for depth in (4, 8):
                for stages in (2, 3):
                    for words in (1, 2, 12, 32):
                        config = AsyncFIFOConfig(depth, 64, 64, PointerEncoding.GRAY, stages)
                        actual = clocked_fifo_transfer(config=config, write_hz=write_hz,
                                                      read_hz=read_hz, words=words)
                        assert (actual.completed_s, actual.reusable_s,
                                actual.peak_occupancy, actual.blocked_write_cycles) == reference(
                                    write_hz, read_hz, words, depth, stages)


def test_explicit_fractional_clock_phases_match_sampled_pointer_oracle():
    config = AsyncFIFOConfig(4, 64, 64, PointerEncoding.GRAY, 2)
    write_hz, read_hz = 4, 3
    write_phase, read_phase = Fraction(1, 8), Fraction(1, 6)
    start, words = Fraction(1, 5), 16
    actual = clocked_fifo_transfer(config=config, write_hz=write_hz,
        read_hz=read_hz, words=words, start_s=start,
        write_phase_s=write_phase, read_phase_s=read_phase)

    # Independent discrete event oracle samples pre-edge pointers, including
    # coincident edges, on a rational quantum containing every phase/period.
    quantum = Fraction(1, 120)
    write_stride = int(Fraction(1, write_hz) / quantum)
    read_stride = int(Fraction(1, read_hz) / quantum)
    write_origin = int(write_phase / quantum)
    read_origin = int(read_phase / quantum)
    visible_write = visible_read = writes = reads = peak = 0
    write_pipe, read_pipe = [0], [0]
    completed = reusable = None
    for tick in range(120_000):
        time = tick * quantum
        we = tick >= write_origin and (tick-write_origin) % write_stride == 0
        re = tick >= read_origin and (tick-read_origin) % read_stride == 0
        before_writes, before_reads = writes, reads
        if we:
            read_pipe.append(before_reads)
            visible_read = read_pipe.pop(0)
        if re:
            write_pipe.append(before_writes)
            visible_write = write_pipe.pop(0)
            if reads < visible_write:
                reads += 1
                if reads == words:
                    completed = time + Fraction(1, read_hz)
        if we and time >= start and writes < words and writes-visible_read < config.depth:
            writes += 1
            peak = max(peak, writes-reads)
        if we and completed is not None and visible_read == words:
            reusable = max(completed, time)
            break
    assert (actual.completed_s, actual.reusable_s, actual.peak_occupancy) == (
        completed, reusable, peak)
    assert actual.writes == actual.reads == words


def test_invalid_explicit_clock_phase_refuses():
    config = AsyncFIFOConfig(4, 64, 64, PointerEncoding.GRAY, 2)
    with pytest.raises(InvalidInput, match="write_phase_s"):
        clocked_fifo_transfer(config=config, write_hz=4, read_hz=3, words=2,
                              write_phase_s=Fraction(1, 4))


def test_abstract_execution_conserves_words_within_occupancy_bound():
    """The abstract transfer moves exactly `words` and never exceeds depth."""
    for write_hz, read_hz, depth, stages, words in (
            (4, 3, 4, 2, 16), (3, 5, 8, 3, 32), (7, 7, 4, 2, 1)):
        config = AsyncFIFOConfig(depth, 64, 64, PointerEncoding.GRAY, stages)
        burst = clocked_fifo_transfer(config=config, write_hz=write_hz,
                                      read_hz=read_hz, words=words)
        # Conservation: every word is written once and read once, and the
        # occupancy watermark never exceeds the declared capacity.
        assert burst.writes == words
        assert burst.reads == words
        assert 0 <= burst.peak_occupancy <= depth


def test_non_gray_pointer_execution_still_refuses():
    config = AsyncFIFOConfig(3, 64, 64, PointerEncoding.BINARY, 2)
    with pytest.raises(UnsupportedSemantics) as exc:
        clocked_fifo_transfer(config=config, write_hz=4, read_hz=3, words=8)
    assert exc.value.code == "UNSUPPORTED_SEMANTICS"
    assert "GRAY" in str(exc.value)


def test_signoff_request_refuses_and_names_the_owner_stage():
    """Asking the abstract CDC path for RTL/signoff qualification is a typed
    refusal: the owner is verification/RTL generation and no differential
    exists, so HETERO_TIMING_ABSTRACT is never relabelled signoff."""
    crossing = Crossing.from_dict({
        "id": "cdc0", "src_clock": "a", "dst_clock": "b",
        "signal_kind": "BUS", "mechanism": "ASYNC_FIFO",
        "synchronizer_stages": None,
        "async_fifo": {"depth": 8, "write_width": 64, "read_width": 64,
                       "pointer_encoding": "GRAY",
                       "synchronizer_stages": 2},
    })
    with pytest.raises(UnsupportedSemantics) as exc:
        assess_crossing(crossing, require_rtl_qualification=True)
    assert exc.value.code == "UNSUPPORTED_SEMANTICS"
    msg = str(exc.value)
    assert "verification/RTL generation" in msg
    assert "no RTL differential exists" in msg
    # The unrequested assessment stays abstract, never signoff.
    assert assess_crossing(crossing).signoff_verified is False
