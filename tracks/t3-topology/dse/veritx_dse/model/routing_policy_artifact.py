"""Versioned, finite stateful routing relation over canonical transports.

Legacy relation v1 stays byte-compatible. This representation admits P2P and
multidrop actions, explicit initial state and correlated continuation. It is
router-transit semantics, not endpoint packetization or allocator fairness.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from veritx_dse.core.artifact import (
    content_id, canonical_bytes, require_fields, require_type_tag,
    require_schema_version, require_embedded_id,
)
from veritx_dse.core.errors import InvalidInput, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int, ResourceGraph
from veritx_dse.model.shared_resource import ResourceRef, ResourceKind
from veritx_dse.model.routing_relation import RoutingStateBinding, RoutingStateDomain


def _state(bindings):
    if not isinstance(bindings, tuple) or any(not isinstance(b, RoutingStateBinding) for b in bindings):
        raise InvalidInput("routing state must be an immutable tuple of bindings")
    if len({b.name for b in bindings}) != len(bindings):
        raise InvalidInput("routing state repeats a variable")
    return tuple(sorted(bindings, key=lambda b: b.name))


def _read_state(d):
    if type(d) is not list:
        raise InvalidInput("routing state must be a JSON list")
    return tuple(RoutingStateBinding.from_dict(b) for b in d)


@dataclass(frozen=True)
class RoutingContext:
    router: int
    destination: int
    state: tuple[RoutingStateBinding, ...] = ()

    def __post_init__(self):
        exact_int("routing router", self.router)
        exact_int("routing destination", self.destination)
        object.__setattr__(self, "state", _state(self.state))

    def to_dict(self):
        return {"router": self.router, "destination": self.destination,
                "state": [b.to_dict() for b in self.state]}

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"router", "destination", "state"}, "routing context")
        if set(d) != {"router", "destination", "state"}:
            raise InvalidInput("routing context requires all versioned fields")
        return cls(d["router"], d["destination"], _read_state(d["state"]))


@dataclass(frozen=True)
class RouteAction:
    resource: ResourceRef | None
    next_router: int
    vc_partition: str | None
    next_state: tuple[RoutingStateBinding, ...] = ()
    tap: int | None = None

    def __post_init__(self):
        exact_int("next_router", self.next_router)
        object.__setattr__(self, "next_state", _state(self.next_state))
        if self.resource is None:
            if self.vc_partition is not None or self.tap is not None or self.next_state:
                raise InvalidInput("ejection does not acquire resources/VCs or carry continuation")
        else:
            if not isinstance(self.resource, ResourceRef) or not isinstance(self.vc_partition, str) or not self.vc_partition:
                raise InvalidInput("forward action needs a resource and opaque VC partition")
            if self.resource.is_shared:
                exact_int("tap", self.tap)
            elif self.tap is not None:
                raise InvalidInput("P2P action cannot name a tap")

    @property
    def eject(self):
        return self.resource is None

    def continuation(self, context):
        if self.eject:
            raise InvalidInput("ejection has no continuation")
        return RoutingContext(self.next_router, context.destination, self.next_state)

    def to_dict(self):
        return {"resource": self.resource.to_dict() if self.resource else None,
                "next_router": self.next_router, "vc_partition": self.vc_partition,
                "next_state": [b.to_dict() for b in self.next_state], "tap": self.tap}

    @classmethod
    def from_dict(cls, d):
        names = {"resource", "next_router", "vc_partition", "next_state", "tap"}
        require_fields(d, names, "routing action")
        if set(d) != names:
            raise InvalidInput("routing action requires all versioned fields")
        return cls(ResourceRef.from_dict(d["resource"]) if d["resource"] is not None else None,
                   d["next_router"], d["vc_partition"], _read_state(d["next_state"]), d["tap"])


@dataclass(frozen=True)
class RoutingRule:
    context: RoutingContext
    actions: tuple[RouteAction, ...]

    def __post_init__(self):
        if not isinstance(self.context, RoutingContext) or not isinstance(self.actions, tuple) or not self.actions:
            raise InvalidInput("routing rule needs a context and nonempty immutable actions")
        if any(not isinstance(a, RouteAction) for a in self.actions) or len(set(self.actions)) != len(self.actions):
            raise InvalidInput("routing actions must be typed and unique")
        object.__setattr__(self, "actions", tuple(sorted(self.actions, key=lambda a: canonical_bytes(a.to_dict()))))

    def to_dict(self):
        return {"context": self.context.to_dict(), "actions": [a.to_dict() for a in self.actions]}

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"context", "actions"}, "routing rule")
        if type(d.get("actions")) is not list:
            raise InvalidInput("routing actions must be a JSON list")
        return cls(RoutingContext.from_dict(d["context"]), tuple(RouteAction.from_dict(a) for a in d["actions"]))


@dataclass(frozen=True)
class RoutingPolicyArtifact:
    resource_graph_id: str
    source_policy_id: str
    state_domains: tuple[RoutingStateDomain, ...]
    initial_contexts: tuple[RoutingContext, ...]
    rules: tuple[RoutingRule, ...]
    allowed_state_transitions: tuple[tuple[tuple[RoutingStateBinding, ...], tuple[RoutingStateBinding, ...]], ...]
    proof_strategy: str = "ACYCLIC_DEPENDENCY_GRAPH"

    def __post_init__(self):
        for name in ("resource_graph_id", "source_policy_id", "proof_strategy"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise InvalidInput(f"{name} must be a nonempty string")
        if not isinstance(self.state_domains, tuple) or any(not isinstance(d, RoutingStateDomain) for d in self.state_domains):
            raise InvalidInput("routing state domains must be typed and immutable")
        domains = {d.name: set(d.values) for d in self.state_domains}
        if len(domains) != len(self.state_domains):
            raise InvalidInput("duplicate routing state domain")
        if not isinstance(self.initial_contexts, tuple) or not self.initial_contexts or any(
                not isinstance(c, RoutingContext) for c in self.initial_contexts):
            raise InvalidInput("routing policy requires explicit initial contexts")
        if not isinstance(self.rules, tuple) or any(not isinstance(r, RoutingRule) for r in self.rules):
            raise InvalidInput("routing rules must be typed and immutable")
        contexts = [r.context for r in self.rules]
        if len(set(contexts)) != len(contexts) or len(set(self.initial_contexts)) != len(self.initial_contexts):
            raise InvalidInput("duplicate routing context")
        if not isinstance(self.allowed_state_transitions, tuple):
            raise InvalidInput("state transitions must be immutable")
        transitions = []
        for pair in self.allowed_state_transitions:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise InvalidInput("state transition requires two binding tuples")
            transitions.append((_state(pair[0]), _state(pair[1])))
        if len(set(transitions)) != len(transitions):
            raise InvalidInput("duplicate state transition")
        def check(state):
            if {b.name for b in state} != set(domains) or any(b.value not in domains[b.name] for b in state):
                raise InvalidInput("routing state does not bind the exact declared domains")
        for a, b in transitions:
            check(a); check(b)
        for context in self.initial_contexts:
            check(context.state)
        for rule in self.rules:
            check(rule.context.state)
            for action in rule.actions:
                if not action.eject:
                    check(action.next_state)
                    if (rule.context.state, action.next_state) not in transitions:
                        raise InvalidInput("illegal adaptive state transition")
        key = lambda obj: canonical_bytes(obj.to_dict())
        object.__setattr__(self, "state_domains", tuple(sorted(self.state_domains, key=lambda d: d.name)))
        object.__setattr__(self, "initial_contexts", tuple(sorted(self.initial_contexts, key=key)))
        object.__setattr__(self, "rules", tuple(sorted(self.rules, key=lambda r: key(r.context))))
        object.__setattr__(self, "allowed_state_transitions", tuple(sorted(transitions, key=lambda t: repr(t))))
        object.__setattr__(self, "_index", MappingProxyType({r.context: r.actions for r in self.rules}))

    def actions(self, context):
        try:
            return self._index[context]
        except KeyError:
            raise InvalidInput("routing continuation/initial context is missing") from None

    def validate_against(self, graph: ResourceGraph, allocation):
        if graph.artifact_id() != self.resource_graph_id:
            raise InvalidInput("routing resource graph parent mismatch")
        known = set(graph.routers)
        for rule in self.rules:
            if rule.context.router not in known or rule.context.destination not in known:
                raise InvalidInput("routing context names a missing router")
            for action in rule.actions:
                if action.eject:
                    if action.next_router != rule.context.router or action.next_router != rule.context.destination:
                        raise InvalidInput("ejection at the wrong router")
                else:
                    resource = graph.resource(action.resource)
                    if resource.source != rule.context.router or resource.landing(action.tap) != action.next_router:
                        raise InvalidInput("wrong canonical resource source/tap/next router")
                    allocation.vcs(action.vc_partition)
                    self.actions(action.continuation(rule.context))
        pending, reached = list(self.initial_contexts), set()
        while pending:
            context = pending.pop()
            if context in reached:
                continue
            reached.add(context)
            pending.extend(a.continuation(context) for a in self.actions(context) if not a.eject)
        if reached != set(self._index):
            raise InvalidInput("routing relation stores unreachable/impossible contexts")

    def identity_dict(self):
        return {"type": "veritx/RoutingPolicyArtifact", "schema_version": 1,
                "resource_graph_id": self.resource_graph_id, "source_policy_id": self.source_policy_id,
                "proof_strategy": self.proof_strategy, "scope": "DECLARED_INITIAL_CONTEXTS_AND_REACHABLE_ROUTER_TRANSIT",
                "state_domains": [d.to_dict() for d in self.state_domains],
                "initial_contexts": [c.to_dict() for c in self.initial_contexts],
                "rules": [r.to_dict() for r in self.rules],
                "allowed_state_transitions": [[[b.to_dict() for b in a], [b.to_dict() for b in z]]
                                               for a, z in self.allowed_state_transitions]}

    def artifact_id(self):
        return content_id("veritx/RoutingPolicyArtifact/v1", self.identity_dict())

    def to_dict(self):
        return {**self.identity_dict(), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, d):
        fields = {"type", "schema_version", "resource_graph_id", "source_policy_id", "proof_strategy",
                  "scope", "state_domains", "initial_contexts", "rules", "allowed_state_transitions", "artifact_id"}
        require_fields(d, fields, "routing policy artifact")
        require_type_tag(d, "veritx/RoutingPolicyArtifact", "routing policy artifact")
        if type(d.get("schema_version")) is not int:
            raise InvalidInput("routing schema version must be an exact int")
        require_schema_version(d, 1, "routing policy artifact")
        for name in ("state_domains", "initial_contexts", "rules", "allowed_state_transitions"):
            if type(d.get(name)) is not list:
                raise InvalidInput(f"{name} must be a JSON list")
        transitions = []
        for pair in d["allowed_state_transitions"]:
            if type(pair) is not list or len(pair) != 2:
                raise InvalidInput("state transition requires two JSON state lists")
            transitions.append((_read_state(pair[0]), _read_state(pair[1])))
        result = cls(d["resource_graph_id"], d["source_policy_id"],
                     tuple(RoutingStateDomain.from_dict(x) for x in d["state_domains"]),
                     tuple(RoutingContext.from_dict(x) for x in d["initial_contexts"]),
                     tuple(RoutingRule.from_dict(x) for x in d["rules"]), tuple(transitions), d["proof_strategy"])
        if d["scope"] != result.identity_dict()["scope"]:
            raise InvalidInput("unsupported routing proof scope")
        require_embedded_id(d, "artifact_id", result.artifact_id(), "routing policy artifact")
        return result


def normalize_legacy_route(topology, route, allocation, graph=None):
    """Phase-A deterministic adapters. Stateful legacy migration is Phase B.

    Refuse torus VC/dateline and adaptive routes rather than erase state or
    pretend a broad VC envelope is the qualified routing realization.
    """
    from veritx_dse.core.route_artifact import RouteArtifact, DOR_TORUS_XY
    from veritx_dse.model.route_artifact_v3 import RouteArtifactV3
    from veritx_dse.model.resource_graph import resource_graph_from_topology
    graph = graph if graph is not None else resource_graph_from_topology(topology)
    graph.validate_against(topology)
    route.validate_against(topology)
    if not isinstance(route, (RouteArtifact, RouteArtifactV3)):
        raise UnsupportedSemantics("stateful legacy routing adapter is pending Phase B; legacy proof/execution retained")
    if isinstance(route, RouteArtifact) and any(c.id == DOR_TORUS_XY for c in route.routing_classes):
        raise UnsupportedSemantics("torus dateline allocation adapter is pending Phase B; legacy proof/execution retained")
    if isinstance(route, RouteArtifactV3) and set(route.allowed_transitions) != set(allocation.resources.allowed_transitions):
        raise UnsupportedSemantics(
            "legacy route transit transitions differ from the VC-assignment projection; "
            "network/protocol allocation separation must be resolved in Phase B, never guessed")
    rows, initial = [], []
    if isinstance(route, RouteArtifact):
        by_id = {c.channel_id: c for c in topology.channels}
        domains = (RoutingStateDomain("class", tuple(c.id for c in route.routing_classes)),)
        transitions = []
        for cls in route.routing_classes:
            state = (RoutingStateBinding("class", cls.id),)
            transitions.append((state, state))
            for src in graph.routers:
                for dst in graph.routers:
                    context = RoutingContext(src, dst, state)
                    if src == dst:
                        action = RouteAction(None, src, None)
                    else:
                        ch = by_id[route.entries[(cls.id, src, dst)]]
                        action = RouteAction(ResourceRef(ResourceKind.CHANNEL, ch.channel_id), ch.dst_router, cls.id, state)
                    rows.append(RoutingRule(context, (action,))); initial.append(context)
        source_id = route.artifact_hash
    else:
        # Router semantics only; all concentrated terminal aliases must agree.
        by_step = {}
        for resource in graph.resources:
            if resource.ref.is_shared:
                for tap, dest in enumerate(resource.destinations):
                    by_step.setdefault((resource.source, tap, dest), []).append(resource.ref)
            else:
                by_step.setdefault((resource.source, None, resource.destinations[0]), []).append(resource.ref)
        canonical, binding, reverse = {}, {}, {}
        for (src, terminal), decision in route.decisions.items():
            dst = route.terminal_to_router.get(terminal, terminal)
            context = RoutingContext(src, dst)
            if src == dst:
                action = RouteAction(None, src, None)
            else:
                matches = by_step.get((src, decision.tap, decision.next_router), [])
                if len(matches) != 1:
                    raise InvalidInput("legacy transport binds ambiguously to canonical topology")
                ref = matches[0]
                if binding.setdefault(decision.resource, ref) != ref or reverse.setdefault(ref, decision.resource) != decision.resource:
                    raise InvalidInput("legacy/canonical resource mapping is not one-to-one")
                action = RouteAction(ref, decision.next_router, str(decision.vc_partition), tap=decision.tap)
            if context in canonical and canonical[context] != action:
                raise UnsupportedSemantics("terminal-specific transit decisions cannot be collapsed into router relation")
            canonical[context] = action
        expected = {RoutingContext(src, dst) for src in graph.routers for dst in graph.routers}
        if set(canonical) != expected:
            raise InvalidInput("legacy router relation is not complete")
        rows = [RoutingRule(c, (a,)) for c, a in canonical.items()]
        initial = list(canonical); domains = (); transitions = [((), ())]
        source_id = route.route_artifact_id()
    policy = RoutingPolicyArtifact(graph.artifact_id(), source_id, domains, tuple(initial), tuple(rows), tuple(transitions))
    policy.validate_against(graph, allocation)
    return policy
