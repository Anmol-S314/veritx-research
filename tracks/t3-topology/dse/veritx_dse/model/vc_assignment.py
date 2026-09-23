"""veritx_dse.model.vc_assignment — VCAssignmentArtifact (Wave B3.3).

VC structure is a fabric semantic, not a buffering budget: which VC ids
exist, what each VC's routing class is, which traffic classes may use
which VC, which transitions are allowed, and (only when a routing class
implements one) which VC is an escape VC.

    TopologyArtifact ──► RouteArtifact (router-level)
            │                    │
            ▼                    ▼
    AgentAttachmentArtifact ──► ResolvedRouteArtifact
                                     │
                                     ▼
                              VCAssignmentArtifact

Parent hash: ``resolved_route_hash`` — VC semantics are routed semantics,
so the binding is to the endpoint-resolved route, never to a design label.

Hard rules (B3.3):
  * vc ids are exactly 0..vc_count-1 — no sparse or renamed VCs;
  * every VC maps to a RoutingClass present in the resolved route;
  * every declared traffic class has a non-empty, legal VC set;
  * transitions and escape designations reference existing VCs;
  * over-limit requirements are UNSUPPORTED, never silently clamped.

The derivation (which cycle needed which separation) lives in the
``derivation`` string and is provenance, not authority: it is transported
by ``to_dict()`` but deliberately excluded from ``vc_assignment_hash``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .resolved_route import ResolvedRouteArtifact

VC_ASSIGNMENT_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/VCAssignmentArtifact"

# Compatibility alias only: the authoritative default class is
# resolved_route.routing_classes[0] (RouteArtifact v2). "DEFAULT" no
# longer names hardware semantics — B3.2d materializes ANYNET_MIN_HOPS /
# DOR_XY explicitly. The name stays so older callers do not break.
DEFAULT_ROUTING_CLASS = "DEFAULT"


class VCAssignmentError(ValueError):
    """The VC assignment is invalid or exceeds the fabric — fail closed."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise VCAssignmentError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise VCAssignmentError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise VCAssignmentError(f"{where} is missing required field {key!r}")
    return d[key]


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise VCAssignmentError(f"{name} must be an int, got {type(value).__name__}")
    return value


def _int_tuple(name: str, value: Any, *,
               allow_empty: bool = False) -> tuple[int, ...]:
    """Strict integer sequence: ``True``/``1.0``/``"1"`` are refused, not
    canonicalized. Authoritative artifacts load the past; they do not
    repair it."""
    if not isinstance(value, (tuple, list)):
        raise VCAssignmentError(
            f"{name} must be a sequence of ints, got {type(value).__name__}")
    out = tuple(_as_int(name, v) for v in value)
    if not out and not allow_empty:
        raise VCAssignmentError(f"{name} must be non-empty")
    return out


def _pairs(name: str, value: Any) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, (tuple, list)):
        raise VCAssignmentError(f"{name} must be a sequence of pairs")
    out: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise VCAssignmentError(f"{name} entries must be (int, int) pairs")
        out.append((_as_int(f"{name} key", item[0]),
                    _as_int(f"{name} value", item[1])))
    return tuple(out)


