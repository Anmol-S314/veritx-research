"""veritx_dse.model.routing_policy — backend-independent routing semantics.

``RoutingPolicyDefinition`` describes what a routing algorithm requires and
permits. It is deliberately none of the following:

  * not an executable route table (``RouteArtifact`` remains the
    authoritative deterministic singleton realization);
  * not a deadlock proof — ``deadlock_proof_obligation`` names the proof
    family a verifier must apply, never a verdict;
  * not a BookSim routing-function name or backend configuration record.

The definition is a reusable, content-addressed semantic object. Two
backends that implement the same routing behavior can reference the same
``policy_hash``; backend executables, seeds and simulator names never enter
the identity.

Later materialization splits by ``candidate_mode``:

    MINIMAL/STATIC/SINGLETON policies  -> existing RouteArtifact
    adaptive/stateful policies         -> a future relation artifact

The semantic dimensions:

  * path_mode, decision_scope, candidate_mode, selection_locus;
  * state_requirements (named packet-routing state, e.g. phase);
  * runtime_observations (what the policy may observe while deciding);
  * randomness;
  * resource_roles and allowed_role_transitions (semantic role ids only —
    concrete VC binding is a separate future artifact);
  * deadlock_proof_obligation (the proof family that must be discharged);
  * immutable semantic parameters.

Only universally safe structural implications are enforced: STATIC policies
may not require runtime observations or RNG. Nothing here assumes that
adaptive means minimal, that multiple roles mean multiple VCs, or that an
escape designation proves deadlock freedom.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import (
    ImmutableError, content_id, freeze, thaw,
)

ROUTING_POLICY_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/RoutingPolicyDefinition"


class RoutingPolicyError(ValueError, SemanticError):
    """The routing-policy definition is malformed — fail closed."""


# ── closed semantic vocabularies ─────────────────────────────────────────

class PathMode(Enum):
    """Whether the policy may take only minimal paths."""
    MINIMAL = "minimal"
    NONMINIMAL = "nonminimal"
    MIXED = "mixed"


class DecisionScope(Enum):
    """When the routing decision is made."""
    STATIC = "static"
    SOURCE_COMMIT = "source_commit"
    PER_HOP = "per_hop"


class CandidateMode(Enum):
    """What a routing decision yields."""
    SINGLETON = "singleton"
    CANDIDATE_SET = "candidate_set"


class SelectionLocus(Enum):
    """Who selects among the candidates."""
    ROUTE_COMPUTE = "route_compute"
    ROUTER_ALLOCATOR = "router_allocator"


class RandomnessMode(Enum):
    """Whether the decision may consume randomness."""
    NONE = "none"
    RNG = "rng"


class RoutingStateKind(Enum):
    """Kind of packet-routing state a policy requires."""
    ROUTE_ORDER = "route_order"
    PHASE = "phase"
    INTERMEDIATE_NODE = "intermediate_node"
    RING_PARTITION = "ring_partition"
    DROP_TAP = "drop_tap"
    CUSTOM = "custom"


class RuntimeObservation(Enum):
    """Dynamic information a policy may observe while deciding."""
    INGRESS_CHANNEL = "ingress_channel"
    CURRENT_VC = "current_vc"
    OUTPUT_CREDIT_OCCUPANCY = "output_credit_occupancy"
    FAULT_STATE = "fault_state"
    CUSTOM = "custom"


class RoutingResourceRoleKind(Enum):
    """Semantic role a routing resource (e.g. a VC subnetwork) plays."""
    DEFAULT = "default"
    ADAPTIVE = "adaptive"
    ESCAPE = "escape"
    PHASE = "phase"
    ROUTE_ORDER = "route_order"
    RING = "ring"
    TAP = "tap"
    CUSTOM = "custom"


class DeadlockProofObligation(Enum):
    """The proof family an independent verifier must apply.

    Naming the obligation is not passing it: no member of this enum is a
    verdict, and this artifact carries no verdict field.
    """
    DETERMINISTIC_CDG = "deterministic_cdg"
    ESCAPE_SUBFUNCTION = "escape_subfunction"
    RESOURCE_ORDERING = "resource_ordering"
    TOPOLOGY_SPECIFIC = "topology_specific"
    EXTERNAL = "external"


# ── strict parsing helpers ───────────────────────────────────────────────

def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise RoutingPolicyError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise RoutingPolicyError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RoutingPolicyError(f"{where} is missing required field {key!r}")
    return d[key]


def _as_str(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise RoutingPolicyError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


def _as_int(name: str, value: Any, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise RoutingPolicyError(
            f"{name} must be an int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise RoutingPolicyError(f"{name} must be >= {minimum}")
    return value


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Any:
    if not isinstance(value, str):
        raise RoutingPolicyError(
            f"{name} must be one of "
            f"{[m.value for m in enum_cls]}, got {value!r}")
    try:
        return enum_cls(value)
    except ValueError:
        raise RoutingPolicyError(
            f"{name} {value!r} is not one of "
            f"{[m.value for m in enum_cls]}") from None


def _json_list(name: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise RoutingPolicyError(
            f"{name} must be a JSON list, got {type(value).__name__}")
    return value


# ── value types ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingStateRequirement:
    """One named piece of packet-routing state a policy requires."""

    name: str
    kind: RoutingStateKind

    def __post_init__(self):
        _as_str("state name", self.name)
        if not isinstance(self.kind, RoutingStateKind):
            raise RoutingPolicyError(
                f"state kind must be a RoutingStateKind, got "
                f"{type(self.kind).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind.value}

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingStateRequirement":
        _strict_keys(d, frozenset({"name", "kind"}), "state_requirement")
        return cls(
            name=_as_str("state name", _need(d, "name", "state_requirement")),
            kind=_enum("state kind", RoutingStateKind,
                       _need(d, "kind", "state_requirement")))


@dataclass(frozen=True)
class RoutingResourceRole:
    """One semantic role; role ids are unique within a policy."""

    id: str
    kind: RoutingResourceRoleKind

    def __post_init__(self):
        _as_str("role id", self.id)
        if not isinstance(self.kind, RoutingResourceRoleKind):
            raise RoutingPolicyError(
                f"role kind must be a RoutingResourceRoleKind, got "
                f"{type(self.kind).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind.value}

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingResourceRole":
        _strict_keys(d, frozenset({"id", "kind"}), "resource_role")
        return cls(
            id=_as_str("role id", _need(d, "id", "resource_role")),
            kind=_enum("role kind", RoutingResourceRoleKind,
                       _need(d, "kind", "resource_role")))


# ── the definition ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingPolicyDefinition:
    """Strict, immutable, content-addressed routing-policy semantics."""

    id: str
    algorithm: str
    algorithm_version: int
    path_mode: PathMode
    decision_scope: DecisionScope
    candidate_mode: CandidateMode
    selection_locus: SelectionLocus
    randomness: RandomnessMode
    deadlock_proof_obligation: DeadlockProofObligation
    state_requirements: tuple[RoutingStateRequirement, ...] = ()
    runtime_observations: tuple[RuntimeObservation, ...] = ()
    resource_roles: tuple[RoutingResourceRole, ...] = ()
    allowed_role_transitions: tuple[tuple[str, str], ...] = ()
    parameters: Any = field(default_factory=dict)
    schema_version: int = ROUTING_POLICY_SCHEMA_VERSION
    policy_hash: str = ""

    def __post_init__(self):
        _as_str("id", self.id)
        _as_str("algorithm", self.algorithm)
        _as_int("algorithm_version", self.algorithm_version, minimum=1)
        for name, enum_cls in (
                ("path_mode", PathMode),
                ("decision_scope", DecisionScope),
                ("candidate_mode", CandidateMode),
                ("selection_locus", SelectionLocus),
                ("randomness", RandomnessMode),
                ("deadlock_proof_obligation", DeadlockProofObligation)):
            value = getattr(self, name)
            if not isinstance(value, enum_cls):
                raise RoutingPolicyError(
                    f"{name} must be a {enum_cls.__name__}, got "
                    f"{type(value).__name__}")

        states = tuple(self.state_requirements)
        for state in states:
            if not isinstance(state, RoutingStateRequirement):
                raise RoutingPolicyError(
                    "state_requirements must contain "
                    "RoutingStateRequirement")
        if len({s.name for s in states}) != len(states):
            raise RoutingPolicyError("state requirement names must be unique")
        states = tuple(sorted(states, key=lambda s: s.name))

        observations = tuple(self.runtime_observations)
        for observation in observations:
            if not isinstance(observation, RuntimeObservation):
                raise RoutingPolicyError(
                    "runtime_observations must contain RuntimeObservation")
        if len(set(observations)) != len(observations):
            raise RoutingPolicyError(
                "runtime observations must be unique")
        observations = tuple(sorted(observations, key=lambda o: o.value))

        roles = tuple(self.resource_roles)
        for role in roles:
            if not isinstance(role, RoutingResourceRole):
                raise RoutingPolicyError(
                    "resource_roles must contain RoutingResourceRole")
        if len({r.id for r in roles}) != len(roles):
            raise RoutingPolicyError("resource role ids must be unique")
        roles = tuple(sorted(roles, key=lambda r: r.id))
        declared = {r.id for r in roles}

        transitions: list[tuple[str, str]] = []
        for item in self.allowed_role_transitions:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise RoutingPolicyError(
                    "allowed_role_transitions entries must be (source, "
                    "target) pairs")
            source = _as_str("transition source", item[0])
            target = _as_str("transition target", item[1])
            if source not in declared or target not in declared:
                raise RoutingPolicyError(
                    f"transition ({source},{target}) references an "
                    f"undeclared role (declared: {sorted(declared)})")
            transitions.append((source, target))
        if len(set(transitions)) != len(transitions):
            raise RoutingPolicyError(
                "allowed role transitions must be unique")
        canonical_transitions = tuple(sorted(transitions))

        if self.decision_scope == DecisionScope.STATIC:
            if observations:
                raise RoutingPolicyError(
                    "STATIC policies must not require runtime observations")
            if self.randomness != RandomnessMode.NONE:
                raise RoutingPolicyError(
                    "STATIC policies must not use RNG")

        if not isinstance(self.parameters, Mapping):
            raise RoutingPolicyError(
                "parameters must be a mapping of semantic parameters")
        try:
            frozen_parameters = freeze(dict(self.parameters))
        except ImmutableError as exc:
            raise RoutingPolicyError(
                f"parameters are not canonical immutable values: {exc}"
            ) from exc

        if type(self.schema_version) is not int or \
                self.schema_version != ROUTING_POLICY_SCHEMA_VERSION:
            raise RoutingPolicyError(
                f"unsupported routing-policy schema_version "
                f"{self.schema_version!r} (expected "
                f"{ROUTING_POLICY_SCHEMA_VERSION})")

        object.__setattr__(self, "state_requirements", states)
        object.__setattr__(self, "runtime_observations", observations)
        object.__setattr__(self, "resource_roles", roles)
        object.__setattr__(self, "allowed_role_transitions",
                           canonical_transitions)
        object.__setattr__(self, "parameters", frozen_parameters)

        expected = self._compute_hash()
        if self.policy_hash:
            if not isinstance(self.policy_hash, str) \
                    or self.policy_hash != expected:
                raise RoutingPolicyError(
                    "policy_hash does not match the policy semantics")
        else:
            object.__setattr__(self, "policy_hash", expected)

    # ── identity ─────────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """Semantic identity: no backend names, provenance or runtime data."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "id": self.id,
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "path_mode": self.path_mode.value,
            "decision_scope": self.decision_scope.value,
            "candidate_mode": self.candidate_mode.value,
            "selection_locus": self.selection_locus.value,
            "state_requirements": [s.to_dict() for s in self.state_requirements],
            "runtime_observations": [o.value for o in self.runtime_observations],
            "randomness": self.randomness.value,
            "resource_roles": [r.to_dict() for r in self.resource_roles],
            "allowed_role_transitions": [list(t)
                                         for t in self.allowed_role_transitions],
            "deadlock_proof_obligation": self.deadlock_proof_obligation.value,
            "parameters": thaw(self.parameters),
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def policy_hash_value(self) -> str:
        """The recomputed content identity (the stored field must equal it)."""
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["policy_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingPolicyDefinition":
        allowed = frozenset({
            "type", "schema_version", "id", "algorithm", "algorithm_version",
            "path_mode", "decision_scope", "candidate_mode",
            "selection_locus", "state_requirements", "runtime_observations",
            "randomness", "resource_roles", "allowed_role_transitions",
            "deadlock_proof_obligation", "parameters", "policy_hash",
        })
        _strict_keys(d, allowed, "routing_policy")
        if _need(d, "type", "routing_policy") != _HASH_TYPE_TAG:
            raise RoutingPolicyError(
                f"routing policy type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")

        states = tuple(RoutingStateRequirement.from_dict(item)
                       for item in _json_list(
                           "state_requirements",
                           _need(d, "state_requirements", "routing_policy")))
        if states != tuple(sorted(states, key=lambda s: s.name)):
            raise RoutingPolicyError(
                "state_requirements must be sorted by name")
        if len({s.name for s in states}) != len(states):
            raise RoutingPolicyError("state requirement names must be unique")

        observations = tuple(_enum(
            "runtime_observations", RuntimeObservation, item)
            for item in _json_list(
                "runtime_observations",
                _need(d, "runtime_observations", "routing_policy")))
        if observations != tuple(sorted(observations, key=lambda o: o.value)):
            raise RoutingPolicyError(
                "runtime_observations must be sorted and unique")

        roles = tuple(RoutingResourceRole.from_dict(item)
                      for item in _json_list(
                          "resource_roles",
                          _need(d, "resource_roles", "routing_policy")))
        if roles != tuple(sorted(roles, key=lambda r: r.id)):
            raise RoutingPolicyError("resource_roles must be sorted by id")
        if len({r.id for r in roles}) != len(roles):
            raise RoutingPolicyError("resource role ids must be unique")

        transitions: list[tuple[str, str]] = []
        for index, row in enumerate(_json_list(
                "allowed_role_transitions",
                _need(d, "allowed_role_transitions", "routing_policy"))):
            if type(row) is not list or len(row) != 2:
                raise RoutingPolicyError(
                    f"allowed_role_transitions[{index}] must be a "
                    "two-element JSON list")
            transitions.append((_as_str(
                f"allowed_role_transitions[{index}] source", row[0]),
                _as_str(f"allowed_role_transitions[{index}] target",
                        row[1])))
        if tuple(transitions) != tuple(sorted(transitions)):
            raise RoutingPolicyError(
                "allowed_role_transitions must be sorted and unique")
        if len(set(transitions)) != len(transitions):
            raise RoutingPolicyError(
                "allowed role transitions must be unique")

        raw_parameters = _need(d, "parameters", "routing_policy")
        if not isinstance(raw_parameters, dict):
            raise RoutingPolicyError(
                "parameters must be a JSON object, got "
                f"{type(raw_parameters).__name__}")

        artifact = cls(
            id=_need(d, "id", "routing_policy"),
            algorithm=_need(d, "algorithm", "routing_policy"),
            algorithm_version=_need(d, "algorithm_version", "routing_policy"),
            path_mode=_enum("path_mode", PathMode,
                            _need(d, "path_mode", "routing_policy")),
            decision_scope=_enum("decision_scope", DecisionScope,
                                 _need(d, "decision_scope", "routing_policy")),
            candidate_mode=_enum("candidate_mode", CandidateMode,
                                 _need(d, "candidate_mode", "routing_policy")),
            selection_locus=_enum("selection_locus", SelectionLocus,
                                  _need(d, "selection_locus", "routing_policy")),
            randomness=_enum("randomness", RandomnessMode,
                             _need(d, "randomness", "routing_policy")),
            deadlock_proof_obligation=_enum(
                "deadlock_proof_obligation", DeadlockProofObligation,
                _need(d, "deadlock_proof_obligation", "routing_policy")),
            state_requirements=states,
            runtime_observations=observations,
            resource_roles=roles,
            allowed_role_transitions=tuple(transitions),
            parameters=raw_parameters,
            schema_version=_need(d, "schema_version", "routing_policy"),
        )
        supplied = _need(d, "policy_hash", "routing_policy")
        if not isinstance(supplied, str) or not supplied:
            raise RoutingPolicyError("policy_hash must be a non-empty string")
        if supplied != artifact._compute_hash():
            raise RoutingPolicyError(
                "policy_hash does not match the policy semantics")
        return artifact
