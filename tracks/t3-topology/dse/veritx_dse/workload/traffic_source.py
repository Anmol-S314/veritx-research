"""veritx_dse.workload.traffic_source — one endpoint-level traffic contract.

This module is deliberately self-contained.  It does not lower a workload, it
does not compile a fabric, and it does not run a simulator.  It gives the
three existing traffic front ends one common, honest view:

* collectives / canonical P2P profiles materialise a
  ``PhysicalTrafficArtifact`` and reach BookSim through
  :func:`veritx_dse.backend.booksim_projection.render_trace`;
* raw traces are the five-column ``cyc src cl dst sz`` dialect consumed by
  :func:`veritx_dse.backend.booksim._scan_trace`.

Both become a tuple of :class:`Packet` values plus a :class:`TrafficSourceInfo`
record.  The simulators keep their own inputs and are not rewritten here.

Scope and non-goals
-------------------
* **Endpoint view only.**  ``Packet.src``/``Packet.dst`` are interpreted
  according to ``TrafficSourceInfo.addressing``.  The contract can describe a
  ``RANK`` source, but it does not invent the participant-to-endpoint mapping
  needed before such a source can be compared with an endpoint trace.
* **Single class for raw traces.**  The raw standalone BookSim backend binds
  ``classes=1``, so :class:`RawTraceSource` accepts class index 0 only.
  Multi-class raw input is refused, never collapsed.
* **Metadata stays metadata.**  A class name is carried verbatim; only the
  trace renderer assigns the dense integer indices BookSim consumes.
* **Deterministic.**  Parsing and rendering are pure functions of the bytes
  and the declared class names.

Rationale: docs/decisions/modules/workload.md
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError

ADDRESSING_ENDPOINT = "ENDPOINT"
ADDRESSING_RANK = "RANK"
_ADDRESSING_VALUES = frozenset({ADDRESSING_ENDPOINT, ADDRESSING_RANK})

#: The raw standalone backend binds one class, whose trace index is zero.
_RAW_SINGLE_CLASS = 0

# Decimal integers only: ``int()`` also accepts underscores and surrounding
# whitespace, which the strict five-column dialect does not.
_INT_RE = re.compile(r"-?[0-9]+")

_TRACE_COLUMNS = ("timestamp", "src", "class", "dst", "flits")


class TrafficSourceError(ValueError, SemanticError):
    """Typed refusal for a malformed or unsupported traffic source."""

    code = "TRAFFIC_SOURCE_REFUSED"


def _require_int(name: str, value: object, *, minimum: int) -> int:
    if type(value) is not int:
        raise TrafficSourceError(
            f"{name} must be an int, got {type(value).__name__}: {value!r}")
    if value < minimum:
        raise TrafficSourceError(
            f"{name} must be >= {minimum}, got {value}")
    return value


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TrafficSourceError(
            f"{name} must be a string, got {type(value).__name__}: "
            f"{value!r}")
    if not value.strip():
        raise TrafficSourceError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


@dataclass(frozen=True)
class Packet:
    """One endpoint-level packet.

    ``timestamp`` is a cycle number, ``src``/``dst`` are ids in the source's
    addressing space, and ``flits`` is the packet's serialization cost.
    """

    timestamp: int
    src: int
    dst: int
    traffic_class: str
    flits: int

    def __post_init__(self) -> None:
        _require_int("Packet.timestamp", self.timestamp, minimum=0)
        _require_int("Packet.src", self.src, minimum=0)
        _require_int("Packet.dst", self.dst, minimum=0)
        _require_text("Packet.traffic_class", self.traffic_class)
        _require_int("Packet.flits", self.flits, minimum=1)


@dataclass(frozen=True)
class TrafficSourceInfo:
    """Identity, addressing space and limitations of a traffic source.

    ``identity`` is content-addressed for byte-backed sources.  ``addressing``
    is exactly ``ENDPOINT`` or ``RANK``; a ``RANK`` source still needs an
    explicit participant-to-endpoint mapping before its ids can be used as
    endpoints.  ``class_names`` lists the source's class names.  The default
    trace renderer assigns dense indices over their sorted order; a source
    that already owns a wire encoding (a rendered trace) preserves its
    declared order.
    """

    identity: str
    addressing: str
    limitations: tuple[str, ...]
    class_names: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text("TrafficSourceInfo.identity", self.identity)
        if not isinstance(self.addressing, str) \
                or self.addressing not in _ADDRESSING_VALUES:
            raise TrafficSourceError(
                f"TrafficSourceInfo.addressing must be one of "
                f"{sorted(_ADDRESSING_VALUES)}, got {self.addressing!r}")
        if not isinstance(self.limitations, tuple):
            raise TrafficSourceError(
                "TrafficSourceInfo.limitations must be a tuple of strings, "
                f"got {type(self.limitations).__name__}")
        for index, limitation in enumerate(self.limitations):
            if not isinstance(limitation, str):
                raise TrafficSourceError(
                    f"TrafficSourceInfo.limitations[{index}] must be a "
                    f"string, got {type(limitation).__name__}")
        if not isinstance(self.class_names, tuple):
            raise TrafficSourceError(
                "TrafficSourceInfo.class_names must be a tuple of strings, "
                f"got {type(self.class_names).__name__}")
        for index, class_name in enumerate(self.class_names):
            _require_text(
                f"TrafficSourceInfo.class_names[{index}]", class_name)
        if len(set(self.class_names)) != len(self.class_names):
            raise TrafficSourceError(
                "TrafficSourceInfo.class_names must be unique, got "
                f"{self.class_names!r}")


class TrafficSource(ABC):
    """A source of endpoint-level packets plus its declared metadata.

    Subclasses implement :meth:`info` and :meth:`packets`.  The default
    :meth:`to_trace` renders the BookSim whitespace dialect and the default
    :meth:`scan` summarizes the validated packet view.
    """

    @abstractmethod
    def info(self) -> TrafficSourceInfo:
        """The source's stable identity and semantic limits."""
        raise NotImplementedError

    @abstractmethod
    def packets(self, *, endpoint_count: int,
                max_packet_flits: int) -> tuple[Packet, ...]:
        """Validate the endpoint universe and return the packet tuple."""
        raise NotImplementedError

    def _class_order(self) -> tuple[str, ...]:
        """The trace class order; sorted by contract unless a source says
        otherwise (a rendered trace already owns its wire order)."""
        return tuple(sorted(self.info().class_names))

    def to_trace(self, *, endpoint_count: int,
                 max_packet_flits: int) -> bytes:
        """Render the packets as ``cyc src cl dst sz`` lines.

        Class indices are dense over ``_class_order()`` (sorted class names
        by default).  Addresses are emitted verbatim: when
        ``info().addressing`` is ``RANK`` the caller must first map ranks to
        endpoints; this contract does not invent that mapping.
        """
        info = self.info()
        class_index = {name: index
                       for index, name in enumerate(self._class_order())}
        lines: list[str] = []
        for packet in self.packets(
                endpoint_count=endpoint_count,
                max_packet_flits=max_packet_flits):
            try:
                index = class_index[packet.traffic_class]
            except KeyError:
                raise TrafficSourceError(
                    f"traffic class {packet.traffic_class!r} is not declared "
                    f"by {info.identity!r}; declared classes: "
                    f"{sorted(info.class_names)}") from None
            lines.append(
                f"{packet.timestamp} {packet.src} {index} "
                f"{packet.dst} {packet.flits}\n")
        return "".join(lines).encode("ascii")

    def scan(self, *, endpoint_count: int,
             max_packet_flits: int) -> dict[str, object]:
        """Summarize the validated packet view.

        ``endpoints`` is the number of distinct ``src``/``dst`` ids in the
        source's addressing space.  For a ``RANK`` source these are ranks, not
        endpoints; map them before comparing with an endpoint trace.
        """
        packets = self.packets(
            endpoint_count=endpoint_count,
            max_packet_flits=max_packet_flits)
        return {
            "packets": len(packets),
            "max_timestamp": max(
                (packet.timestamp for packet in packets), default=0),
            "endpoints": len(
                {packet.src for packet in packets}
                | {packet.dst for packet in packets}),
            "classes": tuple(sorted(
                {packet.traffic_class for packet in packets})),
        }


