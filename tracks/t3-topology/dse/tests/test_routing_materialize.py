"""routing_materialize tests — exact deterministic policy realization.

Only policies whose forwarding reduces to ``(current_router, destination)
-> one channel`` materialize into RouteArtifact. Everything adaptive or
stateful is refused, never approximated. ``policy_hash`` and the proof
obligation never enter the realized artifact identity.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifact,
)
from veritx_dse.model import routing_materialize as rm
from veritx_dse.model.routing_materialize import (
    CUSTOM_STATIC, WEIGHTED_SHORTEST_PATH, RoutingMaterializationError,
    materialize_route_artifact,
)
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RoutingStateKind, RoutingStateRequirement,
    RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_family,
)

GOLDEN_DOR_4MESH = (
    "sha256:4453bfaa95859168166c7097decf11757e5d9e81e7f150f964f77fa500c39b37",
    "sha256:c3f2e5fd87e0efeb53f38d0532854c4727422725077ee44cfd59e6f5a637177b")
GOLDEN_DOR_16MESH = (
    "sha256:5a5fa9fe190d51c8107bae557bd07e470db08770e2e5f02786a32fb3fb80cec7",
    "sha256:4f60ec53df7a226e84f58afa7d415a809722b55c71127993c55b44a9f0af6ef2")
GOLDEN_ANYNET_4MESH = (
    "sha256:f83f2b83d3a6e564a6a8d686d521142c877395c2a692f9842f7a7e63c0e00f21",
    "sha256:18cc6856ca5d17e615e53e66a01a19f74106529ec67771591b9182107ef03e34")
GOLDEN_WEIGHTED_HOP_VS_WEIGHT = (
    "sha256:ce9ca955592a6dc7e02812d7f04b0460b348f395e77f9004269ed46434177932",
    "sha256:82304b233c109dd1f0b8bc8b65af352308ab4efee9bb7ff58a07455c700c50a7")
GOLDEN_WEIGHTED_DIAMOND = (
    "sha256:9e9a6924a5a2a805f2216a3e7d012be5bef7524c09ac0193dc078103f8c9dfcf",
    "sha256:3572d226a9760b008e4b6860192b8af6f31ba0048a70bd735d9c4853fc1d1dbe")
GOLDEN_WEIGHTED_PARALLEL = (
    "sha256:6c4ef433d32b9ca720f6e4821f15f71576ed65cf49e43d796f495b8d22797715",
    "sha256:17bcf31111593a99b3241164ea407895c3cf75d4fea6d0df6214126e538281d5")


def _role(rid, kind):
    return RoutingResourceRole(id=rid, kind=kind)


def _policy(**over) -> RoutingPolicyDefinition:
    kw = dict(
        id="policy", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),),
    )
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _dor(**over):
    kw = dict(id="dor_xy", algorithm="dimension_order")
    kw.update(over)
    return _policy(**kw)


def _anynet(**over):
    kw = dict(id="anynet_dijkstra", algorithm="weighted_shortest_path",
              parameters={"weight_metric": "hop_count",
                          "tie_break_policy": "anynet_ascending_min"})
    kw.update(over)
    return _policy(**kw)


def _weighted(**over):
    kw = dict(id="weighted_shortest_path",
              algorithm="weighted_shortest_path",
              parameters={"weight_metric": "route_weight",
                          "tie_break_policy": "lexicographic_channel_ids"})
    kw.update(over)
    return _policy(**kw)


def _custom(**over):
    kw = dict(id="custom_static_table", algorithm="custom_static_table",
              parameters={"table_ref": "custom_table_v1"})
    kw.update(over)
    return _policy(**kw)


def _topo(routers, channels) -> TopologyArtifact:
    return TopologyArtifact(family=MaterializedFamily.MESH, routers=routers,
                            channels=channels)


def _routers(n):
    return tuple(Router(i, (i,), 1) for i in range(n))


def _hop_vs_weight() -> TopologyArtifact:
    """0->3 directly costs 10; 0->1->2->3 costs 3."""
    channels = (
        DirectedChannel(0, 0, 1, 1, 0, 64, 1, route_weight=1),
        DirectedChannel(1, 1, 1, 0, 0, 64, 1, route_weight=1),
        DirectedChannel(2, 1, 1, 2, 0, 64, 1, route_weight=1),
        DirectedChannel(3, 2, 1, 1, 0, 64, 1, route_weight=1),
        DirectedChannel(4, 2, 1, 3, 0, 64, 1, route_weight=1),
        DirectedChannel(5, 3, 1, 2, 0, 64, 1, route_weight=1),
        DirectedChannel(6, 0, 2, 3, 0, 64, 1, route_weight=10),
        DirectedChannel(7, 3, 2, 0, 0, 64, 1, route_weight=10),
    )
    return _topo(_routers(4), channels)


def _diamond() -> TopologyArtifact:
    """Two equal-cost 0->3 paths: (ch1,ch4) and (ch2,ch3)."""
    channels = (
        DirectedChannel(0, 1, 1, 0, 0, 64, 1),
        DirectedChannel(1, 0, 1, 1, 0, 64, 1),
        DirectedChannel(2, 0, 1, 2, 0, 64, 1),
        DirectedChannel(3, 2, 1, 3, 0, 64, 1),
        DirectedChannel(4, 1, 1, 3, 0, 64, 1),
        DirectedChannel(5, 2, 1, 0, 0, 64, 1),
        DirectedChannel(6, 3, 1, 2, 0, 64, 1),
        DirectedChannel(7, 3, 1, 1, 0, 64, 1),
    )
    return _topo(_routers(4), channels)


def _parallel() -> TopologyArtifact:
    """0->1 has ch0(w5), ch1(w1), ch2(w1); 1->0 has ch3(w1), ch4(w2)."""
    channels = (
        DirectedChannel(0, 0, 1, 1, 0, 64, 1, route_weight=5),
        DirectedChannel(1, 0, 2, 1, 0, 64, 1, route_weight=1),
        DirectedChannel(2, 0, 3, 1, 0, 64, 1, route_weight=1),
        DirectedChannel(3, 1, 1, 0, 0, 64, 1, route_weight=1),
        DirectedChannel(4, 1, 2, 0, 0, 64, 1, route_weight=2),
    )
    return _topo((Router(0, (0,), 1), Router(1, (1,), 1)), channels)


def _diamond_anynet_table() -> dict[tuple[int, int], int]:
    artifact = materialize_route_artifact(_anynet(), _diamond(), name="seed")
    return {(src, dst): channel
            for (_cls, src, dst), channel in artifact.entries.items()}


def _walk(artifact, topology, routing_class, src, dst):
    channels = {c.channel_id: c for c in topology.channels}
    hops, cur = [], src
    while cur != dst:
        channel = channels[artifact.entries[(routing_class, cur, dst)]]
        hops.append(channel)
        cur = channel.dst_router
    return hops


# ── DOR_XY and ANYNET compatibility ────────────────────────────────────────

def test_dor_4mesh_matches_sealed_slice6_hashes():
    artifact = materialize_route_artifact(
        _dor(), materialize_family(MaterializedFamily.MESH, endpoint_count=4),
        name="m")
    assert (artifact.route_table_hash, artifact.artifact_hash) \
        == GOLDEN_DOR_4MESH


def test_dor_16mesh_matches_sealed_slice6_hashes():
    artifact = materialize_route_artifact(
        _dor(), materialize_family(MaterializedFamily.MESH, endpoint_count=16),
        name="m")
    assert (artifact.route_table_hash, artifact.artifact_hash) \
        == GOLDEN_DOR_16MESH


def test_dor_matches_direct_route_artifact_construction():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    via_policy = materialize_route_artifact(_dor(), topo, name="m")
    direct = RouteArtifact.from_topology(
        topo, name="m", routing_classes=(DOR_XY,))
    assert via_policy.to_dict() == direct.to_dict()
    assert via_policy.validate_against(topo) is None


def test_anynet_4mesh_matches_sealed_slice6_hashes():
    artifact = materialize_route_artifact(
        _anynet(),
        materialize_family(MaterializedFamily.MESH, endpoint_count=4),
        name="m")
    assert (artifact.route_table_hash, artifact.artifact_hash) \
        == GOLDEN_ANYNET_4MESH


def test_anynet_matches_direct_route_artifact_construction():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    via_policy = materialize_route_artifact(_anynet(), topo, name="m")
    direct = RouteArtifact.from_topology(
        topo, name="m", routing_classes=(ANYNET_MIN_HOPS,))
    assert via_policy.to_dict() == direct.to_dict()


def test_dor_torus_is_still_refused():
    torus = materialize_family(MaterializedFamily.TORUS, endpoint_count=16)
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_dor(), torus, name="m")


def test_dor_implicit_and_explicit_parameters_agree():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    implicit = materialize_route_artifact(_dor(), topo, name="m")
    explicit = materialize_route_artifact(
        _dor(parameters={"dimension_order": ["x", "y"], "wraparound": False}),
        topo, name="m")
    assert implicit.artifact_hash == explicit.artifact_hash


@pytest.mark.parametrize("parameters", [
    {"dimension_order": ["y", "x"], "wraparound": False},
    {"dimension_order": ["x", "y"], "wraparound": True},
    {"dimension_order": ["x", "y"], "wraparound": False, "extra": 1},
    {"weight_metric": "hop_count"},
])
def test_dor_incompatible_parameters_are_refused(parameters):
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_dor(parameters=parameters), topo, name="m")


@pytest.mark.parametrize("parameters", [
    {"weight_metric": "hop_count"},
    {"weight_metric": "hop_count", "tie_break_policy": "first"},
    {"weight_metric": "hop_count", "tie_break_policy": "anynet_ascending_min",
     "extra": 1},
])
def test_anynet_unsupported_parameters_are_refused(parameters):
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_anynet(parameters=parameters), topo, name="m")


def test_policy_id_does_not_choose_behavior():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    original = materialize_route_artifact(_dor(), topo, name="m")
    renamed = materialize_route_artifact(
        _dor(id="something_else_entirely"), topo, name="m")
    assert renamed.artifact_hash == original.artifact_hash


def test_proof_obligation_does_not_move_the_realized_table():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    baseline = materialize_route_artifact(_dor(), topo, name="m")
    other = materialize_route_artifact(
        _dor(deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC),
        topo, name="m")
    assert other.to_dict() == baseline.to_dict()


def test_policy_hash_never_enters_route_artifact_identity():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    artifact = materialize_route_artifact(_dor(), topo, name="m")
    assert "policy_hash" not in artifact.to_dict()
    assert "policy_hash" not in {f.name for f in dataclasses.fields(RouteArtifact)}


# ── weighted shortest path ─────────────────────────────────────────────────

def test_weighted_prefers_lower_route_weight_over_fewer_hops():
    topo = _hop_vs_weight()
    weighted = materialize_route_artifact(_weighted(), topo, name="w")
    hop_count = materialize_route_artifact(_anynet(), topo, name="a")
    assert weighted.entries[(WEIGHTED_SHORTEST_PATH, 0, 3)] == 0
    assert hop_count.entries[(ANYNET_MIN_HOPS, 0, 3)] == 6  # the 1-hop path
    hops = _walk(weighted, topo, WEIGHTED_SHORTEST_PATH, 0, 3)
    assert [c.channel_id for c in hops] == [0, 2, 4]
    assert sum(c.route_weight for c in hops) == 3


def test_weighted_equal_cost_tie_breaks_lexicographically():
    topo = _diamond()
    artifact = materialize_route_artifact(_weighted(), topo, name="w")
    # (ch1,ch4) vs (ch2,ch3): equal cost, lexicographically smaller wins.
    assert artifact.entries[(WEIGHTED_SHORTEST_PATH, 0, 3)] == 1


def test_weighted_parallel_links_pick_lower_weight():
    artifact = materialize_route_artifact(_weighted(), _parallel(), name="w")
    assert artifact.entries[(WEIGHTED_SHORTEST_PATH, 0, 1)] == 1
    assert artifact.entries[(WEIGHTED_SHORTEST_PATH, 1, 0)] == 3


def test_weighted_equal_weight_parallel_links_use_sequence_tie_break():
    artifact = materialize_route_artifact(_weighted(), _parallel(), name="w")
    # ch1 and ch2 both cost 1; (1,) < (2,) so ch1 wins.
    assert artifact.entries[(WEIGHTED_SHORTEST_PATH, 0, 1)] == 1


def test_weighted_golden_hashes():
    for topo, golden in ((_hop_vs_weight(), GOLDEN_WEIGHTED_HOP_VS_WEIGHT),
                         (_diamond(), GOLDEN_WEIGHTED_DIAMOND),
                         (_parallel(), GOLDEN_WEIGHTED_PARALLEL)):
        artifact = materialize_route_artifact(_weighted(), topo, name="w")
        assert (artifact.route_table_hash, artifact.artifact_hash) == golden
        assert artifact.validate_against(topo) is None


def test_weighted_class_definition_records_execution_semantics():
    artifact = materialize_route_artifact(_weighted(), _diamond(), name="w")
    definition = artifact.routing_classes[0]
    assert definition.id == WEIGHTED_SHORTEST_PATH
    assert definition.algorithm == "weighted_shortest_path"
    assert definition.algorithm_version == 1
    parameters = definition.parameters_dict()
    assert parameters["edge_cost_field"] == "route_weight"
    assert parameters["objective"] == "minimum_total_route_weight"
    assert parameters["tie_break"] == "lexicographic_channel_id_sequence"
    text = str(artifact.to_dict())
    assert "policy_hash" not in text
    assert "booksim" not in text.lower()


def test_weighted_requires_minimal_path_mode():
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(
            _weighted(path_mode=PathMode.NONMINIMAL), _diamond(), name="w")


@pytest.mark.parametrize("parameters", [
    {"weight_metric": "route_weight", "tie_break_policy": "first"},
    {"weight_metric": "route_weight"},
    {"weight_metric": "route_weight", "tie_break_policy":
     "lexicographic_channel_ids", "extra": 1},
])
def test_weighted_parameters_are_strict(parameters):
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_weighted(parameters=parameters),
                                   _diamond(), name="w")


def test_weighted_unreachable_pairs_fail_closed():
    topo = _topo((Router(0, (0,), 1), Router(1, (1,), 1)),
                 (DirectedChannel(0, 0, 1, 1, 0, 64, 1),))
    with pytest.raises(RoutingMaterializationError, match="no directed path"):
        materialize_route_artifact(_weighted(), topo, name="w")


# ── custom static tables ───────────────────────────────────────────────────

def test_custom_complete_table_is_accepted():
    topo = _diamond()
    table = _diamond_anynet_table()
    artifact = materialize_route_artifact(
        _custom(), topo, name="c", custom_entries=table)
    assert artifact.entries[(CUSTOM_STATIC, 0, 3)] == table[(0, 3)]
    assert len(artifact.entries) == len(table)
    definition = artifact.routing_classes[0]
    assert definition.id == CUSTOM_STATIC
    assert definition.parameters_dict() == {"table_ref": "custom_table_v1"}
    assert artifact.validate_against(topo) is None


def test_custom_missing_pair_is_refused():
    table = _diamond_anynet_table()
    table.pop((0, 3))
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_custom(), _diamond(), name="c",
                                   custom_entries=table)


def test_custom_extra_pair_is_refused():
    table = _diamond_anynet_table()
    table[(0, 99)] = next(iter(table.values()))
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_custom(), _diamond(), name="c",
                                   custom_entries=table)


def test_custom_nonexistent_channel_is_refused():
    table = _diamond_anynet_table()
    table[(0, 3)] = 999
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_custom(), _diamond(), name="c",
                                   custom_entries=table)


def test_custom_channel_leaving_wrong_source_is_refused():
    table = _diamond_anynet_table()
    table[(0, 3)] = 4  # channel 4 is 1->3
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_custom(), _diamond(), name="c",
                                   custom_entries=table)


def test_custom_forwarding_loop_is_refused():
    table = _diamond_anynet_table()
    table[(0, 3)] = 1  # 0->1
    table[(1, 3)] = 0  # 1->0: locally legal, still loops
    with pytest.raises(RoutingMaterializationError, match="loop"):
        materialize_route_artifact(_custom(), _diamond(), name="c",
                                   custom_entries=table)


def test_custom_requires_entries():
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_custom(), _diamond(), name="c")


@pytest.mark.parametrize("bad_entries", [
    [(0, 3, 1)],
    "not-a-mapping",
    {"0,3": 1},
    {(0,): 1},
    {(0, 3, 4): 1},
    {(0, "3"): 1},
    {(True, 3): 1},
    {(0, 3): "1"},
    {(0, 3): True},
])
def test_custom_entry_shapes_are_strict(bad_entries):
    with pytest.raises(RoutingMaterializationError):
        materialize_route_artifact(_custom(), _diamond(), name="c",
                                   custom_entries=bad_entries)


def test_custom_entries_are_only_valid_for_custom_static():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    for policy in (_dor(), _anynet(), _weighted()):
        with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
            materialize_route_artifact(policy, topo, name="m",
                                       custom_entries={(0, 1): 0})


def test_custom_caller_mutation_does_not_change_the_artifact():
    table = _diamond_anynet_table()
    artifact = materialize_route_artifact(
        _custom(), _diamond(), name="c", custom_entries=table)
    before = artifact.entries[(CUSTOM_STATIC, 0, 3)]
    table[(0, 3)] = 7
    table[(2, 0)] = 7
    assert artifact.entries[(CUSTOM_STATIC, 0, 3)] == before
    with pytest.raises(TypeError):
        artifact.entries[(CUSTOM_STATIC, 0, 3)] = 0


def test_custom_one_legal_route_change_changes_identity():
    topo = _diamond()
    table = _diamond_anynet_table()
    baseline = materialize_route_artifact(
        _custom(), topo, name="c", custom_entries=table)
    table[(0, 3)] = 2  # the other legal first hop; route still terminates
    changed = materialize_route_artifact(
        _custom(), topo, name="c", custom_entries=table)
    assert changed.route_table_hash != baseline.route_table_hash
    assert changed.artifact_hash != baseline.artifact_hash


@pytest.mark.parametrize("parameters", [
    {},
    {"table_ref": ""},
    {"table_ref": "custom_table_v1", "extra": 1},
    {"other_ref": "custom_table_v1"},
])
def test_custom_parameters_are_strict(parameters):
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_custom(parameters=parameters), _diamond(),
                                   name="c",
                                   custom_entries=_diamond_anynet_table())


# ── adaptive/stateful refusals (Slice-10 reference profiles) ───────────────

def _adaptive_xy_yx():
    return _policy(
        id="adaptive_xy_yx", algorithm="source_commit_xy_yx",
        decision_scope=DecisionScope.SOURCE_COMMIT, randomness=RandomnessMode.RNG,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(_role("xy", RoutingResourceRoleKind.ROUTE_ORDER),
                        _role("yx", RoutingResourceRoleKind.ROUTE_ORDER)),
        allowed_role_transitions=(("xy", "xy"), ("yx", "yx")))


def _min_adapt():
    return _policy(
        id="min_adapt_mesh", algorithm="per_hop_min_adaptive",
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")))


def _valiant():
    return _policy(
        id="valiant", algorithm="phased_valiant", path_mode=PathMode.NONMINIMAL,
        decision_scope=DecisionScope.PER_HOP, randomness=RandomnessMode.RNG,
        state_requirements=(
            RoutingStateRequirement("intermediate",
                                    RoutingStateKind.INTERMEDIATE_NODE),
            RoutingStateRequirement("phase", RoutingStateKind.PHASE)),
        resource_roles=(_role("phase0", RoutingResourceRoleKind.PHASE),
                        _role("phase1", RoutingResourceRoleKind.PHASE)),
        allowed_role_transitions=(("phase0", "phase1"),))


def _ugal():
    return _policy(
        id="ugal", algorithm="congestion_aware_ugal", path_mode=PathMode.MIXED,
        decision_scope=DecisionScope.SOURCE_COMMIT, randomness=RandomnessMode.RNG,
        deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        state_requirements=(
            RoutingStateRequirement("intermediate",
                                    RoutingStateKind.INTERMEDIATE_NODE),
            RoutingStateRequirement("phase", RoutingStateKind.PHASE)),
        resource_roles=(_role("minimal", RoutingResourceRoleKind.ADAPTIVE),
                        _role("nonminimal", RoutingResourceRoleKind.CUSTOM)),
        allowed_role_transitions=(("minimal", "minimal"),
                                  ("nonminimal", "nonminimal")))


def _fault_planar():
    return _policy(
        id="fault_planar_adaptive", algorithm="fault_aware_planar",
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC,
        runtime_observations=(RuntimeObservation.FAULT_STATE,),
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")))


@pytest.mark.parametrize("profile", [
    _adaptive_xy_yx, _min_adapt, _valiant, _ugal, _fault_planar])
def test_adaptive_and_stateful_profiles_are_refused(profile):
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(profile(), topo, name="m")


@pytest.mark.parametrize("over", [
    dict(candidate_mode=CandidateMode.CANDIDATE_SET),
    dict(selection_locus=SelectionLocus.ROUTER_ALLOCATOR),
    dict(decision_scope=DecisionScope.SOURCE_COMMIT),
    dict(decision_scope=DecisionScope.PER_HOP),
    dict(decision_scope=DecisionScope.SOURCE_COMMIT,
         randomness=RandomnessMode.RNG),
    dict(decision_scope=DecisionScope.PER_HOP,
         state_requirements=(RoutingStateRequirement("phase",
                                                     RoutingStateKind.PHASE),)),
    dict(decision_scope=DecisionScope.SOURCE_COMMIT,
         runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,)),
    dict(resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),
                         _role("escape", RoutingResourceRoleKind.ESCAPE)),
         allowed_role_transitions=(("default", "default"),
                                   ("escape", "escape"))),
    dict(resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),),
         allowed_role_transitions=(("adaptive", "adaptive"),)),
    dict(path_mode=PathMode.NONMINIMAL),
    dict(path_mode=PathMode.MIXED),
    dict(algorithm="mystery_algorithm"),
    dict(algorithm_version=2),
])
def test_representability_gate_refusals(over):
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    with pytest.raises(RoutingMaterializationError, match="UNREPRESENTABLE"):
        materialize_route_artifact(_policy(**over), topo, name="m")


def test_bad_parent_types_are_refused():
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    with pytest.raises(RoutingMaterializationError, match="TopologyArtifact"):
        materialize_route_artifact(_dor(), object(), name="m")
    with pytest.raises(RoutingMaterializationError, match="RoutingPolicyDefinition"):
        materialize_route_artifact(object(), topo, name="m")
    with pytest.raises(RoutingMaterializationError, match="name"):
        materialize_route_artifact(_dor(), topo, name="")


# ── scope sentinels ────────────────────────────────────────────────────────

def test_materializer_does_not_import_verification_backend_or_astra():
    tree = ast.parse(inspect.getsource(rm))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("channel_vc_cdg", "protocol_vc", "booksim", "astra",
                 "backend", "verification")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_materializer_never_claims_deadlock_freedom():
    assert not hasattr(rm, "certify_channel_vc_deadlock")
    assert not hasattr(rm, "certify_protocol_vc_separation")
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    artifact = materialize_route_artifact(_dor(), topo, name="m")
    assert "verdict" not in artifact.to_dict()
