"""RoutingRelationArtifact tests — topology-bound legal routing actions.

The relation records the complete envelope of legal actions; it does not
select congestion-aware actions, bind roles to VCs, or prove deadlock
freedom. Reference fixtures prove the schema can express MinAdapt-like,
XY/YX-envelope and phased-state routing without implementing any of them.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.route_artifact import DOR_XY, RouteArtifact
from veritx_dse.model import routing_relation as rr
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RoutingStateKind, RoutingStateRequirement,
    RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_relation import (
    ROUTING_RELATION_SCHEMA_VERSION, RoutingAction, RoutingActionKind,
    RoutingContext, RoutingDecision, RoutingRelationArtifact,
    RoutingRelationError, RoutingStateBinding, RoutingStateDomain,
    build_routing_relation,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_family,
)

GOLDEN_MIN_ADAPT = (
    "46abf0d59fcb9f3faf656183736052ef3993ca1e545fb91e7e70b3627f38b528")
GOLDEN_XY_YX = (
    "0fda463e36aa42fe7bcb9ff85bdf3c085e3e53e7aac0aa5276a28701d288642c")
GOLDEN_PHASED = (
    "3d474e1e06104420d5e5dfbb47731a96370340a6088496f5f6f29a6cb3f2da06")

EXPECTED_FIELDS = {
    "topology_hash", "policy_hash", "state_domains", "decisions",
    "schema_version", "relation_hash",
}

FORBIDDEN_KEYS = {
    "design_hash", "mapping_hash", "attachment_hash", "endpoint_id",
    "endpoint_ids", "logical_rank", "rank", "vc_id", "vc_ids", "vc_count",
    "vc_start", "vc_end", "booksim", "booksim_routing_function", "astra",
    "backend", "binary", "binary_path", "seed", "congestion",
    "congestion_values", "verdict", "certificate", "deadlock_certificate",
}


def _role(rid, kind):
    return RoutingResourceRole(id=rid, kind=kind)


def _min_adapt_policy() -> RoutingPolicyDefinition:
    return RoutingPolicyDefinition(
        id="min_adapt_like", algorithm="per_hop_min_adaptive",
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
                                  ("escape", "escape")))


def _xy_yx_policy() -> RoutingPolicyDefinition:
    return RoutingPolicyDefinition(
        id="xy_yx_envelope", algorithm="source_commit_xy_yx",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.SOURCE_COMMIT,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.RNG,
        deadlock_proof_obligation=DeadlockProofObligation.RESOURCE_ORDERING,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(_role("xy", RoutingResourceRoleKind.ROUTE_ORDER),
                        _role("yx", RoutingResourceRoleKind.ROUTE_ORDER)),
        allowed_role_transitions=(("xy", "xy"), ("yx", "yx")))


def _phased_policy() -> RoutingPolicyDefinition:
    return RoutingPolicyDefinition(
        id="toy_phased", algorithm="toy_phased", algorithm_version=1,
        path_mode=PathMode.NONMINIMAL, decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.RNG,
        deadlock_proof_obligation=DeadlockProofObligation.RESOURCE_ORDERING,
        state_requirements=(RoutingStateRequirement("phase",
                                                    RoutingStateKind.PHASE),),
        resource_roles=(_role("phase0", RoutingResourceRoleKind.PHASE),
                        _role("phase1", RoutingResourceRoleKind.PHASE)),
        allowed_role_transitions=(("phase0", "phase1"),
                                  ("phase1", "phase1")))


def _dor_policy() -> RoutingPolicyDefinition:
    return RoutingPolicyDefinition(
        id="dor_xy", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),))


def _mesh4() -> TopologyArtifact:
    return materialize_family(MaterializedFamily.MESH, endpoint_count=4)


def _phased_topology() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.MESH,
        routers=(Router(0, (0,), 1), Router(1, (1,), 1)),
        channels=(DirectedChannel(0, 0, 1, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 1, 0, 0, 64, 1)))


def _channel(topo, src, dst):
    ids = [c.channel_id for c in topo.channels
           if c.src_router == src and c.dst_router == dst]
    assert len(ids) == 1, (src, dst, ids)
    return ids[0]


def _coords(topo):
    return {r.router_id: r.coordinates for r in topo.routers}


def _dor_first_hops(topo):
    artifact = RouteArtifact.from_topology(
        topo, name="seed", routing_classes=(DOR_XY,))
    return {(s, d): ch for (_cls, s, d), ch in artifact.entries.items()}


def _x_step(topo, r, d):
    coords = _coords(topo)
    id_of = {c: i for i, c in coords.items()}
    (x, y), (dx, _dy) = coords[r], coords[d]
    return _channel(topo, r, id_of[(x + (1 if dx > x else -1), y)])


def _y_step(topo, r, d):
    coords = _coords(topo)
    id_of = {c: i for i, c in coords.items()}
    (x, y), (_dx, dy) = coords[r], coords[d]
    return _channel(topo, r, id_of[(x, y + (1 if dy > y else -1))])


def _forward(channel, role, state=(), priority=0) -> RoutingAction:
    return RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=channel,
                         next_role_id=role, next_state=state,
                         priority=priority)


def _eject() -> RoutingAction:
    return RoutingAction(kind=RoutingActionKind.EJECT, channel_id=None,
                         next_role_id=None, priority=0)


def _min_adapt_decisions(topo):
    dor = _dor_first_hops(topo)
    decisions = []
    for r in range(topo.router_count):
        for d in range(topo.router_count):
            for role in (None, "adaptive", "escape"):
                context = RoutingContext(router_id=r, destination_router_id=d,
                                         current_role_id=role)
                if r == d:
                    decisions.append(RoutingDecision(context, (_eject(),)))
                    continue
                escape = _forward(dor[(r, d)], "escape", (), 0)
                if role == "escape":
                    decisions.append(RoutingDecision(context, (escape,)))
                else:
                    adaptive = []
                    if _coords(topo)[r][0] != _coords(topo)[d][0]:
                        adaptive.append(_forward(_x_step(topo, r, d),
                                                 "adaptive", (), 1))
                    if _coords(topo)[r][1] != _coords(topo)[d][1]:
                        adaptive.append(_forward(_y_step(topo, r, d),
                                                 "adaptive", (), 1))
                    decisions.append(RoutingDecision(
                        context, (escape, *adaptive)))
    return decisions


def _xy_yx_decisions(topo):
    dor = _dor_first_hops(topo)
    decisions = []
    for r in range(topo.router_count):
        for d in range(topo.router_count):
            for role in (None, "xy", "yx"):
                context = RoutingContext(router_id=r, destination_router_id=d,
                                         current_role_id=role)
                if r == d:
                    decisions.append(RoutingDecision(context, (_eject(),)))
                elif role is None:
                    yx_first = (_y_step(topo, r, d)
                                if _coords(topo)[r][1] != _coords(topo)[d][1]
                                else dor[(r, d)])
                    decisions.append(RoutingDecision(context, (
                        _forward(dor[(r, d)], "xy"),
                        _forward(yx_first, "yx"))))
                elif role == "xy":
                    decisions.append(RoutingDecision(
                        context, (_forward(dor[(r, d)], "xy"),)))
                else:
                    yx_first = (_y_step(topo, r, d)
                                if _coords(topo)[r][1] != _coords(topo)[d][1]
                                else dor[(r, d)])
                    decisions.append(RoutingDecision(
                        context, (_forward(yx_first, "yx"),)))
    return decisions


def _phased_decisions(topo):
    phase0 = (RoutingStateBinding("phase", 0),)
    phase1 = (RoutingStateBinding("phase", 1),)
    decisions = []
    for r in range(topo.router_count):
        for d in range(topo.router_count):
            for role in (None, "phase0", "phase1"):
                for state in (phase0, phase1):
                    context = RoutingContext(router_id=r,
                                             destination_router_id=d,
                                             current_role_id=role,
                                             state=state)
                    if r == d:
                        decisions.append(RoutingDecision(context, (_eject(),)))
                    else:
                        decisions.append(RoutingDecision(context, (_forward(
                            _channel(topo, r, d), "phase1", phase1, 0),)))
    return decisions


@pytest.fixture(scope="module")
def min_adapt_relation():
    return build_routing_relation(
        _min_adapt_policy(), _mesh4(), _min_adapt_decisions(_mesh4()))


@pytest.fixture(scope="module")
def xy_yx_relation():
    return build_routing_relation(
        _xy_yx_policy(), _mesh4(), _xy_yx_decisions(_mesh4()))


@pytest.fixture(scope="module")
def phased_relation():
    return build_routing_relation(
        _phased_policy(), _phased_topology(), _phased_decisions(
            _phased_topology()),
        state_domains=(RoutingStateDomain("phase", (0, 1)),))


def _decision_map(artifact):
    return {(d.context.router_id, d.context.destination_router_id,
             d.context.current_role_id): d for d in artifact.decisions}


# ── reference fixture identity ─────────────────────────────────────────────

def test_min_adapt_like_relation_hash_is_pinned(min_adapt_relation):
    assert min_adapt_relation.relation_hash == GOLDEN_MIN_ADAPT
    assert len(min_adapt_relation.decisions) == 48
    assert min_adapt_relation.state_domains == ()


def test_xy_yx_relation_hash_is_pinned(xy_yx_relation):
    assert xy_yx_relation.relation_hash == GOLDEN_XY_YX
    assert len(xy_yx_relation.decisions) == 48


def test_phased_relation_hash_is_pinned(phased_relation):
    assert phased_relation.relation_hash == GOLDEN_PHASED
    assert len(phased_relation.decisions) == 24
    assert phased_relation.state_domains == (
        RoutingStateDomain("phase", (0, 1)),)


@pytest.mark.parametrize("fixture", [
    "min_adapt_relation", "xy_yx_relation", "phased_relation"])
def test_reference_fixtures_round_trip(fixture, request):
    artifact = request.getfixturevalue(fixture)
    restored = RoutingRelationArtifact.from_dict(artifact.to_dict())
    assert restored.relation_hash == artifact.relation_hash
    assert restored.to_dict() == artifact.to_dict()


# ── MinAdapt-like behavior ─────────────────────────────────────────────────

def test_min_adapt_injection_offers_escape_plus_two_adaptive(min_adapt_relation):
    decision = _decision_map(min_adapt_relation)[(0, 3, None)]
    assert [(a.channel_id, a.next_role_id, a.priority)
            for a in decision.actions] == [
        (0, "adaptive", 1), (0, "escape", 0), (1, "adaptive", 1)]


def test_min_adapt_adaptive_context_keeps_same_pattern(min_adapt_relation):
    decision = _decision_map(min_adapt_relation)[(0, 3, "adaptive")]
    assert [(a.channel_id, a.next_role_id, a.priority)
            for a in decision.actions] == [
        (0, "adaptive", 1), (0, "escape", 0), (1, "adaptive", 1)]


def test_min_adapt_escape_context_uses_escape_only(min_adapt_relation):
    decision = _decision_map(min_adapt_relation)[(0, 3, "escape")]
    assert [(a.channel_id, a.next_role_id) for a in decision.actions] \
        == [(0, "escape")]


def test_min_adapt_destination_is_eject_only(min_adapt_relation):
    decision = _decision_map(min_adapt_relation)[(3, 3, None)]
    assert len(decision.actions) == 1
    assert decision.actions[0].kind == RoutingActionKind.EJECT
    assert decision.actions[0].channel_id is None
    assert decision.actions[0].next_role_id is None
    assert decision.actions[0].next_state == ()


# ── XY/YX envelope behavior ────────────────────────────────────────────────

def test_xy_yx_injection_may_commit_to_either_role(xy_yx_relation):
    decision = _decision_map(xy_yx_relation)[(0, 3, None)]
    assert {a.next_role_id for a in decision.actions} == {"xy", "yx"}
    assert {a.channel_id for a in decision.actions} == {0, 1}


def test_xy_yx_held_role_stays_within_role(xy_yx_relation):
    decisions = _decision_map(xy_yx_relation)
    assert {a.next_role_id for a in decisions[(0, 3, "xy")].actions} == {"xy"}
    assert {a.next_role_id for a in decisions[(0, 3, "yx")].actions} == {"yx"}
    assert {a.channel_id for a in decisions[(0, 3, "yx")].actions} == {1}


# ── phased state ───────────────────────────────────────────────────────────

def test_phased_state_round_trips_through_actions(phased_relation):
    decisions = _decision_map(phased_relation)
    phase0 = (RoutingStateBinding("phase", 0),)
    phase1 = (RoutingStateBinding("phase", 1),)
    injection = [d for d in phased_relation.decisions
                 if d.context.router_id == 0
                 and d.context.destination_router_id == 1
                 and d.context.current_role_id is None]
    assert {d.context.state for d in injection} == {phase0, phase1}
    for decision in injection:
        action = decision.actions[0]
        assert action.next_role_id == "phase1"
        assert action.next_state == phase1


# ── identity mutation gates ────────────────────────────────────────────────

def _rebuild(artifact, policy, topology, decisions):
    return build_routing_relation(
        policy, topology, decisions,
        state_domains=artifact.state_domains)


def test_priority_change_moves_identity(min_adapt_relation):
    decisions = []
    for decision in min_adapt_relation.decisions:
        actions = tuple(
            dataclasses.replace(a, priority=7)
            if a.kind == RoutingActionKind.FORWARD
            and a.next_role_id == "escape" else a
            for a in decision.actions)
        decisions.append(RoutingDecision(decision.context, actions))
    changed = _rebuild(min_adapt_relation, _min_adapt_policy(), _mesh4(),
                       decisions)
    assert changed.relation_hash != min_adapt_relation.relation_hash


def test_role_change_moves_identity(min_adapt_relation):
    decisions = []
    for decision in min_adapt_relation.decisions:
        actions = tuple(
            dataclasses.replace(a, next_role_id="escape")
            if a.kind == RoutingActionKind.FORWARD
            and a.channel_id == 1 and a.next_role_id == "adaptive" else a
            for a in decision.actions)
        decisions.append(RoutingDecision(decision.context, actions))
    changed = _rebuild(min_adapt_relation, _min_adapt_policy(), _mesh4(),
                       decisions)
    assert changed.relation_hash != min_adapt_relation.relation_hash


def test_state_change_moves_identity(phased_relation):
    phase0 = (RoutingStateBinding("phase", 0),)
    decisions = []
    for decision in phased_relation.decisions:
        if decision.actions and \
                decision.actions[0].kind == RoutingActionKind.FORWARD:
            actions = (dataclasses.replace(decision.actions[0],
                                           next_state=phase0),)
            decisions.append(RoutingDecision(decision.context, actions))
        else:
            decisions.append(decision)
    changed = build_routing_relation(
        _phased_policy(), _phased_topology(), decisions,
        state_domains=(RoutingStateDomain("phase", (0, 1)),))
    assert changed.relation_hash != phased_relation.relation_hash


def test_channel_change_moves_identity(min_adapt_relation):
    decisions = []
    for decision in min_adapt_relation.decisions:
        actions = tuple(
            dataclasses.replace(a, channel_id=1)
            if a.next_role_id == "escape" and a.channel_id == 0
            and decision.context.router_id == 0 else a
            for a in decision.actions)
        decisions.append(RoutingDecision(decision.context, actions))
    changed = _rebuild(min_adapt_relation, _min_adapt_policy(), _mesh4(),
                       decisions)
    assert changed.relation_hash != min_adapt_relation.relation_hash


def test_domain_values_participate_in_identity():
    topology = _phased_topology()
    base = build_routing_relation(
        _phased_policy(), topology, _phased_decisions(topology),
        state_domains=(RoutingStateDomain("phase", (0, 1)),))
    other_hash = RoutingRelationArtifact(
        topology_hash=topology.topology_hash(), policy_hash=_phased_policy().policy_hash,
        state_domains=(RoutingStateDomain("phase", (0, 1, 2)),),
        decisions=base.decisions).relation_hash
    assert other_hash != base.relation_hash


def test_construction_order_does_not_move_identity(min_adapt_relation):
    shuffled_decisions = tuple(reversed([
        RoutingDecision(d.context, tuple(reversed(d.actions)))
        for d in min_adapt_relation.decisions]))
    same = _rebuild(min_adapt_relation, _min_adapt_policy(), _mesh4(),
                    shuffled_decisions)
    assert same.relation_hash == min_adapt_relation.relation_hash
    assert same.to_dict() == min_adapt_relation.to_dict()


# ── totality ───────────────────────────────────────────────────────────────

def test_missing_context_is_refused(min_adapt_relation):
    with pytest.raises(RoutingRelationError, match="not total"):
        _rebuild(min_adapt_relation, _min_adapt_policy(), _mesh4(),
                 min_adapt_relation.decisions[:-1])


def test_missing_state_combination_is_refused(phased_relation):
    with pytest.raises(RoutingRelationError, match="not total"):
        _rebuild(phased_relation, _phased_policy(), _phased_topology(),
                 phased_relation.decisions[:-1])


def test_duplicate_context_is_refused(min_adapt_relation):
    with pytest.raises(RoutingRelationError, match="duplicate decision"):
        RoutingRelationArtifact(
            topology_hash=min_adapt_relation.topology_hash,
            policy_hash=min_adapt_relation.policy_hash,
            decisions=min_adapt_relation.decisions
            + (min_adapt_relation.decisions[0],))


def test_duplicate_action_is_refused():
    context = RoutingContext(router_id=0, destination_router_id=1,
                             current_role_id=None)
    action = _forward(0, "adaptive")
    with pytest.raises(RoutingRelationError, match="duplicate semantic"):
        RoutingDecision(context, (action, action))


def test_destination_and_forward_consistency():
    destination = RoutingContext(router_id=1, destination_router_id=1,
                                 current_role_id=None)
    origin = RoutingContext(router_id=0, destination_router_id=1,
                            current_role_id=None)
    with pytest.raises(RoutingRelationError, match="exactly one EJECT"):
        RoutingDecision(destination, (_forward(0, "adaptive"),))
    with pytest.raises(RoutingRelationError, match="EJECT"):
        RoutingDecision(origin, (_eject(),))
    with pytest.raises(RoutingRelationError, match="non-empty"):
        RoutingDecision(destination, ())


# ── strict parsing ─────────────────────────────────────────────────────────

def _valid_dict(relation):
    return relation.to_dict()


def test_unknown_fields_are_refused(min_adapt_relation):
    d = _valid_dict(min_adapt_relation)
    d["extra"] = 1
    with pytest.raises(RoutingRelationError, match="unknown fields"):
        RoutingRelationArtifact.from_dict(d)


@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS | {"type"}))
def test_missing_required_fields_are_refused(min_adapt_relation, field):
    d = _valid_dict(min_adapt_relation)
    d.pop(field)
    with pytest.raises(RoutingRelationError):
        RoutingRelationArtifact.from_dict(d)


@pytest.mark.parametrize("bad_type", [None, "srota/RouteArtifact", 3])
def test_type_tag_is_strict(min_adapt_relation, bad_type):
    d = _valid_dict(min_adapt_relation)
    if bad_type is None:
        d.pop("type")
    else:
        d["type"] = bad_type
    with pytest.raises(RoutingRelationError, match="type"):
        RoutingRelationArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [2, True, "1", 1.0])
def test_schema_version_is_strict(min_adapt_relation, bad):
    d = _valid_dict(min_adapt_relation)
    d["schema_version"] = bad
    with pytest.raises(RoutingRelationError, match="schema_version"):
        RoutingRelationArtifact.from_dict(d)


def test_relation_hash_tampering_is_refused(min_adapt_relation):
    d = _valid_dict(min_adapt_relation)
    d["relation_hash"] = "0" * 64
    with pytest.raises(RoutingRelationError, match="relation_hash"):
        RoutingRelationArtifact.from_dict(d)
    d = _valid_dict(min_adapt_relation)
    d["relation_hash"] = ""
    with pytest.raises(RoutingRelationError, match="relation_hash"):
        RoutingRelationArtifact.from_dict(d)


def test_persisted_collections_must_be_canonical(min_adapt_relation,
                                                 phased_relation):
    d = _valid_dict(min_adapt_relation)
    d["decisions"] = list(reversed(d["decisions"]))
    with pytest.raises(RoutingRelationError, match="sorted"):
        RoutingRelationArtifact.from_dict(d)
    d = _valid_dict(min_adapt_relation)
    index = next(i for i, x in enumerate(d["decisions"])
                 if len(x["actions"]) > 1)
    d["decisions"][index]["actions"] = list(
        reversed(d["decisions"][index]["actions"]))
    with pytest.raises(RoutingRelationError, match="canonical order"):
        RoutingRelationArtifact.from_dict(d)
    d = _valid_dict(phased_relation)
    d["state_domains"][0]["values"] = [1, 0]
    with pytest.raises(RoutingRelationError, match="canonical"):
        RoutingRelationArtifact.from_dict(d)
    d = _valid_dict(phased_relation)
    d["state_domains"][0]["values"] = [0, 0]
    with pytest.raises(RoutingRelationError, match="duplicate"):
        RoutingRelationArtifact.from_dict(d)


def test_action_kind_is_strict(min_adapt_relation):
    d = _valid_dict(min_adapt_relation)
    for index, decision in enumerate(d["decisions"]):
        if decision["context"]["router_id"] != \
                decision["context"]["destination_router_id"]:
            decision["actions"][0]["kind"] = "hover"
            break
    with pytest.raises(RoutingRelationError, match="kind"):
        RoutingRelationArtifact.from_dict(d)


def test_action_and_context_shapes_are_strict(min_adapt_relation):
    d = _valid_dict(min_adapt_relation)
    index = next(i for i, x in enumerate(d["decisions"])
                 if x["context"]["router_id"] != x["context"]
                 ["destination_router_id"])
    d["decisions"][index]["actions"][0]["next_state"] = "phase"
    with pytest.raises(RoutingRelationError, match="next_state"):
        RoutingRelationArtifact.from_dict(d)
    d = _valid_dict(min_adapt_relation)
    d["decisions"][index]["context"]["state"] = {"phase": 0}
    with pytest.raises(RoutingRelationError, match="state"):
        RoutingRelationArtifact.from_dict(d)


# ── parent validation ──────────────────────────────────────────────────────

def test_wrong_topology_parent_is_refused(min_adapt_relation):
    torus = materialize_family(MaterializedFamily.TORUS, endpoint_count=4)
    with pytest.raises(RoutingRelationError, match="topology_hash"):
        min_adapt_relation.validate_against(torus, _min_adapt_policy())


def test_wrong_policy_parent_is_refused(min_adapt_relation):
    with pytest.raises(RoutingRelationError, match="policy_hash"):
        min_adapt_relation.validate_against(_mesh4(), _xy_yx_policy())


def test_non_artifact_parents_are_refused(min_adapt_relation):
    with pytest.raises(RoutingRelationError, match="TopologyArtifact"):
        min_adapt_relation.validate_against(object(), _min_adapt_policy())
    with pytest.raises(RoutingRelationError, match="RoutingPolicyDefinition"):
        min_adapt_relation.validate_against(_mesh4(), object())


def _tampered(artifact, new_decisions):
    return RoutingRelationArtifact(
        topology_hash=artifact.topology_hash, policy_hash=artifact.policy_hash,
        state_domains=artifact.state_domains, decisions=new_decisions)


def test_undeclared_current_role_is_refused(min_adapt_relation):
    decisions = tuple(
        RoutingDecision(RoutingContext(router_id=d.context.router_id,
                                       destination_router_id=(
                                           d.context.destination_router_id),
                                       current_role_id="ghost",
                                       state=d.context.state),
                        d.actions)
        if d.context.current_role_id is None else d
        for d in min_adapt_relation.decisions)
    with pytest.raises(RoutingRelationError, match="current role"):
        _tampered(min_adapt_relation, decisions).validate_against(
            _mesh4(), _min_adapt_policy())


def test_undeclared_next_role_is_refused(min_adapt_relation):
    decisions = tuple(
        RoutingDecision(d.context, tuple(
            dataclasses.replace(a, next_role_id="ghost")
            if a.kind == RoutingActionKind.FORWARD and a.channel_id == 1
            else a for a in d.actions))
        for d in min_adapt_relation.decisions)
    with pytest.raises(RoutingRelationError, match="next role"):
        _tampered(min_adapt_relation, decisions).validate_against(
            _mesh4(), _min_adapt_policy())


def test_illegal_role_transition_is_refused(xy_yx_relation):
    decisions = tuple(
        RoutingDecision(d.context, tuple(
            dataclasses.replace(a, next_role_id="yx")
            if a.kind == RoutingActionKind.FORWARD
            and a.next_role_id == "xy"
            and d.context.current_role_id == "xy" else a
            for a in d.actions))
        for d in xy_yx_relation.decisions)
    with pytest.raises(RoutingRelationError, match="transition"):
        _tampered(xy_yx_relation, decisions).validate_against(
            _mesh4(), _xy_yx_policy())


def test_nonexistent_channel_is_refused(min_adapt_relation):
    decisions = tuple(
        RoutingDecision(d.context, tuple(
            dataclasses.replace(a, channel_id=999)
            if a.kind == RoutingActionKind.FORWARD
            and a.channel_id == 0 and a.next_role_id == "adaptive" else a
            for a in d.actions))
        for d in min_adapt_relation.decisions)
    with pytest.raises(RoutingRelationError, match="not in the topology"):
        _tampered(min_adapt_relation, decisions).validate_against(
            _mesh4(), _min_adapt_policy())


def test_channel_leaving_wrong_router_is_refused(min_adapt_relation):
    wrong = None
    for channel in _mesh4().channels:
        if channel.src_router != 0:
            wrong = channel.channel_id
            break
    decisions = []
    for d in min_adapt_relation.decisions:
        actions = tuple(
            dataclasses.replace(a, channel_id=wrong)
            if a.kind == RoutingActionKind.FORWARD
            and a.channel_id == 0 and a.next_role_id == "adaptive"
            else a for a in d.actions)
        decisions.append(RoutingDecision(d.context, actions))
    with pytest.raises(RoutingRelationError, match="leaves router"):
        _tampered(min_adapt_relation, tuple(decisions)).validate_against(
            _mesh4(), _min_adapt_policy())


def test_missing_state_domain_is_refused(phased_relation):
    tampered = RoutingRelationArtifact(
        topology_hash=phased_relation.topology_hash,
        policy_hash=phased_relation.policy_hash, state_domains=(),
        decisions=phased_relation.decisions)
    with pytest.raises(RoutingRelationError, match="state domains"):
        tampered.validate_against(_phased_topology(), _phased_policy())


def test_extra_state_domain_is_refused(phased_relation):
    tampered = RoutingRelationArtifact(
        topology_hash=phased_relation.topology_hash,
        policy_hash=phased_relation.policy_hash,
        state_domains=phased_relation.state_domains
        + (RoutingStateDomain("mode", (0,)),),
        decisions=phased_relation.decisions)
    with pytest.raises(RoutingRelationError, match="state domains"):
        tampered.validate_against(_phased_topology(), _phased_policy())


def test_state_value_outside_domain_is_refused(phased_relation):
    phase0 = (RoutingStateBinding("phase", 0),)
    phase9 = (RoutingStateBinding("phase", 9),)
    decisions = tuple(
        RoutingDecision(RoutingContext(
            router_id=d.context.router_id,
            destination_router_id=d.context.destination_router_id,
            current_role_id=d.context.current_role_id,
            state=phase9 if d.context.state == phase0 else d.context.state),
            d.actions)
        for d in phased_relation.decisions)
    with pytest.raises(RoutingRelationError, match="outside the declared"):
        _tampered(phased_relation, decisions).validate_against(
            _phased_topology(), _phased_policy())


def test_empty_state_domain_is_refused():
    with pytest.raises(RoutingRelationError, match="non-empty"):
        RoutingStateDomain("phase", ())


@pytest.mark.parametrize("bad_values", [
    (0, 0), (0, 1.5), (True,), (None,), ("",), ({"x": 1},),
])
def test_malformed_state_domains_are_refused(bad_values):
    with pytest.raises(RoutingRelationError):
        RoutingStateDomain("phase", bad_values)


def test_duplicate_and_extra_state_bindings_are_refused():
    with pytest.raises(RoutingRelationError, match="duplicate"):
        RoutingContext(router_id=0, destination_router_id=1,
                       current_role_id=None,
                       state=(RoutingStateBinding("phase", 0),
                              RoutingStateBinding("phase", 1)))
    with pytest.raises(RoutingRelationError, match="duplicate"):
        RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=0,
                      next_role_id="adaptive",
                      next_state=(RoutingStateBinding("phase", 0),
                                  RoutingStateBinding("phase", 1)))


def test_eject_with_channel_or_role_is_refused():
    with pytest.raises(RoutingRelationError, match="channel_id"):
        RoutingAction(kind=RoutingActionKind.EJECT, channel_id=0,
                      next_role_id=None)
    with pytest.raises(RoutingRelationError, match="next_role_id"):
        RoutingAction(kind=RoutingActionKind.EJECT, channel_id=None,
                      next_role_id="escape")
    with pytest.raises(RoutingRelationError, match="next-state"):
        RoutingAction(kind=RoutingActionKind.EJECT, channel_id=None,
                      next_role_id=None,
                      next_state=(RoutingStateBinding("phase", 0),))


def test_bool_priority_and_channel_are_refused():
    with pytest.raises(RoutingRelationError, match="priority"):
        RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=0,
                      next_role_id="adaptive", priority=True)
    with pytest.raises(RoutingRelationError, match="channel_id"):
        RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=True,
                      next_role_id="adaptive")


# ── deterministic authority guard ──────────────────────────────────────────

def test_deterministic_policy_is_refused_by_the_builder():
    with pytest.raises(RoutingRelationError,
                       match="REDUNDANT_DETERMINISTIC_POLICY"):
        build_routing_relation(_dor_policy(), _mesh4(), ())


def test_deterministic_policy_is_refused_by_validation(min_adapt_relation):
    deterministic = _dor_policy()
    tampered = RoutingRelationArtifact(
        topology_hash=min_adapt_relation.topology_hash,
        policy_hash=deterministic.policy_hash,
        state_domains=min_adapt_relation.state_domains,
        decisions=min_adapt_relation.decisions)
    with pytest.raises(RoutingRelationError,
                       match="REDUNDANT_DETERMINISTIC_POLICY"):
        tampered.validate_against(_mesh4(), deterministic)


# ── immutability ───────────────────────────────────────────────────────────

def test_caller_mutation_cannot_alter_the_relation():
    topology = _phased_topology()
    domains = [RoutingStateDomain("phase", (0, 1))]
    decisions = list(_phased_decisions(topology))
    artifact = build_routing_relation(
        _phased_policy(), topology, decisions, state_domains=domains)
    before = artifact.relation_hash
    decisions.pop()
    decisions.clear()
    domains.append(RoutingStateDomain("mode", (0,)))
    assert artifact.relation_hash == before
    assert len(artifact.decisions) == 24
    assert artifact.state_domains == (RoutingStateDomain("phase", (0, 1)),)


def test_relation_fields_are_immutable(min_adapt_relation):
    with pytest.raises(dataclasses.FrozenInstanceError):
        min_adapt_relation.relation_hash = "0" * 64
    with pytest.raises(TypeError):
        min_adapt_relation.decisions[0] = min_adapt_relation.decisions[1]


def test_to_dict_returns_independent_data(min_adapt_relation):
    first = min_adapt_relation.to_dict()
    first["decisions"].clear()
    first["decisions"].append({"context": {}, "actions": []})
    first["state_domains"].append({"name": "ghost", "values": [1]})
    second = min_adapt_relation.to_dict()
    assert len(second["decisions"]) == 48
    assert second["state_domains"] == []
    assert min_adapt_relation.relation_hash == GOLDEN_MIN_ADAPT


# ── scope sentinels ────────────────────────────────────────────────────────

def test_schema_has_no_forbidden_fields(min_adapt_relation, xy_yx_relation,
                                        phased_relation):
    names = {f.name for f in dataclasses.fields(RoutingRelationArtifact)}
    assert names == EXPECTED_FIELDS
    assert not names & FORBIDDEN_KEYS
    for artifact in (min_adapt_relation, xy_yx_relation, phased_relation):
        d = artifact.to_dict()
        assert set(d) == EXPECTED_FIELDS | {"type"}
        blob = str(d)
        for token in FORBIDDEN_KEYS:
            assert token not in blob
        for token in ("booksim", "astra", "simulator", "binary", "verdict"):
            assert token not in blob.lower()


def test_relation_does_not_import_verifiers_or_backends():
    tree = ast.parse(inspect.getsource(rr))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("booksim", "astra", "backend", "channel_vc_cdg",
                 "protocol_vc", "vc_assignment", "router_behavior",
                 "verification")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_relation_does_not_claim_execution_or_deadlock():
    assert not hasattr(rr, "certify_channel_vc_deadlock")
    assert not hasattr(rr, "certify_protocol_vc_separation")
    assert ROUTING_RELATION_SCHEMA_VERSION == 1
