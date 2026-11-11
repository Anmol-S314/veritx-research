"""target_service.py — generic deterministic target/memory service model.

This module is a standalone, duck-typed implementation of the native
memory-device contract consumed by ``backend/native_coupled.py``::

    tick()
    send(addr, is_write, size, src, dst, callback) -> bool
    get_stats()
    finalize()
    memory_ticks
    tCK_ps
    tx_bytes

The model is deliberately small and explicit: per-bank read/write FIFOs, a
fixed service occupancy (or a byte-rate service), optional row-hit/miss
timing, and exact integer counters. It is *not* a DRAM protocol model: there
is no refresh, no bank-group timing, no coherency, no capacity enforcement,
and no protocol-level request/response handshake.

Address mapping
---------------
``mapping="channel_bank_row_col_v1"`` peels transaction index bits
least-significant first in the order named by the mapping:

    channel, bank, row, column

``tx_bytes`` is the transaction granule. ``channel`` is the lowest-order
field, then ``banks_per_channel`` banks, then ``ROWS_PER_BANK`` rows, then an
unbounded column-group index. Addresses inside the same ``tx_bytes`` granule
decode to the same location. There is no capacity wrap or refusal; the
column index is unbounded so every non-negative address has a deterministic
location.

Timing
------
A request accepted at cycle ``c`` is placed in its bank's class FIFO. On the
first ``tick()`` after acceptance, a free bank starts it. A service of
duration ``d`` completes at the end of tick ``c_start + d - 1``; with an idle
bank this is exactly ``d`` cycles after acceptance. Callbacks fire once, in
that tick. Row state is updated when service starts.

Rationale: docs/decisions/modules/simulation.md
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from veritx_dse.core.errors import SemanticError

try:  # canonical_json is the repository's single canonical serializer.
    from veritx_dse.core.spec import canonical_json as _canonical_json
except ImportError:  # pragma: no cover - pydantic is a declared dependency
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))


MODEL_ID = "TARGET_FIFO_BANK_V1"
MAPPING = "channel_bank_row_col_v1"
ARBITRATIONS = frozenset({"FIFO", "ROUND_ROBIN"})

#: Transactions per row. Rows are peeled from the transaction index after
#: channel and bank; the column index is the unbounded quotient above it.
ROWS_PER_BANK = 1 << 14

__all__ = [
    "ARBITRATIONS",
    "MAPPING",
    "MODEL_ID",
    "ROWS_PER_BANK",
    "TargetService",
    "TargetServiceConfig",
    "TargetServiceError",
    "execute_read_write_trace",
]


class TargetServiceError(ValueError, SemanticError):
    """Rejected target-service configuration, lifecycle, or trace input."""


def _is_int(value: Any) -> bool:
    """True for a real integer, not ``bool`` (which subclasses ``int``)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(name: str, value: Any, minimum: int) -> int:
    if not _is_int(value) or value < minimum:
        raise TargetServiceError(
            f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def _require_optional_int(name: str, value: Any, minimum: int) -> int | None:
    if value is None:
        return None
    return _require_int(name, value, minimum)


def _require_power_of_two(name: str, value: Any) -> int:
    _require_int(name, value, 1)
    if value & (value - 1):
        raise TargetServiceError(
            f"{name} must be a positive power of two, got {value!r}")
    return value


def _require_address(addr: Any) -> int:
    if not _is_int(addr) or addr < 0:
        raise TargetServiceError(
            f"addr must be a non-negative integer, got {addr!r}")
    return addr


@dataclass(frozen=True)
class TargetServiceConfig:
    """Frozen, validated configuration for :class:`TargetService`.

    ``service_cycles`` and ``bytes_per_cycle`` are mutually exclusive: set
    exactly one. ``service_cycles`` is a fixed occupancy per request;
    ``bytes_per_cycle`` yields ``ceil(size / bytes_per_cycle)`` cycles.

    ``row_hit_cycles`` and ``row_miss_cycles`` are optional timing
    adjustments. Row statistics are tracked even when both are ``None``.
    A first access to a bank is a row miss; a different row while another is
    open is a row conflict; the same row is a hit. Conflicts use the miss
    adjustment.
    """

    tx_bytes: int
    tCK_ps: int
    channels: int
    banks_per_channel: int
    read_queue_depth: int
    write_queue_depth: int
    service_cycles: int | None = None
    bytes_per_cycle: int | None = None
    read_latency_cycles: int = 0
    write_latency_cycles: int = 0
    row_hit_cycles: int | None = None
    row_miss_cycles: int | None = None
    model_id: str = MODEL_ID
    version: int = 1
    arbitration: str = "FIFO"
    mapping: str = MAPPING

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise TargetServiceError("model_id must be a non-empty string")
        _require_int("version", self.version, 1)
        _require_power_of_two("tx_bytes", self.tx_bytes)
        _require_int("tCK_ps", self.tCK_ps, 1)
        _require_int("channels", self.channels, 1)
        _require_int("banks_per_channel", self.banks_per_channel, 1)
        _require_int("read_queue_depth", self.read_queue_depth, 1)
        _require_int("write_queue_depth", self.write_queue_depth, 1)
        if (self.service_cycles is None) == (self.bytes_per_cycle is None):
            raise TargetServiceError(
                "exactly one of service_cycles or bytes_per_cycle must be "
                f"set (got service_cycles={self.service_cycles!r}, "
                f"bytes_per_cycle={self.bytes_per_cycle!r})")
        _require_optional_int("service_cycles", self.service_cycles, 1)
        _require_optional_int("bytes_per_cycle", self.bytes_per_cycle, 1)
        _require_int("read_latency_cycles", self.read_latency_cycles, 0)
        _require_int("write_latency_cycles", self.write_latency_cycles, 0)
        _require_optional_int("row_hit_cycles", self.row_hit_cycles, 0)
        _require_optional_int("row_miss_cycles", self.row_miss_cycles, 0)
        if (not isinstance(self.arbitration, str)
                or self.arbitration not in ARBITRATIONS):
            raise TargetServiceError(
                f"arbitration must be one of {sorted(ARBITRATIONS)}, "
                f"got {self.arbitration!r}")
        if self.mapping != MAPPING:
            raise TargetServiceError(
                f"mapping must be {MAPPING!r}, got {self.mapping!r}")

    def to_dict(self) -> dict[str, Any]:
        """Return the closed, JSON-serializable configuration surface."""
        return {
            "model_id": self.model_id,
            "version": self.version,
            "tx_bytes": self.tx_bytes,
            "tCK_ps": self.tCK_ps,
            "channels": self.channels,
            "banks_per_channel": self.banks_per_channel,
            "read_queue_depth": self.read_queue_depth,
            "write_queue_depth": self.write_queue_depth,
            "service_cycles": self.service_cycles,
            "bytes_per_cycle": self.bytes_per_cycle,
            "read_latency_cycles": self.read_latency_cycles,
            "write_latency_cycles": self.write_latency_cycles,
            "row_hit_cycles": self.row_hit_cycles,
            "row_miss_cycles": self.row_miss_cycles,
            "arbitration": self.arbitration,
            "mapping": self.mapping,
        }

    def config_id(self) -> str:
        """Bare SHA-256 over canonical JSON; equal configs share an id."""
        payload = _canonical_json(self.to_dict()).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class _Request:
    sequence: int
    addr: int
    is_write: bool
    size: int
    src: Any
    dst: Any
    callback: Callable[[int, int, int], None] | None
    accepted_tick: int
    location: tuple[int, int, int, int]
    completed: bool = False


@dataclass
class _Bank:
    channel: int
    bank: int
    read_q: deque[_Request] = field(default_factory=deque)
    write_q: deque[_Request] = field(default_factory=deque)
    in_service: _Request | None = None
    service_end_tick: int = 0
    open_row: int | None = None
    #: None until the first contended choice; then the class to prefer.
    prefer_write: bool | None = None


class TargetService:
    """Deterministic per-bank FIFO target service.

    The instance satisfies the duck-typed native memory-device contract.
    Every bank has an independent service engine, so a tick starts service on
    every free bank. ``FIFO`` arbitration picks the older head across the
    bank's read and write FIFOs; ``ROUND_ROBIN`` alternates the preferred
    class whenever both classes are non-empty.
    """

    def __init__(self, config: TargetServiceConfig):
        if not isinstance(config, TargetServiceConfig):
            raise TargetServiceError(
                "TargetService requires a TargetServiceConfig, got "
                f"{type(config).__name__}")
        self._config = config
        self._banks = [
            _Bank(channel=channel, bank=bank)
            for channel in range(config.channels)
            for bank in range(config.banks_per_channel)
        ]
        self._cycles = 0
        self._closed = False
        self._next_sequence = 0

        self._accepted_reads = 0
        self._accepted_writes = 0
        self._accepted_read_bytes = 0
        self._accepted_write_bytes = 0
        self._served_reads = 0
        self._served_writes = 0
        self._read_latency_sum = 0
        self._write_latency_sum = 0
        self._read_queue_len_sum = 0
        self._write_queue_len_sum = 0
        self._row_hits = 0
        self._row_misses = 0
        self._row_conflicts = 0
        self._backpressure_events = 0
        self._read_backpressure_events = 0
        self._write_backpressure_events = 0

    # ------------------------------------------------------------------
    # Native memory-device contract
    # ------------------------------------------------------------------
    @property
    def config(self) -> TargetServiceConfig:
        return self._config

    @property
    def tCK_ps(self) -> int:
        return self._config.tCK_ps

    @property
    def tx_bytes(self) -> int:
        return self._config.tx_bytes

    @property
    def memory_ticks(self) -> int:
        return self._cycles

    @property
    def cycles(self) -> int:
        return self._cycles

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def outstanding(self) -> int:
        """Accepted requests not yet completed (queued or in service)."""
        return ((self._accepted_reads - self._served_reads)
                + (self._accepted_writes - self._served_writes))

    @property
    def has_outstanding(self) -> bool:
        return self.outstanding > 0

    def decode_address(self, addr: int) -> tuple[int, int, int, int]:
        """Decode a byte address to ``(channel, bank, row, column)``.

        The transaction index is ``addr // tx_bytes``. Fields are peeled
        least-significant first: channel, bank, row, column. The column index
        is unbounded (no capacity wrap or refusal).
        """
        _require_address(addr)
        config = self._config
        tx_index = addr // config.tx_bytes
        channel = tx_index % config.channels
        quotient = tx_index // config.channels
        bank = quotient % config.banks_per_channel
        quotient //= config.banks_per_channel
        row = quotient % ROWS_PER_BANK
        column = quotient // ROWS_PER_BANK
        return channel, bank, row, column

    def send(self, addr: int, is_write: Any, size: int, src: Any, dst: Any,
             callback: Callable[[int, int, int], None] | None) -> bool:
        """Try to enqueue one transaction.

        Returns ``True`` when the transaction is accepted, ``False`` when the
        relevant per-bank class FIFO is full. A rejected transaction is not
        counted and its callback is never called. Sending after
        :meth:`finalize` raises :class:`TargetServiceError`.
        """
        if self._closed:
            raise TargetServiceError(
                "TargetService is finalized (closed); send refused")
        _require_address(addr)
        if not _is_int(size) or size <= 0:
            raise TargetServiceError(
                f"size must be a positive integer, got {size!r}")
        if isinstance(is_write, bool):
            write = is_write
        elif _is_int(is_write) and is_write in (0, 1):
            write = bool(is_write)
        else:
            raise TargetServiceError(
                f"is_write must be bool or 0/1, got {is_write!r}")
        if callback is not None and not callable(callback):
            raise TargetServiceError(
                "callback must be callable or None")

        channel, bank, row, column = self.decode_address(addr)
        state = self._banks[
            channel * self._config.banks_per_channel + bank]
        queue = state.write_q if write else state.read_q
        depth = (self._config.write_queue_depth if write
                 else self._config.read_queue_depth)
        if len(queue) >= depth:
            self._backpressure_events += 1
            if write:
                self._write_backpressure_events += 1
            else:
                self._read_backpressure_events += 1
            return False

        request = _Request(
            sequence=self._next_sequence,
            addr=addr,
            is_write=write,
            size=size,
            src=src,
            dst=dst,
            callback=callback,
            accepted_tick=self._cycles,
            location=(channel, bank, row, column),
        )
        self._next_sequence += 1
        queue.append(request)
        if write:
            self._accepted_writes += 1
            self._accepted_write_bytes += size
        else:
            self._accepted_reads += 1
            self._accepted_read_bytes += size
        return True

    def tick(self) -> None:
        """Advance one memory clock.

        Free banks start the next FIFO request; services whose end tick is
        the current tick complete and fire their callbacks exactly once.
        """
        self._cycles += 1
        now = self._cycles

        # Start first, complete second: a duration-1 request completes at the
        # end of the tick in which it starts, and a duration-d request
        # occupies exactly d ticks.
        for bank in self._banks:
            if bank.in_service is not None:
                continue
            request = self._select(bank)
            if request is not None:
                self._start(bank, request, now)

        for bank in self._banks:
            request = bank.in_service
            if request is not None and bank.service_end_tick <= now:
                self._complete(bank, request, now)

        self._read_queue_len_sum += sum(
            len(bank.read_q) for bank in self._banks)
        self._write_queue_len_sum += sum(
            len(bank.write_q) for bank in self._banks)

    def get_stats(self) -> dict[str, Any]:
        """Return exact counters, nested under ``memory_system`` as well.

        The native contract reads ``stats["memory_system"]``; the same keys
        are also exposed at the top level for standalone callers. Totals are
        accepted requests (matching the native ledger), not attempts. Queue
        lengths are waiting FIFO entries summed across banks, not the
        requests currently in service. Averages are sampled once per
        completed ``tick()``.
        """
        read_outstanding = self._accepted_reads - self._served_reads
        write_outstanding = self._accepted_writes - self._served_writes
        read_queue_len = sum(len(bank.read_q) for bank in self._banks)
        write_queue_len = sum(len(bank.write_q) for bank in self._banks)
        cycles = self._cycles
        body: dict[str, Any] = {
            "total_num_read_requests": self._accepted_reads,
            "total_num_write_requests": self._accepted_writes,
            "num_read_reqs": self._accepted_reads,
            "num_write_reqs": self._accepted_writes,
            "num_read_reqs_served": self._served_reads,
            "num_write_reqs_served": self._served_writes,
            "num_read_reqs_outstanding": read_outstanding,
            "num_write_reqs_outstanding": write_outstanding,
            "num_write_reqs_coalesced": 0,
            "row_hits": self._row_hits,
            "row_misses": self._row_misses,
            "row_conflicts": self._row_conflicts,
            "avg_read_latency": (
                self._read_latency_sum / self._served_reads
                if self._served_reads else 0.0),
            "avg_write_latency": (
                self._write_latency_sum / self._served_writes
                if self._served_writes else 0.0),
            "read_queue_len": read_queue_len,
            "write_queue_len": write_queue_len,
            "read_queue_len_avg": (
                self._read_queue_len_sum / cycles if cycles else 0.0),
            "write_queue_len_avg": (
                self._write_queue_len_sum / cycles if cycles else 0.0),
            "cycles": cycles,
            "memory_ticks": cycles,
            "accepted_requests": (
                self._accepted_reads + self._accepted_writes),
            "served_requests": self._served_reads + self._served_writes,
            "outstanding_requests": read_outstanding + write_outstanding,
            "backpressure_events": self._backpressure_events,
            "read_backpressure_events": self._read_backpressure_events,
            "write_backpressure_events": self._write_backpressure_events,
            "total_read_bytes": self._accepted_read_bytes,
            "total_write_bytes": self._accepted_write_bytes,
        }
        return {"memory_system": dict(body), **body}

    def finalize(self) -> None:
        """Close the service; refuse new sends.

        Finalization is not a silent drain. If any accepted request remains
        queued or in service, the service is marked closed and
        :class:`TargetServiceError` is raised. ``drain()`` may still be used
        afterwards to complete the outstanding work, then ``finalize()``
        succeeds idempotently.
        """
        self._closed = True
        if self.outstanding:
            raise TargetServiceError(
                "TargetService.finalize refused: "
                f"{self.outstanding} outstanding request(s) remain "
                f"(read={self._accepted_reads - self._served_reads}, "
                f"write={self._accepted_writes - self._served_writes})")

    # ------------------------------------------------------------------
    # Deterministic drain helper
    # ------------------------------------------------------------------
    def drain(self, max_ticks: int | None = None) -> int:
        """Tick until no request is outstanding; return ticks advanced.

        ``max_ticks`` bounds the number of ticks this call may advance. If
        the bound is exhausted while work remains, raise
        :class:`TargetServiceError` and leave the service unchanged apart
        from the ticks already advanced.
        """
        if max_ticks is not None:
            _require_int("max_ticks", max_ticks, 0)
        ticks = 0
        while self.outstanding:
            if max_ticks is not None and ticks >= max_ticks:
                raise TargetServiceError(
                    f"TargetService.drain exhausted max_ticks={max_ticks} "
                    f"with {self.outstanding} outstanding request(s)")
            self.tick()
            ticks += 1
        return ticks

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _select(self, bank: _Bank) -> _Request | None:
        read_q, write_q = bank.read_q, bank.write_q
        if not read_q and not write_q:
            return None
        if not read_q:
            return write_q.popleft()
        if not write_q:
            return read_q.popleft()
        if self._config.arbitration == "FIFO":
            if read_q[0].sequence <= write_q[0].sequence:
                return read_q.popleft()
            return write_q.popleft()
        # ROUND_ROBIN: only a contended bank toggles the preference. The
        # first contention starts with the older head's class, so the first
        # choice never inverts arrival order.
        prefer_write = bank.prefer_write
        if prefer_write is None:
            prefer_write = write_q[0].sequence < read_q[0].sequence
        bank.prefer_write = not prefer_write
        return write_q.popleft() if prefer_write else read_q.popleft()

    def _start(self, bank: _Bank, request: _Request, now: int) -> None:
        config = self._config
        if config.service_cycles is not None:
            base = config.service_cycles
        else:
            # bytes_per_cycle is validated positive; integer ceil is exact.
            base = ((request.size + config.bytes_per_cycle - 1)
                    // config.bytes_per_cycle)

        row = request.location[2]
        if bank.open_row is None:
            self._row_misses += 1
            row_adjust = (config.row_miss_cycles
                          if config.row_miss_cycles is not None else 0)
        elif bank.open_row == row:
            self._row_hits += 1
            row_adjust = (config.row_hit_cycles
                          if config.row_hit_cycles is not None else 0)
        else:
            self._row_conflicts += 1
            row_adjust = (config.row_miss_cycles
                          if config.row_miss_cycles is not None else 0)
        bank.open_row = row

        latency = (config.write_latency_cycles if request.is_write
                   else config.read_latency_cycles)
        duration = base + latency + row_adjust
        bank.in_service = request
        bank.service_end_tick = now + duration - 1

    def _complete(self, bank: _Bank, request: _Request, now: int) -> None:
        if request.completed:
            raise TargetServiceError(
                "internal invariant violated: request completed twice")
        request.completed = True
        bank.in_service = None
        bank.service_end_tick = 0
        latency = now - request.accepted_tick
        if request.is_write:
            self._served_writes += 1
            self._write_latency_sum += latency
        else:
            self._served_reads += 1
            self._read_latency_sum += latency
        if request.callback is not None:
            # Match the native Mem contract: (addr, is_write, size).
            request.callback(request.addr, int(request.is_write), request.size)


# ----------------------------------------------------------------------
# Standalone Ramulator-style trace driver
# ----------------------------------------------------------------------
def _parse_uint(token: str, what: str) -> int:
    try:
        value = int(token, 0)
    except ValueError:
        try:
            value = int(token, 10)
        except ValueError:
            raise TargetServiceError(
                f"{what} is not an integer: {token!r}") from None
    if value < 0:
        raise TargetServiceError(
            f"{what} must be non-negative, got {token!r}")
    return value


def _parse_read_write_trace(
        trace_text: str) -> list[tuple[int, bool, int]]:
    """Parse ``R|W <addr> [addr_vec ...]`` lines into records.

    The first token after the opcode is the flat byte address. Any trailing
    tokens are optional Ramulator address-vector columns and are validated as
    non-negative integers (comma-separated fields are supported), but the
    flat address is authoritative. Blank lines are ignored; every other
    malformed line refuses.
    """
    if not isinstance(trace_text, str):
        raise TargetServiceError(
            "trace_text must be a string, got "
            f"{type(trace_text).__name__}")
    records: list[tuple[int, bool, int]] = []
    for line_no, raw in enumerate(trace_text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise TargetServiceError(
                f"trace line {line_no} does not parse as "
                f"'R|W <addr> [addr_vec]': {line[:80]!r}")
        op = parts[0]
        if op not in ("R", "W"):
            raise TargetServiceError(
                f"trace line {line_no} has unknown opcode {op!r} "
                f"(expected 'R' or 'W'): {line[:80]!r}")
        addr = _parse_uint(parts[1], f"trace line {line_no} address")
        for column in parts[2:]:
            for token in column.split(","):
                if not token:
                    raise TargetServiceError(
                        f"trace line {line_no} has an empty address-vector "
                        f"field: {line[:80]!r}")
                _parse_uint(
                    token, f"trace line {line_no} address-vector field")
        records.append((addr, op == "W", line_no))
    return records


def execute_read_write_trace(
        trace_text: str, *, service: TargetService,
        max_ticks: int | None = None) -> dict[str, Any]:
    """Drive one Ramulator-style ``R|W <addr>`` trace through ``service``.

    Each trace line is one ``service.tx_bytes`` transaction (the Ramulator
    trace is transaction-granular). The helper issues one line per tick,
    retries backpressured lines after advancing, then drains to quiescence.
    It requires a quiescent service at entry and does not call ``finalize``;
    the caller owns lifecycle closure.

    Returns ``{"status": "COMPLETE", "metrics": {...}, "stats": {...}}``.
    Malformed lines, a non-power-of-two transaction size, a ``max_ticks``
    shortfall, or undrained completion refuse with
    :class:`TargetServiceError`.
    """
    if max_ticks is not None:
        _require_int("max_ticks", max_ticks, 0)

    size = getattr(service, "tx_bytes", None)
    if not _is_int(size) or size <= 0 or (size & (size - 1)):
        raise TargetServiceError(
            "trace transaction size must be a positive power of two, got "
            f"{size!r}")

    if getattr(service, "has_outstanding", False):
        raise TargetServiceError(
            "execute_read_write_trace requires a quiescent service; "
            f"{service.outstanding} request(s) are already outstanding")

    records = _parse_read_write_trace(trace_text)

    completed: list[tuple[int, int, int]] = []

    def callback(addr: int, is_write: int, request_size: int) -> None:
        completed.append((addr, int(is_write), request_size))

    ticks = 0

    def advance() -> None:
        nonlocal ticks
        if max_ticks is not None and ticks >= max_ticks:
            raise TargetServiceError(
                "execute_read_write_trace exhausted "
                f"max_ticks={max_ticks} with {service.outstanding} "
                "outstanding request(s)")
        service.tick()
        ticks += 1

    for addr, is_write, _line_no in records:
        while True:
            if service.send(addr, is_write, size, 0, 0, callback):
                break
            advance()
        # One line per memory clock: deterministic issue-rate semantics.
        advance()

    while service.has_outstanding:
        advance()

    if service.has_outstanding:
        raise TargetServiceError(
            "execute_read_write_trace left "
            f"{service.outstanding} outstanding request(s) — refusing "
            "undrained completion")
    if len(completed) != len(records):
        raise TargetServiceError(
            "execute_read_write_trace observed "
            f"{len(completed)} callback(s) for {len(records)} accepted "
            "request(s) — refusing incomplete completion")

    stats = service.get_stats()
    reads = sum(1 for _addr, is_write, _line_no in records if not is_write)
    writes = len(records) - reads
    metrics = {
        "requests": len(records),
        "reads": reads,
        "writes": writes,
        "transaction_bytes": size,
        "bytes": len(records) * size,
        "read_bytes": reads * size,
        "write_bytes": writes * size,
        "ticks": ticks,
        "cycles": service.memory_ticks,
        "max_ticks": max_ticks,
        "callbacks": len(completed),
    }
    return {"status": "COMPLETE", "metrics": metrics, "stats": stats}
