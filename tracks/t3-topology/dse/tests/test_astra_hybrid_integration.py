"""ASTRA links the canonical fork, including its GEC-hybrid parser surface."""
from dataclasses import replace
import pytest

from veritx_dse.application.evaluation_context import build_evaluation_context
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.backend.astra_adapter import Astra2Adapter
from veritx_dse.backend.astra_machine import declared_runtime_config_fields
from veritx_dse.core.paths import ASTRA_BS_BIN, REPO


def test_parser_surface_uses_linked_canonical_fork_not_nested_copy():
    fields = declared_runtime_config_fields()
    assert 'hybrid_gec_observation_file' in fields
    assert 'routing_dump_file' in fields


@pytest.mark.parametrize('endpoints,concentration', [(16, 1), (64, 4)])
def test_hybrid_machine_prepares_without_dropping_observation_field(endpoints, concentration):
    base = build_typed_preset_request('gec_hybrid16')
    request = replace(base, topology=replace(base.topology, concentration=concentration),
        agents=(replace(base.agents[0], count=endpoints),),
        workload=replace(base.workload, tp=endpoints))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == 'COMPILED', compilation.error
    adapter = Astra2Adapter(binary=ASTRA_BS_BIN, repo_root=REPO)
    context = build_evaluation_context(compilation)
    prepared = adapter.prepare(context, EvaluationQuestion.SYSTEM_MAKESPAN)
    # Machine text must retain GEC hybrid, six phase/tap VCs and observations.
    text = prepared.native_prepared.machine.network_config_text
    assert 'hybrid_gec_observation_file = hybrid.observations;' in text
    assert 'routing_function = hybrid_gec;' in text
    assert 'num_vcs = 6;' in text


@pytest.mark.skipif(not ASTRA_BS_BIN.is_file(), reason='ASTRA runtime not built')
def test_real_hybrid_runtime_answers_all_three_system_questions(tmp_path):
    from veritx_dse.application.federated_evaluator import evaluate_federated, AstraRunOptions
    from veritx_dse.backend.registry import default_backend_registry
    request = build_typed_preset_request('gec_hybrid16')
    compilation = FabricCompiler().compile(request)
    outcome = evaluate_federated(compilation,
        tuple(EvaluationQuestion[x] for x in ('SYSTEM_MAKESPAN', 'COMMUNICATION_EXPOSURE', 'PER_RANK_COMPLETION')),
        default_backend_registry(astra_bin=ASTRA_BS_BIN, repo_root=REPO),
        astra_options=AstraRunOptions(repo_root=REPO, timeout_s=60), run_dir=str(tmp_path))
    assert outcome.status == 'EVALUATED', [a.to_dict() for a in outcome.analyses]
    assert len(outcome.analyses) == 3
    assert all(a.status == 'EVALUATED' and a.native_evidence_id for a in outcome.analyses)