@dataclass(frozen=True)
class VCAssignmentArtifact:
    """The authoritative VC structure of one resolved fabric."""

    resolved_route_hash: str
    vc_count: int
    vc_ids: tuple[int, ...]
    traffic_class_to_vcs: tuple[tuple[str, tuple[int, ...]], ...]
    vc_to_routing_class: tuple[tuple[int, str], ...]
    allowed_transitions: tuple[tuple[int, int], ...]
    escape_vcs: tuple[int, ...]
    derivation: str
    schema_version: int = VC_ASSIGNMENT_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        if not isinstance(self.resolved_route_hash, str) \
                or not self.resolved_route_hash:
            raise VCAssignmentError(
                "resolved_route_hash must be a non-empty string")
        _as_int("vc_count", self.vc_count)
        if self.vc_count < 1:
            raise VCAssignmentError("vc_count must be >= 1")
        if not isinstance(self.vc_ids, tuple):
            raise VCAssignmentError("vc_ids must be a tuple")
        _int_tuple("vc_ids", self.vc_ids)
        if self.vc_ids != tuple(range(self.vc_count)):
            raise VCAssignmentError(
                "vc_ids must be exactly 0..vc_count-1 (canonical)")
        if not isinstance(self.traffic_class_to_vcs, tuple) \
                or not self.traffic_class_to_vcs:
            raise VCAssignmentError(
                "traffic_class_to_vcs must be a non-empty tuple")
        seen_classes: set[str] = set()
        prev = None
        for item in self.traffic_class_to_vcs:
            if not isinstance(item, tuple) or len(item) != 2:
                raise VCAssignmentError(
                    "traffic_class_to_vcs entries must be (class, vcs) pairs")
            cls, vcs = item
            if not isinstance(cls, str) or not cls:
                raise VCAssignmentError(
                    "traffic class names must be non-empty strings")
            if cls in seen_classes:
                raise VCAssignmentError(
                    f"traffic class {cls!r} declared twice")
            seen_classes.add(cls)
            if prev is not None and cls <= prev:
                raise VCAssignmentError(
                    "traffic_class_to_vcs must be sorted by class name")
            prev = cls
            if not isinstance(vcs, tuple) or not vcs:
                raise VCAssignmentError(
                    f"traffic class {cls!r} has an empty VC set")
            _int_tuple(f"traffic class {cls!r} VC set", vcs)
            if tuple(sorted(set(vcs))) != vcs:
                raise VCAssignmentError(
                    f"traffic class {cls!r} VC set must be sorted and unique")
            for vc in vcs:
                if not 0 <= vc < self.vc_count:
                    raise VCAssignmentError(
                        f"traffic class {cls!r} references VC {vc} outside "
                        f"0..{self.vc_count - 1}")
        if not isinstance(self.vc_to_routing_class, tuple) \
                or len(self.vc_to_routing_class) != self.vc_count:
            raise VCAssignmentError(
                "vc_to_routing_class must name every VC exactly once")
        for item in self.vc_to_routing_class:
            if not isinstance(item, tuple) or len(item) != 2:
                raise VCAssignmentError(
                    "vc_to_routing_class entries must be (vc, class) pairs")
        expected_ids = list(range(self.vc_count))
        actual_ids = [_as_int("vc_to_routing_class key", k)
                      for k, _ in self.vc_to_routing_class]
        if actual_ids != expected_ids:
            raise VCAssignmentError(
                "vc_to_routing_class keys must be exactly 0..vc_count-1")
        for _vc, routing_class in self.vc_to_routing_class:
            if not isinstance(routing_class, str) or not routing_class:
                raise VCAssignmentError(
                    "routing class names must be non-empty strings")
        transitions = _pairs("allowed_transitions", self.allowed_transitions)
        if tuple(sorted(set(transitions))) != transitions:
            raise VCAssignmentError(
                "allowed_transitions must be sorted and unique")
        for src, dst in transitions:
            if not 0 <= src < self.vc_count or not 0 <= dst < self.vc_count:
                raise VCAssignmentError(
                    f"transition ({src},{dst}) references a VC outside "
                    f"0..{self.vc_count - 1}")
        if not isinstance(self.escape_vcs, tuple):
            raise VCAssignmentError("escape_vcs must be a tuple")
        _int_tuple("escape_vcs", self.escape_vcs, allow_empty=True)
        if tuple(sorted(set(self.escape_vcs))) != self.escape_vcs:
            raise VCAssignmentError(
                "escape_vcs must be sorted and unique")
        for vc in self.escape_vcs:
            if not 0 <= vc < self.vc_count:
                raise VCAssignmentError(
                    f"escape VC {vc} outside 0..{self.vc_count - 1}")
        if not isinstance(self.derivation, str) or not self.derivation:
            raise VCAssignmentError(
                "derivation must be a non-empty provenance string")
        if type(self.schema_version) is not int or \
                self.schema_version != VC_ASSIGNMENT_SCHEMA_VERSION:
            raise VCAssignmentError(
                f"unsupported vc-assignment schema_version "
                f"{self.schema_version!r}")
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise VCAssignmentError("artifact_hash does not match content")

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """The SEMANTIC identity that ``vc_assignment_hash`` commits to.

        ``derivation`` is provenance and is deliberately absent: two
        artifacts describing the same VC structure must hash identically
        no matter which compiler pass produced them (B3.0 identity rule).
        Provenance travels in ``to_dict()``, never in the hash.
        """
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "resolved_route_hash": self.resolved_route_hash,
            "vc_count": self.vc_count,
            "vc_ids": list(self.vc_ids),
            "traffic_class_to_vcs": [
                [cls, list(vcs)] for cls, vcs in self.traffic_class_to_vcs
            ],
            "vc_to_routing_class": [
                [vc, routing] for vc, routing in self.vc_to_routing_class
            ],
            "allowed_transitions": [list(p) for p in self.allowed_transitions],
            "escape_vcs": list(self.escape_vcs),
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def vc_assignment_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["derivation"] = self.derivation
        d["artifact_hash"] = self.vc_assignment_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> VCAssignmentArtifact:
        allowed = frozenset({
            "type", "schema_version", "resolved_route_hash", "vc_count",
            "vc_ids", "traffic_class_to_vcs", "vc_to_routing_class",
            "allowed_transitions", "escape_vcs", "derivation",
            "artifact_hash",
        })
        _strict_keys(d, allowed, "vc_assignment")
        if _need(d, "type", "vc_assignment") != _HASH_TYPE_TAG:
            raise VCAssignmentError(
                f"unexpected artifact type {d.get('type')!r}")
        try:
            traffic = tuple(
                (cls, tuple(vcs))
                for cls, vcs in _need(
                    d, "traffic_class_to_vcs", "vc_assignment")
            )
            # No int()/str() repair: malformed persisted values must be
            # rejected by __post_init__, never canonicalized into valid
            # state (True / 1.0 / "1" are impostors, not integers).
            routing = tuple(
                (vc, rc)
                for vc, rc in _need(
                    d, "vc_to_routing_class", "vc_assignment")
            )
            return cls(
                resolved_route_hash=_need(d, "resolved_route_hash", "vc_assignment"),
                vc_count=_need(d, "vc_count", "vc_assignment"),
                vc_ids=tuple(_need(d, "vc_ids", "vc_assignment")),
                traffic_class_to_vcs=traffic,
                vc_to_routing_class=routing,
                allowed_transitions=_pairs(
                    "allowed_transitions",
                    _need(d, "allowed_transitions", "vc_assignment")),
                escape_vcs=tuple(_need(d, "escape_vcs", "vc_assignment")),
                derivation=_need(d, "derivation", "vc_assignment"),
                schema_version=_need(d, "schema_version", "vc_assignment"),
                artifact_hash=_need(d, "artifact_hash", "vc_assignment"),
            )
        except VCAssignmentError:
            raise
        except (TypeError, ValueError) as exc:
            raise VCAssignmentError(
                f"malformed VCAssignmentArtifact: {exc}") from exc

    # ── parent legality ────────────────────────────────────────────────
    def validate_against(self, resolved_route: ResolvedRouteArtifact) -> None:
        """Prove every reference lands in the resolved route artifact."""
        if self.resolved_route_hash != resolved_route.resolved_route_hash():
            raise VCAssignmentError(
                "resolved_route_hash does not match the resolved route "
                "artifact")
        known = set(resolved_route.routing_classes)
        used = {rc for _vc, rc in self.vc_to_routing_class}
        unknown = used - known
        if unknown:
            raise VCAssignmentError(
                f"VC routing classes {sorted(unknown)} are not defined by "
                f"the resolved route (has {sorted(known)})")
        for cls, vcs in self.traffic_class_to_vcs:
            for vc in vcs:
                if not 0 <= vc < self.vc_count:
                    raise VCAssignmentError(
                        f"traffic class {cls!r} references VC {vc} outside "
                        f"0..{self.vc_count - 1}")


