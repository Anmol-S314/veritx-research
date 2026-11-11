"""fifo — AsyncFIFO performance consequence model.

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from collections import deque

from ._core import DomainIntentError
from ._parse import _as_int
from .enums import FidelityLevel
from .crossing import AsyncFIFOConfig

# --------------------------------------------------------------------------
# async FIFO performance model (intent correctness vs consequence, §33)
# --------------------------------------------------------------------------

class AsyncFIFOModel:
    """Deterministic occupancy / backpressure model for one async FIFO.

    This answers "what does the FIFO COST?" — accepted writes, accepted reads,
    occupancy, full/empty and backpressure — as distinct from
    :func:`assess_crossing`, which answers "is the intent coherent?".

    It is a Q1 micro-oracle over an exact integer cycle counter. It models:
    capacity, backpressure, and the ``synchronizer_stages`` read-domain latency
    before a written item becomes readable. It does NOT model analog
    metastability, bit-error rates, clock ratio, or multi-rate event execution.
    Clock-ratio exploration belongs to the Level-1 heterogeneous timing model;
    this class deliberately reports ``HETERO_TIMING_ABSTRACT`` and no more.

    Invariants held by construction: occupancy never exceeds ``depth``, never
    goes negative, and items become readable in write order.
    """

    def __init__(self, config: AsyncFIFOConfig,
                 synchronizer_latency_cycles: int | None = None) -> None:
        if not isinstance(config, AsyncFIFOConfig):
            raise DomainIntentError(
                "AsyncFIFOModel needs an AsyncFIFOConfig, got "
                f"{type(config).__name__}")
        if synchronizer_latency_cycles is not None and \
                synchronizer_latency_cycles != config.synchronizer_stages:
            # Two authorities for one fact: the declared config wins and the
            # conflict is refused rather than silently resolved.
            raise DomainIntentError(
                f"synchronizer_latency_cycles="
                f"{synchronizer_latency_cycles} contradicts the declared "
                f"async_fifo.synchronizer_stages="
                f"{config.synchronizer_stages}. One value, one authority.")
        self._config = config
        self._latency = config.synchronizer_stages
        # (sequence, read-eligible cycle) in write order.
        self._entries: deque[tuple[int, int]] = deque()
        self._next_seq = 0
        self._cycle = 0
        self._accepted_writes = 0
        self._accepted_reads = 0
        self._rejected_writes = 0
        self._rejected_reads = 0
        self._read_order: list[int] = []

    # -- introspection ---------------------------------------------------
    @property
    def config(self) -> AsyncFIFOConfig:
        return self._config

    @property
    def fidelity(self) -> FidelityLevel:
        return FidelityLevel.HETERO_TIMING_ABSTRACT

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def depth(self) -> int:
        return self._config.depth

    @property
    def occupancy(self) -> int:
        """Items occupying a slot: readable plus still in synchronizer."""
        return len(self._entries)

    @property
    def full(self) -> bool:
        return self.occupancy >= self._config.depth

    @property
    def empty(self) -> bool:
        return self.occupancy == 0

    @property
    def readable(self) -> int:
        """Items whose synchronizer latency has elapsed."""
        return sum(1 for _, eligible in self._entries
                   if eligible <= self._cycle)

    @property
    def in_synchronizer(self) -> int:
        return self.occupancy - self.readable

    @property
    def accepted_writes(self) -> int:
        return self._accepted_writes

    @property
    def accepted_reads(self) -> int:
        return self._accepted_reads

    @property
    def backpressured_writes(self) -> int:
        """Writes refused because the FIFO was full."""
        return self._rejected_writes

    @property
    def read_order(self) -> tuple[int, ...]:
        """Sequence numbers in the order they were read (ordering invariant)."""
        return tuple(self._read_order)

    # -- operations ------------------------------------------------------
    def advance(self, cycles: int = 1) -> None:
        """Advance the shared reference cycle counter by ``cycles``."""
        _as_int("AsyncFIFOModel.advance(cycles)", cycles, minimum=0)
        self._cycle += cycles

    def write_accepted(self) -> bool:
        """Attempt one write. False when full => backpressure, not a drop."""
        if self.full:
            self._rejected_writes += 1
            return False
        seq = self._next_seq
        self._next_seq += 1
        self._entries.append((seq, self._cycle + self._latency))
        self._accepted_writes += 1
        return True

    def read_accepted(self) -> bool:
        """Attempt one read. False when empty or not yet synchronised."""
        if not self._entries:
            self._rejected_reads += 1
            return False
        seq, eligible = self._entries[0]
        if eligible > self._cycle:
            # Occupied but still in the synchronizer: not yet readable.
            self._rejected_reads += 1
            return False
        self._entries.popleft()
        self._accepted_reads += 1
        self._read_order.append(seq)
        return True

    def fill(self) -> int:
        """Write until full; returns accepted count. Test/oracle helper."""
        accepted = 0
        while self.write_accepted():
            accepted += 1
        return accepted

    def drain(self) -> int:
        """Read every currently-readable item; returns accepted count."""
        accepted = 0
        while self.read_accepted():
            accepted += 1
        return accepted

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"AsyncFIFOModel(depth={self.depth}, occupancy="
                f"{self.occupancy}, cycle={self._cycle}, "
                f"fidelity={self.fidelity.value})")
