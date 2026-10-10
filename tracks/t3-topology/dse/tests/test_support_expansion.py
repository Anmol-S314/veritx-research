"""Support expansion keeps qualified execution separate from prototypes."""
from copy import deepcopy

import pytest

from tools.sweep_intent_knobs import baseline, run, valid_expansion_specs
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.evaluation_context import build_evaluation_context
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.backend.booksim_adapter import BookSimAdapter
from veritx_dse.backend.booksim_projection import (
    prepare_booksim_input, parse_config_values,
)
from veritx_dse.backend.booksim_execution import (
    BookSimExecutionError, validate_mesh_class_vc_observations,
    execute_prepared_booksim,
)
from veritx_dse.backend.astra_machine import embedded_fabric_config, AstraMachineError
from veritx_dse.core.constants import PLANE_C_MAX_VC
from veritx_dse.model.compile_request_v4 import CompileRequestV4


def request_doc(two_classes=False, cycles=1):
    doc = baseline()
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['dependencies'] = [
        {'source': f'a{i}', 'target': f'b{i}', 'kind': 'blocking'}
        for i in range(cycles)
    ] + [
        {'source': f'b{i}', 'target': f'a{i}', 'kind': 'blocking'}
        for i in range(cycles)
    ]
    if two_classes:
        first = doc['workload']['collectives'][0]
        first['traffic_class'] = 'a0'
        second = deepcopy(first)
        second['traffic_class'] = 'b0'
        doc['workload']['collectives'].append(second)
    return doc


def prepared(two_classes=False, cycles=1):
    compiled = FabricCompiler().compile(
        CompileRequestV4.from_dict(request_doc(two_classes, cycles)))
    assert compiled.status == 'COMPILED', compiled.error
    context = build_evaluation_context(compiled)
    adapter = BookSimAdapter()
    _, physical = adapter._canonical_traffic(
        context, traffic_class=context.unified_traffic_class)
    return prepare_booksim_input(adapter._projection_parents(context, physical)), compiled


@pytest.mark.parametrize('cycles', range(1, 8))
def test_single_class_subset_preserves_compiled_vc_count_and_exact_range(cycles, monkeypatch):
    p, c = prepared(cycles=cycles)
    assert c.bundle.vc_assignment.vc_count == cycles + 1
    values = parse_config_values(p.config_text)
    assert values['mesh_class_vc_begin'] == values['mesh_class_vc_end'] == '{0}'
    assert p.trace_class_map == ('tp_collective',)
    from veritx_dse.backend import astra_machine
    fields = astra_machine.declared_runtime_config_fields()
    required = {'mesh_class_vc_begin', 'mesh_class_vc_end'}
    if not required <= fields:
        with pytest.raises(AstraMachineError, match='parser declares no field'):
            embedded_fabric_config(p, embedded_classes=2)
    # Future parser ABI renderer unit test; not a native execution claim.
    monkeypatch.setattr(astra_machine, 'declared_runtime_config_fields',
                        lambda: fields | required)
    embedded = embedded_fabric_config(p, embedded_classes=2)
    v = parse_config_values(embedded.text)
    assert v['mesh_class_vc_begin'] == v['mesh_class_vc_end'] == '{0,0}'


def test_two_classes_keep_distinct_vcs_and_embedded_kind_abi_refuses():
    p, _ = prepared(two_classes=True)
    values = parse_config_values(p.config_text)
    assert p.trace_class_map == ('a0', 'b0')
    assert values['mesh_class_vc_begin'] == values['mesh_class_vc_end'] == '{1,0}'
    with pytest.raises(AstraMachineError, match='traffic-class ABI extension'):
        embedded_fabric_config(p, embedded_classes=2)
    text = ('VeritX: mesh route class = 0, vc = 1\n'
            'VeritX: mesh route class = 1, vc = 0')
    assert validate_mesh_class_vc_observations(
        p.config_text, text, expected_classes={0, 1}
    ) == {'0': {'1': 1}, '1': {'0': 1}}


@pytest.mark.parametrize('text', [
    '', 'VeritX: mesh route class = 0, vc = 0',
    'VeritX: mesh route class = 2, vc = 1',
    'VeritX: mesh route class = 0, vc = -1',
    'VeritX: mesh route class = 0, vc = 1',
])
def test_missing_foreign_or_out_of_range_observations_refuse(text):
    p, _ = prepared(two_classes=True)
    with pytest.raises(BookSimExecutionError):
        validate_mesh_class_vc_observations(p.config_text, text, expected_classes={0, 1})


