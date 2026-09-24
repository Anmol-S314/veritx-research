"""veritx_dse.model.vc_resource — routing-independent concrete VC resources.

``VCResourceArtifact`` answers exactly one question:

    Which concrete virtual-channel ids exist, which traffic classes may use
    them, and which concrete VC->VC transitions are legal?

It deliberately knows nothing about:

  * routing classes or routing roles (``adaptive``, ``escape``, ...);
  * escape routing or escape designations;
  * RouteArtifact / RoutingRelationArtifact / ResolvedRouteArtifact;
  * topology, design identity, backends or deadlock proofs.

The same concrete VC structure can occur in different designs, so the
artifact carries no design hash and no parent hash. ``derivation`` is
provenance: it round-trips but is excluded from semantic identity.

The sealed Slice-8 deterministic ``VCAssignmentArtifact`` is projected into
this model one way by ``vc_resources_from_assignment``; the reverse
projection is intentionally not offered because a generic VC resource
structure carries no routing-class binding.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.vc_assignment import VCAssignmentArtifact

VC_RESOURCE_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/VCResourceArtifact"


class VCResourceError(ValueError, SemanticError):
    """The VC resource structure is malformed — fail closed."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise VCResourceError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise VCResourceError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise VCResourceError(f"{where} is missing required field {key!r}")
    return d[key]


