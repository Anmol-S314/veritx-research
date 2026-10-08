"""Exact two-clock abstract FIFO burst execution, independent of the Q1 model.

Pointers become visible after N STRICTLY FUTURE receiver edges, both ways.
Reads win simultaneous edges. Starts empty; callers serialize bursts until
all freed slots are visible again. Not an RTL/metastability oracle.
"""
from collections import deque
from dataclasses import dataclass
from fractions import Fraction

from veritx_dse.core.errors import InvalidInput, UnsupportedSemantics
from veritx_dse.model.domain_intent import AsyncFIFOConfig, PointerEncoding
from veritx_dse.model.resource_graph import exact_int


def edge_at_or_after(time, period):
    return -(-time // period) * period


def visible_after(time, period, stages):
    return (time // period + stages) * period


@dataclass(frozen=True)
class FIFOBurst:
    completed_s: Fraction
    reusable_s: Fraction
    writes: int
    reads: int
    peak_occupancy: int
    blocked_write_cycles: int


def clocked_fifo_transfer(*, config, write_hz, read_hz, words, start_s=Fraction(0)):
    if not isinstance(config, AsyncFIFOConfig):
        raise InvalidInput("FIFO transfer requires the declared config")
    if config.pointer_encoding is not PointerEncoding.GRAY:
        raise UnsupportedSemantics("two-clock execution supports GRAY pointers only")
    exact_int("write_hz", write_hz, 1)
    exact_int("read_hz", read_hz, 1)
    exact_int("words", words, 1)
    if words > 1_000_000:
        raise UnsupportedSemantics("abstract FIFO burst exceeds one million words")
    if not isinstance(start_s, Fraction) or start_s < 0:
        raise InvalidInput("start_s must be a non-negative exact Fraction")
    wp, rp = Fraction(1, write_hz), Fraction(1, read_hz)
    wt, rt = edge_at_or_after(start_s, wp), edge_at_or_after(start_s, rp)
    entries, released = deque(), deque()
    writes = reads = visible_reads = peak = blocked = 0
    while reads < words:
        # Skip idle edges instead of enumerating a large clock-ratio Cartesian grid.
        if entries:
            rt = max(rt, entries[0])
        if writes < words:
            while released and released[0][0] <= wt:
                _, visible_reads = released.popleft()
            if writes - visible_reads >= config.depth:
                if not released:
                    # Full FIFO: the next consumer edge creates the first release.
                    wt_next = None
                else:
                    next_wt = edge_at_or_after(released[0][0], wp)
                    blocked += int((next_wt - wt) / wp)
                    wt = next_wt
                    wt_next = wt
            else:
                wt_next = wt
        else:
            wt_next = None
        if entries and (wt_next is None or rt <= wt_next):
            entries.popleft()
            reads += 1
            released.append((visible_after(rt, wp, config.synchronizer_stages), reads))
            last_read = rt
            rt += rp
        elif wt_next is not None:
            # A skipped write may now see a release; reconsider before accepting.
            while released and released[0][0] <= wt:
                _, visible_reads = released.popleft()
            if writes - visible_reads >= config.depth:
                continue
            writes += 1
            entries.append(visible_after(wt, rp, config.synchronizer_stages))
            peak = max(peak, writes - reads)
            wt += wp
        else:
            raise InvalidInput("FIFO execution made no progress")
    finish = last_read + rp
    return FIFOBurst(finish, max(finish, visible_after(last_read, wp, config.synchronizer_stages)),
                    writes, reads, peak, blocked)