@dataclass(frozen=True)
class _TraceRow:
    """One validated trace row, before class-name mapping."""

    line_no: int
    timestamp: int
    src: int
    cls: int
    dst: int
    flits: int


def _parse_trace(trace: bytes) -> tuple[_TraceRow, ...]:
    """Strictly parse the five-column whitespace trace dialect."""
    if not isinstance(trace, bytes):
        raise TrafficSourceError(
            f"trace must be bytes, got {type(trace).__name__}")
    try:
        text = trace.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrafficSourceError(f"trace is not UTF-8: {exc}") from exc

    rows: list[_TraceRow] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in ("#", "%"):
            continue
        parts = line.split()
        if len(parts) != len(_TRACE_COLUMNS):
            raise TrafficSourceError(
                f"trace line {line_no}: expected exactly "
                f"{len(_TRACE_COLUMNS)} whitespace columns "
                f"(cyc src cl dst sz), got {len(parts)}: {line!r}")
        values: list[int] = []
        for column, part in zip(_TRACE_COLUMNS, parts):
            if _INT_RE.fullmatch(part) is None:
                raise TrafficSourceError(
                    f"trace line {line_no}: {column} field {part!r} is not "
                    "an integer")
            values.append(int(part))
        timestamp, src, cls, dst, flits = values
        if timestamp < 0:
            raise TrafficSourceError(
                f"trace line {line_no}: negative timestamp {timestamp}")
        if src < 0:
            raise TrafficSourceError(
                f"trace line {line_no}: negative src {src}")
        if dst < 0:
            raise TrafficSourceError(
                f"trace line {line_no}: negative dst {dst}")
        if flits < 1:
            raise TrafficSourceError(
                f"trace line {line_no}: flits must be >= 1, got {flits}")
        rows.append(_TraceRow(
            line_no=line_no, timestamp=timestamp, src=src, cls=cls, dst=dst,
            flits=flits))
    if not rows:
        raise TrafficSourceError("trace has no parseable packets")
    return tuple(rows)


