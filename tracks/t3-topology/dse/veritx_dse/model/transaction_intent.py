"""veritx_dse.model.transaction_intent — canonical agent transaction intent.

Rationale: docs/decisions/modules/model.md

Where this layer sits (program §9)::

    workload operation
        -> transaction
        -> agent issue policy      <-- THIS MODULE
        -> packetization
        -> flits
        -> VC/router flow control  <-- BookSim owns these
        -> BookSim

The critical distinction this module exists to keep honest:

    ``max_outstanding`` is an AGENT TRANSACTION CREDIT — a bound on how many
    transactions one agent may have in flight at once.

    It is NOT a BookSim router buffer credit, which is a per-VC flit slot in
    the network's flow-control state.

Those two are different objects at different pipeline stages with different
owners. Nothing in this module names, aliases, threads or converts between
them, and nothing here emits BookSim config, flits, timing or any other
network knob. This is issue-eligibility intent only.

Semantic boundary: the ordering, splitting and outstanding semantics below are
CANONICAL and protocol-neutral. They are not "AXI ordering" — mapping them onto
AXI/CHI/TileLink is a later adapter's job, and until such an adapter proves a
mapping this module makes no protocol claim.

Identity: this is an intent submodel. Its ``to_dict()`` is what a schema root
(e.g. a ``CompileRequestV5``) composes into its design identity; this module
does not hash itself, because a fragment's identity is not a design's identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.errors import SemanticError

TRANSACTION_INTENT_SCHEMA_VERSION = 1


class TransactionIntentError(ValueError, SemanticError):
    """The declared transaction intent is invalid or unsupported — fail closed."""


# --------------------------------------------------------------------------
# local typed helpers
#
# veritx_dse.model.compile_model._as_int/_as_str raise a bare ValueError.
# This module needs every refusal to surface as TransactionIntentError so a
# caller can catch the module's own boundary, so the helpers are re-declared
# in the style of model/address_decode.py rather than imported.
# --------------------------------------------------------------------------

def _as_int(name: str, value: Any, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise TransactionIntentError(
            f"{name} must be an exact int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise TransactionIntentError(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise TransactionIntentError(
            f"{name} must be a bool, got {type(value).__name__} {value!r}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise TransactionIntentError(
            f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise TransactionIntentError(f"{name} must be non-empty")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise TransactionIntentError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise TransactionIntentError(
            f"{where} has unknown fields: {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise TransactionIntentError(f"{where} is missing required field {key!r}")
    return d[key]


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Any:
    if not isinstance(value, str):
        raise TransactionIntentError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise TransactionIntentError(
            f"unknown {name} {value!r}; known: "
            f"{[m.value for m in enum_cls]}") from None


def _optional_str(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _as_str(name, value, allow_empty=False)


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------

class OrderingMode(Enum):
    """Canonical ordering strength for one ordering domain.

    Deliberately protocol-neutral: this is not "AXI ordering".
    """

    STRONG = "STRONG"
    RELAXED = "RELAXED"
    CUSTOM = "CUSTOM"


class TransactionKind(Enum):
    """Which flavour of transaction an outstanding credit is spent on.

    Local to the issue-policy concern (``OutstandingTracker``). It is not a
    network traffic class and must never be confused with one.
    """

    READ = "READ"
    WRITE = "WRITE"


# --------------------------------------------------------------------------
# outstanding limit
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OutstandingLimit:
    """AGENT TRANSACTION CREDIT: live-transaction bounds at one agent.

    Each field is a bound on concurrently LIVE transactions of that kind.
    ``None`` means *not constrained by design intent* — which is exactly how
    schema v4 behaved, so a design that declares no limit migrates without a
    change in meaning. ``None`` is never spelled ``0``: a limit of 0 would
    mean "never issue", which is a different statement.

    This is NOT a BookSim router buffer credit (a per-VC flit slot). The two
    live at different stages of the pipeline and are never interchanged here.
    """

    reads: int | None = None
    writes: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        for name in ("reads", "writes", "total"):
            _as_optional_positive(f"OutstandingLimit.{name}",
                                  getattr(self, name))
        if self.reads is None and self.writes is None and self.total is None:
            raise TransactionIntentError(
                "OutstandingLimit must constrain at least one of reads, "
                "writes or total: an all-None limit is vacuous. To declare "
                "no limit at all, omit the OutstandingLimit entirely "
                "(outstanding=None), which is what a schema-v4 design "
                "meant — never an empty limit object and never 0.")
        if self.total is not None:
            for name in ("reads", "writes"):
                value = getattr(self, name)
                if value is not None and self.total < value:
                    raise TransactionIntentError(
                        f"OutstandingLimit.total ({self.total}) must be "
                        f">= {name} ({value}): total bounds reads and "
                        f"writes together, so a total below a per-kind bound "
                        f"can never be satisfied. Raise total to >= {value} "
                        f"or lower {name}.")

    def to_dict(self) -> dict[str, Any]:
        return {"reads": self.reads, "writes": self.writes,
                "total": self.total}

    @classmethod
    def from_dict(cls, d: Any) -> "OutstandingLimit":
        _strict_keys(d, frozenset({"reads", "writes", "total"}),
                     "outstanding limit")
        return cls(reads=_as_optional_positive("outstanding limit reads",
                                              d.get("reads")),
                   writes=_as_optional_positive("outstanding limit writes",
                                                d.get("writes")),
                   total=_as_optional_positive("outstanding limit total",
                                               d.get("total")))


def _as_optional_positive(name: str, value: Any) -> int | None:
    if value is None:
        return None
    return _as_int(name, value, minimum=1)


# --------------------------------------------------------------------------
# ordering
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderingPolicy:
    """Canonical ordering semantics for one ordering domain.

    ``STRONG``   no later operation in the ordering domain issues before an
                 earlier one completes.
    ``RELAXED``  independent transactions may progress concurrently.
    ``CUSTOM``   an explicit hazard-dependency graph decides eligibility.

    Hazards are modelled separately (RAW/WAR/WAW) so a CUSTOM policy can be
    stated precisely, and so ``WRITE X`` + ``READ X`` under RAW enforcement
    provably serialises on completion rather than on issue.
    """

    mode: OrderingMode
    enforce_raw: bool = False
    enforce_war: bool = False
    enforce_waw: bool = False
    ordering_domain: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OrderingMode):
            raise TransactionIntentError(
                f"OrderingPolicy.mode must be an OrderingMode, got "
                f"{type(self.mode).__name__}")
        _as_bool("OrderingPolicy.enforce_raw", self.enforce_raw)
        _as_bool("OrderingPolicy.enforce_war", self.enforce_war)
        _as_bool("OrderingPolicy.enforce_waw", self.enforce_waw)
        _optional_str("OrderingPolicy.ordering_domain", self.ordering_domain)

        hazards = (self.enforce_raw, self.enforce_war, self.enforce_waw)
        if self.mode is OrderingMode.STRONG and not all(hazards):
            raise TransactionIntentError(
                "OrderingPolicy mode STRONG with a disabled hazard: STRONG "
                "means no later operation in the ordering domain issues "
                "before an earlier one completes, so RAW, WAR and WAW must "
                "all be enforced — a disabled hazard makes it not strong. "
                "Use mode=RELAXED for concurrent progress, or mode=CUSTOM "
                "with exactly the hazards you intend to enforce.")
        if self.mode is OrderingMode.CUSTOM and not any(hazards):
            raise TransactionIntentError(
                "OrderingPolicy mode CUSTOM with no hazard enabled: a "
                "CUSTOM dependency graph that enforces neither RAW, WAR nor "
                "WAW constrains nothing. Enable at least one hazard, or use "
                "mode=RELAXED to state that independent transactions may "
                "progress freely.")

    @property
    def enforced_hazards(self) -> tuple[str, ...]:
        return tuple(name for name, on in (
            ("RAW", self.enforce_raw), ("WAR", self.enforce_war),
            ("WAW", self.enforce_waw)) if on)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "enforce_raw": self.enforce_raw,
                "enforce_war": self.enforce_war, "enforce_waw": self.enforce_waw,
                "ordering_domain": self.ordering_domain}

    @classmethod
    def from_dict(cls, d: Any) -> "OrderingPolicy":
        _strict_keys(d, frozenset({"mode", "enforce_raw", "enforce_war",
                                   "enforce_waw", "ordering_domain"}),
                     "ordering policy")
        return cls(
            mode=_enum("ordering mode", OrderingMode,
                       _need(d, "mode", "ordering policy")),
            enforce_raw=_as_bool("ordering policy enforce_raw",
                                 d.get("enforce_raw", False)),
            enforce_war=_as_bool("ordering policy enforce_war",
                                 d.get("enforce_war", False)),
            enforce_waw=_as_bool("ordering policy enforce_waw",
                                 d.get("enforce_waw", False)),
            ordering_domain=_optional_str("ordering policy ordering_domain",
                                          d.get("ordering_domain")),
        )


# --------------------------------------------------------------------------
# splitting
# --------------------------------------------------------------------------

def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


@dataclass(frozen=True)
class SplittingPolicy:
    """Payload splitting: how one operation materialises as child transactions.

    ``boundary_bytes`` is the child size. Legal values are powers of two that
    evenly divide ``max_payload_bytes`` (e.g. 64 B or 128 B under a 512 B
    payload), so every split is exact and no ragged remainder child is ever
    invented. A "custom" value that is not a power of two, or that does not
    divide the payload, refuses.
    """

    max_payload_bytes: int
    boundary_bytes: int

    def __post_init__(self) -> None:
        _as_int("SplittingPolicy.max_payload_bytes", self.max_payload_bytes,
                minimum=1)
        _as_int("SplittingPolicy.boundary_bytes", self.boundary_bytes,
                minimum=1)
        if not _is_power_of_two(self.boundary_bytes):
            raise TransactionIntentError(
                f"SplittingPolicy.boundary_bytes "
                f"({self.boundary_bytes}) must be a power of two: a split "
                "boundary that is not a power of two cannot tile a payload "
                "into equal, aligned child transactions. Choose a power of "
                "two such as 64, 128 or 256.")
        if self.max_payload_bytes % self.boundary_bytes != 0:
            raise TransactionIntentError(
                f"SplittingPolicy.boundary_bytes ({self.boundary_bytes}) "
                f"must evenly divide max_payload_bytes "
                f"({self.max_payload_bytes}): "
                f"{self.max_payload_bytes} % {self.boundary_bytes} = "
                f"{self.max_payload_bytes % self.boundary_bytes}. An uneven "
                "split would need a ragged remainder child, which this "
                "policy refuses rather than inventing. Choose a boundary "
                f"that divides {self.max_payload_bytes} (e.g. 64 or 128 "
                "under a 512-byte payload).")
        if self.boundary_bytes > self.max_payload_bytes:
            # Unreachable when the modulus law above holds (a boundary larger
            # than the payload can only divide it when it exceeds it), but
            # kept as an explicit statement of the intended ordering.
            raise TransactionIntentError(
                f"SplittingPolicy.boundary_bytes ({self.boundary_bytes}) "
                f"must be <= max_payload_bytes "
                f"({self.max_payload_bytes}).")

    @property
    def child_count_per_max_payload(self) -> int:
        return self.max_payload_bytes // self.boundary_bytes

    def to_dict(self) -> dict[str, Any]:
        return {"max_payload_bytes": self.max_payload_bytes,
                "boundary_bytes": self.boundary_bytes}

    @classmethod
    def from_dict(cls, d: Any) -> "SplittingPolicy":
        _strict_keys(d, frozenset({"max_payload_bytes", "boundary_bytes"}),
                     "splitting policy")
        return cls(
            max_payload_bytes=_as_int(
                "splitting policy max_payload_bytes",
                _need(d, "max_payload_bytes", "splitting policy"), minimum=1),
            boundary_bytes=_as_int(
                "splitting policy boundary_bytes",
                _need(d, "boundary_bytes", "splitting policy"), minimum=1),
        )


@dataclass(frozen=True)
class ChildTransaction:
    """One materialised child of a split operation.

    Ranges are half-open: ``[address_start, address_end)``.
    """

    sequence: int
    address_start: int
    address_end: int
    byte_length: int
    parent_id: str
    ordering_domain: str | None
    traffic_class: str
    is_last: bool

    def __post_init__(self) -> None:
        _as_int("ChildTransaction.sequence", self.sequence, minimum=0)
        _as_int("ChildTransaction.address_start", self.address_start, minimum=0)
        _as_int("ChildTransaction.address_end", self.address_end, minimum=1)
        _as_int("ChildTransaction.byte_length", self.byte_length, minimum=1)
        _as_bool("ChildTransaction.is_last", self.is_last)
        _as_str("ChildTransaction.parent_id", self.parent_id, allow_empty=False)
        _as_str("ChildTransaction.traffic_class", self.traffic_class,
                allow_empty=False)
        _optional_str("ChildTransaction.ordering_domain",
                      self.ordering_domain)
        if self.address_end <= self.address_start:
            raise TransactionIntentError(
                f"ChildTransaction {self.parent_id}#{self.sequence}: "
                f"address_end ({self.address_end}) must be strictly greater "
                f"than address_start ({self.address_start}); ranges are "
                "half-open [start, end).")
        if self.byte_length != self.address_end - self.address_start:
            raise TransactionIntentError(
                f"ChildTransaction {self.parent_id}#{self.sequence}: "
                f"byte_length ({self.byte_length}) must equal "
                f"address_end - address_start "
                f"({self.address_end} - {self.address_start} = "
                f"{self.address_end - self.address_start}).")

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "address_start": self.address_start,
                "address_end": self.address_end,
                "byte_length": self.byte_length, "parent_id": self.parent_id,
                "ordering_domain": self.ordering_domain,
                "traffic_class": self.traffic_class, "is_last": self.is_last}

    @classmethod
    def from_dict(cls, d: Any) -> "ChildTransaction":
        _strict_keys(d, frozenset({"sequence", "address_start", "address_end",
                                   "byte_length", "parent_id",
                                   "ordering_domain", "traffic_class",
                                   "is_last"}), "child transaction")
        return cls(
            sequence=_need(d, "sequence", "child transaction"),
            address_start=_need(d, "address_start", "child transaction"),
            address_end=_need(d, "address_end", "child transaction"),
            byte_length=_need(d, "byte_length", "child transaction"),
            parent_id=_need(d, "parent_id", "child transaction"),
            ordering_domain=_optional_str(
                "child transaction ordering_domain",
                d.get("ordering_domain")),
            traffic_class=_need(d, "traffic_class", "child transaction"),
            is_last=_need(d, "is_last", "child transaction"),
        )


def split_transactions(*, parent_id: str, address_base: int, payload_bytes: int,
                       splitting: SplittingPolicy, ordering_domain: str | None,
                       traffic_class: str) -> tuple[ChildTransaction, ...]:
    """Materialise one operation into ``payload / boundary`` child transactions.

    This is the whole point of ``SplittingPolicy``: a declared split must
    PRODUCE children, not merely record that splitting is enabled. Each child
    carries parent identity, a 0-based sequence, an exclusive ``address_end``,
    the ordering domain and the traffic class, so completion accounting and
    packetisation downstream can be attributed.

    Invariants (all asserted by the test suite):
      * conservation: ``sum(c.byte_length) == payload_bytes``
      * contiguity:   ``children[i].address_end == children[i+1].address_start``
      * ``children[0].address_start == address_base``
      * ``children[-1].address_end == address_base + payload_bytes``
      * every child carries ``parent_id`` and ``ordering_domain``
    """
    if not isinstance(splitting, SplittingPolicy):
        raise TransactionIntentError(
            f"splitting must be a SplittingPolicy, got "
            f"{type(splitting).__name__}")
    _as_str("split_transactions parent_id", parent_id, allow_empty=False)
    _as_str("split_transactions traffic_class", traffic_class, allow_empty=False)
    _optional_str("split_transactions ordering_domain", ordering_domain)
    _as_int("split_transactions address_base", address_base, minimum=0)
    _as_int("split_transactions payload_bytes", payload_bytes, minimum=1)

    if payload_bytes > splitting.max_payload_bytes:
        raise TransactionIntentError(
            f"payload_bytes ({payload_bytes}) exceeds "
            f"SplittingPolicy.max_payload_bytes "
            f"({splitting.max_payload_bytes}): the policy states the largest "
            "operation it may carry, so a larger payload is refused rather "
            "than silently split into more, smaller children. Raise "
            "max_payload_bytes or declare a smaller operation.")
    if payload_bytes % splitting.boundary_bytes != 0:
        raise TransactionIntentError(
            f"payload_bytes ({payload_bytes}) must be a multiple of "
            f"SplittingPolicy.boundary_bytes "
            f"({splitting.boundary_bytes}): "
            f"{payload_bytes} % {splitting.boundary_bytes} = "
            f"{payload_bytes % splitting.boundary_bytes}. An uneven split "
            "would need a ragged remainder child, which is refused rather "
            "than invented. Choose a payload that divides evenly.")

    count = payload_bytes // splitting.boundary_bytes
    children: list[ChildTransaction] = []
    for index in range(count):
        start = address_base + index * splitting.boundary_bytes
        end = start + splitting.boundary_bytes
        children.append(ChildTransaction(
            sequence=index,
            address_start=start,
            address_end=end,
            byte_length=splitting.boundary_bytes,
            parent_id=parent_id,
            ordering_domain=ordering_domain,
            traffic_class=traffic_class,
            is_last=(index == count - 1),
        ))

    # Invariants are re-derived here rather than trusted from the loop, so a
    # future edit cannot silently violate them.
    if sum(c.byte_length for c in children) != payload_bytes:
        raise TransactionIntentError(
            f"split conservation violated for parent {parent_id!r}: children "
            f"total {sum(c.byte_length for c in children)} bytes, payload was "
            f"{payload_bytes} bytes.")
    for left, right in zip(children, children[1:]):
        if left.address_end != right.address_start:
            raise TransactionIntentError(
                f"split contiguity violated for parent {parent_id!r}: child "
                f"#{left.sequence} ends at {left.address_end} but child "
                f"#{right.sequence} starts at {right.address_start}.")
    if children[0].address_start != address_base:
        raise TransactionIntentError(
            f"split base violated for parent {parent_id!r}: first child "
            f"starts at {children[0].address_start}, expected "
            f"{address_base}.")
    if children[-1].address_end != address_base + payload_bytes:
        raise TransactionIntentError(
            f"split end violated for parent {parent_id!r}: last child ends "
            f"at {children[-1].address_end}, expected "
            f"{address_base + payload_bytes}.")
    return tuple(children)


# --------------------------------------------------------------------------
# reordering + the composed policy
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReorderingPolicy:
    """Whether an agent may let independent transactions leave in a new order.

    ``max_window`` bounds how many already-issued transactions may be held
    out of program order at once. Disabling reordering with a non-zero window
    states two contradicting things, so it refuses.
    """

    enabled: bool
    max_window: int = 0

    def __post_init__(self) -> None:
        _as_bool("ReorderingPolicy.enabled", self.enabled)
        _as_int("ReorderingPolicy.max_window", self.max_window, minimum=0)
        if self.enabled and self.max_window < 1:
            raise TransactionIntentError(
                "ReorderingPolicy enabled with max_window "
                f"({self.max_window}): a reorder window of 0 permits no "
                "transaction to leave out of order, so reordering would be "
                "inert. Set max_window >= 1, or set enabled=False to declare "
                "that reordering is off.")
        if not self.enabled and self.max_window != 0:
            raise TransactionIntentError(
                f"ReorderingPolicy disabled with max_window "
                f"({self.max_window}): the two fields disagree — a non-zero "
                "window describes reordering that the disabled flag then "
                "forbids. Set max_window to 0, or set enabled=True with a "
                "window >= 1.")

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "max_window": self.max_window}

    @classmethod
    def from_dict(cls, d: Any) -> "ReorderingPolicy":
        _strict_keys(d, frozenset({"enabled", "max_window"}),
                     "reordering policy")
        return cls(
            enabled=_need(d, "enabled", "reordering policy"),
            max_window=d.get("max_window", 0),
        )


@dataclass(frozen=True)
class TransactionPolicy:
    """One agent's complete transaction policy.

    Every component is optional. All-absent is the explicit NEUTRAL value and
    is provably equivalent to what schema v4 did (no outstanding bound, no
    declared ordering, no split, no reorder window), which is what lets a
    v4 design migrate to v5 without its meaning changing. Omitting a component
    never becomes a numeric ``0`` or a fabricated default.
    """

    outstanding: OutstandingLimit | None = None
    ordering: OrderingPolicy | None = None
    splitting: SplittingPolicy | None = None
    reordering: ReorderingPolicy | None = None

    def __post_init__(self) -> None:
        for name, cls in (("outstanding", OutstandingLimit),
                          ("ordering", OrderingPolicy),
                          ("splitting", SplittingPolicy),
                          ("reordering", ReorderingPolicy)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, cls):
                raise TransactionIntentError(
                    f"TransactionPolicy.{name} must be a {cls.__name__} or "
                    f"None, got {type(value).__name__}")

    @property
    def is_neutral(self) -> bool:
        """True when this policy constrains nothing (the v4-equivalent state)."""
        return (self.outstanding is None and self.ordering is None
                and self.splitting is None and self.reordering is None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outstanding": self.outstanding.to_dict()
            if self.outstanding else None,
            "ordering": self.ordering.to_dict() if self.ordering else None,
            "splitting": self.splitting.to_dict() if self.splitting else None,
            "reordering": self.reordering.to_dict()
            if self.reordering else None,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "TransactionPolicy":
        _strict_keys(d, frozenset({"outstanding", "ordering", "splitting",
                                   "reordering"}), "transaction policy")
        outstanding = d.get("outstanding")
        ordering = d.get("ordering")
        splitting = d.get("splitting")
        reordering = d.get("reordering")
        return cls(
            outstanding=(OutstandingLimit.from_dict(outstanding)
                         if outstanding is not None else None),
            ordering=(OrderingPolicy.from_dict(ordering)
                      if ordering is not None else None),
            splitting=(SplittingPolicy.from_dict(splitting)
                       if splitting is not None else None),
            reordering=(ReorderingPolicy.from_dict(reordering)
                        if reordering is not None else None),
        )


# --------------------------------------------------------------------------
# outstanding tracker — the Q1 micro-oracle that proves a limit is real
# --------------------------------------------------------------------------

class OutstandingTracker:
    """Deterministic live-transaction counter proving ``max_outstanding`` binds.

    This is a Q1 mathematical micro-oracle, NOT a simulator: it carries no
    notion of time, no flits, no network and no BookSim state. It answers one
    question — may an operation issue right now — and nothing else.

    It spends AGENT TRANSACTION CREDITS. It never touches router buffer
    credits (per-VC flit slots), which belong to the network's own
    flow-control state and are a different pipeline stage entirely.

    Deliberately mutable and deliberately not a frozen dataclass: its whole
    purpose is to hold changing counts.
    """

    __slots__ = ("_limit", "_live_reads", "_live_writes", "_live_total",
                 "_blocked_attempts")

    def __init__(self, limit: OutstandingLimit) -> None:
        if not isinstance(limit, OutstandingLimit):
            raise TransactionIntentError(
                f"limit must be an OutstandingLimit, got "
                f"{type(limit).__name__}")
        self._limit = limit
        self._live_reads = 0
        self._live_writes = 0
        self._live_total = 0
        self._blocked_attempts = 0

    @property
    def limit(self) -> OutstandingLimit:
        return self._limit

    @property
    def live_reads(self) -> int:
        return self._live_reads

    @property
    def live_writes(self) -> int:
        return self._live_writes

    @property
    def live_total(self) -> int:
        return self._live_total

    @property
    def blocked_attempts(self) -> int:
        """How many ``try_issue`` calls were refused for lack of a credit."""
        return self._blocked_attempts

    def _as_kind(self, kind: TransactionKind) -> TransactionKind:
        if not isinstance(kind, TransactionKind):
            raise TransactionIntentError(
                f"kind must be a TransactionKind, got "
                f"{type(kind).__name__}")
        return kind

    def _at_limit(self, kind: TransactionKind) -> bool:
        limit = self._limit
        if kind is TransactionKind.READ:
            if limit.reads is not None and self._live_reads >= limit.reads:
                return True
        else:
            if limit.writes is not None and self._live_writes >= limit.writes:
                return True
        if limit.total is not None and self._live_total >= limit.total:
            return True
        return False

    def try_issue(self, kind: TransactionKind) -> bool:
        """Attempt to issue one transaction. ``False`` means BLOCKED by credit.

        A refused issue leaves every count unchanged — a blocked operation is
        not partially accounted for.
        """
        self._as_kind(kind)
        if self._at_limit(kind):
            self._blocked_attempts += 1
            return False
        if kind is TransactionKind.READ:
            self._live_reads += 1
        else:
            self._live_writes += 1
        self._live_total += 1
        return True

    def complete(self, kind: TransactionKind) -> None:
        """Release one live credit. Refuses to release a credit never spent."""
        self._as_kind(kind)
        if kind is TransactionKind.READ:
            if self._live_reads < 1:
                raise TransactionIntentError(
                    "complete(READ) refused: no live read to release "
                    f"(live_reads={self._live_reads}). Releasing a credit "
                    "that was never issued would let the tracker drift below "
                    "its real occupancy.")
            self._live_reads -= 1
        else:
            if self._live_writes < 1:
                raise TransactionIntentError(
                    "complete(WRITE) refused: no live write to release "
                    f"(live_writes={self._live_writes}). Releasing a credit "
                    "that was never issued would let the tracker drift below "
                    "its real occupancy.")
            self._live_writes -= 1
        self._live_total -= 1
        if self._live_total < 0:                       # pragma: no cover - invariant
            raise TransactionIntentError(
                "outstanding tracker underflowed its total count")

    def assert_invariants(self) -> None:
        """Check the bound holds right now. Raised by tests and by any guard."""
        limit = self._limit
        if self._live_total < 0 or self._live_reads < 0 or \
                self._live_writes < 0:
            raise TransactionIntentError(
                "outstanding tracker has a negative live count "
                f"(reads={self._live_reads}, writes={self._live_writes}, "
                f"total={self._live_total})")
        if limit.total is not None and self._live_total > limit.total:
            raise TransactionIntentError(
                f"outstanding total {self._live_total} exceeds its declared "
                f"limit {limit.total}")
        if limit.reads is not None and self._live_reads > limit.reads:
            raise TransactionIntentError(
                f"outstanding reads {self._live_reads} exceeds its declared "
                f"limit {limit.reads}")
        if limit.writes is not None and self._live_writes > limit.writes:
            raise TransactionIntentError(
                f"outstanding writes {self._live_writes} exceeds its declared "
                f"limit {limit.writes}")


__all__ = [
    "TRANSACTION_INTENT_SCHEMA_VERSION",
    "TransactionIntentError",
    "OrderingMode",
    "TransactionKind",
    "OutstandingLimit",
    "OrderingPolicy",
    "SplittingPolicy",
    "ReorderingPolicy",
    "TransactionPolicy",
    "ChildTransaction",
    "split_transactions",
    "OutstandingTracker",
]
