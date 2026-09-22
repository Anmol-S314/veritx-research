"""RoutingPolicyDefinition tests — backend-independent routing semantics.

The definition says what a routing algorithm requires and permits. It is
not executable, not a deadlock proof, and not a backend configuration
record; the reference profiles below are test fixtures proving the
vocabulary is expressive, not a production algorithm registry.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingPolicyError,
    RoutingResourceRole, RoutingResourceRoleKind, RoutingStateKind,
    RoutingStateRequirement, RuntimeObservation, SelectionLocus,
)

GOLDEN_POLICY_HASHES = {
    "dor_xy": "c451979bf68ac87535cf117adc1b9ff98cb45ea6a50ff42d22f7e312f68a2426",
    "anynet_dijkstra":
        "7aa7709531f0bf15d815c9d3029cc608c24c43353faf08a507ada8f33e1b70b3",
    "adaptive_xy_yx":
        "2014babee0ef037448b877d224773b6c91570cce777396e25976c2085046109b",
    "min_adapt_mesh":
        "3712baf61bd643d379f0d11717629c47c2df8958281640c00affc51ec5853946",
    "valiant": "22e8502eb3ccd4f2700c9b088db79fd1ac0bdf386991daf590d2d5c4b198ff85",
    "ugal": "8002859acdc2c3328899029cd9fe951818615a132f8da2283540e00a7b9cd803",
    "fault_planar":
        "0e8797c80c85e1203c827f18900fc93d34e24962ee6d5e8dfa8677ddc0bafb79",
    "custom_static":
        "1998a5f5a58b928a23492b49dc21aebc076614b745a34342caa55b86e1f800f4",
}

EXPECTED_FIELDS = {
    "id", "algorithm", "algorithm_version", "path_mode", "decision_scope",
    "candidate_mode", "selection_locus", "randomness",
    "deadlock_proof_obligation", "state_requirements",
    "runtime_observations", "resource_roles", "allowed_role_transitions",
    "parameters", "schema_version", "policy_hash",
}

FORBIDDEN_KEYS = {
    "topology_hash", "topology", "channel_id", "channel_ids", "endpoint_id",
    "endpoint_ids", "vc_id", "vc_ids", "vc_count", "seed", "rng_seed",
    "simulator", "simulator_path", "binary", "binary_path", "booksim",
    "booksim_routing_function", "congestion", "congestion_values", "verdict",
    "proof", "certificate", "attachment_hash", "router_route_hash",
    "resolved_route_hash",
}


def _role(rid, kind):
    return RoutingResourceRole(id=rid, kind=kind)


def _profiles() -> dict[str, RoutingPolicyDefinition]:
    return {
        "dor_xy": RoutingPolicyDefinition(
            id="dor_xy", algorithm="dimension_order", algorithm_version=1,
            path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
            candidate_mode=CandidateMode.SINGLETON,
            selection_locus=SelectionLocus.ROUTE_COMPUTE,
            randomness=RandomnessMode.NONE,
            deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
            resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
            allowed_role_transitions=(("default", "default"),)),
        "anynet_dijkstra": RoutingPolicyDefinition(
            id="anynet_dijkstra", algorithm="weighted_shortest_path",
            algorithm_version=1, path_mode=PathMode.MINIMAL,
            decision_scope=DecisionScope.STATIC,
            candidate_mode=CandidateMode.SINGLETON,
            selection_locus=SelectionLocus.ROUTE_COMPUTE,
            randomness=RandomnessMode.NONE,
            deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
            resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
            allowed_role_transitions=(("default", "default"),),
            parameters={"weight_metric": "hop_count",
                        "tie_break_policy": "anynet_ascending_min"}),
        "adaptive_xy_yx": RoutingPolicyDefinition(
            id="adaptive_xy_yx", algorithm="source_commit_xy_yx",
            algorithm_version=1, path_mode=PathMode.MINIMAL,
            decision_scope=DecisionScope.SOURCE_COMMIT,
            candidate_mode=CandidateMode.SINGLETON,
            selection_locus=SelectionLocus.ROUTE_COMPUTE,
            randomness=RandomnessMode.RNG,
            deadlock_proof_obligation=DeadlockProofObligation.RESOURCE_ORDERING,
            runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
            resource_roles=(_role("xy", RoutingResourceRoleKind.ROUTE_ORDER),
                            _role("yx", RoutingResourceRoleKind.ROUTE_ORDER)),
            allowed_role_transitions=(("xy", "xy"), ("yx", "yx"))),
        "min_adapt_mesh": RoutingPolicyDefinition(
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
                                      ("escape", "escape"))),
        "valiant": RoutingPolicyDefinition(
            id="valiant", algorithm="phased_valiant", algorithm_version=1,
            path_mode=PathMode.NONMINIMAL, decision_scope=DecisionScope.PER_HOP,
            candidate_mode=CandidateMode.SINGLETON,
            selection_locus=SelectionLocus.ROUTE_COMPUTE,
            randomness=RandomnessMode.RNG,
            deadlock_proof_obligation=DeadlockProofObligation.RESOURCE_ORDERING,
            state_requirements=(
                RoutingStateRequirement("intermediate",
                                        RoutingStateKind.INTERMEDIATE_NODE),
                RoutingStateRequirement("phase", RoutingStateKind.PHASE)),
            resource_roles=(_role("phase0", RoutingResourceRoleKind.PHASE),
                            _role("phase1", RoutingResourceRoleKind.PHASE)),
            allowed_role_transitions=(("phase0", "phase1"),)),
        "ugal": RoutingPolicyDefinition(
            id="ugal", algorithm="congestion_aware_ugal", algorithm_version=1,
            path_mode=PathMode.MIXED, decision_scope=DecisionScope.SOURCE_COMMIT,
            candidate_mode=CandidateMode.SINGLETON,
            selection_locus=SelectionLocus.ROUTE_COMPUTE,
            randomness=RandomnessMode.RNG,
            deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC,
            runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
            state_requirements=(
                RoutingStateRequirement("intermediate",
                                        RoutingStateKind.INTERMEDIATE_NODE),
                RoutingStateRequirement("phase", RoutingStateKind.PHASE)),
            resource_roles=(_role("minimal", RoutingResourceRoleKind.ADAPTIVE),
                            _role("nonminimal",
                                  RoutingResourceRoleKind.CUSTOM)),
            allowed_role_transitions=(("minimal", "minimal"),
                                      ("nonminimal", "nonminimal"))),
        "fault_planar": RoutingPolicyDefinition(
            id="fault_planar_adaptive", algorithm="fault_aware_planar",
            algorithm_version=1, path_mode=PathMode.MINIMAL,
            decision_scope=DecisionScope.PER_HOP,
            candidate_mode=CandidateMode.CANDIDATE_SET,
            selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
            randomness=RandomnessMode.NONE,
            deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC,
            runtime_observations=(RuntimeObservation.FAULT_STATE,),
            resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                            _role("escape", RoutingResourceRoleKind.ESCAPE)),
            allowed_role_transitions=(("adaptive", "adaptive"),
                                      ("adaptive", "escape"),
                                      ("escape", "escape"))),
        "custom_static": RoutingPolicyDefinition(
            id="custom_static_table", algorithm="custom_static_table",
            algorithm_version=1, path_mode=PathMode.MINIMAL,
            decision_scope=DecisionScope.STATIC,
            candidate_mode=CandidateMode.SINGLETON,
            selection_locus=SelectionLocus.ROUTE_COMPUTE,
            randomness=RandomnessMode.NONE,
            deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
            resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
            allowed_role_transitions=(("default", "default"),),
            parameters={"table_ref": "custom_table_v1"}),
    }


def _base(**over) -> RoutingPolicyDefinition:
    kw = dict(
        id="policy", algorithm="algo", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.SOURCE_COMMIT,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.RNG,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        state_requirements=(RoutingStateRequirement("phase", RoutingStateKind.PHASE),),
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "escape"),),
        parameters={"k": 1},
    )
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


@pytest.fixture(scope="module")
def profiles():
    return _profiles()


# ── vocabulary ─────────────────────────────────────────────────────────────

def test_enum_vocabularies_are_closed():
    assert {m.value for m in PathMode} == {"minimal", "nonminimal", "mixed"}
    assert {m.value for m in DecisionScope} == {
        "static", "source_commit", "per_hop"}
    assert {m.value for m in CandidateMode} == {"singleton", "candidate_set"}
    assert {m.value for m in SelectionLocus} == {
        "route_compute", "router_allocator"}
    assert {m.value for m in RandomnessMode} == {"none", "rng"}
    assert {m.value for m in RoutingStateKind} == {
        "route_order", "phase", "intermediate_node", "ring_partition",
        "drop_tap", "custom"}
    assert {m.value for m in RuntimeObservation} == {
        "ingress_channel", "current_vc", "output_credit_occupancy",
        "fault_state", "custom"}
    assert {m.value for m in RoutingResourceRoleKind} == {
        "default", "adaptive", "escape", "phase", "route_order", "ring",
        "tap", "custom"}
    assert {m.value for m in DeadlockProofObligation} == {
        "deterministic_cdg", "escape_subfunction", "resource_ordering",
        "topology_specific", "external"}


def test_proof_obligation_is_not_a_verdict():
    values = {m.value for m in DeadlockProofObligation}
    assert not values & {"pass", "fail", "unsupported", "not_run"}
    definition = _base()
    assert not hasattr(definition, "verdict")
    assert not hasattr(definition, "certify")
    assert "verdict" not in definition.to_dict()


# ── identity and round trip ────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(GOLDEN_POLICY_HASHES))
def test_reference_profile_hashes_are_pinned(profiles, name):
    assert profiles[name].policy_hash == GOLDEN_POLICY_HASHES[name]


@pytest.mark.parametrize("name", sorted(GOLDEN_POLICY_HASHES))
def test_round_trip_is_lossless(profiles, name):
    original = profiles[name]
    restored = RoutingPolicyDefinition.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.policy_hash == original.policy_hash
    assert restored == original


def test_policy_hash_is_a_bare_64_hex_digest(profiles):
    for profile in profiles.values():
        assert len(profile.policy_hash) == 64
        assert all(c in "0123456789abcdef" for c in profile.policy_hash)
        assert not profile.policy_hash.startswith("sha256:")


def test_reference_profiles_are_distinct(profiles):
    assert len({p.policy_hash for p in profiles.values()}) == 8


def test_identical_constructions_hash_equal():
    assert _base().policy_hash == _base().policy_hash
    assert _base(parameters={"k": 1}).policy_hash \
        == _base(parameters={"k": 1}).policy_hash


def test_canonical_order_does_not_move_hash():
    left = _base(
        state_requirements=(RoutingStateRequirement("phase", RoutingStateKind.PHASE),
                            RoutingStateRequirement("intermediate",
                                                    RoutingStateKind.INTERMEDIATE_NODE)),
        resource_roles=(_role("escape", RoutingResourceRoleKind.ESCAPE),
                        _role("adaptive", RoutingResourceRoleKind.ADAPTIVE)),
        allowed_role_transitions=(("adaptive", "escape"),
                                  ("adaptive", "adaptive")))
    right = _base(
        state_requirements=(RoutingStateRequirement("intermediate",
                                                    RoutingStateKind.INTERMEDIATE_NODE),
                            RoutingStateRequirement("phase", RoutingStateKind.PHASE)),
        resource_roles=(_role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
                        _role("escape", RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape")))
    assert left.policy_hash == right.policy_hash


def test_parameter_key_order_does_not_move_hash():
    left = _base(parameters={"a": 1, "b": 2})
    right = _base(parameters={"b": 2, "a": 1})
    assert left.policy_hash == right.policy_hash


def test_mutation_sensitivity():
    base = _base()
    variants = [
        _base(id="other"),
        _base(algorithm="other"),
        _base(algorithm_version=2),
        _base(path_mode=PathMode.NONMINIMAL),
        _base(decision_scope=DecisionScope.PER_HOP),
        _base(candidate_mode=CandidateMode.CANDIDATE_SET),
        _base(selection_locus=SelectionLocus.ROUTER_ALLOCATOR),
        _base(randomness=RandomnessMode.NONE),
        _base(deadlock_proof_obligation=DeadlockProofObligation.TOPOLOGY_SPECIFIC),
        _base(state_requirements=(RoutingStateRequirement(
            "phase", RoutingStateKind.ROUTE_ORDER),)),
        _base(runtime_observations=(RuntimeObservation.FAULT_STATE,)),
        _base(resource_roles=(_role("escape", RoutingResourceRoleKind.CUSTOM),),
              allowed_role_transitions=(("escape", "escape"),)),
        _base(allowed_role_transitions=(("escape", "escape"),)),
        _base(parameters={"k": 2}),
    ]
    hashes = {base.policy_hash} | {v.policy_hash for v in variants}
    assert len(hashes) == len(variants) + 1


# ── strict parsing ─────────────────────────────────────────────────────────

def test_unknown_fields_are_refused():
    d = _base().to_dict()
    d["extra"] = 1
    with pytest.raises(RoutingPolicyError, match="unknown fields"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS))
def test_missing_required_fields_are_refused(field):
    d = _base().to_dict()
    d.pop(field)
    with pytest.raises(RoutingPolicyError, match="missing required field"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("bad_type", [None, "srota/RouteArtifact", 7])
def test_type_tag_is_strict(bad_type):
    d = _base().to_dict()
    if bad_type is None:
        d.pop("type")
    else:
        d["type"] = bad_type
    with pytest.raises(RoutingPolicyError, match="type"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("bad", [2, True, "1", 1.0])
def test_schema_version_must_be_the_exact_int(bad):
    d = _base().to_dict()
    d["schema_version"] = bad
    with pytest.raises(RoutingPolicyError, match="schema_version"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("field,bad", [
    ("path_mode", "bogus"),
    ("path_mode", 1),
    ("path_mode", True),
    ("decision_scope", None),
    ("candidate_mode", "sets"),
    ("selection_locus", 3),
    ("randomness", "maybe"),
    ("deadlock_proof_obligation", "proven"),
])
def test_enum_fields_are_strict(field, bad):
    d = _base().to_dict()
    d[field] = bad
    with pytest.raises(RoutingPolicyError):
        RoutingPolicyDefinition.from_dict(d)


def test_constructor_rejects_string_enums():
    with pytest.raises(RoutingPolicyError, match="PathMode"):
        _base(path_mode="minimal")


@pytest.mark.parametrize("bad", [True, 1.0, "1", 0])
def test_algorithm_version_is_strict(bad):
    d = _base().to_dict()
    d["algorithm_version"] = bad
    with pytest.raises(RoutingPolicyError, match="algorithm_version"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("field", ["id", "algorithm"])
def test_empty_ids_are_refused(field):
    d = _base().to_dict()
    d[field] = ""
    with pytest.raises(RoutingPolicyError, match=field):
        RoutingPolicyDefinition.from_dict(d)
    with pytest.raises(RoutingPolicyError):
        _base(**{field: ""})


def test_state_requirements_are_unique_and_sorted():
    with pytest.raises(RoutingPolicyError, match="unique"):
        _base(state_requirements=(
            RoutingStateRequirement("phase", RoutingStateKind.PHASE),
            RoutingStateRequirement("phase", RoutingStateKind.CUSTOM)))
    d = _profiles()["valiant"].to_dict()
    d["state_requirements"] = list(reversed(d["state_requirements"]))
    with pytest.raises(RoutingPolicyError, match="sorted"):
        RoutingPolicyDefinition.from_dict(d)


def test_resource_roles_are_unique_and_sorted():
    with pytest.raises(RoutingPolicyError, match="unique"):
        _base(resource_roles=(
            _role("adaptive", RoutingResourceRoleKind.ADAPTIVE),
            _role("adaptive", RoutingResourceRoleKind.ESCAPE)))
    d = _profiles()["min_adapt_mesh"].to_dict()
    d["resource_roles"] = list(reversed(d["resource_roles"]))
    with pytest.raises(RoutingPolicyError, match="sorted"):
        RoutingPolicyDefinition.from_dict(d)


def test_transitions_must_reference_declared_roles():
    with pytest.raises(RoutingPolicyError, match="undeclared"):
        _base(allowed_role_transitions=(("adaptive", "ghost"),))
    d = _base().to_dict()
    d["allowed_role_transitions"] = [["adaptive", "ghost"]]
    with pytest.raises(RoutingPolicyError, match="undeclared"):
        RoutingPolicyDefinition.from_dict(d)


def test_duplicate_transitions_are_refused():
    with pytest.raises(RoutingPolicyError, match="unique"):
        _base(allowed_role_transitions=(("adaptive", "escape"),
                                        ("adaptive", "escape")))
    d = _base().to_dict()
    d["allowed_role_transitions"] = [["adaptive", "escape"],
                                     ["adaptive", "escape"]]
    with pytest.raises(RoutingPolicyError, match="unique"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("bad_rows", [
    [["adaptive"]],
    [["adaptive", "escape", "extra"]],
    [("adaptive", "escape")],
    [["adaptive", ""]],
    ["adaptive escape"],
])
def test_persisted_transition_rows_are_strict(bad_rows):
    d = _base().to_dict()
    d["allowed_role_transitions"] = bad_rows
    with pytest.raises(RoutingPolicyError):
        RoutingPolicyDefinition.from_dict(d)


def test_persisted_observations_must_be_sorted_unique():
    d = _base().to_dict()
    d["runtime_observations"] = ["fault_state", "custom"]
    with pytest.raises(RoutingPolicyError, match="sorted"):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["runtime_observations"] = ["custom", "custom"]
    with pytest.raises(RoutingPolicyError, match="unique"):
        RoutingPolicyDefinition.from_dict(d)


@pytest.mark.parametrize("bad", [[], "params", None, 3])
def test_parameters_must_be_a_json_object(bad):
    d = _base().to_dict()
    d["parameters"] = bad
    with pytest.raises(RoutingPolicyError, match="parameters"):
        RoutingPolicyDefinition.from_dict(d)


def test_parameters_must_be_canonical_values():
    with pytest.raises(RoutingPolicyError, match="parameters"):
        _base(parameters={"bad": object()})
    with pytest.raises(RoutingPolicyError, match="parameters"):
        _base(parameters={1: "non-string-key"})


def test_persisted_state_and_role_shapes_are_strict():
    d = _base().to_dict()
    d["state_requirements"] = "phase"
    with pytest.raises(RoutingPolicyError, match="state_requirements"):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["state_requirements"] = [["extra", "phase", 1]]
    with pytest.raises(RoutingPolicyError):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["resource_roles"] = [{"id": "adaptive"}]
    with pytest.raises(RoutingPolicyError, match="missing required field"):
        RoutingPolicyDefinition.from_dict(d)


def test_policy_hash_is_required_and_verified():
    d = _base().to_dict()
    d.pop("policy_hash")
    with pytest.raises(RoutingPolicyError, match="missing required field"):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["policy_hash"] = ""
    with pytest.raises(RoutingPolicyError, match="policy_hash"):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["policy_hash"] = "0" * 64
    with pytest.raises(RoutingPolicyError, match="policy_hash"):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["policy_hash"] = "sha256:" + d["policy_hash"]
    with pytest.raises(RoutingPolicyError, match="policy_hash"):
        RoutingPolicyDefinition.from_dict(d)
    with pytest.raises(RoutingPolicyError, match="policy_hash"):
        _base(policy_hash="deadbeef")


def test_tampered_semantics_are_refused():
    d = _base().to_dict()
    d["path_mode"] = "nonminimal"
    with pytest.raises(RoutingPolicyError, match="policy_hash"):
        RoutingPolicyDefinition.from_dict(d)
    d = _base().to_dict()
    d["parameters"] = {"k": 2}
    with pytest.raises(RoutingPolicyError, match="policy_hash"):
        RoutingPolicyDefinition.from_dict(d)


# ── universally safe invariants only ───────────────────────────────────────

def test_static_policies_may_not_observe_runtime_state():
    with pytest.raises(RoutingPolicyError, match="runtime observations"):
        _base(decision_scope=DecisionScope.STATIC,
              randomness=RandomnessMode.NONE)


def test_static_policies_may_not_use_rng():
    with pytest.raises(RoutingPolicyError, match="RNG"):
        _base(decision_scope=DecisionScope.STATIC,
              runtime_observations=())


def test_valid_locus_combinations_are_accepted():
    assert _base(candidate_mode=CandidateMode.CANDIDATE_SET,
                 selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
                 decision_scope=DecisionScope.PER_HOP).policy_hash
    assert _base(candidate_mode=CandidateMode.SINGLETON,
                 selection_locus=SelectionLocus.ROUTE_COMPUTE,
                 decision_scope=DecisionScope.PER_HOP).policy_hash


def test_per_hop_singleton_is_valid():
    assert _base(decision_scope=DecisionScope.PER_HOP,
                 candidate_mode=CandidateMode.SINGLETON).policy_hash


def test_adaptive_role_does_not_imply_minimal_path():
    assert _base(path_mode=PathMode.NONMINIMAL).policy_hash


def test_escape_role_does_not_imply_a_proof():
    definition = _base(
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION)
    assert definition.deadlock_proof_obligation \
        == DeadlockProofObligation.ESCAPE_SUBFUNCTION
    assert not hasattr(definition, "verdict")


# ── immutability ───────────────────────────────────────────────────────────

def test_definition_is_frozen():
    definition = _base()
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.algorithm = "other"


def test_parameters_are_deeply_frozen():
    definition = _base(parameters={"nested": {"values": [1, 2]}})
    with pytest.raises(TypeError):
        definition.parameters["nested"] = 1
    with pytest.raises(TypeError):
        definition.parameters["nested"]["values"] = ()
    assert definition.parameters["nested"]["values"] == (1, 2)


def test_caller_parameter_dict_cannot_mutate_policy():
    raw = {"nested": [1, 2]}
    definition = _base(parameters=raw)
    raw["nested"].append(3)
    raw["extra"] = 1
    assert definition.parameters["nested"] == (1, 2)
    assert "extra" not in definition.parameters


def test_to_dict_is_a_defensive_copy():
    definition = _base(parameters={"nested": [1, 2]})
    first = definition.to_dict()
    first["parameters"]["nested"].append(3)
    first["id"] = "mutated"
    second = definition.to_dict()
    assert second["parameters"]["nested"] == [1, 2]
    assert second["id"] == "policy"


# ── reference profile expressivity ─────────────────────────────────────────

def test_reference_profiles_express_expected_dimensions(profiles):
    dor = profiles["dor_xy"]
    assert (dor.path_mode, dor.decision_scope, dor.candidate_mode,
            dor.selection_locus, dor.randomness) == (
        PathMode.MINIMAL, DecisionScope.STATIC, CandidateMode.SINGLETON,
        SelectionLocus.ROUTE_COMPUTE, RandomnessMode.NONE)
    assert dor.allowed_role_transitions == (("default", "default"),)

    anynet = profiles["anynet_dijkstra"]
    assert anynet.parameters["weight_metric"] == "hop_count"
    assert anynet.deadlock_proof_obligation \
        == DeadlockProofObligation.DETERMINISTIC_CDG

    xy_yx = profiles["adaptive_xy_yx"]
    assert xy_yx.decision_scope == DecisionScope.SOURCE_COMMIT
    assert xy_yx.randomness == RandomnessMode.RNG
    assert xy_yx.runtime_observations \
        == (RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,)
    assert {r.id for r in xy_yx.resource_roles} == {"xy", "yx"}

    min_adapt = profiles["min_adapt_mesh"]
    assert min_adapt.candidate_mode == CandidateMode.CANDIDATE_SET
    assert min_adapt.selection_locus == SelectionLocus.ROUTER_ALLOCATOR
    assert min_adapt.allowed_role_transitions == (
        ("adaptive", "adaptive"), ("adaptive", "escape"),
        ("escape", "escape"))
    assert min_adapt.deadlock_proof_obligation \
        == DeadlockProofObligation.ESCAPE_SUBFUNCTION

    valiant = profiles["valiant"]
    assert valiant.path_mode == PathMode.NONMINIMAL
    assert valiant.randomness == RandomnessMode.RNG
    assert {s.name for s in valiant.state_requirements} \
        == {"phase", "intermediate"}
    assert {r.id for r in valiant.resource_roles} == {"phase0", "phase1"}

    ugal = profiles["ugal"]
    assert ugal.path_mode == PathMode.MIXED
    assert ugal.deadlock_proof_obligation \
        == DeadlockProofObligation.TOPOLOGY_SPECIFIC
    assert {s.name for s in ugal.state_requirements} \
        == {"phase", "intermediate"}

    planar = profiles["fault_planar"]
    assert planar.runtime_observations == (RuntimeObservation.FAULT_STATE,)
    assert planar.candidate_mode == CandidateMode.CANDIDATE_SET
    assert len(planar.resource_roles) > 1

    custom = profiles["custom_static"]
    assert custom.decision_scope == DecisionScope.STATIC
    assert custom.candidate_mode == CandidateMode.SINGLETON
    assert custom.algorithm == "custom_static_table"


def test_schema_has_no_materialized_execution_fields(profiles):
    names = {f.name for f in dataclasses.fields(RoutingPolicyDefinition)}
    assert names == EXPECTED_FIELDS
    assert not names & FORBIDDEN_KEYS
    for profile in profiles.values():
        d = profile.to_dict()
        assert set(d) == EXPECTED_FIELDS | {"type"}
        assert not set(d) & FORBIDDEN_KEYS
        text = json.dumps(d)
        for token in ("booksim", "simulator", "binary_path", "\"seed\"",
                      "verdict"):
            assert token not in text
        for key in profile.parameters:
            assert "congestion" not in key.lower()


def test_no_concrete_topology_channel_endpoint_or_vc_values(profiles):
    for profile in profiles.values():
        blob = json.dumps(profile.to_dict())
        assert "channel_id" not in blob
        assert "endpoint_id" not in blob
        assert "vc_id" not in blob
        assert "topology_hash" not in blob
