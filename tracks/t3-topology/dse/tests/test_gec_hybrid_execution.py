"""Hybrid compile -> ranked union certificate -> native live execution.

Runtime observations qualify route-compute choices/VC ranges, not allocator
fairness or a complete packet-path log. No escape-subnetwork claim is made.
"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import _typed_request
from veritx_dse.model.gec_hybrid_route import GecHybridRoute, GecHybridCandidateError
from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent

REPO = Path(__file__).resolve().parents[4]


def hybrid_request(k=4, c=1, o=1, d=3):
    return _typed_request(GecTopologyIntent(
        mode=GecMode.HYBRID, grid_side_length=k, concentration=c,
        express_channel_groups_per_dimension=o,
        destinations_per_express_channel=d),
        endpoints=k*k*c, tp=k*k*c, payload_bytes=k*k*c*128)


def _compile(**params):
    request = hybrid_request(**params)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    return compilation, request


@pytest.mark.parametrize("params", [{}, {"k": 3, "d": 2}, {"k": 5, "o": 2, "d": 2}])
def test_hybrid_certifies_the_complete_phase_tap_union(params):
    compilation, _ = _compile(**params)
    route = compilation.bundle.router_route
    assert isinstance(route, GecHybridRoute)
    va = compilation.bundle.vc_assignment
    assert va.vc_count == 2 * route.params.d
    assert va.allowed_transitions == route.allowed_transitions
    assert va.escape_vcs == ()
    deadlock = next(o for o in compilation.certificate.obligations if o.obligation == "DEADLOCK_FREE")
    assert deadlock.method == "gec-hybrid-ranked-union/v1"
    assert deadlock.evidence["rank_proof_id"]
    assert deadlock.evidence["router_route_hash"] == route.route_artifact_id()
    assert deadlock.evidence["scope"] == "STRUCTURAL_CANDIDATE_UNION_ONLY"


def test_pruned_adaptive_choice_is_not_a_legal_route():
    compilation, _ = _compile()
    route = compilation.bundle.router_route
    choices = dict(route.choices)
    choices[(0, 3)] = choices[(0, 3)][:1]
    broken = replace(route, choices=choices)
    with pytest.raises(GecHybridCandidateError, match="complete source candidate union"):
        broken.validate_against(compilation.bundle.topology)


def test_changed_vc_envelope_fails_deadlock_obligation():
    from veritx_dse.verification.certificate import _deadlock_free_shared
    compilation, _ = _compile()
    bundle = compilation.bundle
    va = replace(bundle.vc_assignment,
                 allowed_transitions=((0, 0),), artifact_hash="")
    result = _deadlock_free_shared(SimpleNamespace(
        router_route=bundle.router_route, topology=bundle.topology,
        vc_assignment=va))
    assert result.status == "FAIL"
    assert "phase/tap envelope" in result.evidence["failure_reason"]


def test_oversized_tap_envelope_refuses_at_vc_stage():
    from veritx_dse.core.constants import PLANE_C_MAX_VC
    taps = PLANE_C_MAX_VC // 2 + 1
    compilation = FabricCompiler().compile(hybrid_request(k=taps + 1, d=taps))
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "VC"
    assert f"{2 * taps} VCs" in compilation.error


def test_blocking_class_cycle_is_not_silently_mapped_to_shared_phase_vcs():
    from veritx_dse.model.compile_model import DependencyGraph, Dependency, DepKind
    request = replace(hybrid_request(), dependencies=DependencyGraph((
        Dependency("X", "Y", DepKind.BLOCKING),
        Dependency("Y", "X", DepKind.BLOCKING),
    )))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "VC"
    assert "dependency-cycle separation is not qualified" in compilation.error


def _prepared(**params):
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    compilation, request = _compile(**params)
    parents = _parents_from_bundle(compilation.bundle, request)
    return prepare_booksim_input(parents), parents


def test_hybrid_renders_native_config_and_binds_runtime_choices():
    from veritx_dse.backend.booksim_projection import parse_config_values
    prepared, _ = _prepared()
    values = parse_config_values(prepared.config_text)
    assert prepared.profile_id == "CERTIFIED_BOOKSIM_GEC_HYBRID_V1"
    assert prepared.lowerer_version == "HYBRIDGECPHASETAP/1"
    assert values["routing_function"] == "hybrid_gec"
    assert values["hybrid"] == "1" and values["mesh"] == "0"
    assert values["num_vcs"] == "6"
    assert values["hybrid_gec_observation_file"] == "hybrid.observations"
    assert prepared.expected_hybrid_candidates
    assert "network_file" not in values


def test_prepared_candidate_tampering_changes_identity_and_refuses():
    from veritx_dse.backend.booksim_projection import (
        assert_canonical_booksim_projection, BookSimProjectionError,
    )
    prepared, parents = _prepared()
    changed = replace(prepared, expected_hybrid_candidates=prepared.expected_hybrid_candidates[1:])
    assert changed.prepared_id() != prepared.prepared_id()
    with pytest.raises(BookSimProjectionError, match="tampered or transplanted"):
        assert_canonical_booksim_projection(changed, parents)


@pytest.mark.parametrize("params", [{}, {"k": 3, "c": 2, "d": 2}, {"k": 5, "o": 2, "d": 2}])
def test_hybrid_executes_live_and_observes_certified_runtime_choices(tmp_path, params):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("no built BookSim binary in tree")
    prepared, _ = _prepared(**params)
    record = execute_prepared_booksim(
        prepared=prepared, binary=binary, run_dir=tmp_path / "run", timeout=120)
    stats = record.evidence.stats
    assert stats["completion_cycles"] > 0
    assert stats["flits_injected"] == stats["flits_accepted"] == prepared.expected_flits
    assert record.evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"
    observations = stats["hybrid_route_choices"]
    assert observations["scope"] == "RUNTIME_ROUTE_COMPUTE_CHOICES"
    assert observations["observations"] > 0 and observations["sha256"]
    assert observations["selected_modes"]["mecs"] > 0
    assert observations["selected_modes"]["mesh"] > 0
    assert observations["nonzero_credit_observations"] > 0


def test_shipped_preset_compiles_and_uses_the_native_hybrid_profile():
    from veritx_dse.application.presets import build_typed_preset_request
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    request = build_typed_preset_request("gec_hybrid16")
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    assert prepare_booksim_input(_parents_from_bundle(compilation.bundle, request)).profile_id == "CERTIFIED_BOOKSIM_GEC_HYBRID_V1"


def test_hybrid_candidate_semantics_stay_in_the_model_layer():
    import ast
    import inspect
    from veritx_dse.model import gec_hybrid_route
    for node in ast.walk(ast.parse(inspect.getsource(gec_hybrid_route))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("veritx_dse"):
            assert node.module.startswith(("veritx_dse.model.", "veritx_dse.core."))


def test_runtime_wrong_vc_tap_or_cost_refuses():
    from veritx_dse.backend.route_observation import compare_hybrid_runtime_choices, RouteObservationError
    prepared, _ = _prepared()
    expected = prepared.expected_hybrid_candidates
    # Router 0 -> node 3, MECS tie at zero credits, phase 0, tap/VC 2.
    correct = "0 3 0 0 0 3 0 0 mecs 3 2 2 2 0\n"
    assert compare_hybrid_runtime_choices(expected=expected, text=correct)["observations"] == 1
    for incorrect in (correct.replace("3 2 2 2 0", "3 1 2 2 0"),
                      correct.replace("3 2 2 2 0", "3 2 0 0 0"),
                      correct.replace("0 0 3 0 0", "0 0 3 1 0"),
                      correct.replace("0 0 3 0 0", "0 0 2 0 0")):
        with pytest.raises(RouteObservationError):
            compare_hybrid_runtime_choices(expected=expected, text=incorrect)
    with pytest.raises(RouteObservationError, match="empty"):
        compare_hybrid_runtime_choices(expected=expected, text="")
