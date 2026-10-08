"""Independent sampled-pointer reference, not production agrees with itself.

This mathematical differential is NOT an independent RTL/CDC qualification.
"""
from fractions import Fraction
from math import lcm

from veritx_dse.model.domain_intent import AsyncFIFOConfig, PointerEncoding
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
