"""Adaptive routing bridge tests: MIN_ADAPT_MESH end to end + scope guards.

Chain: min_adapt_mesh_policy -> materialize_routing_relation ->
binding -> make_adaptive_routing_realization -> adaptive_backend_selection
-> qualify_min_adapt (escape certificate PASS). Plus: refusal of every
other adaptive fork function, LOCKED routing (no user knob), and the
evidence-scope guard proving deterministic-table equivalence can never be
claimed for adaptive execution.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend import route_observation as ro  # noqa: E402
from veritx_dse.model import routing_relation_materialize as rrm  # noqa: E402
from veritx_dse.model.routing_realization import (  # noqa: E402
    MIN_ADAPT_FIDELITY,
    RoutingRealizationError,
    RoutingRealizationKind,
    adaptive_backend_selection,
    make_adaptive_routing_realization,
)
from veritx_dse.model.routing_resource_binding import (  # noqa: E402
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    materialize_family,
)
from veritx_dse.model.vc_resource import VCResourceArtifact  # noqa: E402
from veritx_dse.verification import adaptive_escape as ae  # noqa: E402

_MESH2 = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
_MESH3 = materialize_family(MaterializedFamily.MESH, endpoint_count=9)

_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

def _resource(vc_count=4, transitions=_TRANSITIONS):
    return VCResourceArtifact(
        vc_count=vc_count, vc_ids=tuple(range(vc_count)),
        traffic_class_to_vcs=(("default", tuple(range(vc_count))),),
        allowed_transitions=transitions)

def _binding(policy, resource):
    return RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash,
        vc_resource_hash=resource.artifact_hash,
        role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))

def _chain(topology=_MESH2):
    policy = rrm.min_adapt_mesh_policy()
    relation = rrm.materialize_routing_relation(topology, policy)
    resource = _resource()
    binding = _binding(policy, resource)
    realization = make_adaptive_routing_realization(
        topology=topology, policy=policy, relation=relation,
        vc_resource=resource, binding=binding)
    return policy, relation, resource, binding, realization

def test_policy_constructor_is_the_exact_profile():
    policy = rrm.min_adapt_mesh_policy()
    assert policy.id == "min_adapt_mesh"
    assert policy.algorithm == "per_hop_min_adaptive"
    assert rrm.materialize_routing_relation(_MESH2, policy) is not None

def test_full_chain_qualifies_on_mesh():
    policy, relation, resource, binding, realization = _chain()
    assert realization.kind is RoutingRealizationKind.ADAPTIVE
    selection = adaptive_backend_selection(
        realization=realization, policy=policy, binding=binding)
    assert selection.routing_function == "min_adapt_mesh"
    assert selection.escape_vcs == (0,)
    assert selection.adaptive_vcs == (1, 2, 3)
    assert selection.first_hop_table_comparable is False
    qualification = ae.qualify_min_adapt(
        topology=_MESH2, policy=policy, relation=relation,
        vc_resource=resource, binding=binding,
        realization_hash=realization.routing_realization_hash)
    assert qualification.verdict == "QUALIFIED"
    assert qualification.routing_function == "min_adapt_mesh"
    assert qualification.fidelity == MIN_ADAPT_FIDELITY
    assert qualification.fidelity != "DETERMINISTIC_CDG"

def test_full_chain_qualifies_on_3x3():
    policy, relation, resource, binding, realization = _chain(_MESH3)
    qualification = ae.qualify_min_adapt(
        topology=_MESH3, policy=policy, relation=relation,
        vc_resource=resource, binding=binding,
        realization_hash=realization.routing_realization_hash)
    assert qualification.verdict == "QUALIFIED"

def test_failed_escape_proof_is_not_qualified():
    policy, relation, resource, binding, realization = _chain()
    bad_cert = ae.certify_adaptive_escape(
        topology=_MESH2, policy=policy, relation=relation,
        vc_resource=resource, binding=binding)
    assert bad_cert.verdict == "PASS"
    tampered = dataclasses.replace(bad_cert, verdict="FAIL")
    qualification = ae.qualify_min_adapt(
        topology=_MESH2, policy=policy, relation=relation,
        vc_resource=resource, binding=binding,
        realization_hash=realization.routing_realization_hash,
        escape_certificate=tampered)
    assert qualification.verdict == "NOT_QUALIFIED"

def test_single_vc_universe_cannot_bind_two_roles():
    policy = rrm.min_adapt_mesh_policy()
    resource = VCResourceArtifact(
        vc_count=1, vc_ids=(0,),
        traffic_class_to_vcs=(("default", (0,)),),
        allowed_transitions=((0, 0),))
    binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash,
        vc_resource_hash=resource.artifact_hash,
        role_to_vcs=(("adaptive", (0,)), ("escape", (0,))))
    with pytest.raises(Exception, match="both|disjoint|partition"):
        binding.validate_against(policy, resource)

def test_non_partitioned_escape_is_refused_by_selection():
    policy, relation, resource, binding, realization = _chain()
    assert binding.role_to_vcs == (("adaptive", (1, 2, 3)), ("escape", (0,)))
    with pytest.raises(RoutingRealizationError):
        from veritx_dse.model.routing_realization import (
            AdaptiveBackendSelection,
        )
        AdaptiveBackendSelection(
            routing_function="min_adapt_mesh",
            policy_hash=policy.policy_hash,
            realization_hash=realization.routing_realization_hash,
            escape_vcs=(0, 1), adaptive_vcs=(2, 3), num_vcs=4)

@pytest.mark.parametrize("algorithm", [
    "limited_adapt_mesh",
    "planar_adapt_mesh",
    "romm_mesh",
    "valiant_mesh",
    "valiant_torus",
    "chaos_mesh",
    "chaos_torus",
    "adaptive_xy_yx_mesh",
    "adaptive_xy_yx_gec",
    "ugal_flatfly",
    "ugal_dragonflynew",
    "hybrid_gec",
    "dor_gec",
])
def test_backend_only_algorithms_are_refused(algorithm):
    with pytest.raises(Exception, match="UNSUPPORTED"):
        rrm.refuse_backend_only_algorithm(algorithm)

def test_limited_adapt_names_its_upstream_breakage():
    with pytest.raises(Exception, match="broken upstream"):
        rrm.refuse_backend_only_algorithm("limited_adapt_mesh")

def test_min_adapt_algorithm_passes_refusal_gate():
    assert rrm.refuse_backend_only_algorithm("per_hop_min_adaptive") is None

def test_non_min_adapt_policy_refused_by_materializer():
    from veritx_dse.model.routing_policy import (  # noqa: E402
        CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
        RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
        RoutingResourceRoleKind, RuntimeObservation, SelectionLocus,
    )

    policy = RoutingPolicyDefinition(
        id="ugal_like", algorithm="ugal_flatfly", algorithm_version=1,
        path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=
            DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(
            RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(
            RoutingResourceRole(
                id="adaptive",
                kind=RoutingResourceRoleKind.ADAPTIVE),
            RoutingResourceRole(
                id="escape",
                kind=RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")))
    with pytest.raises(Exception, match="UNSUPPORTED"):
        rrm.materialize_routing_relation(_MESH2, policy)

def test_routing_function_stays_locked():
    from veritx_dse.model.compile_model import NocConfig  # noqa: E402

    fields = set(NocConfig.__dataclass_fields__)
    assert "routing_function" not in fields
    assert "vc_map" not in fields
    assert "turn_restrictions" not in fields

def test_deterministic_claim_refused_for_adaptive():
    with pytest.raises(ro.RouteObservationError, match="cannot certify"):
        ro.refuse_deterministic_claim_for_adaptive("per_hop_min_adaptive")

def test_deterministic_policies_pass_the_scope_gate():
    assert ro.refuse_deterministic_claim_for_adaptive("dimension_order") \
        is None

def test_adaptive_candidate_table_renders_for_inspection_only():
    policy, relation, resource, binding, realization = _chain()
    rows = ro.render_adaptive_candidate_table(relation)
    assert len(rows) == len(relation.decisions)
    multi = [row for row in rows if len(row[3]) > 1]
    assert multi, "adaptive contexts must offer candidate sets"
    assert ro.ADAPTIVE_OBSERVATION_SCOPE

def test_dor_and_adaptive_fidelities_are_distinct():
    assert MIN_ADAPT_FIDELITY == "ADAPTIVE_RUNTIME_SELECTION"
    assert "DETERMINISTIC" not in MIN_ADAPT_FIDELITY
