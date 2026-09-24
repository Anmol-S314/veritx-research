"""veritx_dse.model.routing_relation — topology-bound legal routing actions.

``RoutingRelationArtifact`` is the second half of the routing-semantics split:

    RoutingPolicyDefinition
            │
            ├── deterministically representable  -> RouteArtifact (Slice 11)
            └── adaptive / stateful / stochastic -> RoutingRelationArtifact

It records the complete envelope of LEGAL routing actions for every declared
context. It deliberately does not:

  * select an action from congestion, faults or RNG;
  * bind abstract routing roles to concrete VC ids;
  * perform VC allocation or model a router allocator;
  * prove deadlock freedom (Slice 9A/9B own that);
  * contain backend names, BookSim VC ranges, endpoints or ranks.

Context is (current router, destination, current abstract role, routing
state). ``current_role_id is None`` is the injection/source context — a
packet that does not yet hold a routing resource role. It is not a declared
role. Actions are FORWARD (an exact topology channel plus next role and next
state) or EJECT (destination only). ``priority`` is semantic preference
metadata; this artifact never encodes how an allocator resolves ties.

The relation is total over its declared state space: every (router,
destination, {None + declared roles}, state-combination) context must have
exactly one decision. A policy that is already exactly representable by the
deterministic RouteArtifact profile is refused here
(``REDUNDANT_DETERMINISTIC_POLICY``) so there is only one deterministic
routing authority.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.routing_policy import (
    CandidateMode, DecisionScope, RandomnessMode, RoutingPolicyDefinition,
    RoutingResourceRoleKind, SelectionLocus,
)
from veritx_dse.model.topology_artifact import TopologyArtifact

ROUTING_RELATION_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/RoutingRelationArtifact"

StateValue = int | str


class RoutingRelationError(ValueError, SemanticError):
    """The routing relation is malformed, tampered with, or not total."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise RoutingRelationError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise RoutingRelationError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RoutingRelationError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _as_int(name: str, value: Any, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise RoutingRelationError(
            f"{name} must be an exact int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise RoutingRelationError(f"{name} must be >= {minimum}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RoutingRelationError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


def _as_state_value(name: str, value: Any) -> StateValue:
    if isinstance(value, bool):
        raise RoutingRelationError(
            f"{name} must be an int or non-empty string, not bool")
    if type(value) is int:
        return value
    if isinstance(value, str) and value:
        return value
    raise RoutingRelationError(
        f"{name} must be an exact int or non-empty string, got {value!r}")


def _value_key(value: StateValue) -> tuple[int, Any]:
    return (0, value) if type(value) is int else (1, value)


def _bindings_key(bindings: Sequence["RoutingStateBinding"]) -> tuple:
    return tuple((b.name, _value_key(b.value)) for b in bindings)


def _context_key(context: "RoutingContext") -> tuple:
    return (context.router_id, context.destination_router_id,
            context.current_role_id or "", _bindings_key(context.state))


def _action_key(action: "RoutingAction") -> tuple:
    return (0 if action.kind == RoutingActionKind.FORWARD else 1,
            action.channel_id if action.channel_id is not None else -1,
            action.next_role_id or "",
            action.priority,
            _bindings_key(action.next_state))


class RoutingActionKind(Enum):
    FORWARD = "forward"
    EJECT = "eject"


