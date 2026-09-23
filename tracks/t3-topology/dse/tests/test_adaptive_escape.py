"""Adaptive escape-subfunction certificate tests.

The verifier proves SROTA's v1 structural conditions over five canonical
parents. Reference fixtures use the real MinAdapt chain; synthetic fixtures
exercise escape accessibility, closure, reachability and the concrete
escape channel/VC dependency graph.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RoutingStateKind, RoutingStateRequirement,
    RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_relation import (
    RoutingAction, RoutingActionKind, RoutingContext, RoutingDecision,
    RoutingStateBinding, RoutingStateDomain, build_routing_relation,
)
from veritx_dse.model.routing_relation_materialize import (
    materialize_routing_relation,
)
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_family,
)
from veritx_dse.model.vc_resource import VCResourceArtifact
from veritx_dse.verification import adaptive_escape as ae
from veritx_dse.verification.adaptive_escape import (
    ADAPTIVE_ESCAPE_SUBFUNCTION_V1, AdaptiveEscapeCertificate,
    AdaptiveEscapeVerificationError, certify_adaptive_escape,
)

_MESH2 = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
_MESH3 = materialize_family(MaterializedFamily.MESH, endpoint_count=9)
_CMESH = materialize_family(MaterializedFamily.CONCENTRATED_MESH,
                            endpoint_count=4)

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

_EXPECTED_2X2_EVIDENCE = {
    "acyclic": True,
    "adaptive_context_count": 12,
    "adaptive_contexts_with_escape": 12,
    "adaptive_role_ids": ["adaptive"],
    "adaptive_vcs": {"adaptive": [1, 2, 3]},
    "concrete_escape_vc_closure": True,
    "escape_cdg_edge_count": 4,
    "escape_cdg_node_count": 8,
    "escape_closure": True,
    "escape_context_count": 12,
    "escape_role_id": "escape",
    "escape_vc_transition_count": 1,
    "escape_vcs": [0],
    "injection_context_count": 12,
    "injection_contexts_with_escape": 12,
    "max_escape_hops": 2,
    "not_verified": [
        "router allocator fairness/starvation",
        "backend implementation equivalence",
        "traffic-class injection eligibility",
        "protocol-level blocking cycles",
        "packet/flit buffer implementation",
        "multicast behavior",
        "arbitrary stateful adaptive routing",
    ],
    "role_to_vcs": {"adaptive": [1, 2, 3], "escape": [0]},
    "routes_checked": 12,
}


def _role(rid, kind):
    return RoutingResourceRole(id=rid, kind=kind)


def _min_adapt_policy(**over) -> RoutingPolicyDefinition:
    kw = dict(
        id="min_adapt_mesh", algorithm="per_hop_min_adaptive",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")),
    )
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _min_adapt_resource(transitions=_MIN_ADAPT_TRANSITIONS, vc_count=4):
    return VCResourceArtifact(
        vc_count=vc_count, vc_ids=tuple(range(vc_count)),
        traffic_class_to_vcs=(("default", tuple(range(vc_count))),),
        allowed_transitions=transitions)


def _binding(policy, resource, rows):
    return RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash,
        vc_resource_hash=resource.artifact_hash, role_to_vcs=rows)


def _min_adapt_binding(policy, resource):
    return _binding(policy, resource,
                    (("adaptive", (1, 2, 3)), ("escape", (0,))))


def _chain(topology):
    policy = _min_adapt_policy()
    resource = _min_adapt_resource()
    binding = _min_adapt_binding(policy, resource)
    relation = materialize_routing_relation(topology, policy)
    return policy, relation, resource, binding


def _cert(topology, policy, relation, resource, binding):
    return certify_adaptive_escape(
        topology=topology, policy=policy, relation=relation,
        vc_resource=resource, binding=binding)


def _two_router() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.MESH,
        routers=(Router(0, (0,), 1), Router(1, (1,), 1)),
        channels=(DirectedChannel(0, 0, 1, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 1, 0, 0, 64, 1)))


def _loop_topology() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.MESH,
        routers=(Router(0, (0,), 1), Router(1, (1,), 1), Router(2, (2,), 1)),
        channels=(DirectedChannel(0, 0, 1, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 1, 0, 0, 64, 1),
                  DirectedChannel(2, 2, 1, 0, 0, 64, 1)))


def _ring_topology() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.MESH,
        routers=(Router(0, (0,), 1), Router(1, (1,), 1), Router(2, (2,), 1)),
        channels=(DirectedChannel(0, 0, 1, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 1, 2, 0, 64, 1),
                  DirectedChannel(2, 2, 1, 0, 0, 64, 1)))


def _simple_relation(topology, policy, next_hop, escape_role="escape",
                     adaptive_role="adaptive"):
    decisions = []
    for router_id in sorted(next_hop):
        for destination in sorted(next_hop):
            for role in (None, adaptive_role, escape_role):
                context = RoutingContext(router_id=router_id,
                                         destination_router_id=destination,
                                         current_role_id=role)
                if router_id == destination:
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.EJECT,
                                      channel_id=None, next_role_id=None,
                                      priority=0),)))
                    continue
                channel = next_hop[router_id]
                actions = [RoutingAction(kind=RoutingActionKind.FORWARD,
                                         channel_id=channel,
                                         next_role_id=escape_role, priority=0)]
                if role != escape_role:
                    actions.append(RoutingAction(
                        kind=RoutingActionKind.FORWARD, channel_id=channel,
                        next_role_id=adaptive_role, priority=1))
                decisions.append(RoutingDecision(context, tuple(actions)))
    return build_routing_relation(policy, topology, decisions)


def _synthetic_resource() -> VCResourceArtifact:
    return VCResourceArtifact(
        vc_count=2, vc_ids=(0, 1),
        traffic_class_to_vcs=(("default", (0, 1)),),
        allowed_transitions=((0, 0), (1, 0), (1, 1)))


def _synthetic_binding(policy, resource):
    return _binding(policy, resource,
                    (("adaptive", (1,)), ("escape", (0,))))


# ── reference PASS fixtures ────────────────────────────────────────────────

def test_2x2_min_adapt_pass_evidence_is_pinned():
    policy, relation, resource, binding = _chain(_MESH2)
    cert = _cert(_MESH2, policy, relation, resource, binding)
    assert cert.verdict == "PASS"
    assert cert.proof_method == ADAPTIVE_ESCAPE_SUBFUNCTION_V1
    assert cert.to_dict()["evidence"] == _EXPECTED_2X2_EVIDENCE


def test_3x3_min_adapt_pass_counts():
    policy, relation, resource, binding = _chain(_MESH3)
    cert = _cert(_MESH3, policy, relation, resource, binding)
    evidence = cert.to_dict()["evidence"]
    assert cert.verdict == "PASS"
    assert evidence["routes_checked"] == 72
    assert evidence["max_escape_hops"] == 4
    assert evidence["escape_cdg_node_count"] == 24
    assert evidence["escape_cdg_edge_count"] == 28
    assert evidence["acyclic"] is True


def test_concentrated_mesh_pass_counts():
    policy, relation, resource, binding = _chain(_CMESH)
    cert = _cert(_CMESH, policy, relation, resource, binding)
    evidence = cert.to_dict()["evidence"]
    assert cert.verdict == "PASS"
    assert evidence["routes_checked"] == 12
    assert evidence["max_escape_hops"] == 2
    assert evidence["escape_cdg_node_count"] == 8
    assert evidence["escape_cdg_edge_count"] == 4


def test_roles_are_identified_by_kind_not_by_name():
    topology = _two_router()
    policy = RoutingPolicyDefinition(
        id="renamed_roles", algorithm="custom_adaptive",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        resource_roles=(_role("ad", RoutingResourceRoleKind.ADAPTIVE),
                        _role("esc", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("ad", "ad"), ("ad", "esc"),
                                  ("esc", "esc")))
    resource = _synthetic_resource()
    binding = _binding(policy, resource,
                       (("ad", (1,)), ("esc", (0,))))
    relation = _simple_relation(topology, policy, {0: 0, 1: 1},
                                escape_role="esc", adaptive_role="ad")
    cert = _cert(topology, policy, relation, resource, binding)
    evidence = cert.to_dict()["evidence"]
    assert cert.verdict == "PASS"
    assert evidence["escape_role_id"] == "esc"
    assert evidence["adaptive_role_ids"] == ["ad"]


def test_certificate_binds_all_five_parents():
    policy, relation, resource, binding = _chain(_MESH2)
    cert = _cert(_MESH2, policy, relation, resource, binding)
    d = cert.to_dict()
    assert d["type"] == "srota/AdaptiveEscapeCertificate"
    assert d["topology_hash"] == _MESH2.topology_hash()
    assert d["policy_hash"] == policy.policy_hash
    assert d["relation_hash"] == relation.relation_hash
    assert d["vc_resource_hash"] == resource.artifact_hash
    assert d["binding_hash"] == binding.binding_hash


def test_scope_and_assumptions_are_explicit():
    policy, relation, resource, binding = _chain(_MESH2)
    cert = _cert(_MESH2, policy, relation, resource, binding)
    assert "does not prove" in cert.scope
    assert len(cert.evidence["not_verified"]) == 7
    assert "backend implementation equivalence" in cert.evidence["not_verified"]


# ── exhaustive coverage checks ─────────────────────────────────────────────

@pytest.mark.parametrize("topology", [_MESH2, _MESH3])
def test_adaptive_escape_coverage_is_exhaustive(topology):
    policy, relation, resource, binding = _chain(topology)
    adaptive_roles = {role.id for role in policy.resource_roles
                      if role.kind == RoutingResourceRoleKind.ADAPTIVE}
    escape_role = next(role.id for role in policy.resource_roles
                       if role.kind == RoutingResourceRoleKind.ESCAPE)
    contexts = [d for d in relation.decisions
                if d.context.current_role_id in adaptive_roles
                and d.context.router_id != d.context.destination_router_id]
    assert contexts
    for decision in contexts:
        assert any(action.kind == RoutingActionKind.FORWARD
                   and action.next_role_id == escape_role
                   for action in decision.actions)
    evidence = _cert(topology, policy, relation, resource,
                     binding).to_dict()["evidence"]
    assert evidence["adaptive_context_count"] == len(contexts)
    assert evidence["adaptive_contexts_with_escape"] == len(contexts)


@pytest.mark.parametrize("topology", [_MESH2, _MESH3])
def test_injection_escape_coverage_is_exhaustive(topology):
    policy, relation, resource, binding = _chain(topology)
    escape_role = "escape"
    contexts = [d for d in relation.decisions
                if d.context.current_role_id is None
                and d.context.router_id != d.context.destination_router_id]
    assert contexts
    for decision in contexts:
        assert any(action.kind == RoutingActionKind.FORWARD
                   and action.next_role_id == escape_role
                   for action in decision.actions)


def test_concrete_adaptive_vcs_can_enter_escape():
    policy, relation, resource, binding = _chain(_MESH2)
    roles = dict(binding.role_to_vcs)
    concrete = set(resource.allowed_transitions)
    for vc in roles["adaptive"]:
        assert any((vc, dst) in concrete for dst in roles["escape"])
    evidence = _cert(_MESH2, policy, relation, resource,
                     binding).to_dict()["evidence"]
    assert evidence["escape_vc_transition_count"] == 1


@pytest.mark.parametrize("topology", [_MESH2, _MESH3])
def test_escape_closure_is_exhaustive(topology):
    policy, relation, resource, binding = _chain(topology)
    escape_role = "escape"
    contexts = [d for d in relation.decisions
                if d.context.current_role_id == escape_role
                and d.context.router_id != d.context.destination_router_id]
    assert contexts
    for decision in contexts:
        forwards = [a for a in decision.actions
                    if a.kind == RoutingActionKind.FORWARD]
        assert len(forwards) == 1
        assert forwards[0].next_role_id == escape_role


def test_concrete_escape_vc_closure_is_exhaustive():
    policy, relation, resource, binding = _chain(_MESH2)
    escape_vcs = set(dict(binding.role_to_vcs)["escape"])
    for src, dst in resource.allowed_transitions:
        if src in escape_vcs:
            assert dst in escape_vcs


def test_escape_cdg_universe_is_channels_times_escape_vcs():
    policy, relation, resource, binding = _chain(_MESH2)
    evidence = _cert(_MESH2, policy, relation, resource,
                     binding).to_dict()["evidence"]
    assert evidence["escape_cdg_node_count"] \
        == _MESH2.channel_count * len(dict(binding.role_to_vcs)["escape"])


# ── FAIL fixtures ──────────────────────────────────────────────────────────

def _replace_decision(relation, key, keep):
    out = []
    for decision in relation.decisions:
        current = (decision.context.router_id,
                   decision.context.destination_router_id,
                   decision.context.current_role_id)
        out.append(RoutingDecision(decision.context, keep(decision))
                   if current == key else decision)
    return out


def test_missing_adaptive_escape_action_fails_with_witness():
    policy, relation, resource, binding = _chain(_MESH2)
    modified = build_routing_relation(policy, _MESH2, _replace_decision(
        relation, (0, 3, "adaptive"),
        lambda d: tuple(a for a in d.actions if a.next_role_id != "escape")))
    cert = _cert(_MESH2, policy, modified, resource, binding)
    assert cert.verdict == "FAIL"
    assert cert.evidence["failure_stage"] == "adaptive_escape_accessibility"
    assert cert.evidence["witness"] == {
        "router_id": 0, "destination_router_id": 3,
        "current_role_id": "adaptive"}


def test_missing_injection_escape_action_fails_with_witness():
    policy, relation, resource, binding = _chain(_MESH2)
    modified = build_routing_relation(policy, _MESH2, _replace_decision(
        relation, (0, 3, None),
        lambda d: tuple(a for a in d.actions if a.next_role_id != "escape")))
    cert = _cert(_MESH2, policy, modified, resource, binding)
    assert cert.verdict == "FAIL"
    assert cert.evidence["failure_stage"] == "injection_escape_availability"
    assert cert.evidence["witness"] == {
        "router_id": 0, "destination_router_id": 3}


def test_escape_leaving_escape_role_fails():
    policy = _min_adapt_policy(allowed_role_transitions=(
        ("adaptive", "adaptive"), ("adaptive", "escape"),
        ("escape", "escape"), ("escape", "adaptive")))
    resource = _min_adapt_resource(
        transitions=tuple(sorted(_MIN_ADAPT_TRANSITIONS + ((0, 1),))))
    binding = _min_adapt_binding(policy, resource)
    base = materialize_routing_relation(_MESH2, _min_adapt_policy())
    modified = build_routing_relation(policy, _MESH2, _replace_decision(
        base, (0, 3, "escape"),
        lambda d: tuple(dataclasses.replace(a, next_role_id="adaptive")
                        for a in d.actions)))
    cert = _cert(_MESH2, policy, modified, resource, binding)
    assert cert.verdict == "FAIL"
    assert cert.evidence["failure_stage"] == "escape_closure"
    assert cert.evidence["witness"]["next_role_id"] == "adaptive"


def test_escape_route_loop_fails_with_witness():
    topology = _loop_topology()
    policy = _min_adapt_policy()
    resource = _synthetic_resource()
    binding = _synthetic_binding(policy, resource)
    relation = _simple_relation(topology, policy, {0: 0, 1: 1, 2: 2})
    cert = _cert(topology, policy, relation, resource, binding)
    assert cert.verdict == "FAIL"
    assert cert.evidence["failure_stage"] == "escape_route_reachability"
    assert cert.evidence["witness"] == {
        "src_router": 0, "destination_router_id": 2, "path": [0, 1, 0]}


def test_cyclic_escape_cdg_fails_although_every_route_terminates():
    topology = _ring_topology()
    policy = _min_adapt_policy()
    resource = _synthetic_resource()
    binding = _synthetic_binding(policy, resource)
    relation = _simple_relation(topology, policy, {0: 0, 1: 1, 2: 2})
    # independently prove reachability: every escape route terminates
    channels = {c.channel_id: c for c in topology.channels}
    decisions = {(d.context.router_id, d.context.destination_router_id,
                  d.context.current_role_id): d for d in relation.decisions}
    for src in range(3):
        for destination in range(3):
            if src == destination:
                continue
            current, hops = src, 0
            while current != destination:
                action = decisions[(current, destination, "escape")].actions[0]
                current = channels[action.channel_id].dst_router
                hops += 1
                assert hops <= 3
    cert = _cert(topology, policy, relation, resource, binding)
    assert cert.verdict == "FAIL"
    assert cert.evidence["failure_stage"] == "escape_cdg_acyclicity"
    assert cert.evidence["witness"]["cycle"] == (
        (0, 0), (1, 0), (2, 0), (0, 0))


# ── UNSUPPORTED fixtures ───────────────────────────────────────────────────

def test_wrong_proof_obligation_is_unsupported():
    policy = _min_adapt_policy(
        deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC)
    resource = _min_adapt_resource()
    binding = _min_adapt_binding(policy, resource)
    base = materialize_routing_relation(_MESH2, _min_adapt_policy())
    relation = build_routing_relation(policy, _MESH2, base.decisions)
    cert = _cert(_MESH2, policy, relation, resource, binding)
    assert cert.verdict == "UNSUPPORTED"
    assert "proof obligation" in cert.evidence["unsupported_reason"]


def test_multiple_escape_roles_are_unsupported():
    topology = _two_router()
    policy = RoutingPolicyDefinition(
        id="multi_escape", algorithm="custom_adaptive", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE),
                        _role("escape2", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("adaptive", "escape2"),
                                  ("escape", "escape"),
                                  ("escape2", "escape2")))
    resource = VCResourceArtifact(
        vc_count=3, vc_ids=(0, 1, 2),
        traffic_class_to_vcs=(("default", (0, 1, 2)),),
        allowed_transitions=((0, 0), (1, 1), (2, 0), (2, 1), (2, 2)))
    binding = _binding(policy, resource,
                       (("adaptive", (2,)), ("escape", (0,)),
                        ("escape2", (1,))))
    decisions = []
    for router_id in (0, 1):
        for destination in (0, 1):
            for role in (None, "adaptive", "escape", "escape2"):
                context = RoutingContext(router_id=router_id,
                                         destination_router_id=destination,
                                         current_role_id=role)
                if router_id == destination:
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.EJECT,
                                      channel_id=None, next_role_id=None,
                                      priority=0),)))
                elif role in ("escape", "escape2"):
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.FORWARD,
                                      channel_id=router_id,
                                      next_role_id=role, priority=0),)))
                else:
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.FORWARD,
                                      channel_id=router_id,
                                      next_role_id="escape", priority=0),
                        RoutingAction(kind=RoutingActionKind.FORWARD,
                                      channel_id=router_id,
                                      next_role_id="adaptive", priority=1))))
    relation = build_routing_relation(policy, topology, decisions)
    cert = _cert(topology, policy, relation, resource, binding)
    assert cert.verdict == "UNSUPPORTED"
    assert "ESCAPE role" in cert.evidence["unsupported_reason"]


def test_phase_role_is_unsupported():
    topology = _two_router()
    policy = RoutingPolicyDefinition(
        id="phase_role", algorithm="custom_adaptive", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE),
                        _role("phase0", RoutingResourceRoleKind.PHASE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape"),
                                  ("phase0", "phase0")))
    resource = VCResourceArtifact(
        vc_count=3, vc_ids=(0, 1, 2),
        traffic_class_to_vcs=(("default", (0, 1, 2)),),
        allowed_transitions=((0, 0), (1, 1), (2, 0), (2, 2)))
    binding = _binding(policy, resource,
                       (("adaptive", (2,)), ("escape", (0,)),
                        ("phase0", (1,))))
    decisions = []
    for router_id in (0, 1):
        for destination in (0, 1):
            for role in (None, "adaptive", "escape", "phase0"):
                context = RoutingContext(router_id=router_id,
                                         destination_router_id=destination,
                                         current_role_id=role)
                if router_id == destination:
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.EJECT,
                                      channel_id=None, next_role_id=None,
                                      priority=0),)))
                elif role in ("escape", "phase0"):
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.FORWARD,
                                      channel_id=router_id,
                                      next_role_id=role, priority=0),)))
                else:
                    decisions.append(RoutingDecision(context, (
                        RoutingAction(kind=RoutingActionKind.FORWARD,
                                      channel_id=router_id,
                                      next_role_id="escape", priority=0),
                        RoutingAction(kind=RoutingActionKind.FORWARD,
                                      channel_id=router_id,
                                      next_role_id="adaptive", priority=1))))
    relation = build_routing_relation(policy, topology, decisions)
    cert = _cert(topology, policy, relation, resource, binding)
    assert cert.verdict == "UNSUPPORTED"
    assert "phase" in cert.evidence["unsupported_reason"]


def test_stateful_escape_routing_is_unsupported():
    topology = _two_router()
    policy = _min_adapt_policy(state_requirements=(
        RoutingStateRequirement("phase", RoutingStateKind.PHASE),))
    resource = _min_adapt_resource()
    binding = _min_adapt_binding(policy, resource)
    phase0 = (RoutingStateBinding("phase", 0),)
    phase1 = (RoutingStateBinding("phase", 1),)
    decisions = []
    for router_id in (0, 1):
        for destination in (0, 1):
            for role in (None, "adaptive", "escape"):
                for state in (phase0, phase1):
                    context = RoutingContext(router_id=router_id,
                                             destination_router_id=destination,
                                             current_role_id=role, state=state)
                    if router_id == destination:
                        decisions.append(RoutingDecision(context, (
                            RoutingAction(kind=RoutingActionKind.EJECT,
                                          channel_id=None, next_role_id=None,
                                          priority=0),)))
                    elif role == "escape":
                        decisions.append(RoutingDecision(context, (
                            RoutingAction(kind=RoutingActionKind.FORWARD,
                                          channel_id=router_id,
                                          next_role_id="escape",
                                          next_state=state, priority=0),)))
                    else:
                        decisions.append(RoutingDecision(context, (
                            RoutingAction(kind=RoutingActionKind.FORWARD,
                                          channel_id=router_id,
                                          next_role_id="escape",
                                          next_state=state, priority=0),
                            RoutingAction(kind=RoutingActionKind.FORWARD,
                                          channel_id=router_id,
                                          next_role_id="adaptive",
                                          next_state=state, priority=1))))
    relation = build_routing_relation(
        policy, topology, decisions,
        state_domains=(RoutingStateDomain("phase", (0, 1)),))
    cert = _cert(topology, policy, relation, resource, binding)
    assert cert.verdict == "UNSUPPORTED"
    assert "stateful" in cert.evidence["unsupported_reason"]


def test_multiple_escape_actions_are_unsupported():
    policy, relation, resource, binding = _chain(_MESH2)
    modified = build_routing_relation(policy, _MESH2, _replace_decision(
        relation, (0, 3, "escape"),
        lambda d: (d.actions[0],
                   RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=1,
                                 next_role_id="escape", priority=0))))
    cert = _cert(_MESH2, policy, modified, resource, binding)
    assert cert.verdict == "UNSUPPORTED"
    assert "multiple legal escape actions" \
        in cert.evidence["unsupported_reason"]


# ── tampering / malformed parents ──────────────────────────────────────────

@pytest.mark.parametrize("slot", [
    "topology", "policy", "relation", "vc_resource", "binding"])
def test_non_artifact_parents_raise(slot):
    policy, relation, resource, binding = _chain(_MESH2)
    parents = {"topology": _MESH2, "policy": policy, "relation": relation,
               "vc_resource": resource, "binding": binding}
    parents[slot] = object()
    with pytest.raises(AdaptiveEscapeVerificationError):
        certify_adaptive_escape(**parents)


def test_wrong_topology_is_rejected():
    policy, relation, resource, binding = _chain(_MESH2)
    with pytest.raises(AdaptiveEscapeVerificationError):
        _cert(_MESH3, policy, relation, resource, binding)


def test_wrong_policy_is_rejected():
    policy, relation, resource, binding = _chain(_MESH2)
    other_policy = _min_adapt_policy(id="other")
    with pytest.raises(AdaptiveEscapeVerificationError):
        _cert(_MESH2, other_policy, relation, resource, binding)


def test_tampered_hashes_raise():
    policy, relation, resource, binding = _chain(_MESH2)
    object.__setattr__(relation, "relation_hash", "0" * 64)
    with pytest.raises(AdaptiveEscapeVerificationError,
                       match="relation failed parent validation"):
        _cert(_MESH2, policy, relation, resource, binding)


def test_tampered_binding_hash_raises():
    policy, relation, resource, binding = _chain(_MESH2)
    object.__setattr__(binding, "binding_hash", "0" * 64)
    with pytest.raises(AdaptiveEscapeVerificationError,
                       match="binding failed parent validation"):
        _cert(_MESH2, policy, relation, resource, binding)


def test_wrong_vc_resource_is_rejected():
    policy, relation, resource, binding = _chain(_MESH2)
    other_resource = _min_adapt_resource(
        transitions=tuple(t for t in _MIN_ADAPT_TRANSITIONS if t != (3, 3)))
    with pytest.raises(AdaptiveEscapeVerificationError,
                       match="binding does not bind this VC resource"):
        _cert(_MESH2, policy, relation, other_resource, binding)


# ── determinism / immutability ─────────────────────────────────────────────

def test_repeated_verification_is_deterministic():
    policy, relation, resource, binding = _chain(_MESH3)
    first = _cert(_MESH3, policy, relation, resource, binding)
    second = _cert(_MESH3, policy, relation, resource, binding)
    assert first.to_dict() == second.to_dict()


def test_construction_order_does_not_change_the_certificate():
    policy, relation, resource, binding = _chain(_MESH2)
    shuffled = build_routing_relation(
        policy, _MESH2, tuple(reversed([
            RoutingDecision(d.context, tuple(reversed(d.actions)))
            for d in relation.decisions])))
    assert shuffled.relation_hash == relation.relation_hash
    assert _cert(_MESH2, policy, shuffled, resource, binding).to_dict() \
        == _cert(_MESH2, policy, relation, resource, binding).to_dict()


def test_certificate_evidence_is_deeply_immutable():
    evidence = {"nested": {"values": [1, 2]}, "cycle": [[0, 0]]}
    cert = AdaptiveEscapeCertificate(
        proof_method=ADAPTIVE_ESCAPE_SUBFUNCTION_V1, verdict="PASS",
        topology_hash="a" * 64, policy_hash="b" * 64, relation_hash="c" * 64,
        vc_resource_hash="d" * 64, binding_hash="e" * 64, evidence=evidence)
    evidence["nested"]["values"].append(3)
    evidence["cycle"].append([9, 9])
    assert cert.evidence["nested"]["values"] == (1, 2)
    assert cert.evidence["cycle"] == ((0, 0),)
    with pytest.raises(TypeError):
        cert.evidence["nested"] = {}


def test_to_dict_returns_fresh_data():
    policy, relation, resource, binding = _chain(_MESH2)
    cert = _cert(_MESH2, policy, relation, resource, binding)
    first = cert.to_dict()
    first["evidence"]["escape_vcs"].append(9)
    first["evidence"]["not_verified"].clear()
    second = cert.to_dict()
    assert second["evidence"]["escape_vcs"] == [0]
    assert len(second["evidence"]["not_verified"]) == 7


# ── scope sentinels ────────────────────────────────────────────────────────

def test_certificate_schema_fields():
    names = {f.name for f in dataclasses.fields(AdaptiveEscapeCertificate)}
    assert names == {
        "proof_method", "verdict", "topology_hash", "policy_hash",
        "relation_hash", "vc_resource_hash", "binding_hash", "evidence",
        "tool", "scope", "schema_version"}


def test_verifier_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(ae))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("route_artifact", "resolved_route", "vc_assignment",
                 "channel_vc_cdg", "protocol_vc", "booksim", "astra",
                 "backend", "cli")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_verifier_is_independent_of_9a_and_9b():
    assert not hasattr(ae, "certify_channel_vc_deadlock")
    assert not hasattr(ae, "certify_protocol_vc_separation")
