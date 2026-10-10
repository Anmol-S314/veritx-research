"""Regressions found by the shipped-config/size execution sweep."""
from dataclasses import replace

import pytest

from veritx_dse.application.evaluation_context import build_evaluation_context
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.backend.adapter import BackendReadiness, SupportLevel
from veritx_dse.backend.booksim_adapter import BookSimAdapter
from veritx_dse.model.topology_intent import FlatFlyIntent
from veritx_dse.workload.intent_lowering import lower_compile_workload


@pytest.mark.parametrize('preset', ['qtree7', 'tree4_7'])
def test_seven_rank_preset_payload_is_lowerable(preset):
    request = build_typed_preset_request(preset)
    assert sum(a.count for a in request.agents) == 7
    assert request.workload.tp == 7
    assert lower_compile_workload(request).graph.workload_id()
    assert request.workload.collectives[0].payload_bytes % 7 == 0


def test_plane_c_is_admitted_in_plan_after_its_own_subnet_binding():
    """Plane C used to be refused at PLAN time because two classes on
    different subnets looked like a shared-VC subset. The subnet-scoped
    binding (model/multi_plane_vc.py) removed that false refusal, so the
    plan now admits it; the live two-subnet conservation proof lives in
    tests/test_srota_plane_c.py."""
    request = build_typed_preset_request('srota32_plane_c')
    compiled = FabricCompiler().compile(request)
    assert compiled.status == 'COMPILED', compiled.error
    context = build_evaluation_context(compiled)
    assessment = BookSimAdapter().assess(context, EvaluationQuestion.NETWORK_COMPLETION)
    assert assessment.support == SupportLevel.SUPPORTED
    assert compiled.multi_plane_vc is not None


@pytest.mark.parametrize('dimensions', [5, 6])
def test_flatfly_native_dimension_limit_is_a_preflight_refusal(dimensions):
    request = replace(build_typed_preset_request('flatfly16'),
                      topology=FlatFlyIntent(2, dimensions, 1))
    compiled = FabricCompiler().compile(request)
    assert compiled.status == 'COMPILED', compiled.error
    assessment = BookSimAdapter().assess(build_evaluation_context(compiled),
                                        EvaluationQuestion.NETWORK_COMPLETION)
    assert assessment.support == SupportLevel.UNSUPPORTED
    assert assessment.readiness == BackendReadiness.BLOCKED
    assert 'n <= 4' in assessment.reason