def _as_int(name: str, value: Any, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise VCResourceError(
            f"{name} must be an exact int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise VCResourceError(f"{name} must be >= {minimum}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise VCResourceError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


def _json_list(name: str, value: Any, *,
               allow_empty: bool = True) -> list[Any]:
    if not isinstance(value, list):
        raise VCResourceError(
            f"{name} must be a JSON list, got {type(value).__name__}")
    if not value and not allow_empty:
        raise VCResourceError(f"{name} must be non-empty")
    return value


def _json_int_list(name: str, value: Any, *,
                   allow_empty: bool = False) -> tuple[int, ...]:
    return tuple(_as_int(name, item)
                 for item in _json_list(name, value,
                                        allow_empty=allow_empty))


def _json_pair_list(name: str, value: Any) -> list[list[Any]]:
    rows = _json_list(name, value)
    out: list[list[Any]] = []
    for index, row in enumerate(rows):
        if type(row) is not list or len(row) != 2:
            raise VCResourceError(
                f"{name}[{index}] must be a two-element JSON list")
        out.append(row)
    return out


@dataclass(frozen=True)
class VCResourceArtifact:
    """Concrete VC universe, traffic eligibility and transition relation."""

    vc_count: int
    vc_ids: tuple[int, ...]
    traffic_class_to_vcs: tuple[tuple[str, tuple[int, ...]], ...]
    allowed_transitions: tuple[tuple[int, int], ...] = ()
    derivation: str = ""
    schema_version: int = VC_RESOURCE_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        _as_int("vc_count", self.vc_count, minimum=1)
        if not isinstance(self.vc_ids, tuple):
            raise VCResourceError("vc_ids must be a tuple")
        vc_ids = tuple(_as_int("vc_id", value) for value in self.vc_ids)
        if vc_ids != tuple(range(self.vc_count)):
            raise VCResourceError(
                "vc_ids must be exactly 0..vc_count-1 (canonical; no sparse "
                "or renamed VCs)")

        if not isinstance(self.traffic_class_to_vcs, tuple):
            raise VCResourceError(
                "traffic_class_to_vcs must be a tuple of (class, vcs) pairs")
        classes: list[tuple[str, tuple[int, ...]]] = []
        for item in self.traffic_class_to_vcs:
            if not isinstance(item, tuple) or len(item) != 2:
                raise VCResourceError(
                    "traffic_class_to_vcs entries must be (class, vcs) pairs")
            cls, vcs = item
            _as_str("traffic class name", cls)
            if not isinstance(vcs, tuple) or not vcs:
                raise VCResourceError(
                    f"traffic class {cls!r} must have a non-empty VC set")
            values = tuple(_as_int(f"traffic class {cls!r} VC", v) for v in vcs)
            if len(set(values)) != len(values):
                raise VCResourceError(
                    f"traffic class {cls!r} VC set has duplicate values")
            values = tuple(sorted(values))
            for vc in values:
                if not 0 <= vc < self.vc_count:
                    raise VCResourceError(
                        f"traffic class {cls!r} references VC {vc} outside "
                        f"0..{self.vc_count - 1}")
            classes.append((cls, values))
        if len({cls for cls, _vcs in classes}) != len(classes):
            raise VCResourceError("traffic class names must be unique")
        classes.sort(key=lambda item: item[0])

        if not isinstance(self.allowed_transitions, tuple):
            raise VCResourceError("allowed_transitions must be a tuple")
        transitions: list[tuple[int, int]] = []
        for item in self.allowed_transitions:
            if not isinstance(item, tuple) or len(item) != 2:
                raise VCResourceError(
                    "allowed_transitions entries must be (src, dst) pairs")
            src = _as_int("transition source VC", item[0])
            dst = _as_int("transition target VC", item[1])
            if not (0 <= src < self.vc_count and 0 <= dst < self.vc_count):
                raise VCResourceError(
                    f"transition ({src},{dst}) references a VC outside "
                    f"0..{self.vc_count - 1}")
            transitions.append((src, dst))
        if len(set(transitions)) != len(transitions):
            raise VCResourceError(
                "allowed transitions must be unique")
        transitions.sort()

        if not isinstance(self.derivation, str):
            raise VCResourceError("derivation must be a string")

        if type(self.schema_version) is not int or \
                self.schema_version != VC_RESOURCE_SCHEMA_VERSION:
            raise VCResourceError(
                f"unsupported vc-resource schema_version "
                f"{self.schema_version!r} (expected "
                f"{VC_RESOURCE_SCHEMA_VERSION})")

        object.__setattr__(self, "vc_ids", vc_ids)
        object.__setattr__(self, "traffic_class_to_vcs", tuple(classes))
        object.__setattr__(self, "allowed_transitions", tuple(transitions))

        expected = self._compute_hash()
        if self.artifact_hash:
            if not isinstance(self.artifact_hash, str) \
                    or self.artifact_hash != expected:
                raise VCResourceError(
                    "artifact_hash does not match the VC resources")
        else:
            object.__setattr__(self, "artifact_hash", expected)

    # ── identity ─────────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """Semantic identity; ``derivation`` is deliberately absent."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "vc_count": self.vc_count,
            "vc_ids": list(self.vc_ids),
            "traffic_class_to_vcs": [
                [cls, list(vcs)] for cls, vcs in self.traffic_class_to_vcs
            ],
            "allowed_transitions": [list(pair)
                                    for pair in self.allowed_transitions],
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["derivation"] = self.derivation
        d["artifact_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "VCResourceArtifact":
        allowed = frozenset({
            "type", "schema_version", "vc_count", "vc_ids",
            "traffic_class_to_vcs", "allowed_transitions", "derivation",
            "artifact_hash",
        })
        _strict_keys(d, allowed, "vc_resource")
        if _need(d, "type", "vc_resource") != _HASH_TYPE_TAG:
            raise VCResourceError(
                f"vc resource type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")

        raw_classes = _json_pair_list(
            "traffic_class_to_vcs",
            _need(d, "traffic_class_to_vcs", "vc_resource"))
        classes: list[tuple[str, tuple[int, ...]]] = []
        for index, row in enumerate(raw_classes):
            class_id = _as_str(
                f"traffic_class_to_vcs[{index}] class", row[0])
            vcs = _json_int_list(
                f"traffic_class_to_vcs[{index}] VC set", row[1])
            if list(vcs) != list(sorted(set(vcs))):
                raise VCResourceError(
                    f"traffic_class_to_vcs[{index}] VC set must be sorted "
                    "and unique")
            classes.append((class_id, vcs))
        if classes != sorted(classes, key=lambda item: item[0]) or \
                len({cls for cls, _vcs in classes}) != len(classes):
            raise VCResourceError(
                "traffic_class_to_vcs must be sorted by class name and "
                "unique")

        raw_transitions = _json_pair_list(
            "allowed_transitions",
            _need(d, "allowed_transitions", "vc_resource"))
        transitions: list[tuple[int, int]] = []
        for index, row in enumerate(raw_transitions):
            transitions.append((
                _as_int(f"allowed_transitions[{index}] source", row[0]),
                _as_int(f"allowed_transitions[{index}] target", row[1])))
        if tuple(transitions) != tuple(sorted(transitions)) or \
                len(set(transitions)) != len(transitions):
            raise VCResourceError(
                "allowed_transitions must be sorted and unique")

        artifact_hash = _need(d, "artifact_hash", "vc_resource")
        if not isinstance(artifact_hash, str) or not artifact_hash:
            raise VCResourceError("artifact_hash must be a non-empty string")
        derivation = _need(d, "derivation", "vc_resource")
        if not isinstance(derivation, str):
            raise VCResourceError("derivation must be a string")
        artifact = cls(
            vc_count=_need(d, "vc_count", "vc_resource"),
            vc_ids=_json_int_list("vc_ids", _need(d, "vc_ids",
                                                  "vc_resource")),
            traffic_class_to_vcs=tuple(classes),
            allowed_transitions=tuple(transitions),
            derivation=derivation,
            schema_version=_need(d, "schema_version", "vc_resource"),
        )
        if artifact_hash != artifact._compute_hash():
            raise VCResourceError(
                "artifact_hash does not match the VC resources")
        return artifact


def vc_resources_from_assignment(
        vc_assignment: VCAssignmentArtifact) -> VCResourceArtifact:
    """One-way projection of the sealed Slice-8 deterministic artifact.

    Copies only the routing-independent VC resources. ``resolved_route_hash``,
    ``vc_to_routing_class`` and ``escape_vcs`` are routing-specific and are
    intentionally dropped: the generic resource model has no routing
    authority.
    """
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise VCResourceError(
            "vc_assignment must be a VCAssignmentArtifact")
    return VCResourceArtifact(
        vc_count=vc_assignment.vc_count,
        vc_ids=tuple(vc_assignment.vc_ids),
        traffic_class_to_vcs=tuple(vc_assignment.traffic_class_to_vcs),
        allowed_transitions=tuple(vc_assignment.allowed_transitions),
        derivation=vc_assignment.derivation,
    )
