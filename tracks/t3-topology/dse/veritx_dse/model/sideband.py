"""veritx_dse.model.sideband — typed sideband interfaces and connectivity.

Rationale: docs/decisions/modules/model.md
Contract: docs/INTENT-V5-CONTRACT.md §7

A sideband connection is its OWN EDGE in the fabric graph.

This is the distinction that keeps the model honest: an interrupt, a QoS hint,
a poison bit, a power-state request or a trace strobe is NOT a payload the main
NoC data plane happens to carry. Modelled that way, "the sideband reaches its
destination" would silently inherit the data plane's routing, flow control and
address policy, and a UI could then render a connection that no artifact
supports. Here a ``SidebandConnection`` is a first-class edge with its own
source and destination refs, its own width check and its own direction rule.
The main fabric's flit/VC/routing machinery is never consulted, and no sideband
is ever promoted into the data plane by omission.

Clock-domain crossing is FLAGGED, never RESOLVED. :meth:`SidebandConnection.\
requires_clock_crossing` reports whether the two ends name different clock
domains. Deciding *how* to cross (2FF, 3FF, handshake, async FIFO) is
``veritx_dse.model.domain_intent``'s job — see that module by name — so this
module deliberately carries no synchronizer, no FIFO depth and no mechanism.
Selecting one here would be exactly the silent fallback the product forbids.

What this module refuses (each is a typed ``SidebandError``, never a downgrade):
    * an unknown ``sideband_id`` (existence)
    * a source that is not ``OUTPUT`` or a destination that is not ``INPUT``
    * a width mismatch between the two ends
    * an agent outside the declared agent universe
    * a self-connection (identical source and destination ref)
    * duplicate interface ids or connection ids
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from veritx_dse.core.errors import SemanticError

SIDEBAND_SCHEMA_VERSION = 1


class SidebandError(ValueError, SemanticError):
    """A sideband declaration is invalid or unsupported — fail closed."""


# --------------------------------------------------------------------------
# vocabulary — exact names fixed by docs/INTENT-V5-CONTRACT.md §3
# --------------------------------------------------------------------------

class SidebandKind(Enum):
    """What a sideband carries. Not a data-plane traffic class."""

    INTERRUPT = "interrupt"
    QOS = "qos"
    ERROR = "error"
    POISON = "poison"
    SNOOP_CONTROL = "snoop_control"
    POWER_STATE = "power_state"
    RESET = "reset"
    CLOCK_REQUEST = "clock_request"
    CREDIT_STATUS = "credit_status"
    TRACE = "trace"
    CUSTOM = "custom"


class Direction(Enum):
    """Direction of a sideband PORT relative to the agent that owns it."""

    OUTPUT = "output"
    INPUT = "input"


# --------------------------------------------------------------------------
# local typed helpers — every refusal is a SidebandError, so a caller catching
# SidebandError sees the whole boundary. compile_model's _as_int/_as_str raise
# a bare ValueError, which would escape the typed refusal.
# --------------------------------------------------------------------------

def _as_int(name: str, value: Any, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise SidebandError(
            f"{name} must be an exact int, got {type(value).__name__} "
            f"{value!r}")
    if minimum is not None and value < minimum:
        raise SidebandError(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise SidebandError(
            f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise SidebandError(f"{name} must be non-empty")
    return value


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise SidebandError(f"{where} is missing required field {key!r}")
    return d[key]


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    """Refuse unknown fields by name, so a typo cannot become a silently
    ignored sideband property."""
    if not isinstance(d, dict):
        raise SidebandError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise SidebandError(
            f"{where} has unknown fields: {sorted(unknown)} "
            f"(allowed: {sorted(allowed)})")


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Any:
    if not isinstance(value, str):
        raise SidebandError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise SidebandError(
            f"unknown {name} {value!r}; known: "
            f"{[member.value for member in enum_cls]}") from None


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


# --------------------------------------------------------------------------
# interface
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SidebandInterface:
    """One declared sideband PORT: its kind, direction, width and domains.

    ``clock_domain`` / ``power_domain`` are plain domain NAMES here. Resolving
    a crossing between two of them belongs to ``domain_intent``; copying that
    law here would create a second authority for one fact.
    ``protocol_binding`` is a protocol identity (e.g. ``AXI``) or ``None`` —
    it is never inferred from the kind.
    """

    id: str
    kind: SidebandKind
    direction: Direction
    width_bits: int
    clock_domain: str | None = None
    power_domain: str | None = None
    protocol_binding: str | None = None

    def __post_init__(self) -> None:
        _as_str("sideband id", self.id, allow_empty=False)
        if not isinstance(self.kind, SidebandKind):
            raise SidebandError(
                f"sideband {self.id!r}: kind must be a SidebandKind, got "
                f"{type(self.kind).__name__}")
        if not isinstance(self.direction, Direction):
            raise SidebandError(
                f"sideband {self.id!r}: direction must be a Direction, got "
                f"{type(self.direction).__name__}")
        _as_int("width_bits", self.width_bits, minimum=1)
        for name in ("clock_domain", "power_domain", "protocol_binding"):
            value = getattr(self, name)
            if value is not None:
                _as_str(name, value, allow_empty=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "direction": self.direction.value,
            "width_bits": self.width_bits,
            "clock_domain": self.clock_domain,
            "power_domain": self.power_domain,
            "protocol_binding": self.protocol_binding,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SidebandInterface":
        where = "sideband interface"
        _strict_keys(d, frozenset({
            "id", "kind", "direction", "width_bits", "clock_domain",
            "power_domain", "protocol_binding"}), where)
        return cls(
            id=_need(d, "id", where),
            kind=_enum("kind", SidebandKind, _need(d, "kind", where)),
            direction=_enum("direction", Direction,
                            _need(d, "direction", where)),
            width_bits=_need(d, "width_bits", where),
            clock_domain=d.get("clock_domain"),
            power_domain=d.get("power_domain"),
            protocol_binding=d.get("protocol_binding"),
        )


# --------------------------------------------------------------------------
# connectivity
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SidebandEndpointRef:
    """One end of a sideband edge: which agent, which sideband port."""

    agent: str
    sideband_id: str

    def __post_init__(self) -> None:
        _as_str("sideband endpoint ref agent", self.agent, allow_empty=False)
        _as_str("sideband endpoint ref sideband_id", self.sideband_id,
                allow_empty=False)

    def to_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "sideband_id": self.sideband_id}

    @classmethod
    def from_dict(cls, d: Any) -> "SidebandEndpointRef":
        where = "sideband endpoint ref"
        _strict_keys(d, frozenset({"agent", "sideband_id"}), where)
        return cls(agent=_need(d, "agent", where),
                   sideband_id=_need(d, "sideband_id", where))


@dataclass(frozen=True)
class SidebandConnection:
    """A sideband edge: source port -> destination port.

    This is an edge of its own. It is never routed through the fabric, never
    given a VC or a traffic class, and never turns into a data-plane payload.
    """

    connection_id: str
    source: SidebandEndpointRef
    destination: SidebandEndpointRef

    def __post_init__(self) -> None:
        _as_str("sideband connection id", self.connection_id,
                allow_empty=False)
        if not isinstance(self.source, SidebandEndpointRef):
            raise SidebandError(
                f"connection {self.connection_id!r}: source must be a "
                f"SidebandEndpointRef, got {type(self.source).__name__}")
        if not isinstance(self.destination, SidebandEndpointRef):
            raise SidebandError(
                f"connection {self.connection_id!r}: destination must be a "
                f"SidebandEndpointRef, got "
                f"{type(self.destination).__name__}")
        if self.source == self.destination:
            raise SidebandError(
                f"connection {self.connection_id!r} is a self-connection "
                f"({self.source.to_dict()}): a sideband edge needs distinct "
                "source and destination ports. A no-op edge is refused "
                "rather than silently accepted as connected.")

    def requires_clock_crossing(
            self,
            interfaces: Mapping[str, SidebandInterface] | Iterable[
                SidebandInterface],
    ) -> bool | None:
        """DERIVED: do the two ends name different clock domains?

        Returns ``True`` when they differ, ``False`` when they match, and
        ``None`` when either end's ``clock_domain`` is undeclared — an
        unknown domain is reported as unknown, never coerced to ``False``.

        This only FLAGS the crossing. The mechanism (SYNC_2FF / SYNC_3FF /
        HANDSHAKE / ASYNC_FIFO) is decided by
        ``veritx_dse.model.domain_intent``; this module has no authority to
        pick one and never does.
        """
        by_id = _interface_map(interfaces)
        src = by_id.get(self.source.sideband_id)
        dst = by_id.get(self.destination.sideband_id)
        if src is None or dst is None:
            return None
        if src.clock_domain is None or dst.clock_domain is None:
            return None
        return src.clock_domain != dst.clock_domain

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "source": self.source.to_dict(),
            "destination": self.destination.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SidebandConnection":
        where = "sideband connection"
        _strict_keys(d, frozenset(
            {"connection_id", "source", "destination"}), where)
        return cls(
            connection_id=_need(d, "connection_id", where),
            source=SidebandEndpointRef.from_dict(
                _need(d, "source", where)),
            destination=SidebandEndpointRef.from_dict(
                _need(d, "destination", where)),
        )


def _interface_map(
        interfaces: Mapping[str, SidebandInterface] | Iterable[
            SidebandInterface],
) -> dict[str, SidebandInterface]:
    if isinstance(interfaces, Mapping):
        for key, value in interfaces.items():
            if not isinstance(value, SidebandInterface):
                raise SidebandError(
                    f"interfaces[{key!r}] must be a SidebandInterface, got "
                    f"{type(value).__name__}")
        return dict(interfaces)
    out: dict[str, SidebandInterface] = {}
    for item in interfaces:
        if not isinstance(item, SidebandInterface):
            raise SidebandError(
                f"interfaces must contain SidebandInterface, got "
                f"{type(item).__name__}")
        if item.id in out:
            raise SidebandError(
                f"duplicate sideband interface id {item.id!r}: interface "
                "ids must be unique across the declared universe")
        out[item.id] = item
    return out


def validate_sidebands(
        interfaces: Mapping[str, SidebandInterface] | Iterable[
            SidebandInterface],
        connections: Iterable[SidebandConnection],
        *,
        agent_universe: Iterable[str],
) -> None:
    """Prove the declared sidebands are well-formed. Returns ``None``.

    Refuses (each names the offending object, the violated law and the legal
    alternative):

    * duplicate interface ids, or an interface list that is not interfaces
    * an agent outside ``agent_universe``
    * an unknown ``sideband_id`` on either end (existence)
    * a source port that is not ``OUTPUT``, or a destination that is not
      ``INPUT``
    * a width mismatch between the two ends
    * duplicate ``connection_id``

    It does NOT decide a clock-crossing mechanism. Call
    :meth:`SidebandConnection.requires_clock_crossing` to FLAG a crossing, then
    declare it in ``veritx_dse.model.domain_intent``.
    """
    by_id = _interface_map(interfaces)

    agents = list(agent_universe)
    seen_agents: set[str] = set()
    for agent in agents:
        _as_str("agent universe entry", agent, allow_empty=False)
        if agent in seen_agents:
            raise SidebandError(
                f"duplicate agent {agent!r} in the agent universe")
        seen_agents.add(agent)

    seen_conn: set[str] = set()
    for conn in connections:
        if not isinstance(conn, SidebandConnection):
            raise SidebandError(
                f"connections must contain SidebandConnection, got "
                f"{type(conn).__name__}")
        if conn.connection_id in seen_conn:
            raise SidebandError(
                f"duplicate sideband connection id {conn.connection_id!r}")
        seen_conn.add(conn.connection_id)

        for end_name, ref in (("source", conn.source),
                              ("destination", conn.destination)):
            if ref.agent not in seen_agents:
                raise SidebandError(
                    f"connection {conn.connection_id!r}: {end_name} agent "
                    f"{ref.agent!r} is not in the agent universe "
                    f"({sorted(seen_agents)[:6]}{'...' if len(seen_agents) > 6 else ''}). "
                    "Declare the agent before attaching a sideband to it.")
            if ref.sideband_id not in by_id:
                raise SidebandError(
                    f"connection {conn.connection_id!r}: {end_name} "
                    f"sideband_id {ref.sideband_id!r} is not a declared "
                    f"sideband interface (known: {sorted(by_id)}). Declare "
                    "the interface before connecting it.")

        src = by_id[conn.source.sideband_id]
        dst = by_id[conn.destination.sideband_id]

        if src.direction is not Direction.OUTPUT:
            raise SidebandError(
                f"connection {conn.connection_id!r}: source sideband "
                f"{src.id!r} has direction {src.direction.value!r}; a "
                "sideband edge's source port must be OUTPUT. Reverse the "
                "connection or declare the port as an output.")
        if dst.direction is not Direction.INPUT:
            raise SidebandError(
                f"connection {conn.connection_id!r}: destination sideband "
                f"{dst.id!r} has direction {dst.direction.value!r}; a "
                "sideband edge's destination port must be INPUT. Reverse "
                "the connection or declare the port as an input.")
        if src.width_bits != dst.width_bits:
            raise SidebandError(
                f"connection {conn.connection_id!r}: width mismatch — "
                f"source {src.id!r} is {src.width_bits} bits and "
                f"destination {dst.id!r} is {dst.width_bits} bits. The two "
                "ends of a sideband edge must agree on width; declare "
                "matching widths or add an explicit width adapter.")

        if src.kind is not dst.kind:
            raise SidebandError(
                f"connection {conn.connection_id!r}: kind mismatch — source "
                f"{src.id!r} is {src.kind.value!r} and destination "
                f"{dst.id!r} is {dst.kind.value!r}. The two ends of a "
                "sideband edge must describe the same signal kind.")


__all__ = [
    "SIDEBAND_SCHEMA_VERSION",
    "SidebandError",
    "SidebandKind",
    "Direction",
    "SidebandInterface",
    "SidebandEndpointRef",
    "SidebandConnection",
    "validate_sidebands",
]
