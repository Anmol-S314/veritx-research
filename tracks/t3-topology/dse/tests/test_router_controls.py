"""Authored router controls must reach canonical artifacts and native bytes."""
from copy import deepcopy

import pytest

from tools.sweep_intent_knobs import baseline
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.evaluation_context import build_evaluation_context
from veritx_dse.backend.booksim_adapter import BookSimAdapter
from veritx_dse.backend.booksim_projection import prepare_booksim_input, parse_config_values
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.noc_controls import ROUTER_CONTROL_FIELDS


def compile_controls(**values):
    doc = deepcopy(baseline())
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['noc_controls'].update(values)
    result = FabricCompiler().compile(CompileRequestV4.from_dict(doc))
    assert result.status == 'COMPILED', result.error
    return result


def prepare_controls(**values):
    compiled = compile_controls(**values)
    context = build_evaluation_context(compiled)
    adapter = BookSimAdapter()
    _, physical = adapter._canonical_traffic(context, traffic_class=context.unified_traffic_class)
    parents = adapter._projection_parents(context, physical)
    return prepare_booksim_input(parents), parents


def test_legacy_absent_and_null_controls_preserve_identity():
    old = baseline()
    request = CompileRequestV4.from_dict(old)
    doc = request.to_dict()
    for name in ROUTER_CONTROL_FIELDS:
        doc['noc_controls'][name] = None
    assert CompileRequestV4.from_dict(doc).design_hash() == request.design_hash()


@pytest.mark.parametrize('field', ROUTER_CONTROL_FIELDS)
def test_authored_controls_change_identity_and_reach_behavior(field):
    c = compile_controls(**{field: 3})
    assert getattr(c.bundle.router_behavior, field) == 3
    assert c.request.design_hash() != CompileRequestV4.from_dict(baseline()).design_hash()
    c.bundle.revalidate()


@pytest.mark.parametrize('field', ROUTER_CONTROL_FIELDS)
@pytest.mark.parametrize('value', [True, -1, 1.5, '4', 65])
def test_invalid_controls_refuse(field, value):
    doc = baseline()
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['noc_controls'][field] = value
    with pytest.raises(ValueError):
        CompileRequestV4.from_dict(doc)


def test_native_config_carries_authored_iq_controls():
    p, _ = prepare_controls(input_buffer_depth_flits_per_vc=4,
        credit_return_latency_cycles=2, allocator_iterations=3,
        route_compute_cycles=2, vc_alloc_cycles=1,
        switch_alloc_cycles=1, switch_traversal_cycles=2)
    values = parse_config_values(p.config_text)
    assert p.profile_id.endswith('_ROUTER_CONTROLS_V1')
    assert {k: values[k] for k in (
        'vc_buf_size', 'credit_delay', 'alloc_iters', 'routing_delay',
        'vc_alloc_delay', 'sw_alloc_delay', 'st_final_delay'
    )} == {'vc_buf_size': '4', 'credit_delay': '2', 'alloc_iters': '3',
           'routing_delay': '2', 'vc_alloc_delay': '1',
           'sw_alloc_delay': '1', 'st_final_delay': '2'}
    assert values['st_prepare_delay'] == '0'
    assert values['buf_size'] == '-1'
    assert values['vc_allocator'] == values['sw_allocator'] == 'islip'


@pytest.mark.parametrize('field', ('vc_alloc_cycles', 'switch_alloc_cycles'))
def test_multi_cycle_allocation_is_preflight_refusal_not_native_abort(field):
    from veritx_dse.backend.booksim_projection import SemanticLoss
    with pytest.raises(SemanticLoss, match='one-cycle VC/switch allocation'):
        prepare_controls(**{field: 2})


def test_round_robin_is_not_silently_replaced():
    from veritx_dse.backend.booksim_projection import SemanticLoss
    with pytest.raises(SemanticLoss, match='iSLIP only'):
        prepare_controls(input_buffer_depth_flits_per_vc=4, arbitration='round_robin')


def test_controlled_defaults_and_astra_machine_values_preserve_legacy_scope():
    from veritx_dse.backend.astra_machine import embedded_fabric_config
    old, _ = prepare_controls()
    controlled, _ = prepare_controls(input_buffer_depth_flits_per_vc=4)
    assert not old.profile_id.endswith('_ROUTER_CONTROLS_V1')
    assert parse_config_values(controlled.config_text)['routing_delay'] == '1'
    legacy_values = dict(embedded_fabric_config(old, embedded_classes=5).machine_values)
    new_values = dict(embedded_fabric_config(controlled, embedded_classes=5).machine_values)
    assert 'routing_delay' not in legacy_values
    assert new_values['routing_delay'] == '1'
    assert new_values['credit_delay'] == '1'
    assert new_values['vc_buf_size'] == '4'


@pytest.mark.parametrize('side_buffer', (True, False))
def test_srota_controls_use_design_intent_not_route_params(side_buffer):
    from veritx_dse.application.presets import build_typed_preset_request
    from veritx_dse.backend.booksim_projection import SemanticLoss
    doc = build_typed_preset_request('srota32').to_dict()
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['topology'].update(sidebuf_enable=side_buffer,
                          sidebuf_watermark=6 if side_buffer else None)
    doc['noc_controls']['input_buffer_depth_flits_per_vc'] = 4
    compiled = FabricCompiler().compile(CompileRequestV4.from_dict(doc))
    assert compiled.status == 'COMPILED', compiled.error
    context = build_evaluation_context(compiled)
    adapter = BookSimAdapter()
    _, physical = adapter._canonical_traffic(context, traffic_class=context.unified_traffic_class)
    parents = adapter._projection_parents(context, physical)
    if side_buffer:
        with pytest.raises(SemanticLoss, match='sidebuf_enable=false'):
            prepare_booksim_input(parents)
    else:
        assert prepare_booksim_input(parents).profile_id.endswith('_ROUTER_CONTROLS_V1')


def test_router_witnesses_are_unique_valid_and_do_not_mutate_baseline():
    from tools.sweep_intent_knobs import router_control_specs
    old = baseline()
    rows = router_control_specs()
    assert len(rows) == len({row['name'] for row in rows}) == 22
    for row in rows:
        CompileRequestV4.from_dict(row['request'])
    assert baseline() == old


def test_all_controlled_profiles_have_real_native_config_readers():
    from veritx_dse.backend import booksim_projection as projection
    from veritx_dse.backend.router_controls import BASE_PROFILE_IDS, controlled_profile
    from veritx_dse.core.paths import REPO
    for name in BASE_PROFILE_IDS:
        base = next(value for value in vars(projection).values()
                    if isinstance(value, projection.BookSimProfile) and value.profile_id == name)
        report = projection.source_audit_report(
            controlled_profile(base), source_root=REPO / 'third_party/booksim2/src')
        assert report['clean'], report['missing_from_source']