def _validate_limits(endpoint_count: int, max_packet_flits: int) -> None:
    _require_int("endpoint_count", endpoint_count, minimum=1)
    _require_int("max_packet_flits", max_packet_flits, minimum=1)


def _validate_rows(rows: tuple[_TraceRow, ...], *, endpoint_count: int,
                   max_packet_flits: int) -> None:
    _validate_limits(endpoint_count, max_packet_flits)
    for row in rows:
        if not (0 <= row.src < endpoint_count) \
                or not (0 <= row.dst < endpoint_count):
            raise TrafficSourceError(
                f"trace line {row.line_no}: endpoint outside "
                f"[0, {endpoint_count}): src={row.src} dst={row.dst}")
        if row.flits > max_packet_flits:
            raise TrafficSourceError(
                f"trace line {row.line_no}: flits {row.flits} exceeds "
                f"max_packet_flits {max_packet_flits}")


class RawTraceSource(TrafficSource):
    """A raw ``cyc src cl dst sz`` trace, single-class by construction.

    The raw standalone backend binds ``classes=1``, so the class column must
    be 0.  The identity is the SHA-256 of the exact input bytes.
    """

    def __init__(self, trace: bytes, *, traffic_class: str = "trace"):
        _require_text("RawTraceSource.traffic_class", traffic_class)
        rows = _parse_trace(trace)
        for row in rows:
            if row.cls != _RAW_SINGLE_CLASS:
                raise TrafficSourceError(
                    f"raw trace line {row.line_no}: class index {row.cls} is "
                    "not 0; the raw standalone BookSim backend binds "
                    "classes=1, so multi-class raw traces are not "
                    "representable (single-class only)")
        self._traffic_class = traffic_class
        self._rows = rows
        self._info = TrafficSourceInfo(
            identity="sha256:" + hashlib.sha256(trace).hexdigest(),
            addressing=ADDRESSING_ENDPOINT,
            limitations=(
                "single-class: the raw standalone BookSim backend binds "
                "classes=1, so only class index 0 is accepted",
                "raw bytes are the sole authority; no logical message or "
                "operation provenance is available",
            ),
            class_names=(traffic_class,),
        )

    def info(self) -> TrafficSourceInfo:
        return self._info

    def packets(self, *, endpoint_count: int,
                max_packet_flits: int) -> tuple[Packet, ...]:
        _validate_rows(self._rows, endpoint_count=endpoint_count,
                       max_packet_flits=max_packet_flits)
        return tuple(
            Packet(timestamp=row.timestamp, src=row.src, dst=row.dst,
                   traffic_class=self._traffic_class, flits=row.flits)
            for row in self._rows)