def make_vc_assignment_artifact(
        *,
        resolved_route: ResolvedRouteArtifact,
        vc_count: int,
        traffic_class_to_vcs: Any,
        derivation: str,
        vc_to_routing_class: Any = None,
        allowed_transitions: Any = None,
        escape_vcs: Any = (),
) -> VCAssignmentArtifact:
    """Build a canonical artifact: sort, dedupe, default, then validate.

    Defaults encode the honest state of the world, not a desired proof:
      * every VC uses the resolved route's default routing class;
      * allowed transitions are VC-preserving only (a packet does not
        switch VCs unless a class says so — silent cross-VC hops are how
        deadlock proofs get falsified);
      * no escape VC is designated.
    """
    _as_int("vc_count", vc_count)
    tc_pairs = tuple(
        (cls, tuple(sorted(set(_int_tuple(
            f"traffic class {cls!r} VC set", vcs)))))
        for cls, vcs in sorted(dict(traffic_class_to_vcs).items())
    )
    ids = tuple(range(vc_count))
    if vc_to_routing_class is None:
        default_cls = (resolved_route.routing_classes[0]
                       if resolved_route.routing_classes
                       else DEFAULT_ROUTING_CLASS)
        vc_routing = tuple((vc, default_cls) for vc in ids)
    else:
        vc_routing = tuple(sorted(
            (_as_int("vc id", vc), rc)
            for vc, rc in dict(vc_to_routing_class).items()
        ))
    if allowed_transitions is None:
        transitions = tuple((vc, vc) for vc in ids)
    else:
        transitions = tuple(sorted({
            (_as_int("transition src", a), _as_int("transition dst", b))
            for a, b in allowed_transitions
        }))
    artifact = VCAssignmentArtifact(
        resolved_route_hash=resolved_route.resolved_route_hash(),
        vc_count=vc_count,
        vc_ids=ids,
        traffic_class_to_vcs=tc_pairs,
        vc_to_routing_class=vc_routing,
        allowed_transitions=transitions,
        escape_vcs=tuple(sorted(set(
            _int_tuple("escape_vcs", escape_vcs, allow_empty=True)))),
        derivation=derivation,
    )
    artifact.validate_against(resolved_route)
    return artifact
