"""veritx_dse.model.vc_assignment — the explicit VC-semantic artifact.

VC structure is fabric semantics, not a buffering budget: which VC ids
exist, which routing class each VC executes, which traffic classes may use
which VC, which VC transitions are allowed, and which VCs are designated
escape VCs.

    ResolvedRouteArtifact
            │
            ▼
    VCAssignmentArtifact

Parent hash: ``resolved_route_hash``. VC semantics are routed semantics, so
the binding is to the endpoint-resolved route, never to a design label.

What this artifact is:

  * an exact, content-addressed description of one candidate VC structure;
  * which routing class every VC executes;
  * which traffic classes may occupy which VCs;
  * a designation of escape VCs as declared intent.

What this artifact is NOT:

  * a proof that the structure is deadlock-free;
  * a proof that the designated escape VCs form a valid escape network.
    That certification belongs to the (channel, VC) resource-graph layer.

Hard rules:

  * VC ids are exactly 0..vc_count-1 — no sparse or renamed VCs;
  * every VC maps to a routing class present in the resolved route;
  * every declared traffic class has a non-empty, sorted, unique VC set;
  * transitions and escape designations reference existing VCs.

``derivation`` records which compiler pass produced the structure. It is
provenance, transported by ``to_dict()`` but excluded from
``vc_assignment_hash``: two derivations that produce the same VC structure
are the same artifact.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.resolved_route import ResolvedRouteArtifact

VC_ASSIGNMENT_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/VCAssignmentArtifact"


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
        raise VCAssignmentError(
            f"{name} must be an int, got {type(value).__name__}")
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


# ── authoring input (not persisted parsing) ──────────────────────────────

def _authoring_pairs(name: str, value: Any) -> list[tuple[Any, Any]]:
    """Materialize authoring input without silently collapsing duplicates.

    Mappings are unambiguous. A sequence of pairs is accepted for symmetry
    with historical callers, but a repeated key fails instead of letting
    ``dict(...)`` keep the last occurrence.
    """
    if isinstance(value, Mapping):
        return list(value.items())
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise VCAssignmentError(
            f"{name} must be a mapping or a sequence of (key, value) pairs")
    out: list[tuple[Any, Any]] = []
    seen: set[Any] = set()
    for index, item in enumerate(value):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise VCAssignmentError(
                f"{name}[{index}] must be a (key, value) pair")
        key = item[0]
        try:
            duplicate = key in seen
        except TypeError:
            raise VCAssignmentError(
                f"{name}[{index}] key {key!r} is not hashable") from None
        if duplicate:
            raise VCAssignmentError(f"{name} declares {key!r} more than once")
        seen.add(key)
        out.append((key, item[1]))
    return out


def _authoring_rows(name: str, value: Any) -> list[tuple[Any, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise VCAssignmentError(f"{name} must be a sequence of pairs")
    out: list[tuple[Any, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise VCAssignmentError(f"{name}[{index}] must be a pair")
        out.append((item[0], item[1]))
    return out


# ── persisted JSON parsing ───────────────────────────────────────────────

def _json_list(name: str, value: Any, *,
               allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list):
        raise VCAssignmentError(
            f"{name} must be a JSON list, got {type(value).__name__}")
    if not value and not allow_empty:
        raise VCAssignmentError(f"{name} must be non-empty")
    return value


def _json_int_list(name: str, value: Any, *,
                   allow_empty: bool = False) -> tuple[int, ...]:
    return tuple(_as_int(name, item)
                 for item in _json_list(name, value, allow_empty=allow_empty))


def _json_pair_list(name: str, value: Any) -> list[list[Any]]:
    rows = _json_list(name, value, allow_empty=True)
    out: list[list[Any]] = []
    for index, row in enumerate(rows):
        if type(row) is not list or len(row) != 2:
            raise VCAssignmentError(
                f"{name}[{index}] must be a two-element JSON list")
        out.append(row)
    return out


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
        if not isinstance(self.allowed_transitions, tuple):
            raise VCAssignmentError("allowed_transitions must be a tuple")
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
        if self.artifact_hash:
            if not isinstance(self.artifact_hash, str) \
                    or self.artifact_hash != expected:
                raise VCAssignmentError(
                    "artifact_hash does not match content")

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """The SEMANTIC identity that ``vc_assignment_hash`` commits to.

        ``derivation`` is provenance and is deliberately absent: two
        artifacts describing the same VC structure must hash identically
        no matter which compiler pass produced them. Provenance travels in
        ``to_dict()``, never in the hash.
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
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def vc_assignment_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["derivation"] = self.derivation
        d["artifact_hash"] = self.vc_assignment_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "VCAssignmentArtifact":
        allowed = frozenset({
            "type", "schema_version", "resolved_route_hash", "vc_count",
            "vc_ids", "traffic_class_to_vcs", "vc_to_routing_class",
            "allowed_transitions", "escape_vcs", "derivation",
            "artifact_hash",
        })
        _strict_keys(d, allowed, "vc_assignment")
        if _need(d, "type", "vc_assignment") != _HASH_TYPE_TAG:
            raise VCAssignmentError(
                f"vc_assignment type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        try:
            traffic: list[tuple[str, tuple[int, ...]]] = []
            for index, (class_id, vcs) in enumerate(_json_pair_list(
                    "traffic_class_to_vcs",
                    _need(d, "traffic_class_to_vcs", "vc_assignment"))):
                if not isinstance(class_id, str) or not class_id:
                    raise VCAssignmentError(
                        f"traffic_class_to_vcs[{index}] class must be a "
                        "non-empty string")
                traffic.append((class_id, _json_int_list(
                    f"traffic_class_to_vcs[{index}] VC set", vcs)))
            routing: list[tuple[int, str]] = []
            for index, (vc, rc) in enumerate(_json_pair_list(
                    "vc_to_routing_class",
                    _need(d, "vc_to_routing_class", "vc_assignment"))):
                _as_int(f"vc_to_routing_class[{index}] VC", vc)
                if not isinstance(rc, str) or not rc:
                    raise VCAssignmentError(
                        f"vc_to_routing_class[{index}] routing class must be "
                        "a non-empty string")
                routing.append((vc, rc))
            transitions: list[tuple[int, int]] = []
            for index, (src, dst) in enumerate(_json_pair_list(
                    "allowed_transitions",
                    _need(d, "allowed_transitions", "vc_assignment"))):
                transitions.append((
                    _as_int(f"allowed_transitions[{index}] source", src),
                    _as_int(f"allowed_transitions[{index}] destination", dst)))
            artifact_hash = _need(d, "artifact_hash", "vc_assignment")
            if not isinstance(artifact_hash, str) or not artifact_hash:
                raise VCAssignmentError(
                    "artifact_hash must be a non-empty string")
            return cls(
                resolved_route_hash=_need(d, "resolved_route_hash",
                                          "vc_assignment"),
                vc_count=_need(d, "vc_count", "vc_assignment"),
                vc_ids=_json_int_list("vc_ids",
                                      _need(d, "vc_ids", "vc_assignment")),
                traffic_class_to_vcs=tuple(traffic),
                vc_to_routing_class=tuple(routing),
                allowed_transitions=tuple(transitions),
                escape_vcs=_json_int_list(
                    "escape_vcs", _need(d, "escape_vcs", "vc_assignment"),
                    allow_empty=True),
                derivation=_need(d, "derivation", "vc_assignment"),
                schema_version=_need(d, "schema_version", "vc_assignment"),
                artifact_hash=artifact_hash,
            )
        except VCAssignmentError:
            raise
        except (TypeError, ValueError) as exc:
            raise VCAssignmentError(
                f"malformed VCAssignmentArtifact: {exc}") from exc

    # ── parent legality ────────────────────────────────────────────────
    def validate_against(self, resolved_route: ResolvedRouteArtifact) -> None:
        """Prove every reference lands in the resolved route artifact."""
        if not isinstance(resolved_route, ResolvedRouteArtifact):
            raise VCAssignmentError(
                "resolved_route must be a ResolvedRouteArtifact")
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

    ``escape_vcs`` is a designation, never a deadlock certificate.
    """
    if not isinstance(resolved_route, ResolvedRouteArtifact):
        raise VCAssignmentError(
            "resolved_route must be a ResolvedRouteArtifact")
    vc_count = _as_int("vc_count", vc_count)
    tc_pairs: list[tuple[str, tuple[int, ...]]] = []
    for cls, vcs in _authoring_pairs("traffic_class_to_vcs",
                                     traffic_class_to_vcs):
        if not isinstance(cls, str) or not cls:
            raise VCAssignmentError(
                "traffic class names must be non-empty strings")
        tc_pairs.append((cls, tuple(sorted(set(_int_tuple(
            f"traffic class {cls!r} VC set", vcs))))))
    tc_pairs.sort(key=lambda item: item[0])
    ids = tuple(range(vc_count))
    if vc_to_routing_class is None:
        default_cls = resolved_route.routing_classes[0]
        vc_routing = tuple((vc, default_cls) for vc in ids)
    else:
        vc_routing = tuple(sorted(
            (_as_int("vc id", vc), rc)
            for vc, rc in _authoring_pairs("vc_to_routing_class",
                                           vc_to_routing_class)))
    if allowed_transitions is None:
        transitions = tuple((vc, vc) for vc in ids)
    else:
        transitions = tuple(sorted({
            (_as_int("transition src", src), _as_int("transition dst", dst))
            for src, dst in _authoring_rows("allowed_transitions",
                                            allowed_transitions)
        }))
    artifact = VCAssignmentArtifact(
        resolved_route_hash=resolved_route.resolved_route_hash(),
        vc_count=vc_count,
        vc_ids=ids,
        traffic_class_to_vcs=tuple(tc_pairs),
        vc_to_routing_class=vc_routing,
        allowed_transitions=transitions,
        escape_vcs=tuple(sorted(set(
            _int_tuple("escape_vcs", escape_vcs, allow_empty=True)))),
        derivation=derivation,
    )
    artifact.validate_against(resolved_route)
    return artifact
