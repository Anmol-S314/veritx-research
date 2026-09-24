"""RoutingResourceBindingArtifact tests — roles to concrete VCs.

The binding is topology-independent: it binds the roles declared by a
RoutingPolicyDefinition to the concrete VCs declared by a
VCResourceArtifact, and proves that the concrete transition graph realizes
the policy's abstract role transitions — exactly, and per source VC.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.model import routing_resource_binding as rrb
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact, RoutingResourceBindingError,
)
from veritx_dse.model.vc_resource import VCResourceArtifact

GOLDEN_MIN_ADAPT = (
    "6abb7b6cac9be82904505f7859262aece7d7bda10df92346ec562e28b788b00a")
GOLDEN_ONE_ROLE = (
    "612e9697180e909e8e9ba798b6eae96c6184f7be95c42163bc9c711183b75772")
GOLDEN_MULTI_VC_ONE_ROLE = (
    "f7dc207042a5eadabea1c409da051c44bb1117e2da2b3ed6ca759fce4ee843e7")
GOLDEN_PHASED = (
    "7aa81fb1ce5fe7f53b9f58863378ce9c2dbb29eea21bb12bda922dd41af7b5bc")

EXPECTED_FIELDS = {
    "policy_hash", "vc_resource_hash", "role_to_vcs", "schema_version",
    "binding_hash",
}

FORBIDDEN_TOKENS = (
    "topology_hash", "relation_hash", "channel_id", "router_id",
    "endpoint", "logical_rank", "rank", "traffic_class_to_vcs",
    "escape_vcs", "vc_to_routing_class", "booksim", "backend", "simulator",
    "verdict", "certificate", "deadlock",
)

_MIN_ADAPT_TRANSITIONS = (
    (0, 0),
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3),
    (3, 0), (3, 1), (3, 2), (3, 3),
)


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


def _min_adapt_resources(transitions=_MIN_ADAPT_TRANSITIONS, **over):
    kw = dict(vc_count=4, vc_ids=(0, 1, 2, 3),
              traffic_class_to_vcs=(("default", (0, 1, 2, 3)),),
              allowed_transitions=transitions)
    kw.update(over)
    return VCResourceArtifact(**kw)


def _binding(policy, resource, role_to_vcs):
    return RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash,
        vc_resource_hash=resource.artifact_hash,
        role_to_vcs=role_to_vcs)


def _valid_min_adapt():
    policy = _min_adapt_policy()
    resource = _min_adapt_resources()
    binding = _binding(policy, resource,
                       (("adaptive", (1, 2, 3)), ("escape", (0,))))
    return policy, resource, binding


def _one_role_policy(**over):
    kw = dict(
        id="one", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(_role("default", RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),))
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _phased_policy():
    return RoutingPolicyDefinition(
        id="toy_phased", algorithm="toy_phased", algorithm_version=1,
        path_mode=PathMode.NONMINIMAL, decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.RNG,
        deadlock_proof_obligation=DeadlockProofObligation.RESOURCE_ORDERING,
        resource_roles=(
            _role("phase0", RoutingResourceRoleKind.PHASE),
            _role("phase1", RoutingResourceRoleKind.PHASE)),
        allowed_role_transitions=(("phase0", "phase0"),
                                  ("phase0", "phase1"),
                                  ("phase1", "phase1")))


def _projected_roles(binding, resource):
    owner = {vc: role for role, vcs in binding.role_to_vcs for vc in vcs}
    return {(owner[src], owner[dst])
            for src, dst in resource.allowed_transitions}


# ── MinAdapt reference fixture ─────────────────────────────────────────────

def test_min_adapt_binding_hash_is_pinned():
    _policy, _resource, binding = _valid_min_adapt()
    assert binding.binding_hash == GOLDEN_MIN_ADAPT


def test_min_adapt_binding_round_trips():
    _policy, _resource, binding = _valid_min_adapt()
    restored = RoutingResourceBindingArtifact.from_dict(binding.to_dict())
    assert restored.binding_hash == binding.binding_hash
    assert restored.to_dict() == binding.to_dict()


def test_min_adapt_role_rows_are_canonical():
    _policy, _resource, binding = _valid_min_adapt()
    assert binding.role_to_vcs == (("adaptive", (1, 2, 3)),
                                   ("escape", (0,)))


def test_min_adapt_projection_is_exact():
    policy, resource, binding = _valid_min_adapt()
    assert _projected_roles(binding, resource) \
        == set(policy.allowed_role_transitions)


def test_min_adapt_per_source_transition_coverage():
    policy, resource, binding = _valid_min_adapt()
    roles = dict(binding.role_to_vcs)
    concrete = set(resource.allowed_transitions)
    for src_vc in roles["adaptive"]:
        assert any((src_vc, dst) in concrete for dst in roles["adaptive"])
        assert any((src_vc, dst) in concrete for dst in roles["escape"])
    for src_vc in roles["escape"]:
        assert any((src_vc, dst) in concrete for dst in roles["escape"])
    # the validator itself accepts the reference fixture
    assert binding.validate_against(policy, resource) is None


# ── generic fixtures ───────────────────────────────────────────────────────

def test_one_role_fixture():
    policy = _one_role_policy()
    resource = VCResourceArtifact(
        vc_count=1, vc_ids=(0,),
        traffic_class_to_vcs=(("default", (0,)),),
        allowed_transitions=((0, 0),))
    binding = _binding(policy, resource, (("default", (0,)),))
    assert binding.validate_against(policy, resource) is None
    assert binding.binding_hash == GOLDEN_ONE_ROLE


def test_multi_vc_single_role_fixture():
    policy = _one_role_policy()
    resource = VCResourceArtifact(
        vc_count=2, vc_ids=(0, 1),
        traffic_class_to_vcs=(("default", (0, 1)),),
        allowed_transitions=((0, 0), (0, 1), (1, 0), (1, 1)))
    binding = _binding(policy, resource, (("default", (0, 1)),))
    assert binding.validate_against(policy, resource) is None
    assert binding.binding_hash == GOLDEN_MULTI_VC_ONE_ROLE


def test_phased_policy_fixture_needs_no_min_adapt_code():
    policy = _phased_policy()
    resource = VCResourceArtifact(
        vc_count=3, vc_ids=(0, 1, 2),
        traffic_class_to_vcs=(("default", (0, 1, 2)),),
        allowed_transitions=((0, 1), (0, 2), (1, 0), (1, 2), (2, 2)))
    binding = _binding(policy, resource,
                       (("phase0", (0, 1)), ("phase1", (2,))))
    assert binding.validate_against(policy, resource) is None
    assert binding.binding_hash == GOLDEN_PHASED
    assert _projected_roles(binding, resource) \
        == set(policy.allowed_role_transitions)


# ── negative MinAdapt cases ────────────────────────────────────────────────

def test_missing_escape_transition_is_refused():
    policy = _min_adapt_policy()
    resource = _min_adapt_resources(transitions=tuple(
        t for t in _MIN_ADAPT_TRANSITIONS if t != (3, 0)))
    binding = _binding(policy, resource,
                       (("adaptive", (1, 2, 3)), ("escape", (0,))))
    with pytest.raises(RoutingResourceBindingError,
                       match="no concrete transition into role 'escape'"):
        binding.validate_against(policy, resource)


def test_partial_adaptive_self_coverage_is_refused():
    policy = _min_adapt_policy()
    resource = _min_adapt_resources(transitions=tuple(
        t for t in _MIN_ADAPT_TRANSITIONS
        if not (t[0] == 2 and t[1] in (1, 2, 3))))
    binding = _binding(policy, resource,
                       (("adaptive", (1, 2, 3)), ("escape", (0,))))
    with pytest.raises(RoutingResourceBindingError,
                       match="no concrete transition into role 'adaptive'"):
        binding.validate_against(policy, resource)


def test_forbidden_escape_to_adaptive_transition_is_refused():
    policy = _min_adapt_policy()
    resource = _min_adapt_resources(
        transitions=tuple(sorted(_MIN_ADAPT_TRANSITIONS + ((0, 1),))))
    binding = _binding(policy, resource,
                       (("adaptive", (1, 2, 3)), ("escape", (0,))))
    with pytest.raises(RoutingResourceBindingError, match="do not realize"):
        binding.validate_against(policy, resource)


def test_missing_abstract_transition_is_refused():
    policy = _min_adapt_policy()
    resource = _min_adapt_resources(transitions=tuple(
        t for t in _MIN_ADAPT_TRANSITIONS if t[1] != 0))
    binding = _binding(policy, resource,
                       (("adaptive", (1, 2, 3)), ("escape", (0,))))
    with pytest.raises(RoutingResourceBindingError, match="missing"):
        binding.validate_against(policy, resource)


def test_overlapping_role_sets_are_refused():
    policy, resource, _binding_ = _valid_min_adapt()
    overlapping = _binding(policy, resource,
                           (("adaptive", (1, 2, 3)), ("escape", (0, 1))))
    with pytest.raises(RoutingResourceBindingError, match="both"):
        overlapping.validate_against(policy, resource)


def test_dangling_vc_is_refused():
    policy, resource, _binding_ = _valid_min_adapt()
    dangling = _binding(policy, resource,
                        (("adaptive", (1, 2)), ("escape", (0,))))
    with pytest.raises(RoutingResourceBindingError, match="unbound"):
        dangling.validate_against(policy, resource)


def test_missing_role_is_refused():
    policy, resource, _binding_ = _valid_min_adapt()
    missing = _binding(policy, resource, (("adaptive", (0, 1, 2, 3)),))
    with pytest.raises(RoutingResourceBindingError, match="missing"):
        missing.validate_against(policy, resource)


def test_undeclared_role_is_refused():
    policy, resource, _binding_ = _valid_min_adapt()
    undeclared = _binding(policy, resource,
                          (("adaptive", (1, 2, 3)), ("escape", (0,)),
                           ("ghost", (0,))))
    with pytest.raises(RoutingResourceBindingError, match="undeclared"):
        undeclared.validate_against(policy, resource)


def test_nonexistent_vc_is_refused():
    policy, resource, _binding_ = _valid_min_adapt()
    bogus = _binding(policy, resource,
                     (("adaptive", (1, 2, 3)), ("escape", (0, 9))))
    with pytest.raises(RoutingResourceBindingError,
                       match="not in the VC resource universe"):
        bogus.validate_against(policy, resource)


def test_empty_and_duplicate_role_sets_are_refused_at_construction():
    policy, resource, _binding_ = _valid_min_adapt()
    with pytest.raises(RoutingResourceBindingError, match="at least one"):
        _binding(policy, resource,
                 (("adaptive", ()), ("escape", (0,))))
    with pytest.raises(RoutingResourceBindingError, match="duplicate"):
        _binding(policy, resource,
                 (("adaptive", (1, 1, 2, 3)), ("escape", (0,))))


# ── identity ───────────────────────────────────────────────────────────────

def test_construction_order_does_not_move_identity():
    policy, resource, canonical = _valid_min_adapt()
    reordered = _binding(policy, resource,
                         (("escape", (0,)), ("adaptive", (3, 2, 1))))
    assert reordered.binding_hash == canonical.binding_hash
    assert reordered.to_dict() == canonical.to_dict()


def test_role_assignment_changes_identity():
    policy, resource, canonical = _valid_min_adapt()
    other = _binding(policy, resource,
                     (("adaptive", (1, 2)), ("escape", (0, 3))))
    assert other.binding_hash != canonical.binding_hash


def test_parent_hashes_participate_in_identity():
    policy, resource, canonical = _valid_min_adapt()
    other_policy = _min_adapt_policy(id="min_adapt_like")
    other_resource = _min_adapt_resources(transitions=tuple(
        t for t in _MIN_ADAPT_TRANSITIONS if t != (3, 3)))
    assert _binding(other_policy, resource,
                    canonical.role_to_vcs).binding_hash \
        != canonical.binding_hash
    assert _binding(policy, other_resource,
                    canonical.role_to_vcs).binding_hash \
        != canonical.binding_hash


def test_binding_contains_no_topology_or_relation_identity():
    policy = _min_adapt_policy()
    resource = _min_adapt_resources()
    binding = _binding(policy, resource,
                       (("adaptive", (1, 2, 3)), ("escape", (0,))))
    names = {f.name for f in dataclasses.fields(RoutingResourceBindingArtifact)}
    assert names == EXPECTED_FIELDS
    blob = str(binding.to_dict()).lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in blob
    # the same artifact is reusable for topology-specific MinAdapt relations
    from veritx_dse.model.routing_relation_materialize import (
        materialize_routing_relation)
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family)
    before = binding.binding_hash
    for endpoint_count in (4, 9):
        topology = materialize_family(MaterializedFamily.MESH,
                                      endpoint_count=endpoint_count)
        relation = materialize_routing_relation(topology, policy)
        assert relation.policy_hash == binding.policy_hash
    assert binding.binding_hash == before


# ── strict parser ──────────────────────────────────────────────────────────

def _valid_dict() -> dict:
    return _valid_min_adapt()[2].to_dict()


def test_unknown_fields_are_refused():
    d = _valid_dict()
    d["extra"] = 1
    with pytest.raises(RoutingResourceBindingError, match="unknown fields"):
        RoutingResourceBindingArtifact.from_dict(d)


@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS | {"type"}))
def test_missing_required_fields_are_refused(field):
    d = _valid_dict()
    d.pop(field)
    with pytest.raises(RoutingResourceBindingError):
        RoutingResourceBindingArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [None, "srota/VCResourceArtifact", 7])
def test_type_tag_is_strict(bad):
    d = _valid_dict()
    if bad is None:
        d.pop("type")
    else:
        d["type"] = bad
    with pytest.raises(RoutingResourceBindingError, match="type"):
        RoutingResourceBindingArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [2, True, "1", 1.0])
def test_schema_version_is_strict(bad):
    d = _valid_dict()
    d["schema_version"] = bad
    with pytest.raises(RoutingResourceBindingError, match="schema_version"):
        RoutingResourceBindingArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [
    [["adaptive"]],
    [["adaptive", [1, 2, 3], 4]],
    [("adaptive", [1, 2, 3]), ("escape", [0])],
    [["", [1, 2, 3]], ["escape", [0]]],
    [["adaptive", "123"], ["escape", [0]]],
    [["adaptive", [1, 2, True]], ["escape", [0]]],
    [["adaptive", [1.5]], ["escape", [0]]],
    [["adaptive", [3, 2, 1]], ["escape", [0]]],
    [["adaptive", [1, 1, 2, 3]], ["escape", [0]]],
    [["ghost", [1, 2, 3]], ["adaptive", [0]]],
    [["escape", [0]], ["adaptive", [1, 2, 3]]],
    [["escape", [0]], ["escape", [1]]],
])
def test_persisted_role_rows_are_strict(bad):
    d = _valid_dict()
    d["role_to_vcs"] = bad
    with pytest.raises(RoutingResourceBindingError):
        RoutingResourceBindingArtifact.from_dict(d)


def test_persisted_binding_hash_is_required_and_verified():
    d = _valid_dict()
    d.pop("binding_hash")
    with pytest.raises(RoutingResourceBindingError, match="missing required"):
        RoutingResourceBindingArtifact.from_dict(d)
    d = _valid_dict()
    d["binding_hash"] = ""
    with pytest.raises(RoutingResourceBindingError, match="binding_hash"):
        RoutingResourceBindingArtifact.from_dict(d)
    d = _valid_dict()
    d["binding_hash"] = "0" * 64
    with pytest.raises(RoutingResourceBindingError, match="binding_hash"):
        RoutingResourceBindingArtifact.from_dict(d)


def test_constructor_rejects_stored_hash_mismatch():
    policy, resource, _binding_ = _valid_min_adapt()
    with pytest.raises(RoutingResourceBindingError, match="binding_hash"):
        RoutingResourceBindingArtifact(
            policy_hash=policy.policy_hash,
            vc_resource_hash=resource.artifact_hash,
            role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))),
            binding_hash="deadbeef")


def test_parent_hash_tampering_is_refused():
    policy, resource, binding = _valid_min_adapt()
    other_policy = _min_adapt_policy(id="other_policy")
    other_resource = _min_adapt_resources(transitions=tuple(
        t for t in _MIN_ADAPT_TRANSITIONS if t != (3, 3)))
    with pytest.raises(RoutingResourceBindingError, match="policy_hash"):
        binding.validate_against(other_policy, resource)
    with pytest.raises(RoutingResourceBindingError, match="vc_resource_hash"):
        binding.validate_against(policy, other_resource)


def test_parent_type_checks_are_refused():
    policy, resource, binding = _valid_min_adapt()
    with pytest.raises(RoutingResourceBindingError,
                       match="RoutingPolicyDefinition"):
        binding.validate_against(object(), resource)
    with pytest.raises(RoutingResourceBindingError, match="VCResourceArtifact"):
        binding.validate_against(policy, object())


# ── immutability ───────────────────────────────────────────────────────────

def test_binding_is_frozen_and_tuple_backed():
    _policy, _resource, binding = _valid_min_adapt()
    with pytest.raises(dataclasses.FrozenInstanceError):
        binding.role_to_vcs = ()
    assert isinstance(binding.role_to_vcs, tuple)
    assert all(isinstance(vcs, tuple) for _role, vcs in binding.role_to_vcs)
    with pytest.raises(TypeError):
        binding.role_to_vcs[0] = ("adaptive", (1,))


def test_mutable_role_rows_are_refused_not_aliased():
    policy, resource, _binding_ = _valid_min_adapt()
    with pytest.raises(RoutingResourceBindingError, match="tuple"):
        _binding(policy, resource,
                 [["adaptive", [1, 2, 3]], ["escape", [0]]])
    with pytest.raises(RoutingResourceBindingError, match="tuple"):
        _binding(policy, resource,
                 (("adaptive", [1, 2, 3]), ("escape", (0,))))


def test_to_dict_returns_fresh_data():
    _policy, _resource, binding = _valid_min_adapt()
    first = binding.to_dict()
    first["role_to_vcs"][0][1].append(9)
    first["role_to_vcs"].clear()
    second = binding.to_dict()
    assert second["role_to_vcs"] == [["adaptive", [1, 2, 3]],
                                     ["escape", [0]]]
    assert binding.binding_hash == GOLDEN_MIN_ADAPT


# ── scope sentinels ────────────────────────────────────────────────────────

def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(rrb))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    local = {name for name in imported if name.startswith("veritx_dse")}
    assert local == {"veritx_dse.core.artifact",
                     "veritx_dse.core.errors",
                     "veritx_dse.model.routing_policy",
                     "veritx_dse.model.vc_resource"}
    forbidden = ("routing_relation", "route_artifact", "resolved_route",
                 "vc_assignment", "topology", "verification", "backend",
                 "booksim", "astra")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name
