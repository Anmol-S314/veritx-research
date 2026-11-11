"""veritx_dse.model.agent_intent_v4 — STAGE 1 per-tile agent + traffic intent.

Rationale: docs/design/mesh-stage1-schema-compiler-scope.md §3 (D3).
Scope: mesh-stage1-schema-compiler-scope §3 (D3 new top-level blocks).

Placement (A): two new top-level Optional blocks on ``CompileRequestV4``
(``agent_intents`` + ``traffic_policy``), beside ``agents``/``dependencies``.
``Agent`` is frozen and shared by v2/v3/v4 and is NOT extended; ``MeshIntent``
gains nothing (P1). Everything here is Optional: absent ≡ empty, so existing
drafts parse and hash identically (P4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from veritx_dse.core.constants import PLANE_C_MAX_VC
from veritx_dse.core.errors import SemanticError


class AgentIntentV4Error(ValueError, SemanticError):
    """A stage-1 agent/traffic intent declaration is invalid."""


#: Closed protocol vocabulary (STAGE 1 §4.4). ``Agent.protocol`` stays a free
#: string for legacy compatibility; when an intent names a protocol, the enum
#: wins (D2 enum-wins rule).
PROTOCOL_VOCAB = ("axi5", "chi", "tilelink", "custom")
PROTOCOL_FAMILIES = frozenset(PROTOCOL_VOCAB)

_AGENT_INTENT_KEYS = frozenset({
    "agent_idx", "protocol", "ordering", "max_outstanding", "split_at",
    "clock_domain", "power_domain", "permission_windows",
})
_PERMISSION_WINDOW_KEYS = frozenset({"address_range", "readable", "writable", "atomic"})
_TRAFFIC_CLASS_VC_KEYS = frozenset({"traffic_class", "vc"})
_TRAFFIC_POLICY_KEYS = frozenset({"traffic_class_vcs"})


class ProtocolFamily(Enum):
    """Closed protocol vocabulary; legacy ``Agent.protocol`` is NOT this."""

    AXI5 = "axi5"
    CHI = "chi"
    TILELINK = "tilelink"
    CUSTOM = "custom"

    @classmethod
    def parse(cls, value: Any) -> "ProtocolFamily":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            for member in cls:
                if member.value == lowered:
                    return member
        raise AgentIntentV4Error(
            f"invalid protocol {value!r}: expected one of "
            f"{sorted(PROTOCOL_VOCAB)} (closed vocabulary)")


class OrderingMode(Enum):
    """Ordering promise declared by one agent group."""

    STRONG = "strong"
    RELAXED = "relaxed"
    RAW = "raw"  # RAW = no ordering promise

    @classmethod
    def parse(cls, value: Any) -> "OrderingMode":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            for member in cls:
                if member.value == lowered:
                    return member
        raise AgentIntentV4Error(
            f"invalid ordering {value!r}: expected one of "
            f"{sorted(m.value for m in cls)}")


def _as_int(name: str, value: Any, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise AgentIntentV4Error(
            f"{name} must be an int, got {type(value).__name__} {value!r}")
    if minimum is not None and value < minimum:
        raise AgentIntentV4Error(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise AgentIntentV4Error(
            f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise AgentIntentV4Error(f"{name} must be non-empty")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise AgentIntentV4Error(
            f"{name} must be a bool, got {type(value).__name__} {value!r}")
    return value


def _strict_keys(d: Any, allowed: frozenset, where: str) -> None:
    if not isinstance(d, dict):
        raise AgentIntentV4Error(f"{where} must be a JSON object")
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise AgentIntentV4Error(f"unknown field {where}.{unknown[0]}")


def _need(d: dict, key: str, where: str) -> Any:
    if key not in d:
        raise AgentIntentV4Error(f"missing required field {where}.{key}")
    return d[key]


def _as_tuple(name: str, value: Any) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    raise AgentIntentV4Error(
        f"{name} must be a list or tuple, got {type(value).__name__}")


@dataclass(frozen=True)
class PermissionWindow:
    """One per-(range) permission claim: read/write/atomic may be denied.

    ``readable=False, writable=False`` is a declared no-access window: it
    compiles, and emitters must not route traffic there.

    Initiator identity is the parent ``AgentIntentV4.agent_idx`` (agent
    GROUP). The tuple ``(agent_idx, address_range)`` is the policy key;
    two groups declaring rights for the same range is the intended
    per-initiator model and must compile. ``atomic=True`` is honored only
    when the group's protocol is ``axi5`` (M1 enforces this).
    """

    address_range: str
    readable: bool = True
    writable: bool = True
    atomic: bool = False

    def __post_init__(self):
        _as_str("PermissionWindow.address_range", self.address_range,
                allow_empty=False)
        _as_bool("PermissionWindow.readable", self.readable)
        _as_bool("PermissionWindow.writable", self.writable)
        _as_bool("PermissionWindow.atomic", self.atomic)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"address_range": self.address_range,
                "readable": self.readable, "writable": self.writable}
        # Absent ≡ False for hash honesty: only emit atomic when True so
        # legacy documents hash identically.
        if self.atomic:
            d["atomic"] = True
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "PermissionWindow":
        _strict_keys(d, _PERMISSION_WINDOW_KEYS, "permission_window")
        atomic = d.get("atomic", False)
        if type(atomic) is not bool:
            raise AgentIntentV4Error(
                f"permission_window.atomic must be a bool, got "
                f"{type(atomic).__name__} {atomic!r}")
        return cls(
            address_range=_need(d, "address_range", "permission_window"),
            readable=d.get("readable", True),
            writable=d.get("writable", True),
            atomic=atomic,
        )


@dataclass(frozen=True)
class TrafficClassVC:
    """Desired VC for one traffic class.

    Desired, never authority: ``derive_vc_assignment_v3`` stays the authority
    and a mismatch is compile INVALID (D4), never a silent override.
    """

    traffic_class: str
    vc: int

    def __post_init__(self):
        _as_str("TrafficClassVC.traffic_class", self.traffic_class,
                allow_empty=False)
        _as_int("TrafficClassVC.vc", self.vc)
        if not 0 <= self.vc < PLANE_C_MAX_VC:
            raise AgentIntentV4Error(
                f"TrafficClassVC.vc must be in "
                f"[0, {PLANE_C_MAX_VC}) (PLANE_C_MAX_VC), got {self.vc}")

    def to_dict(self) -> dict[str, Any]:
        return {"traffic_class": self.traffic_class, "vc": self.vc}

    @classmethod
    def from_dict(cls, d: Any) -> "TrafficClassVC":
        _strict_keys(d, _TRAFFIC_CLASS_VC_KEYS, "traffic_class_vc")
        return cls(
            traffic_class=_need(d, "traffic_class", "traffic_class_vc"),
            vc=_need(d, "vc", "traffic_class_vc"),
        )


@dataclass(frozen=True)
class AgentIntentV4:
    """One row per Agent GROUP (``agent_idx`` indexes ``agents``).

    A present-but-otherwise-empty row is legal (explicit "no per-tile
    intent"). ``clock_domain``/``power_domain`` must exist and match the
    group's ``Agent`` declaration when set (checked by M3, §5.8).
    """

    agent_idx: int
    protocol: ProtocolFamily | None = None
    ordering: OrderingMode | None = None
    max_outstanding: int | None = None
    split_at: int | None = None
    clock_domain: str | None = None
    power_domain: str | None = None
    permission_windows: tuple[PermissionWindow, ...] = ()

    def __post_init__(self):
        _as_int("AgentIntentV4.agent_idx", self.agent_idx, minimum=0)
        if self.protocol is not None:
            if isinstance(self.protocol, str):
                object.__setattr__(self, "protocol",
                                   ProtocolFamily.parse(self.protocol))
            else:
                object.__setattr__(self, "protocol",
                                   ProtocolFamily(self.protocol.value)
                                   if isinstance(self.protocol, ProtocolFamily)
                                   else ProtocolFamily(self.protocol))
        if self.ordering is not None:
            if isinstance(self.ordering, str):
                object.__setattr__(self, "ordering",
                                   OrderingMode.parse(self.ordering))
            else:
                object.__setattr__(self, "ordering",
                                   OrderingMode(self.ordering.value)
                                   if isinstance(self.ordering, OrderingMode)
                                   else OrderingMode(self.ordering))
        if self.max_outstanding is not None:
            _as_int("AgentIntentV4.max_outstanding", self.max_outstanding,
                    minimum=1)
        if self.split_at is not None:
            _as_int("AgentIntentV4.split_at", self.split_at, minimum=1)
        for name in ("clock_domain", "power_domain"):
            value = getattr(self, name)
            if value is not None:
                _as_str(f"AgentIntentV4.{name}", value, allow_empty=False)
        windows = _as_tuple("AgentIntentV4.permission_windows",
                            self.permission_windows)
        for window in windows:
            if not isinstance(window, PermissionWindow):
                raise AgentIntentV4Error(
                    "AgentIntentV4.permission_windows must contain "
                    f"PermissionWindow, got {type(window).__name__}")
        names = [w.address_range for w in windows]
        if len(set(names)) != len(names):
            raise AgentIntentV4Error(
                "AgentIntentV4.permission_windows has duplicate "
                f"address_range values: {sorted(n for n in names if names.count(n) > 1)}")
        object.__setattr__(
            self, "permission_windows",
            tuple(sorted(windows, key=lambda w: (w.address_range,
                                                w.readable, w.writable,
                                                w.atomic))))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"agent_idx": self.agent_idx}
        if self.protocol is not None:
            d["protocol"] = self.protocol.value
        if self.ordering is not None:
            d["ordering"] = self.ordering.value
        if self.max_outstanding is not None:
            d["max_outstanding"] = self.max_outstanding
        if self.split_at is not None:
            d["split_at"] = self.split_at
        if self.clock_domain is not None:
            d["clock_domain"] = self.clock_domain
        if self.power_domain is not None:
            d["power_domain"] = self.power_domain
        if self.permission_windows:
            d["permission_windows"] = [w.to_dict()
                                        for w in self.permission_windows]
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "AgentIntentV4":
        _strict_keys(d, _AGENT_INTENT_KEYS, "agent_intent")
        protocol = d.get("protocol")
        ordering = d.get("ordering")
        raw_windows = d.get("permission_windows", [])
        if not isinstance(raw_windows, list):
            raise AgentIntentV4Error(
                "agent_intent.permission_windows must be a JSON array")
        windows = tuple(PermissionWindow.from_dict(row)
                        for row in raw_windows)
        return cls(
            agent_idx=_need(d, "agent_idx", "agent_intent"),
            protocol=(ProtocolFamily.parse(protocol)
                      if protocol is not None else None),
            ordering=(OrderingMode.parse(ordering)
                      if ordering is not None else None),
            max_outstanding=d.get("max_outstanding"),
            split_at=d.get("split_at"),
            clock_domain=d.get("clock_domain"),
            power_domain=d.get("power_domain"),
            permission_windows=windows,
        )


@dataclass(frozen=True)
class TrafficPolicyV4:
    """Traffic-class VC desires for the whole request.

    Absent = derived default (§5.3): nothing is asserted, the derived
    assignment is the sole authority.
    """

    traffic_class_vcs: tuple[TrafficClassVC, ...] = ()

    def __post_init__(self):
        rows = _as_tuple("TrafficPolicyV4.traffic_class_vcs",
                         self.traffic_class_vcs)
        for row in rows:
            if not isinstance(row, TrafficClassVC):
                raise AgentIntentV4Error(
                    "TrafficPolicyV4.traffic_class_vcs must contain "
                    f"TrafficClassVC, got {type(row).__name__}")
        classes = [r.traffic_class for r in rows]
        if len(set(classes)) != len(classes):
            raise AgentIntentV4Error(
                "TrafficPolicyV4.traffic_class_vcs has duplicate "
                f"traffic_class values: "
                f"{sorted(c for c in classes if classes.count(c) > 1)}")
        object.__setattr__(
            self, "traffic_class_vcs",
            tuple(sorted(rows, key=lambda r: (r.traffic_class, r.vc))))

    def is_empty(self) -> bool:
        return not self.traffic_class_vcs

    def to_dict(self) -> dict[str, Any]:
        return {"traffic_class_vcs": [r.to_dict()
                                       for r in self.traffic_class_vcs]}

    @classmethod
    def from_dict(cls, d: Any) -> "TrafficPolicyV4":
        if d is None:
            return cls()
        _strict_keys(d, _TRAFFIC_POLICY_KEYS, "traffic_policy")
        raw = d.get("traffic_class_vcs", [])
        if not isinstance(raw, list):
            raise AgentIntentV4Error(
                "traffic_policy.traffic_class_vcs must be a JSON array")
        return cls(traffic_class_vcs=tuple(
            TrafficClassVC.from_dict(row) for row in raw))


def agent_intents_from_dict(d: Any) -> tuple[AgentIntentV4, ...]:
    """Strict array parse for the top-level ``agent_intents`` block."""
    if d is None:
        return ()
    if not isinstance(d, list):
        raise AgentIntentV4Error("agent_intents must be a JSON array")
    return tuple(AgentIntentV4.from_dict(row) for row in d)


__all__ = [
    "AgentIntentV4", "AgentIntentV4Error", "OrderingMode",
    "PermissionWindow", "ProtocolFamily", "TrafficClassVC",
    "TrafficPolicyV4", "PROTOCOL_VOCAB", "PROTOCOL_FAMILIES",
    "agent_intents_from_dict",
]