def test_prototype_cannot_advertise_ready_or_execute_by_default(tmp_path):
    p, c = prepared(two_classes=True)
    context = build_evaluation_context(c)
    assessment = BookSimAdapter().assess(context, EvaluationQuestion.NETWORK_COMPLETION)
    assert assessment.readiness.value == 'BLOCKED'
    # The refusal is a NAMED withdrawn-capability refusal, not a generic
    # "unregistered by construction" gap: it names the producer owner stage
    # and the exact missing obligation.
    assert 'WITHDRAWN capability' in assessment.reason
    assert 'third_party/booksim2' in assessment.reason
    assert 'mesh_class_vc_begin' in assessment.reason
    assert "VeritX: mesh route class" in assessment.reason
    with pytest.raises(BookSimExecutionError, match='diagnostic execution requires explicit opt-in'):
        execute_prepared_booksim(prepared=p, binary=tmp_path/'missing',
                                 run_dir=tmp_path/'run', timeout=1)


@pytest.mark.parametrize('d', (5, 6, 7, 8))
def test_default_envelope_compiles_real_higher_vc_hybrid(d):
    if PLANE_C_MAX_VC < 2*d:
        pytest.skip('explicit deployment VC override narrows the default envelope')
    doc = build_typed_preset_request('gec_hybrid16').to_dict()
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['topology'].update(grid_side_length=d+1, concentration=1,
        express_channel_groups_per_dimension=1, destinations_per_express_channel=d)
    doc['agents'][0]['count'] = (d+1)**2
    c = FabricCompiler().compile(CompileRequestV4.from_dict(doc))
    assert c.status == 'COMPILED', c.error
    assert c.bundle.vc_assignment.vc_count == 2*d
    assert c.certificate is not None
    assessment = BookSimAdapter().assess(
        build_evaluation_context(c), EvaluationQuestion.NETWORK_COMPLETION)
    # No binary must become UNAVAILABLE/BLOCKED, not an artificial VC refusal.
    assert assessment.support.value == 'SUPPORTED', assessment.reason


def test_above_configured_vc_limit_still_refuses():
    c = FabricCompiler().compile(CompileRequestV4.from_dict(
        request_doc(cycles=PLANE_C_MAX_VC)))
    assert c.status != 'COMPILED'
    assert 'VC' in c.error


def test_valid_matrix_has_unique_parseable_fresh_identities():
    rows = valid_expansion_specs()
    assert len(rows) == len({r['name'] for r in rows}) == 216
    for row in rows:
        assert 'design_hash' not in row['request']
        assert 'guardrail_hash' not in row['request']
        CompileRequestV4.from_dict(row['request'])
        assert row['execute']


@pytest.mark.parametrize('n', (None, 1, 7))
def test_srota_native_capacity_is_square_grid_not_configured_dimension(n):
    from veritx_dse.model.family_registry import terminal_node_count
    values = {'k': '4', 'c': '2'}
    if n is not None:
        values['n'] = str(n)
    assert terminal_node_count('srota', values) == 32


def test_sparse_srota_prepared_machine_keeps_native_namespace():
    from veritx_dse.backend.astra_machine import fabric_node_count
    doc = build_typed_preset_request('srota32').to_dict()
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['agents'][0]['count'] = 16
    doc['workload']['tp'] = 8
    doc['noc_controls']['link_width'] = 64
    c = FabricCompiler().compile(CompileRequestV4.from_dict(doc))
    assert c.status == 'COMPILED', c.error
    context = build_evaluation_context(c)
    adapter = BookSimAdapter()
    _, physical = adapter._canonical_traffic(
        context, traffic_class=context.unified_traffic_class)
    p = prepare_booksim_input(adapter._projection_parents(context, physical))
    assert p.endpoint_count == 16
    assert 'n' not in parse_config_values(p.config_text)
    assert fabric_node_count(p) == 32


def test_existing_witness_output_is_not_overwritten(tmp_path):
    result = tmp_path/'result.json'
    result.write_text('historical evidence')
    with pytest.raises(FileExistsError, match='fresh witness directory'):
        run({'name': 'would-overwrite'}, tmp_path)
    assert result.read_text() == 'historical evidence'
