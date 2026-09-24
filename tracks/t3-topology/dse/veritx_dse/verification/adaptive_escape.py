"""veritx_dse.verification.adaptive_escape — v1 escape-subfunction proof.

SROTA's first independent adaptive-routing deadlock certificate. It consumes
five canonical parents:

    TopologyArtifact
    RoutingPolicyDefinition
    RoutingRelationArtifact
    VCResourceArtifact
    RoutingResourceBindingArtifact

and proves the structural conditions of SROTA's v1 escape-subfunction model:

  1. every adaptive routing context has a legal action into the escape role;
  2. source/injection routing can enter the escape role;
  3. the escape subfunction is closed (deterministic, escape-only);
  4. every source reaches every destination through escape routing;
  5. the concrete ``(channel, escape-VC)`` dependency graph is acyclic.

It does NOT prove arbitrary adaptive routing. A PASS is scoped to this
structural model and explicitly does not certify allocator fairness, backend
implementation equivalence, traffic-class injection eligibility, protocol
blocking, packet/flit buffering, multicast, or arbitrary stateful adaptive
routing. Routing roles are identified by ``RoutingResourceRole.kind``, never
by literal role names, and no legacy ``escape_vcs`` field is consulted.

Malformed or tampered parents raise ``AdaptiveEscapeVerificationError``;
``UNSUPPORTED`` is reserved for valid inputs outside the v1 profile.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import freeze, thaw
from veritx_dse.model.routing_policy import (
    DeadlockProofObligation, RoutingPolicyDefinition, RoutingResourceRoleKind,
)
from veritx_dse.model.routing_relation import (
    RoutingActionKind, RoutingRelationArtifact, RoutingRelationError,
)
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact, RoutingResourceBindingError,
)
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact

ADAPTIVE_ESCAPE_SUBFUNCTION_V1 = "ADAPTIVE_ESCAPE_SUBFUNCTION_V1"
ADAPTIVE_ESCAPE_PROOF_METHODS = (ADAPTIVE_ESCAPE_SUBFUNCTION_V1,)

ADAPTIVE_ESCAPE_TOOL = "veritx_dse.verification.adaptive_escape"
ADAPTIVE_ESCAPE_SCOPE = (
    "SROTA v1 escape-subfunction structural model; does not prove arbitrary "
    "adaptive routing, allocator fairness, backend equivalence, "
    "traffic-class injection eligibility, protocol blocking, packet/flit "
    "buffering, multicast, or stateful adaptive routing")

ADAPTIVE_ESCAPE_CERTIFICATE_SCHEMA_VERSION = 1
VERDICTS = ("PASS", "FAIL", "UNSUPPORTED", "NOT_RUN")

_NOT_VERIFIED = (
    "router allocator fairness/starvation",
    "backend implementation equivalence",
    "traffic-class injection eligibility",
    "protocol-level blocking cycles",
    "packet/flit buffer implementation",
    "multicast behavior",
    "arbitrary stateful adaptive routing",
)


class AdaptiveEscapeVerificationError(ValueError, SemanticError):
    """A parent is malformed, tampered with or inconsistent — fail closed."""


@dataclass(frozen=True)
class AdaptiveEscapeCertificate:
    """Immutable v1 escape-subfunction verdict with all bound hashes."""

    proof_method: str
    verdict: str
    topology_hash: str
    policy_hash: str
    relation_hash: str
    vc_resource_hash: str
    binding_hash: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    tool: str = ADAPTIVE_ESCAPE_TOOL
    scope: str = ADAPTIVE_ESCAPE_SCOPE
    schema_version: int = ADAPTIVE_ESCAPE_CERTIFICATE_SCHEMA_VERSION

    def __post_init__(self):
        if self.proof_method not in ADAPTIVE_ESCAPE_PROOF_METHODS:
            raise AdaptiveEscapeVerificationError(
                f"proof method {self.proof_method!r} is not in the closed "
                f"vocabulary {list(ADAPTIVE_ESCAPE_PROOF_METHODS)}")
        if self.verdict not in VERDICTS:
            raise AdaptiveEscapeVerificationError(
                f"verdict {self.verdict!r} is not one of {list(VERDICTS)}")
        for name in ("topology_hash", "policy_hash", "relation_hash",
                     "vc_resource_hash", "binding_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise AdaptiveEscapeVerificationError(
                    f"{name} must be a non-empty string")
        if not isinstance(self.tool, str) or not self.tool:
            raise AdaptiveEscapeVerificationError(
                "tool must be a non-empty string")
        if not isinstance(self.scope, str) or not self.scope:
            raise AdaptiveEscapeVerificationError(
                "scope must be a non-empty string")
        if type(self.schema_version) is not int or \
                self.schema_version != \
                ADAPTIVE_ESCAPE_CERTIFICATE_SCHEMA_VERSION:
            raise AdaptiveEscapeVerificationError(
                f"unsupported adaptive-escape certificate schema_version "
                f"{self.schema_version!r}")
        if not isinstance(self.evidence, Mapping):
            raise AdaptiveEscapeVerificationError("evidence must be a mapping")
        object.__setattr__(self, "evidence", freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/AdaptiveEscapeCertificate",
            "schema_version": self.schema_version,
            "proof_method": self.proof_method,
            "verdict": self.verdict,
            "topology_hash": self.topology_hash,
            "policy_hash": self.policy_hash,
            "relation_hash": self.relation_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "binding_hash": self.binding_hash,
            "evidence": thaw(self.evidence),
            "tool": self.tool,
            "scope": self.scope,
        }


def _validate_parents(
        topology: TopologyArtifact,
        policy: RoutingPolicyDefinition,
        relation: RoutingRelationArtifact,
        vc_resource: VCResourceArtifact,
        binding: RoutingResourceBindingArtifact,
) -> dict[str, str]:
    for name, value, expected in (
            ("topology", topology, TopologyArtifact),
            ("policy", policy, RoutingPolicyDefinition),
            ("relation", relation, RoutingRelationArtifact),
            ("vc_resource", vc_resource, VCResourceArtifact),
            ("binding", binding, RoutingResourceBindingArtifact)):
        if not isinstance(value, expected):
            raise AdaptiveEscapeVerificationError(
                f"{name} must be a {expected.__name__}")
    if relation.topology_hash != topology.topology_hash():
        raise AdaptiveEscapeVerificationError(
            "relation does not bind this topology")
    if relation.policy_hash != policy.policy_hash:
        raise AdaptiveEscapeVerificationError(
            "relation does not bind this routing policy")
    if binding.policy_hash != policy.policy_hash:
        raise AdaptiveEscapeVerificationError(
            "binding does not bind this routing policy")
    if binding.vc_resource_hash != vc_resource.artifact_hash:
        raise AdaptiveEscapeVerificationError(
            "binding does not bind this VC resource artifact")
    try:
        relation.validate_against(topology, policy)
    except RoutingRelationError as exc:
        raise AdaptiveEscapeVerificationError(
            f"relation failed parent validation: {exc}") from exc
    try:
        binding.validate_against(policy, vc_resource)
    except RoutingResourceBindingError as exc:
        raise AdaptiveEscapeVerificationError(
            f"binding failed parent validation: {exc}") from exc
    return {
        "topology_hash": topology.topology_hash(),
        "policy_hash": policy.policy_hash,
        "relation_hash": relation.relation_hash,
        "vc_resource_hash": vc_resource.artifact_hash,
        "binding_hash": binding.binding_hash,
    }


def _profile_problem(policy: RoutingPolicyDefinition,
                     relation: RoutingRelationArtifact) -> str | None:
    if policy.deadlock_proof_obligation \
            != DeadlockProofObligation.ESCAPE_SUBFUNCTION:
        return (f"proof obligation is "
                f"{policy.deadlock_proof_obligation.value}, not "
                "escape_subfunction")
    if policy.state_requirements or relation.state_domains:
        return "stateful escape routing is outside the v1 proof profile"
    escapes = [role for role in policy.resource_roles
               if role.kind == RoutingResourceRoleKind.ESCAPE]
    adaptives = [role for role in policy.resource_roles
                 if role.kind == RoutingResourceRoleKind.ADAPTIVE]
    if len(escapes) != 1:
        return (f"exactly one ESCAPE role is required by the v1 profile "
                f"(found {len(escapes)})")
    if not adaptives:
        return "at least one ADAPTIVE role is required by the v1 profile"
    unsupported = sorted({role.kind.value for role in policy.resource_roles
                          if role.kind not in (
                              RoutingResourceRoleKind.ADAPTIVE,
                              RoutingResourceRoleKind.ESCAPE)})
    if unsupported:
        return (f"routing role kinds {unsupported} are outside the v1 "
                "escape-subfunction profile")
    return None


def _decision_map(relation: RoutingRelationArtifact) -> dict[tuple, Any]:
    return {(decision.context.router_id,
             decision.context.destination_router_id,
             decision.context.current_role_id): decision
            for decision in relation.decisions}


def _escape_route(
        start: int, destination: int, escape_role: str,
        decisions: Mapping[tuple, Any],
        channels: Mapping[int, Any],
) -> tuple[list[Any] | None, list[int] | None]:
    """Follow the unique escape action; returns (hops, loop_witness)."""
    hops: list[Any] = []
    path: list[int] = [start]
    seen = {start}
    current = start
    while current != destination:
        decision = decisions.get((current, destination, escape_role))
        if decision is None or len(decision.actions) != 1:
            return None, path
        action = decision.actions[0]
        if action.kind != RoutingActionKind.FORWARD:
            return None, path
        channel = channels.get(action.channel_id)
        if channel is None or channel.src_router != current:
            return None, path
        hops.append(channel)
        current = channel.dst_router
        if current in seen:
            path.append(current)
            return None, path
        seen.add(current)
        path.append(current)
    return hops, None


def _find_cycle(nodes: tuple, edges: tuple) -> list | None:
    adjacency: dict[Any, list] = {node: [] for node in nodes}
    for src, dst in edges:
        adjacency[src].append(dst)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in nodes}
    parent: dict[Any, Any] = {}
    for root in nodes:
        if color[root] != WHITE:
            continue
        stack = [(root, 0)]
        color[root] = GRAY
        parent[root] = None
        while stack:
            node, index = stack[-1]
            if index < len(adjacency[node]):
                stack[-1] = (node, index + 1)
                nxt = adjacency[node][index]
                if color[nxt] == WHITE:
                    color[nxt] = GRAY
                    parent[nxt] = node
                    stack.append((nxt, 0))
                elif color[nxt] == GRAY:
                    cycle = [nxt]
                    cur = node
                    while cur is not None and cur != nxt:
                        cycle.append(cur)
                        cur = parent[cur]
                    cycle.append(nxt)
                    cycle.reverse()
                    return cycle
            else:
                color[node] = BLACK
                stack.pop()
    return None


def certify_adaptive_escape(
        *,
        topology: TopologyArtifact,
        policy: RoutingPolicyDefinition,
        relation: RoutingRelationArtifact,
        vc_resource: VCResourceArtifact,
        binding: RoutingResourceBindingArtifact,
) -> AdaptiveEscapeCertificate:
    """Prove (or refute) the v1 escape-subfunction structural conditions."""
    hashes = _validate_parents(topology, policy, relation, vc_resource,
                               binding)

    def certificate(verdict: str, evidence: dict) -> AdaptiveEscapeCertificate:
        return AdaptiveEscapeCertificate(
            proof_method=ADAPTIVE_ESCAPE_SUBFUNCTION_V1, verdict=verdict,
            topology_hash=hashes["topology_hash"],
            policy_hash=hashes["policy_hash"],
            relation_hash=hashes["relation_hash"],
            vc_resource_hash=hashes["vc_resource_hash"],
            binding_hash=hashes["binding_hash"], evidence=evidence)

    problem = _profile_problem(policy, relation)
    if problem is not None:
        return certificate("UNSUPPORTED", {
            "unsupported_reason": problem,
            "role_kinds": sorted(role.kind.value
                                 for role in policy.resource_roles),
            "not_verified": list(_NOT_VERIFIED),
        })

    escape_role = next(role.id for role in policy.resource_roles
                       if role.kind == RoutingResourceRoleKind.ESCAPE)
    adaptive_roles = tuple(sorted(role.id for role in policy.resource_roles
                                  if role.kind == RoutingResourceRoleKind.ADAPTIVE))
    role_vcs = dict(binding.role_to_vcs)
    escape_vcs = tuple(role_vcs[escape_role])
    escape_set = set(escape_vcs)
    channels = {channel.channel_id: channel for channel in topology.channels}
    router_ids = sorted(router.router_id for router in topology.routers)
    decisions = _decision_map(relation)
    concrete = set(vc_resource.allowed_transitions)

    evidence: dict[str, Any] = {
        "escape_role_id": escape_role,
        "adaptive_role_ids": list(adaptive_roles),
        "role_to_vcs": {role: list(vcs)
                        for role, vcs in sorted(role_vcs.items())},
        "escape_vcs": list(escape_vcs),
        "adaptive_vcs": {role: list(role_vcs[role]) for role in adaptive_roles},
        "not_verified": list(_NOT_VERIFIED),
    }

    # 1. adaptive contexts must offer a legal escape action
    adaptive_contexts = [
        decision for decision in relation.decisions
        if decision.context.current_role_id in adaptive_roles
        and decision.context.router_id
        != decision.context.destination_router_id]
    evidence["adaptive_context_count"] = len(adaptive_contexts)
    with_escape = [decision for decision in adaptive_contexts
                   if any(action.kind == RoutingActionKind.FORWARD
                          and action.next_role_id == escape_role
                          for action in decision.actions)]
    evidence["adaptive_contexts_with_escape"] = len(with_escape)
    if len(with_escape) != len(adaptive_contexts):
        missing = next(decision for decision in adaptive_contexts
                       if decision not in with_escape)
        return certificate("FAIL", {**evidence,
            "failure_stage": "adaptive_escape_accessibility",
            "witness": {
                "router_id": missing.context.router_id,
                "destination_router_id":
                    missing.context.destination_router_id,
                "current_role_id": missing.context.current_role_id,
            }})

    # 2. every adaptive VC can concretely enter the escape role
    for role in adaptive_roles:
        for vc in role_vcs[role]:
            if not any((vc, dst) in concrete for dst in escape_vcs):
                return certificate("FAIL", {**evidence,
                    "failure_stage": "concrete_adaptive_escape_accessibility",
                    "witness": {"role_id": role, "vc": vc}})

    # 3. injection contexts must offer a legal escape action
    injection_contexts = [
        decision for decision in relation.decisions
        if decision.context.current_role_id is None
        and decision.context.router_id
        != decision.context.destination_router_id]
    evidence["injection_context_count"] = len(injection_contexts)
    injection_with_escape = [
        decision for decision in injection_contexts
        if any(action.kind == RoutingActionKind.FORWARD
               and action.next_role_id == escape_role
               for action in decision.actions)]
    evidence["injection_contexts_with_escape"] = len(injection_with_escape)
    if len(injection_with_escape) != len(injection_contexts):
        missing = next(decision for decision in injection_contexts
                       if decision not in injection_with_escape)
        return certificate("FAIL", {**evidence,
            "failure_stage": "injection_escape_availability",
            "witness": {
                "router_id": missing.context.router_id,
                "destination_router_id":
                    missing.context.destination_router_id,
            }})

    # 4. escape closure: exactly one escape-only FORWARD per escape context
    escape_contexts = [
        decision for decision in relation.decisions
        if decision.context.current_role_id == escape_role
        and decision.context.router_id
        != decision.context.destination_router_id]
    evidence["escape_context_count"] = len(escape_contexts)
    for decision in escape_contexts:
        forwards = [action for action in decision.actions
                    if action.kind == RoutingActionKind.FORWARD]
        if len(forwards) > 1:
            return certificate("UNSUPPORTED", {
                **evidence,
                "unsupported_reason":
                    "multiple legal escape actions at one escape context "
                    "(v1 requires a deterministic escape subfunction)",
                "witness": {
                    "router_id": decision.context.router_id,
                    "destination_router_id":
                        decision.context.destination_router_id,
                }})
        if len(forwards) != 1 or forwards[0].next_role_id != escape_role:
            return certificate("FAIL", {**evidence,
                "failure_stage": "escape_closure",
                "witness": {
                    "router_id": decision.context.router_id,
                    "destination_router_id":
                        decision.context.destination_router_id,
                    "next_role_id": (forwards[0].next_role_id
                                     if forwards else None),
                }})
    evidence["escape_closure"] = True

    # 5. concrete escape VCs may only transition into escape VCs
    escape_vc_transitions = tuple(
        (src, dst) for src, dst in sorted(concrete)
        if src in escape_set and dst in escape_set)
    for src, dst in sorted(concrete):
        if src in escape_set and dst not in escape_set:
            return certificate("FAIL", {**evidence,
                "failure_stage": "concrete_escape_vc_closure",
                "witness": {"src_vc": src, "dst_vc": dst}})
    evidence["concrete_escape_vc_closure"] = True
    evidence["escape_vc_transition_count"] = len(escape_vc_transitions)

    # 6. escape routing must reach every destination from every source
    routes_checked = 0
    max_hops = 0
    for src in router_ids:
        for destination in router_ids:
            if src == destination:
                continue
            hops, loop_witness = _escape_route(
                src, destination, escape_role, decisions, channels)
            if hops is None:
                return certificate("FAIL", {**evidence,
                    "failure_stage": "escape_route_reachability",
                    "witness": {"src_router": src,
                                "destination_router_id": destination,
                                "path": loop_witness}})
            routes_checked += 1
            max_hops = max(max_hops, len(hops))
    evidence["routes_checked"] = routes_checked
    evidence["max_escape_hops"] = max_hops

    # 7. concrete (channel, escape-VC) dependency graph must be acyclic
    nodes = tuple((channel.channel_id, vc)
                  for channel in sorted(topology.channels,
                                        key=lambda c: c.channel_id)
                  for vc in escape_vcs)
    edges: set[tuple] = set()
    for src in router_ids:
        for destination in router_ids:
            if src == destination:
                continue
            hops, _loop = _escape_route(src, destination, escape_role,
                                        decisions, channels)
            for first, second in zip(hops, hops[1:]):
                for vc_a in escape_vcs:
                    for vc_b in escape_vcs:
                        if (vc_a, vc_b) in escape_vc_transitions:
                            edges.add(((first.channel_id, vc_a),
                                       (second.channel_id, vc_b)))
    ordered_edges = tuple(sorted(edges))
    evidence["escape_cdg_node_count"] = len(nodes)
    evidence["escape_cdg_edge_count"] = len(ordered_edges)
    cycle = _find_cycle(nodes, ordered_edges)
    if cycle is not None:
        return certificate("FAIL", {**evidence,
            "failure_stage": "escape_cdg_acyclicity",
            "witness": {"cycle": [list(node) for node in cycle]}})
    evidence["acyclic"] = True
    return certificate("PASS", evidence)