# ── value types ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingStateDomain:
    """Finite canonical domain for one declared routing state variable."""

    name: str
    values: tuple[StateValue, ...]

    def __post_init__(self):
        _as_str("state domain name", self.name)
        raw = self.values
        if not isinstance(raw, (tuple, list)):
            raise RoutingRelationError(
                "state domain values must be a sequence")
        values = tuple(_as_state_value("state domain value", v) for v in raw)
        if not values:
            raise RoutingRelationError(
                f"state domain {self.name!r} must be non-empty")
        if len(set(values)) != len(values):
            raise RoutingRelationError(
                f"state domain {self.name!r} has duplicate values")
        object.__setattr__(self, "values",
                           tuple(sorted(values, key=_value_key)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "values": list(self.values)}

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingStateDomain":
        _strict_keys(d, frozenset({"name", "values"}), "state_domain")
        raw = _need(d, "values", "state_domain")
        if not isinstance(raw, list):
            raise RoutingRelationError(
                "state domain values must be a JSON list")
        domain = cls(name=_as_str("state domain name",
                                  _need(d, "name", "state_domain")),
                     values=tuple(raw))
        if list(domain.values) != raw:
            raise RoutingRelationError(
                f"state domain {domain.name!r} values must be canonical "
                "(unique, sorted ints then strings)")
        return domain


@dataclass(frozen=True)
class RoutingStateBinding:
    """One exact value for one declared routing state variable."""

    name: str
    value: StateValue

    def __post_init__(self):
        _as_str("state binding name", self.name)
        _as_state_value("state binding value", self.value)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingStateBinding":
        _strict_keys(d, frozenset({"name", "value"}), "state_binding")
        return cls(name=_as_str("state binding name",
                                _need(d, "name", "state_binding")),
                   value=_as_state_value(
                       "state binding value", _need(d, "value",
                                                    "state_binding")))


def _normalize_bindings(name: str, raw: Any) -> tuple[RoutingStateBinding, ...]:
    if not isinstance(raw, (tuple, list)):
        raise RoutingRelationError(f"{name} must be a sequence of bindings")
    bindings = tuple(raw)
    for binding in bindings:
        if not isinstance(binding, RoutingStateBinding):
            raise RoutingRelationError(
                f"{name} must contain RoutingStateBinding")
    if len({b.name for b in bindings}) != len(bindings):
        raise RoutingRelationError(f"{name} has duplicate state names")
    return tuple(sorted(bindings, key=lambda b: b.name))


@dataclass(frozen=True)
class RoutingAction:
    """One legal routing action from a context.

    ``priority`` is exact integer routing preference metadata (higher means
    preferred). Tuple order never carries priority: action order is
    canonicalized for identity and consumers must read this field.
    """

    kind: RoutingActionKind
    channel_id: int | None
    next_role_id: str | None
    next_state: tuple[RoutingStateBinding, ...] = ()
    priority: int = 0

    def __post_init__(self):
        if not isinstance(self.kind, RoutingActionKind):
            raise RoutingRelationError(
                f"action kind must be a RoutingActionKind, got "
                f"{type(self.kind).__name__}")
        _as_int("action priority", self.priority)
        if self.kind == RoutingActionKind.FORWARD:
            _as_int("forward channel_id", self.channel_id, minimum=0)
            _as_str("forward next_role_id", self.next_role_id)
            object.__setattr__(
                self, "next_state",
                _normalize_bindings("action next_state", self.next_state))
        else:
            if self.channel_id is not None:
                raise RoutingRelationError(
                    "EJECT actions must not carry a channel_id")
            if self.next_role_id is not None:
                raise RoutingRelationError(
                    "EJECT actions must not carry a next_role_id")
            if tuple(self.next_state):
                raise RoutingRelationError(
                    "EJECT actions must not carry next-state bindings")
            object.__setattr__(self, "next_state", ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "channel_id": self.channel_id,
            "next_role_id": self.next_role_id,
            "next_state": [b.to_dict() for b in self.next_state],
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingAction":
        _strict_keys(d, frozenset({"kind", "channel_id", "next_role_id",
                                   "next_state", "priority"}), "action")
        kind_value = _need(d, "kind", "action")
        if not isinstance(kind_value, str):
            raise RoutingRelationError(
                f"action kind must be a string, got {kind_value!r}")
        try:
            kind = RoutingActionKind(kind_value)
        except ValueError:
            raise RoutingRelationError(
                f"action kind {kind_value!r} is not one of "
                f"{[k.value for k in RoutingActionKind]}") from None
        raw_state = _need(d, "next_state", "action")
        if not isinstance(raw_state, list):
            raise RoutingRelationError(
                "action next_state must be a JSON list")
        next_state = tuple(RoutingStateBinding.from_dict(b)
                           for b in raw_state)
        if list(next_state) != list(sorted(next_state,
                                           key=lambda b: b.name)):
            raise RoutingRelationError(
                "action next_state must be sorted by name")
        return cls(
            kind=kind, channel_id=_need(d, "channel_id", "action"),
            next_role_id=_need(d, "next_role_id", "action"),
            next_state=next_state,
            priority=_need(d, "priority", "action"))


@dataclass(frozen=True)
class RoutingContext:
    """One routing decision point.

    ``current_role_id is None`` is the injection/source context (no routing
    resource role is held yet); it is not a declared routing resource role.
    """

    router_id: int
    destination_router_id: int
    current_role_id: str | None
    state: tuple[RoutingStateBinding, ...] = ()

    def __post_init__(self):
        _as_int("context router_id", self.router_id, minimum=0)
        _as_int("context destination_router_id", self.destination_router_id,
                minimum=0)
        if self.current_role_id is not None:
            _as_str("context current_role_id", self.current_role_id)
        object.__setattr__(
            self, "state", _normalize_bindings("context state", self.state))

    def to_dict(self) -> dict[str, Any]:
        return {
            "router_id": self.router_id,
            "destination_router_id": self.destination_router_id,
            "current_role_id": self.current_role_id,
            "state": [b.to_dict() for b in self.state],
        }

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingContext":
        _strict_keys(d, frozenset({"router_id", "destination_router_id",
                                   "current_role_id", "state"}), "context")
        raw_state = _need(d, "state", "context")
        if not isinstance(raw_state, list):
            raise RoutingRelationError(
                "context state must be a JSON list")
        state = tuple(RoutingStateBinding.from_dict(b) for b in raw_state)
        if list(state) != list(sorted(state, key=lambda b: b.name)):
            raise RoutingRelationError(
                "context state must be sorted by name")
        return cls(
            router_id=_need(d, "router_id", "context"),
            destination_router_id=_need(d, "destination_router_id", "context"),
            current_role_id=_need(d, "current_role_id", "context"),
            state=state)


@dataclass(frozen=True)
class RoutingDecision:
    """The non-empty set of legal actions for exactly one context."""

    context: RoutingContext
    actions: tuple[RoutingAction, ...]

    def __post_init__(self):
        if not isinstance(self.context, RoutingContext):
            raise RoutingRelationError("context must be a RoutingContext")
        if not isinstance(self.actions, (tuple, list)) or not self.actions:
            raise RoutingRelationError("actions must be a non-empty sequence")
        actions = tuple(self.actions)
        for action in actions:
            if not isinstance(action, RoutingAction):
                raise RoutingRelationError(
                    "actions must contain RoutingAction")
        if len(set(actions)) != len(actions):
            raise RoutingRelationError(
                "duplicate semantic actions are not allowed")
        actions = tuple(sorted(actions, key=_action_key))
        at_destination = (self.context.router_id
                          == self.context.destination_router_id)
        if at_destination:
            if len(actions) != 1 or \
                    actions[0].kind != RoutingActionKind.EJECT:
                raise RoutingRelationError(
                    "destination contexts must resolve to exactly one EJECT")
        elif any(a.kind != RoutingActionKind.FORWARD for a in actions):
            raise RoutingRelationError(
                "EJECT is only legal at the destination router")
        object.__setattr__(self, "actions", actions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingDecision":
        _strict_keys(d, frozenset({"context", "actions"}), "decision")
        raw_actions = _need(d, "actions", "decision")
        if not isinstance(raw_actions, list):
            raise RoutingRelationError("decision actions must be a JSON list")
        actions = tuple(RoutingAction.from_dict(a) for a in raw_actions)
        if list(actions) != list(sorted(actions, key=_action_key)):
            raise RoutingRelationError(
                "decision actions must be in canonical order")
        return cls(
            context=RoutingContext.from_dict(_need(d, "context", "decision")),
            actions=actions)


# ── deterministic authority guard ────────────────────────────────────────

def _is_deterministically_representable(
        policy: RoutingPolicyDefinition) -> bool:
    """The exact Slice-11 deterministic profile; those belong to RouteArtifact."""
    if not isinstance(policy, RoutingPolicyDefinition):
        return False
    if policy.decision_scope != DecisionScope.STATIC \
            or policy.candidate_mode != CandidateMode.SINGLETON \
            or policy.selection_locus != SelectionLocus.ROUTE_COMPUTE \
            or policy.randomness != RandomnessMode.NONE:
        return False
    if policy.state_requirements or policy.runtime_observations:
        return False
    roles = policy.resource_roles
    if len(roles) != 1 \
            or roles[0].kind != RoutingResourceRoleKind.DEFAULT:
        return False
    role_id = roles[0].id
    return policy.allowed_role_transitions in ((), ((role_id, role_id),))


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingRelationArtifact:
    """Topology-bound, total set of legal routing actions per context."""

    topology_hash: str
    policy_hash: str
    state_domains: tuple[RoutingStateDomain, ...] = ()
    decisions: tuple[RoutingDecision, ...] = ()
    schema_version: int = ROUTING_RELATION_SCHEMA_VERSION
    relation_hash: str = ""

    def __post_init__(self):
        for name in ("topology_hash", "policy_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RoutingRelationError(
                    f"{name} must be a non-empty string")
        domains = tuple(self.state_domains)
        for domain in domains:
            if not isinstance(domain, RoutingStateDomain):
                raise RoutingRelationError(
                    "state_domains must contain RoutingStateDomain")
        if len({d.name for d in domains}) != len(domains):
            raise RoutingRelationError("state domain names must be unique")
        domains = tuple(sorted(domains, key=lambda d: d.name))
        decisions = tuple(self.decisions)
        for decision in decisions:
            if not isinstance(decision, RoutingDecision):
                raise RoutingRelationError(
                    "decisions must contain RoutingDecision")
        keys = [_context_key(d.context) for d in decisions]
        if len(set(keys)) != len(keys):
            raise RoutingRelationError("duplicate decision contexts")
        decisions = tuple(sorted(decisions, key=lambda d:
                                 _context_key(d.context)))
        if type(self.schema_version) is not int or \
                self.schema_version != ROUTING_RELATION_SCHEMA_VERSION:
            raise RoutingRelationError(
                f"unsupported routing-relation schema_version "
                f"{self.schema_version!r} (expected "
                f"{ROUTING_RELATION_SCHEMA_VERSION})")
        object.__setattr__(self, "state_domains", domains)
        object.__setattr__(self, "decisions", decisions)
        expected = self._compute_hash()
        if self.relation_hash:
            if not isinstance(self.relation_hash, str) \
                    or self.relation_hash != expected:
                raise RoutingRelationError(
                    "relation_hash does not match the routing relation")
        else:
            object.__setattr__(self, "relation_hash", expected)

    # ── identity ─────────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "policy_hash": self.policy_hash,
            "state_domains": [d.to_dict() for d in self.state_domains],
            "decisions": [d.to_dict() for d in self.decisions],
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["relation_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingRelationArtifact":
        allowed = frozenset({
            "type", "schema_version", "topology_hash", "policy_hash",
            "state_domains", "decisions", "relation_hash",
        })
        _strict_keys(d, allowed, "routing_relation")
        if _need(d, "type", "routing_relation") != _HASH_TYPE_TAG:
            raise RoutingRelationError(
                f"routing relation type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        raw_domains = _need(d, "state_domains", "routing_relation")
        if not isinstance(raw_domains, list):
            raise RoutingRelationError("state_domains must be a JSON list")
        domains = tuple(RoutingStateDomain.from_dict(x) for x in raw_domains)
        if domains != tuple(sorted(domains, key=lambda x: x.name)):
            raise RoutingRelationError(
                "state_domains must be sorted by name")
        raw_decisions = _need(d, "decisions", "routing_relation")
        if not isinstance(raw_decisions, list):
            raise RoutingRelationError("decisions must be a JSON list")
        decisions = tuple(RoutingDecision.from_dict(x) for x in raw_decisions)
        keys = [_context_key(x.context) for x in decisions]
        if keys != sorted(keys):
            raise RoutingRelationError(
                "decisions must be sorted by context")
        if len(set(keys)) != len(keys):
            raise RoutingRelationError("duplicate decision contexts")
        for decision in decisions:
            if list(decision.actions) != list(
                    sorted(decision.actions, key=_action_key)):
                raise RoutingRelationError(
                    "decision actions must be in canonical order")
        artifact = cls(
            topology_hash=_need(d, "topology_hash", "routing_relation"),
            policy_hash=_need(d, "policy_hash", "routing_relation"),
            state_domains=domains,
            decisions=decisions,
            schema_version=_need(d, "schema_version", "routing_relation"),
        )
        supplied = _need(d, "relation_hash", "routing_relation")
        if not isinstance(supplied, str) or not supplied:
            raise RoutingRelationError(
                "relation_hash must be a non-empty string")
        if supplied != artifact._compute_hash():
            raise RoutingRelationError(
                "relation_hash does not match the routing relation")
        return artifact

    # ── parent validation ────────────────────────────────────────────────
    def validate_against(self, topology: TopologyArtifact,
                         policy: RoutingPolicyDefinition) -> None:
        if not isinstance(topology, TopologyArtifact):
            raise RoutingRelationError("topology must be a TopologyArtifact")
        if not isinstance(policy, RoutingPolicyDefinition):
            raise RoutingRelationError(
                "policy must be a RoutingPolicyDefinition")
        if self.topology_hash != topology.topology_hash():
            raise RoutingRelationError(
                "topology_hash does not match the materialized topology")
        if self.policy_hash != policy.policy_hash:
            raise RoutingRelationError(
                "policy_hash does not match the routing policy definition")
        if _is_deterministically_representable(policy):
            raise RoutingRelationError(
                "REDUNDANT_DETERMINISTIC_POLICY: this policy belongs to the "
                "deterministic RouteArtifact profile (Slice 11)")

        required_states = tuple(s.name for s in policy.state_requirements)
        domain_by_name = {d.name: d for d in self.state_domains}
        if set(domain_by_name) != set(required_states):
            missing = sorted(set(required_states) - set(domain_by_name))
            extra = sorted(set(domain_by_name) - set(required_states))
            raise RoutingRelationError(
                f"state domains do not match the policy requirements "
                f"(missing {missing}, extra {extra})")

        roles = {r.id for r in policy.resource_roles}
        transitions = set(policy.allowed_role_transitions)
        channels = {c.channel_id: c for c in topology.channels}
        router_ids = sorted(r.router_id for r in topology.routers)

        domain_values = [domain_by_name[name].values
                         for name in required_states]
        expected: set[tuple] = set()
        for router_id in router_ids:
            for destination in router_ids:
                for role in (None, *sorted(roles)):
                    for combination in itertools.product(*domain_values):
                        bindings = tuple(
                            RoutingStateBinding(name, value)
                            for name, value in zip(required_states,
                                                   combination))
                        expected.add((router_id, destination,
                                      role or "", _bindings_key(bindings)))

        for decision in self.decisions:
            context = decision.context
            if context.router_id not in router_ids \
                    or context.destination_router_id not in router_ids:
                raise RoutingRelationError(
                    f"decision context {context.router_id}->"
                    f"{context.destination_router_id} is outside the "
                    "topology")
            if context.current_role_id is not None \
                    and context.current_role_id not in roles:
                raise RoutingRelationError(
                    f"current role {context.current_role_id!r} is not "
                    "declared by the policy")
            _check_state(context.state, domain_by_name, "context state")
            for action in decision.actions:
                if action.kind != RoutingActionKind.FORWARD:
                    continue
                channel = channels.get(action.channel_id)
                if channel is None:
                    raise RoutingRelationError(
                        f"forward channel {action.channel_id} is not in "
                        "the topology")
                if channel.src_router != context.router_id:
                    raise RoutingRelationError(
                        f"forward channel {action.channel_id} leaves router "
                        f"{channel.src_router}, not {context.router_id}")
                if action.next_role_id not in roles:
                    raise RoutingRelationError(
                        f"next role {action.next_role_id!r} is not declared "
                        "by the policy")
                if context.current_role_id is not None and (
                        context.current_role_id,
                        action.next_role_id) not in transitions:
                    raise RoutingRelationError(
                        f"role transition {context.current_role_id!r} -> "
                        f"{action.next_role_id!r} is not allowed by the "
                        "policy")
                _check_state(action.next_state, domain_by_name,
                             "action next_state")

        got = {_context_key(d.context) for d in self.decisions}
        missing = expected - got
        extra = got - expected
        if missing or extra:
            raise RoutingRelationError(
                f"relation is not total over the declared context space "
                f"(missing {len(missing)}, extra {len(extra)})")
        if self.relation_hash != self._compute_hash():
            raise RoutingRelationError(
                "relation_hash does not match the routing relation")


def _check_state(bindings: Sequence[RoutingStateBinding],
                 domain_by_name: Mapping[str, RoutingStateDomain],
                 where: str) -> None:
    names = {b.name for b in bindings}
    if names != set(domain_by_name):
        raise RoutingRelationError(
            f"{where} must bind every declared state exactly once")
    for binding in bindings:
        domain = domain_by_name[binding.name]
        if binding.value not in domain.values:
            raise RoutingRelationError(
                f"{where} value {binding.value!r} is outside the declared "
                f"domain of {binding.name!r}")


def build_routing_relation(
        policy: RoutingPolicyDefinition,
        topology: TopologyArtifact,
        decisions: Iterable[RoutingDecision],
        *,
        state_domains: Iterable[RoutingStateDomain] = (),
) -> RoutingRelationArtifact:
    """Construct and fully validate a total legal-action relation."""
    if not isinstance(policy, RoutingPolicyDefinition):
        raise RoutingRelationError(
            "policy must be a RoutingPolicyDefinition")
    if not isinstance(topology, TopologyArtifact):
        raise RoutingRelationError("topology must be a TopologyArtifact")
    if _is_deterministically_representable(policy):
        raise RoutingRelationError(
            "REDUNDANT_DETERMINISTIC_POLICY: this policy belongs to the "
            "deterministic RouteArtifact profile (Slice 11)")
    artifact = RoutingRelationArtifact(
        topology_hash=topology.topology_hash(),
        policy_hash=policy.policy_hash,
        state_domains=tuple(state_domains),
        decisions=tuple(decisions),
    )
    artifact.validate_against(topology, policy)
    return artifact