class RenderedTraceSource(TrafficSource):
    """An already-rendered trace with an explicit dense class map.

    This adapts a canonical ``render_trace`` result (dense class indices over
    sorted class names) into the common packet view.  The declared class order
    is preserved when rendering, so an input trace round-trips byte-for-byte
    when it uses the canonical five-column formatting.
    """

    def __init__(self, trace: bytes, *, class_names: tuple[str, ...],
                 identity: str, limitations: tuple[str, ...] = ()):
        if not isinstance(class_names, tuple) or not class_names:
            raise TrafficSourceError(
                "RenderedTraceSource.class_names must be a non-empty tuple "
                f"of strings, got {class_names!r}")
        for index, class_name in enumerate(class_names):
            _require_text(f"RenderedTraceSource.class_names[{index}]",
                          class_name)
        if len(set(class_names)) != len(class_names):
            raise TrafficSourceError(
                "RenderedTraceSource.class_names must be unique, got "
                f"{class_names!r}")
        rows = _parse_trace(trace)
        for row in rows:
            if not 0 <= row.cls < len(class_names):
                raise TrafficSourceError(
                    f"trace line {row.line_no}: class index {row.cls} is "
                    f"outside the declared class map [0, {len(class_names)}) "
                    f"for {class_names!r}")
        self._class_names = class_names
        self._rows = rows
        self._info = TrafficSourceInfo(
            identity=identity,
            addressing=ADDRESSING_ENDPOINT,
            limitations=limitations,
            class_names=class_names,
        )

    def info(self) -> TrafficSourceInfo:
        return self._info

    def _class_order(self) -> tuple[str, ...]:
        # A rendered trace already owns its wire class order.  Canonical
        # render_trace emits sorted names, so this equals the contract's
        # default order there; for other inputs it preserves the indices.
        return self._class_names

    def packets(self, *, endpoint_count: int,
                max_packet_flits: int) -> tuple[Packet, ...]:
        _validate_rows(self._rows, endpoint_count=endpoint_count,
                       max_packet_flits=max_packet_flits)
        return tuple(
            Packet(timestamp=row.timestamp, src=row.src, dst=row.dst,
                   traffic_class=self._class_names[row.cls],
                   flits=row.flits)
            for row in self._rows)


class CanonicalTraceSource(RenderedTraceSource):
    """Adapter from a canonical ``PhysicalTrafficArtifact`` trace render.

    The heavy backend module is imported lazily so importing this contract
    stays cheap and does not pull the projection in.
    """

    @classmethod
    def from_physical_traffic(
            cls, physical_traffic: Any,
            terminal_map: Any | None = None) -> "CanonicalTraceSource":
        """Wrap ``render_trace(physical_traffic, terminal_map)``.

        A ``terminal_map`` remaps canonical endpoints to the simulator's node
        ids; callers then pass that rendered node count as ``endpoint_count``.
        """
        from veritx_dse.backend import booksim_projection

        rendered = booksim_projection.render_trace(
            physical_traffic, terminal_map)
        class_names = booksim_projection.trace_class_map(physical_traffic)
        return cls(
            rendered,
            class_names=class_names,
            identity="sha256:" + hashlib.sha256(rendered).hexdigest(),
            limitations=(
                "canonical renderer assigns dense 0..N-1 timestamps; "
                "class indices are dense over sorted class names",
            ),
        )


__all__ = [
    "ADDRESSING_ENDPOINT",
    "ADDRESSING_RANK",
    "CanonicalTraceSource",
    "Packet",
    "RawTraceSource",
    "RenderedTraceSource",
    "TrafficSource",
    "TrafficSourceError",
    "TrafficSourceInfo",
]
