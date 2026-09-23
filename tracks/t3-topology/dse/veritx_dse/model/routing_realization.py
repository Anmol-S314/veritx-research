"""veritx_dse.model.routing_realization — executable routing identity.

``RoutingRealizationArtifact`` is one canonical **hardware-execution
identity** for routing, regardless of whether routing is represented by:

1. the deterministic route chain
   (``RouteArtifact`` -> ``ResolvedRouteArtifact`` -> ``VCAssignmentArtifact``);
   or
2. the adaptive/stateful relation chain
   (``RoutingPolicyDefinition`` -> ``RoutingRelationArtifact`` ->
   ``RoutingResourceBindingArtifact``).

It exists to separate *source artifact identity* and *proof/presentation
metadata* from *routing behavior that changes executable fabric semantics*.
A future ``FabricArtifact`` binds only ``routing_realization_hash`` instead
of embedding deterministic/adaptive routing internals.

Why a normalization layer is required:

* ``RoutingRelationArtifact`` and ``RoutingResourceBindingArtifact`` each
  contain ``policy_hash``, and ``RoutingPolicyDefinition`` identity includes
  non-execution fields: the presentation ``id`` and the verification
  ``deadlock_proof_obligation``. Binding either source hash directly would
  let a proof-method or naming change masquerade as a hardware change.
* ``VCAssignmentArtifact`` identity includes proof-oriented ``escape_vcs``
  designation; only ``VC -> routing class`` is deterministic-only execution
  semantics not already owned by ``VCResourceArtifact``.

Source hashes are retained as immutable, strictly validated provenance for
``validate_against_*`` and traceability, and deliberately do **not**
participate in ``routing_realization_hash``.

Both kinds bind ``topology_hash`` and ``vc_resource_hash`` as semantic
identity, so a realization cannot be transplanted onto another topology or
concrete VC-resource universe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id, thaw
from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.routing_policy import (
    ROUTING_POLICY_SCHEMA_VERSION, RoutingPolicyDefinition,
)
from veritx_dse.model.routing_relation import (
    ROUTING_RELATION_SCHEMA_VERSION, RoutingRelationArtifact,
)
from veritx_dse.model.routing_resource_binding import (
    ROUTING_RESOURCE_BINDING_SCHEMA_VERSION,
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_assignment import VCAssignmentArtifact
from veritx_dse.model.vc_resource import (
    VCResourceArtifact, vc_resources_from_assignment,
)

ROUTING_REALIZATION_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/RoutingRealizationArtifact"

# Dedicated projection domains.
_DETERMINISTIC_VC_ROUTING_DOMAIN = "srota/DeterministicVCRoutingSemantics/v1"
_POLICY_EXECUTION_DOMAIN = "srota/RoutingPolicyExecutionSemantics/v1"
_RELATION_EXECUTION_DOMAIN = "srota/RoutingRelationExecutionSemantics/v1"
_ADAPTIVE_ROUTING_DOMAIN = "srota/AdaptiveRoutingExecutionSemantics/v1"
_ADAPTIVE_VC_ROUTING_DOMAIN = "srota/AdaptiveVCRoutingSemantics/v1"


class RoutingRealizationError(ValueError):
    """The routing realization is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise RoutingRealizationError(
            f"{name} must be an exact int, got {type(value).__name__}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RoutingRealizationError(f"{name} must be a non-empty string")
    return value


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _as_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _is_hex64(value):
        raise RoutingRealizationError(
            f"{name} must be a 64-character lowercase hex digest")
    return value


def _as_source_hash(name: str, value: Any) -> str:
    """Source hashes may be bare digests or ``sha256:``-prefixed digests."""
    if not isinstance(value, str):
        raise RoutingRealizationError(
            f"{name} must be a hash string, got {type(value).__name__}")
    body = value[7:] if value.startswith("sha256:") else value
    if not _is_hex64(body):
        raise RoutingRealizationError(
            f"{name} must be a 64-character lowercase hex digest, optionally "
            "'sha256:'-prefixed")
    return value


def _require_enum(name: str, enum_cls: type[Enum], value: Any) -> None:
    if not isinstance(value, enum_cls):
        raise RoutingRealizationError(
            f"{name} must be a {enum_cls.__name__}, got "
            f"{type(value).__name__}")


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise RoutingRealizationError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise RoutingRealizationError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RoutingRealizationError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Enum:
    if not isinstance(value, str):
        raise RoutingRealizationError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise RoutingRealizationError(
            f"unknown {name} {value!r}; known: "
            f"{[member.value for member in enum_cls]}") from None


def _require_instance(name: str, value: Any, cls: type) -> None:
    if not isinstance(value, cls):
        raise RoutingRealizationError(
            f"{name} must be a {cls.__name__}, got {type(value).__name__}")


# ── vocabulary and source-hash authority ─────────────────────────────────

class RoutingRealizationKind(Enum):
    DETERMINISTIC = "deterministic"
    ADAPTIVE = "adaptive"


_SOURCE_NAMES_BY_KIND = {
    RoutingRealizationKind.DETERMINISTIC: (
        "resolved_route_hash", "route_hash", "vc_assignment_hash"),
    RoutingRealizationKind.ADAPTIVE: (
        "policy_hash", "relation_hash", "routing_resource_binding_hash"),
}


def _validate_source_hashes(
        kind: RoutingRealizationKind,
        source_hashes: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(source_hashes, tuple):
        raise RoutingRealizationError("source_hashes must be a tuple")
    allowed = _SOURCE_NAMES_BY_KIND[kind]
    names: list[str] = []
    rows: list[tuple[str, str]] = []
    for row in source_hashes:
        if not isinstance(row, tuple) or len(row) != 2:
            raise RoutingRealizationError(
                "source_hashes rows must be (name, hash) pairs")
        name, digest = row
        _as_str("source hash name", name)
        _as_source_hash(f"source hash {name!r}", digest)
        names.append(name)
        rows.append((name, digest))
    if len(set(names)) != len(names):
        raise RoutingRealizationError("source hash names must be unique")
    if tuple(names) != allowed:
        extra = sorted(set(names) - set(allowed))
        missing = sorted(set(allowed) - set(names))
        raise RoutingRealizationError(
            f"{kind.value} source hashes must be exactly {list(allowed)} "
            f"(missing {missing}, extra {extra})")
    return tuple(rows)


# ── deterministic VC-routing semantics ───────────────────────────────────

def deterministic_vc_routing_semantics_hash(
        vc_assignment: VCAssignmentArtifact) -> str:
    """Project only ``VC -> routing class`` for deterministic routing.

    The generic VC universe, traffic-class eligibility and legal concrete
    transitions are owned by ``VCResourceArtifact``. ``resolved_route_hash``
    is already bound by the deterministic ``routing_semantics_hash``.
    ``escape_vcs`` is a proof/interpretation designation consumed only by
    verification modules, not by canonical execution semantics, so it is
    excluded.
    """
    _require_instance("vc_assignment", vc_assignment, VCAssignmentArtifact)
    payload = {
        "vc_to_routing_class": [[vc, routing_class]
                                for vc, routing_class
                                in vc_assignment.vc_to_routing_class],
    }
    return content_id(_DETERMINISTIC_VC_ROUTING_DOMAIN, payload)


# ── adaptive policy execution semantics ──────────────────────────────────

# Every RoutingPolicyDefinition identity field is classified as exactly one
# of: EXECUTION (hardware), PRESENTATION, VERIFICATION. The classification
# is a hard gate: policy_execution_semantics_dict() fails closed if the
# supplied policy has an identity field this module has not classified.
_POLICY_EXECUTION_FIELDS = (
    "algorithm", "algorithm_version", "path_mode", "decision_scope",
    "candidate_mode", "selection_locus", "randomness", "state_requirements",
    "runtime_observations", "resource_roles", "allowed_role_transitions",
    "parameters",
)
_POLICY_PRESENTATION_FIELDS = ("id",)
_POLICY_VERIFICATION_FIELDS = ("deadlock_proof_obligation",)
_POLICY_CLASSIFIED_FIELDS = (
    _POLICY_EXECUTION_FIELDS + _POLICY_PRESENTATION_FIELDS
    + _POLICY_VERIFICATION_FIELDS)

_POLICY_VALUE_EXTRACTORS = {
    "algorithm": lambda p: p.algorithm,
    "algorithm_version": lambda p: p.algorithm_version,
    "path_mode": lambda p: p.path_mode.value,
    "decision_scope": lambda p: p.decision_scope.value,
    "candidate_mode": lambda p: p.candidate_mode.value,
    "selection_locus": lambda p: p.selection_locus.value,
    "randomness": lambda p: p.randomness.value,
    "state_requirements": lambda p: [s.to_dict()
                                     for s in p.state_requirements],
    "runtime_observations": lambda p: [o.value
                                       for o in p.runtime_observations],
    "resource_roles": lambda p: [r.to_dict() for r in p.resource_roles],
    "allowed_role_transitions": lambda p: [list(t)
                                           for t in p.allowed_role_transitions],
    "parameters": lambda p: thaw(p.parameters),
}


def policy_execution_semantics_dict(
        policy: RoutingPolicyDefinition) -> dict[str, Any]:
    """EXECUTION-only projection of a routing policy definition.

    Excludes presentation ``id`` and verification
    ``deadlock_proof_obligation``. Fails closed if any identity field is not
    explicitly classified.
    """
    _require_instance("policy", policy, RoutingPolicyDefinition)
    if policy.schema_version != ROUTING_POLICY_SCHEMA_VERSION:
        raise RoutingRealizationError(
            f"UNSUPPORTED routing policy schema_version "
            f"{policy.schema_version!r} (expected "
            f"{ROUTING_POLICY_SCHEMA_VERSION})")
    identity_keys = set(policy.identity_dict())
    classified = set(_POLICY_CLASSIFIED_FIELDS) | {"type", "schema_version"}
    if identity_keys != classified:
        unclassified = sorted(identity_keys - classified)
        raise RoutingRealizationError(
            "unclassified RoutingPolicyDefinition identity fields: "
            f"{unclassified}; classify each as execution, presentation or "
            "verification before this projection may be used")
    return {name: _POLICY_VALUE_EXTRACTORS[name](policy)
            for name in _POLICY_EXECUTION_FIELDS}


def routing_policy_execution_semantics_hash(
        policy: RoutingPolicyDefinition) -> str:
    return content_id(_POLICY_EXECUTION_DOMAIN,
                      policy_execution_semantics_dict(policy))


# ── adaptive relation execution semantics ────────────────────────────────

_RELATION_IDENTITY_FIELDS = frozenset({
    "type", "schema_version", "topology_hash", "policy_hash",
    "state_domains", "decisions",
})


def relation_execution_semantics_dict(
        relation: RoutingRelationArtifact) -> dict[str, Any]:
    """Project exactly the relation behavior: topology, states, decisions.

    Excludes ``policy_hash`` (policy execution semantics are hashed
    separately) and all serialization/type metadata. Every context, action,
    channel id, next role, next state, priority and EJECT semantic is
    retained because ``RoutingDecision.to_dict`` is used verbatim.
    """
    _require_instance("relation", relation, RoutingRelationArtifact)
    if relation.schema_version != ROUTING_RELATION_SCHEMA_VERSION:
        raise RoutingRealizationError(
            f"UNSUPPORTED routing relation schema_version "
            f"{relation.schema_version!r} (expected "
            f"{ROUTING_RELATION_SCHEMA_VERSION})")
    if set(relation.identity_dict()) != _RELATION_IDENTITY_FIELDS:
        raise RoutingRealizationError(
            "unclassified RoutingRelationArtifact identity fields: "
            f"{sorted(set(relation.identity_dict()) - _RELATION_IDENTITY_FIELDS)}")
    return {
        "topology_hash": relation.topology_hash,
        "state_domains": [domain.to_dict() for domain in relation.state_domains],
        "decisions": [decision.to_dict() for decision in relation.decisions],
    }


def routing_relation_execution_semantics_hash(
        relation: RoutingRelationArtifact) -> str:
    return content_id(_RELATION_EXECUTION_DOMAIN,
                      relation_execution_semantics_dict(relation))


def adaptive_routing_semantics_hash(
        policy: RoutingPolicyDefinition,
        relation: RoutingRelationArtifact) -> str:
    """Combine policy + relation execution semantics for adaptive routing."""
    payload = {
        "policy_execution_semantics_hash":
            routing_policy_execution_semantics_hash(policy),
        "relation_execution_semantics_hash":
            routing_relation_execution_semantics_hash(relation),
    }
    return content_id(_ADAPTIVE_ROUTING_DOMAIN, payload)


# ── adaptive role -> VC projection ───────────────────────────────────────

_BINDING_IDENTITY_FIELDS = frozenset({
    "type", "schema_version", "policy_hash", "vc_resource_hash",
    "role_to_vcs",
})


def adaptive_vc_routing_semantics_dict(
        binding: RoutingResourceBindingArtifact) -> dict[str, Any]:
    """Project the concrete role -> VC partition, excluding ``policy_hash``."""
    _require_instance("binding", binding, RoutingResourceBindingArtifact)
    if binding.schema_version != ROUTING_RESOURCE_BINDING_SCHEMA_VERSION:
        raise RoutingRealizationError(
            f"UNSUPPORTED routing resource binding schema_version "
            f"{binding.schema_version!r} (expected "
            f"{ROUTING_RESOURCE_BINDING_SCHEMA_VERSION})")
    if set(binding.identity_dict()) != _BINDING_IDENTITY_FIELDS:
        raise RoutingRealizationError(
            "unclassified RoutingResourceBindingArtifact identity fields: "
            f"{sorted(set(binding.identity_dict()) - _BINDING_IDENTITY_FIELDS)}")
    return {
        "vc_resource_hash": binding.vc_resource_hash,
        "role_to_vcs": [[role_id, list(vcs)]
                        for role_id, vcs in binding.role_to_vcs],
    }


def adaptive_vc_routing_semantics_hash(
        binding: RoutingResourceBindingArtifact) -> str:
    return content_id(_ADAPTIVE_VC_ROUTING_DOMAIN,
                      adaptive_vc_routing_semantics_dict(binding))


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingRealizationArtifact:
    """Hardware-execution identity for one routing realization."""

    kind: RoutingRealizationKind
    topology_hash: str
    vc_resource_hash: str
    routing_semantics_hash: str
    vc_routing_semantics_hash: str
    source_hashes: tuple[tuple[str, str], ...]
    schema_version: int = ROUTING_REALIZATION_SCHEMA_VERSION
    routing_realization_hash: str = ""

    def __post_init__(self):
        _require_enum("kind", RoutingRealizationKind, self.kind)
        _as_hash("topology_hash", self.topology_hash)
        _as_hash("vc_resource_hash", self.vc_resource_hash)
        _as_hash("routing_semantics_hash", self.routing_semantics_hash)
        _as_hash("vc_routing_semantics_hash",
                 self.vc_routing_semantics_hash)
        object.__setattr__(
            self, "source_hashes",
            _validate_source_hashes(self.kind, self.source_hashes))
        if type(self.schema_version) is not int or \
                self.schema_version != ROUTING_REALIZATION_SCHEMA_VERSION:
            raise RoutingRealizationError(
                f"unsupported routing-realization schema_version "
                f"{self.schema_version!r} (expected "
                f"{ROUTING_REALIZATION_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.routing_realization_hash:
            _as_hash("routing_realization_hash",
                     self.routing_realization_hash)
            if self.routing_realization_hash != expected:
                raise RoutingRealizationError(
                    "routing_realization_hash does not match content")
        else:
            object.__setattr__(self, "routing_realization_hash", expected)

    # ── identity (source hashes excluded) ──────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "topology_hash": self.topology_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "routing_semantics_hash": self.routing_semantics_hash,
            "vc_routing_semantics_hash": self.vc_routing_semantics_hash,
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def source_hash(self, name: str) -> str:
        """Provenance lookup; never part of hardware identity."""
        for row_name, digest in self.source_hashes:
            if row_name == name:
                return digest
        raise RoutingRealizationError(f"unknown source hash {name!r}")

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["source_hashes"] = [[name, digest]
                              for name, digest in self.source_hashes]
        d["routing_realization_hash"] = self._compute_hash()
        return d

    # ── persisted parsing (validate, never repair) ─────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "RoutingRealizationArtifact":
        allowed = frozenset({
            "type", "schema_version", "kind", "topology_hash",
            "vc_resource_hash", "routing_semantics_hash",
            "vc_routing_semantics_hash", "source_hashes",
            "routing_realization_hash",
        })
        _strict_keys(d, allowed, "routing_realization")
        if _need(d, "type", "routing_realization") != _HASH_TYPE_TAG:
            raise RoutingRealizationError(
                f"routing realization type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        raw_sources = _need(d, "source_hashes", "routing_realization")
        if not isinstance(raw_sources, list):
            raise RoutingRealizationError(
                "routing_realization.source_hashes must be a JSON list")
        rows: list[tuple[str, str]] = []
        for row in raw_sources:
            if not isinstance(row, list) or len(row) != 2:
                raise RoutingRealizationError(
                    "source_hashes rows must be [name, hash] pairs")
            rows.append((row[0], row[1]))
        return cls(
            kind=_enum("routing realization kind", RoutingRealizationKind,
                       _need(d, "kind", "routing_realization")),
            topology_hash=_need(d, "topology_hash", "routing_realization"),
            vc_resource_hash=_need(d, "vc_resource_hash",
                                   "routing_realization"),
            routing_semantics_hash=_need(
                d, "routing_semantics_hash", "routing_realization"),
            vc_routing_semantics_hash=_need(
                d, "vc_routing_semantics_hash", "routing_realization"),
            source_hashes=tuple(rows),
            schema_version=_need(d, "schema_version", "routing_realization"),
            routing_realization_hash=_need(
                d, "routing_realization_hash", "routing_realization"),
        )

    # ── parent validation ──────────────────────────────────────────────
    def _check_common(self, topology: TopologyArtifact,
                      vc_resource: VCResourceArtifact) -> None:
        if self.topology_hash != topology.topology_hash():
            raise RoutingRealizationError(
                "topology_hash does not match the materialized topology")
        if self.vc_resource_hash != vc_resource.artifact_hash:
            raise RoutingRealizationError(
                "vc_resource_hash does not match the VC resource artifact")
        if self.routing_realization_hash != self._compute_hash():
            raise RoutingRealizationError(
                "routing_realization_hash does not match content")

    def validate_against_deterministic(
            self, *, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            route: RouteArtifact,
            resolved_route: ResolvedRouteArtifact,
            vc_assignment: VCAssignmentArtifact,
            vc_resource: VCResourceArtifact) -> None:
        """Prove the full deterministic chain and every source hash."""
        if self.kind is not RoutingRealizationKind.DETERMINISTIC:
            raise RoutingRealizationError(
                "validate_against_deterministic requires a DETERMINISTIC "
                "realization")
        _require_instance("topology", topology, TopologyArtifact)
        _require_instance("attachment", attachment, AgentAttachmentArtifact)
        _require_instance("route", route, RouteArtifact)
        _require_instance("resolved_route", resolved_route,
                          ResolvedRouteArtifact)
        _require_instance("vc_assignment", vc_assignment,
                          VCAssignmentArtifact)
        _require_instance("vc_resource", vc_resource, VCResourceArtifact)
        try:
            route.validate_against(topology)
            resolved_route.validate_against(topology, attachment, route)
            vc_assignment.validate_against(resolved_route)
        except ValueError as exc:
            raise RoutingRealizationError(
                f"deterministic routing chain is not legal: {exc}") from exc
        projection = vc_resources_from_assignment(vc_assignment)
        if projection.artifact_hash != vc_resource.artifact_hash:
            raise RoutingRealizationError(
                "supplied VCResourceArtifact is not the routing-independent "
                "projection of the deterministic VCAssignmentArtifact")
        self._check_common(topology, vc_resource)
        if self.routing_semantics_hash != resolved_route.resolved_route_hash():
            raise RoutingRealizationError(
                "routing_semantics_hash does not match the resolved route")
        if self.vc_routing_semantics_hash != \
                deterministic_vc_routing_semantics_hash(vc_assignment):
            raise RoutingRealizationError(
                "vc_routing_semantics_hash does not match the deterministic "
                "VC -> routing-class projection")
        expected_sources = (
            ("resolved_route_hash", resolved_route.resolved_route_hash()),
            ("route_hash", route.artifact_hash),
            ("vc_assignment_hash", vc_assignment.vc_assignment_hash()),
        )
        if self.source_hashes != expected_sources:
            raise RoutingRealizationError(
                "source_hashes do not match the supplied deterministic "
                "routing artifacts")

    def validate_against_adaptive(
            self, *, topology: TopologyArtifact,
            policy: RoutingPolicyDefinition,
            relation: RoutingRelationArtifact,
            vc_resource: VCResourceArtifact,
            binding: RoutingResourceBindingArtifact) -> None:
        """Prove the full adaptive chain and every source hash."""
        if self.kind is not RoutingRealizationKind.ADAPTIVE:
            raise RoutingRealizationError(
                "validate_against_adaptive requires an ADAPTIVE realization")
        _require_instance("topology", topology, TopologyArtifact)
        _require_instance("policy", policy, RoutingPolicyDefinition)
        _require_instance("relation", relation, RoutingRelationArtifact)
        _require_instance("vc_resource", vc_resource, VCResourceArtifact)
        _require_instance("binding", binding,
                          RoutingResourceBindingArtifact)
        try:
            relation.validate_against(topology, policy)
            binding.validate_against(policy, vc_resource)
        except ValueError as exc:
            raise RoutingRealizationError(
                f"adaptive routing chain is not legal: {exc}") from exc
        self._check_common(topology, vc_resource)
        if self.routing_semantics_hash != \
                adaptive_routing_semantics_hash(policy, relation):
            raise RoutingRealizationError(
                "routing_semantics_hash does not match the adaptive "
                "execution-semantics projection")
        if self.vc_routing_semantics_hash != \
                adaptive_vc_routing_semantics_hash(binding):
            raise RoutingRealizationError(
                "vc_routing_semantics_hash does not match the adaptive "
                "role -> VC projection")
        expected_sources = (
            ("policy_hash", policy.policy_hash),
            ("relation_hash", relation.relation_hash),
            ("routing_resource_binding_hash", binding.binding_hash),
        )
        if self.source_hashes != expected_sources:
            raise RoutingRealizationError(
                "source_hashes do not match the supplied adaptive routing "
                "artifacts")


# ── builders ─────────────────────────────────────────────────────────────

def make_deterministic_routing_realization(
        *, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        route: RouteArtifact,
        resolved_route: ResolvedRouteArtifact,
        vc_assignment: VCAssignmentArtifact,
        vc_resource: VCResourceArtifact) -> RoutingRealizationArtifact:
    """Normalize the deterministic route chain into hardware identity."""
    for name, value, cls in (
            ("topology", topology, TopologyArtifact),
            ("attachment", attachment, AgentAttachmentArtifact),
            ("route", route, RouteArtifact),
            ("resolved_route", resolved_route, ResolvedRouteArtifact),
            ("vc_assignment", vc_assignment, VCAssignmentArtifact),
            ("vc_resource", vc_resource, VCResourceArtifact)):
        _require_instance(name, value, cls)
    artifact = RoutingRealizationArtifact(
        kind=RoutingRealizationKind.DETERMINISTIC,
        topology_hash=topology.topology_hash(),
        vc_resource_hash=vc_resource.artifact_hash,
        routing_semantics_hash=resolved_route.resolved_route_hash(),
        vc_routing_semantics_hash=deterministic_vc_routing_semantics_hash(
            vc_assignment),
        source_hashes=(
            ("resolved_route_hash", resolved_route.resolved_route_hash()),
            ("route_hash", route.artifact_hash),
            ("vc_assignment_hash", vc_assignment.vc_assignment_hash()),
        ),
    )
    artifact.validate_against_deterministic(
        topology=topology, attachment=attachment, route=route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        vc_resource=vc_resource)
    return artifact


def make_adaptive_routing_realization(
        *, topology: TopologyArtifact,
        policy: RoutingPolicyDefinition,
        relation: RoutingRelationArtifact,
        vc_resource: VCResourceArtifact,
        binding: RoutingResourceBindingArtifact
) -> RoutingRealizationArtifact:
    """Normalize the adaptive relation chain into hardware identity."""
    for name, value, cls in (
            ("topology", topology, TopologyArtifact),
            ("policy", policy, RoutingPolicyDefinition),
            ("relation", relation, RoutingRelationArtifact),
            ("vc_resource", vc_resource, VCResourceArtifact),
            ("binding", binding, RoutingResourceBindingArtifact)):
        _require_instance(name, value, cls)
    artifact = RoutingRealizationArtifact(
        kind=RoutingRealizationKind.ADAPTIVE,
        topology_hash=topology.topology_hash(),
        vc_resource_hash=vc_resource.artifact_hash,
        routing_semantics_hash=adaptive_routing_semantics_hash(policy,
                                                               relation),
        vc_routing_semantics_hash=adaptive_vc_routing_semantics_hash(binding),
        source_hashes=(
            ("policy_hash", policy.policy_hash),
            ("relation_hash", relation.relation_hash),
            ("routing_resource_binding_hash", binding.binding_hash),
        ),
    )
    artifact.validate_against_adaptive(
        topology=topology, policy=policy, relation=relation,
        vc_resource=vc_resource, binding=binding)
    return artifact
