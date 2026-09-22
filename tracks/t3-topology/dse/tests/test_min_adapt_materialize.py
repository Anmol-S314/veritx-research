"""MinAdapt source-semantics materialization tests.

The materializer expands the Slice-10 MIN_ADAPT_MESH policy into a total
legal-action relation; a test-only oracle independently derives the same
source-level rules. No backend, no concrete VC numbers, no deadlock proof.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.model import routing_relation_materialize as rrm
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RoutingStateKind, RoutingStateRequirement,
    RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_relation import (
    RoutingAction, RoutingActionKind, RoutingRelationError,
)
from veritx_dse.model.routing_relation_materialize import (
    ADAPTIVE_PRIORITY, ADAPTIVE_ROLE, ESCAPE_PRIORITY, ESCAPE_ROLE,
    RoutingRelationMaterializationError, materialize_routing_relation,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_family,
)

GOLDEN_2X2 = (
    "46abf0d59fcb9f3faf656183736052ef3993ca1e545fb91e7e70b3627f38b528")
GOLDEN_3X3 = (
    "dcc037e906ad45bdcfd2f6be7fc8d75443a8044cd6373f6f3a626b448e1d0726")
GOLDEN_CONCENTRATED = (
    "7ff9344a014d04c49ecb45a7683234bc4dc8d55232a4832597cd3dd6c3e6bd07")


def _role(rid, kind):
    return RoutingResourceRole(id=rid, kind=kind)


def _min_adapt_policy(**over) -> RoutingPolicyDefinition:
    """The exact Slice-12 manual-fixture / Slice-10 reference profile."""
    kw = dict(
        id="min_adapt_like", algorithm="per_hop_min_adaptive",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(_role(ADAPTIVE_ROLE, RoutingResourceRoleKind.ADAPTIVE),
                        _role(ESCAPE_ROLE, RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=((ADAPTIVE_ROLE, ADAPTIVE_ROLE),
                                  (ADAPTIVE_ROLE, ESCAPE_ROLE),
                                  (ESCAPE_ROLE, ESCAPE_ROLE)),
    )
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _mesh(n: int) -> TopologyArtifact:
    return materialize_family(MaterializedFamily.MESH, endpoint_count=n)


def _mesh2() -> TopologyArtifact:
    return _mesh(4)


def _mesh3() -> TopologyArtifact:
    return _mesh(9)


def _concentrated() -> TopologyArtifact:
    return materialize_family(MaterializedFamily.CONCENTRATED_MESH,
                              endpoint_count=4)


def _rebuild(topo: TopologyArtifact, *,
             routers=None, extra=(), drop_pairs=()) -> TopologyArtifact:
    """Rebuild a topology with sequentially valid source ports."""
    routers = tuple(routers if routers is not None else topo.routers)
    channels = [c for c in topo.channels
                if (c.src_router, c.dst_router) not in drop_pairs]
    channels += list(extra)
    next_port = {r.router_id: r.seat_capacity for r in routers}
    built = []
    for channel in channels:
        src_port = next_port.get(channel.src_router, 0)
        next_port[channel.src_router] = src_port + 1
        built.append(DirectedChannel(
            channel_id=len(built), src_router=channel.src_router,
            src_port=src_port, dst_router=channel.dst_router, dst_port=0,
            width_bits=channel.width_bits,
            latency_cycles=channel.latency_cycles,
            route_weight=channel.route_weight))
    return TopologyArtifact(family=topo.family, routers=routers,
                            channels=tuple(built))


def _decision_map(artifact):
    return {(d.context.router_id, d.context.destination_router_id,
             d.context.current_role_id): tuple(d.actions)
            for d in artifact.decisions}


def _action_sort_key(action):
    return (0 if action.kind == RoutingActionKind.FORWARD else 1,
            action.channel_id if action.channel_id is not None else -1,
            action.next_role_id or "", action.priority)


def _oracle_actions(topo, router_id, destination, role):
    """Independent test-only source-level min_adapt_mesh oracle."""
    coords = {r.router_id: r.coordinates for r in topo.routers}
    id_of = {c: i for i, c in coords.items()}
    by_pair = {(c.src_router, c.dst_router): c.channel_id
               for c in topo.channels}
    (x, y), (dx, dy) = coords[router_id], coords[destination]

    if router_id == destination:
        return (RoutingAction(kind=RoutingActionKind.EJECT, channel_id=None,
                              next_role_id=None,
                              priority=ESCAPE_PRIORITY),)

    def step(axis):
        if axis == "x":
            return (x + (1 if dx > x else -1), y)
        return (x, y + (1 if dy > y else -1))

    if x != dx:
        escape_channel = by_pair[(router_id, id_of[step("x")])]
    else:
        escape_channel = by_pair[(router_id, id_of[step("y")])]
    if role == ESCAPE_ROLE:
        return (RoutingAction(kind=RoutingActionKind.FORWARD,
                              channel_id=escape_channel,
                              next_role_id=ESCAPE_ROLE,
                              priority=ESCAPE_PRIORITY),)
    actions = [RoutingAction(kind=RoutingActionKind.FORWARD,
                             channel_id=escape_channel,
                             next_role_id=ESCAPE_ROLE,
                             priority=ESCAPE_PRIORITY)]
    for axis in ("x", "y"):
        differs = x != dx if axis == "x" else y != dy
        if differs:
            actions.append(RoutingAction(
                kind=RoutingActionKind.FORWARD,
                channel_id=by_pair[(router_id, id_of[step(axis)])],
                next_role_id=ADAPTIVE_ROLE,
                priority=ADAPTIVE_PRIORITY))
    return tuple(sorted(actions, key=_action_sort_key))


def _oracle_map(topo, policy):
    return {(r.router_id, d.router_id, role): _oracle_actions(
        topo, r.router_id, d.router_id, role)
        for r in topo.routers for d in topo.routers
        for role in (None, ADAPTIVE_ROLE, ESCAPE_ROLE)}


# ── reference compatibility ───────────────────────────────────────────────

def test_slice12_manual_fixture_hash_is_reproduced():
    artifact = materialize_routing_relation(_mesh2(), _min_adapt_policy())
    assert artifact.relation_hash == GOLDEN_2X2


def test_slice10_reference_policy_also_materializes():
    artifact = materialize_routing_relation(
        _mesh2(), _min_adapt_policy(id="min_adapt_mesh"))
    assert artifact.validate_against(_mesh2(),
                                     _min_adapt_policy(id="min_adapt_mesh")) \
        is None
    assert artifact.relation_hash != GOLDEN_2X2  # policy id is bound


def test_3x3_relation_hash_is_pinned():
    artifact = materialize_routing_relation(_mesh3(), _min_adapt_policy())
    assert artifact.relation_hash == GOLDEN_3X3
    assert len(artifact.decisions) == 243


def test_concentrated_mesh_hash_is_pinned():
    artifact = materialize_routing_relation(_concentrated(),
                                            _min_adapt_policy())
    assert artifact.relation_hash == GOLDEN_CONCENTRATED


def test_concentrated_mesh_decisions_match_mesh_at_router_level():
    mesh = materialize_routing_relation(_mesh2(), _min_adapt_policy())
    concentrated = materialize_routing_relation(_concentrated(),
                                                _min_adapt_policy())
    assert concentrated.decisions == mesh.decisions
    assert concentrated.topology_hash != mesh.topology_hash
    assert concentrated.relation_hash != mesh.relation_hash


def test_materialized_relation_round_trips():
    from veritx_dse.model.routing_relation import RoutingRelationArtifact
    artifact = materialize_routing_relation(_mesh2(), _min_adapt_policy())
    restored = RoutingRelationArtifact.from_dict(artifact.to_dict())
    assert restored.relation_hash == artifact.relation_hash
    assert restored.to_dict() == artifact.to_dict()


# ── independent source-level oracle ───────────────────────────────────────

def test_oracle_matches_2x2():
    topology = _mesh2()
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    assert _decision_map(artifact) == _oracle_map(topology, _min_adapt_policy())


def test_oracle_matches_3x3():
    topology = _mesh3()
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    assert _decision_map(artifact) == _oracle_map(topology, _min_adapt_policy())


# ── action semantics ──────────────────────────────────────────────────────

def _manhattan(topo, a, b):
    ca = {r.router_id: r.coordinates for r in topo.routers}
    return sum(abs(x - y) for x, y in zip(ca[a], ca[b]))


@pytest.mark.parametrize("topology", [_mesh2(), _mesh3()])
def test_adaptive_actions_reduce_manhattan_distance_exactly_one(topology):
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    channel_by_id = {c.channel_id: c for c in topology.channels}
    for decision in artifact.decisions:
        if decision.context.router_id == decision.context.destination_router_id:
            continue
        for action in decision.actions:
            if action.kind != RoutingActionKind.FORWARD:
                continue
            assert action.channel_id in channel_by_id
            channel = channel_by_id[action.channel_id]
            assert channel.src_router == decision.context.router_id
            assert _manhattan(topology, channel.dst_router,
                              decision.context.destination_router_id) \
                == _manhattan(topology, decision.context.router_id,
                              decision.context.destination_router_id) - 1


@pytest.mark.parametrize("topology", [_mesh2(), _mesh3()])
def test_adaptive_actions_are_exactly_the_minimal_dimensions(topology):
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    coords = {r.router_id: r.coordinates for r in topology.routers}
    for decision in artifact.decisions:
        if decision.context.router_id == decision.context.destination_router_id:
            continue
        adaptive = [a for a in decision.actions
                    if a.next_role_id == ADAPTIVE_ROLE]
        if decision.context.current_role_id == ESCAPE_ROLE:
            assert adaptive == []
            continue
        (x, y) = coords[decision.context.router_id]
        (dx, dy) = coords[decision.context.destination_router_id]
        differing = (1 if x != dx else 0) + (1 if y != dy else 0)
        assert len(adaptive) == differing
        assert all(a.priority == ADAPTIVE_PRIORITY for a in adaptive)


def test_single_dimensional_case_keeps_two_distinct_actions():
    artifact = materialize_routing_relation(_mesh2(), _min_adapt_policy())
    actions = _decision_map(artifact)[(0, 1, ADAPTIVE_ROLE)]
    assert actions == (
        RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=0,
                      next_role_id=ADAPTIVE_ROLE,
                      priority=ADAPTIVE_PRIORITY),
        RoutingAction(kind=RoutingActionKind.FORWARD, channel_id=0,
                      next_role_id=ESCAPE_ROLE, priority=ESCAPE_PRIORITY),
    )
    assert len(actions) == 2
    assert actions[0].channel_id == actions[1].channel_id


def test_both_dimensions_give_three_actions():
    artifact = materialize_routing_relation(_mesh2(), _min_adapt_policy())
    actions = _decision_map(artifact)[(0, 3, None)]
    assert len(actions) == 3
    assert {a.next_role_id for a in actions} == {ADAPTIVE_ROLE, ESCAPE_ROLE}
    assert [(a.channel_id, a.next_role_id, a.priority)
            for a in actions] == [
        (0, ADAPTIVE_ROLE, ADAPTIVE_PRIORITY),
        (0, ESCAPE_ROLE, ESCAPE_PRIORITY),
        (1, ADAPTIVE_ROLE, ADAPTIVE_PRIORITY)]


@pytest.mark.parametrize("topology", [_mesh2(), _mesh3()])
def test_injection_matches_adaptive_role_envelope(topology):
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    decisions = _decision_map(artifact)
    for key, actions in decisions.items():
        router_id, destination, role = key
        if role is None and router_id != destination:
            assert actions == decisions[(router_id, destination, ADAPTIVE_ROLE)]


@pytest.mark.parametrize("topology", [_mesh2(), _mesh3()])
def test_escape_role_is_sticky_and_escape_only(topology):
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    for decision in artifact.decisions:
        if decision.context.current_role_id != ESCAPE_ROLE:
            continue
        if decision.context.router_id == decision.context.destination_router_id:
            continue
        assert len(decision.actions) == 1
        action = decision.actions[0]
        assert action.next_role_id == ESCAPE_ROLE
        assert action.priority == ESCAPE_PRIORITY
        assert action.channel_id is not None


@pytest.mark.parametrize("topology", [_mesh2(), _mesh3()])
def test_destination_contexts_are_eject_only(topology):
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    for decision in artifact.decisions:
        if decision.context.router_id != decision.context.destination_router_id:
            continue
        assert len(decision.actions) == 1
        action = decision.actions[0]
        assert action.kind == RoutingActionKind.EJECT
        assert action.channel_id is None
        assert action.next_role_id is None
        assert action.priority == ESCAPE_PRIORITY


@pytest.mark.parametrize("topology", [_mesh2(), _mesh3()])
def test_non_destination_contexts_never_eject(topology):
    artifact = materialize_routing_relation(topology, _min_adapt_policy())
    for decision in artifact.decisions:
        if decision.context.router_id == decision.context.destination_router_id:
            continue
        assert all(a.kind == RoutingActionKind.FORWARD
                   for a in decision.actions)


# ── policy refusals ───────────────────────────────────────────────────────

@pytest.mark.parametrize("over", [
    dict(algorithm="dimension_order"),
    dict(algorithm="weighted_shortest_path"),
    dict(algorithm_version=2),
    dict(parameters={"escape_bias": 1}),
    dict(path_mode=PathMode.NONMINIMAL),
    dict(path_mode=PathMode.MIXED),
    dict(decision_scope=DecisionScope.STATIC, runtime_observations=()),
    dict(decision_scope=DecisionScope.SOURCE_COMMIT),
    dict(candidate_mode=CandidateMode.SINGLETON),
    dict(selection_locus=SelectionLocus.ROUTE_COMPUTE),
    dict(randomness=RandomnessMode.RNG),
    dict(state_requirements=(RoutingStateRequirement(
        "phase", RoutingStateKind.PHASE),)),
    dict(runtime_observations=(RuntimeObservation.FAULT_STATE,)),
    dict(deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC),
])
def test_non_min_adapt_policies_are_refused(over):
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(_mesh2(), _min_adapt_policy(**over))


@pytest.mark.parametrize("roles,transitions", [
    ((_role(ADAPTIVE_ROLE, RoutingResourceRoleKind.ADAPTIVE),),
     ((ADAPTIVE_ROLE, ADAPTIVE_ROLE),)),
    ((_role(ADAPTIVE_ROLE, RoutingResourceRoleKind.ADAPTIVE),
      _role(ESCAPE_ROLE, RoutingResourceRoleKind.CUSTOM)),
     ((ADAPTIVE_ROLE, ADAPTIVE_ROLE), (ADAPTIVE_ROLE, ESCAPE_ROLE),
      (ESCAPE_ROLE, ESCAPE_ROLE))),
    ((_role(ADAPTIVE_ROLE, RoutingResourceRoleKind.ADAPTIVE),
      _role(ESCAPE_ROLE, RoutingResourceRoleKind.ESCAPE),
      _role("extra", RoutingResourceRoleKind.CUSTOM)),
     ((ADAPTIVE_ROLE, ADAPTIVE_ROLE), (ADAPTIVE_ROLE, ESCAPE_ROLE),
      (ESCAPE_ROLE, ESCAPE_ROLE), ("extra", "extra"))),
])
def test_wrong_resource_roles_are_refused(roles, transitions):
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(
            _mesh2(), _min_adapt_policy(resource_roles=roles,
                                        allowed_role_transitions=transitions))


@pytest.mark.parametrize("transitions", [
    ((ADAPTIVE_ROLE, ADAPTIVE_ROLE), (ADAPTIVE_ROLE, ESCAPE_ROLE)),
    ((ADAPTIVE_ROLE, ADAPTIVE_ROLE), (ESCAPE_ROLE, ESCAPE_ROLE)),
    ((ADAPTIVE_ROLE, ADAPTIVE_ROLE), (ADAPTIVE_ROLE, ESCAPE_ROLE),
     (ESCAPE_ROLE, ESCAPE_ROLE), (ESCAPE_ROLE, ADAPTIVE_ROLE)),
])
def test_wrong_role_transitions_are_refused(transitions):
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(
            _mesh2(), _min_adapt_policy(
                allowed_role_transitions=transitions))


def test_deterministic_policy_is_refused_here():
    deterministic = RoutingPolicyDefinition(
        id="dor_xy", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),))
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(_mesh2(), deterministic)


# ── topology refusals ─────────────────────────────────────────────────────

def test_non_mesh_families_are_refused():
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(
            materialize_family(MaterializedFamily.TORUS, endpoint_count=4),
            _min_adapt_policy())
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(
            materialize_family(MaterializedFamily.RING, endpoint_count=4),
            _min_adapt_policy())


def test_malformed_mesh_coordinates_are_refused():
    routers = tuple(
        dataclasses.replace(r, coordinates=(2, 1)) if r.router_id == 3 else r
        for r in _mesh2().routers)
    topology = _rebuild(_mesh2(), routers=routers)
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(topology, _min_adapt_policy())


def test_missing_mesh_link_is_refused():
    topology = _rebuild(_mesh2(), drop_pairs={(0, 1)})
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(topology, _min_adapt_policy())


def test_diagonal_link_is_refused():
    base = _mesh2()
    extra = DirectedChannel(channel_id=99, src_router=0, src_port=0,
                            dst_router=3, dst_port=0, width_bits=64,
                            latency_cycles=1)
    topology = _rebuild(base, extra=(extra,))
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(topology, _min_adapt_policy())


def test_wrap_link_is_refused():
    base = _mesh3()
    extra = DirectedChannel(channel_id=99, src_router=0, src_port=0,
                            dst_router=2, dst_port=0, width_bits=64,
                            latency_cycles=1)
    topology = _rebuild(base, extra=(extra,))
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(topology, _min_adapt_policy())


def test_parallel_directed_links_are_refused():
    base = _mesh2()
    extra = DirectedChannel(channel_id=99, src_router=0, src_port=0,
                            dst_router=1, dst_port=0, width_bits=64,
                            latency_cycles=1)
    topology = _rebuild(base, extra=(extra,))
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(topology, _min_adapt_policy())


def test_extra_non_mesh_link_is_refused():
    base = _mesh3()
    extra = DirectedChannel(channel_id=99, src_router=0, src_port=0,
                            dst_router=4, dst_port=0, width_bits=64,
                            latency_cycles=1)
    topology = _rebuild(base, extra=(extra,))
    with pytest.raises(RoutingRelationMaterializationError,
                       match="UNSUPPORTED"):
        materialize_routing_relation(topology, _min_adapt_policy())


def test_non_artifact_arguments_are_refused():
    with pytest.raises(RoutingRelationMaterializationError,
                       match="RoutingPolicyDefinition"):
        materialize_routing_relation(_mesh2(), object())
    with pytest.raises(RoutingRelationMaterializationError,
                       match="TopologyArtifact"):
        materialize_routing_relation(object(), _min_adapt_policy())


# ── validation / scope sentinels ──────────────────────────────────────────

def test_materialized_relation_validates_against_parents():
    topology = _mesh2()
    policy = _min_adapt_policy()
    artifact = materialize_routing_relation(topology, policy)
    assert artifact.validate_against(topology, policy) is None
    with pytest.raises(RoutingRelationError):
        artifact.validate_against(_mesh3(), policy)


def test_relation_contains_no_concrete_vc_bindings():
    artifact = materialize_routing_relation(_mesh2(), _min_adapt_policy())
    blob = str(artifact.to_dict())
    for token in ("vc_id", "vc_ids", "vc_count", "vcbegin", "vcend",
                  "vc_begin", "vc_end", "vc0", "vc1"):
        assert token not in blob.lower()


def test_materializer_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(rrm))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("booksim", "astra", "backend", "vc_assignment",
                 "channel_vc_cdg", "protocol_vc", "allocator")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_materializer_does_not_claim_backend_or_deadlock():
    assert not hasattr(rrm, "certify_channel_vc_deadlock")
    assert not hasattr(rrm, "certify_protocol_vc_separation")
    assert not hasattr(rrm, "bind_routing_roles")
