"""V5 root authoring and explicit diagnostic adapter: no V4/native substitution."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from veritx_dse.application.design_view_v2 import build_design_view_v2, V5_DECLARATIONS
from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.application.data_movement import execute_data_movement
from veritx_dse.application.abstract_experiment import LIMITS
from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.product.service import canonical_request_doc
from test_v5_product_boundary import service
from test_v5_design_binding import _request
from test_data_movement_execution import experiment


def test_full_root_review_extensions_and_hash_freshness():
    request = _request(records=True)
    parent = canonical_request_doc(request)
    changed = replace(request, access_policy=None)
    root = canonical_request_doc(changed)
    view = build_design_view_v2(root, project_id='p', presentation='review',
        draft_design_hash='sha256:' + changed.design_hash(), parent_doc=parent,
        review_snapshot_hash='sha256:' + request.design_hash())
    assert view['readiness'] == 'VALIDATED_DECLARATION'
    assert view['review_freshness'] == 'STALE'
    assert view['draft_identity']['draft_design_hash'] != 'sha256:' + changed.base_v4.design_hash()
    assert view['scientific_diff'] == [{'field': 'CompileRequestV5.access_policy',
        'before': parent['access_policy'], 'after': None, 'kind': 'changed'}]
    assert view['later_stage_claims']['qualification'] is None
    assert view['compile_check_status'] == 'NOT_RUN'
    entries = [e for s in view['sections'] for e in s['entries']]
    assert set('CompileRequestV5.' + f for f in V5_DECLARATIONS) <= {e['field'] for e in entries}
    assert all(e['ownership']['canonical_field'].startswith('base_v4.') for e in entries if not e['field'].startswith('CompileRequestV5.'))
    completeness = view['completeness']
    assert set(completeness['active_scientific_fields']) - set(completeness['represented_fields']) == set(completeness['unrepresented_active_fields'])


def test_nested_save_reload_and_stale_review_preserve_every_extension(tmp_path):
    svc, pid, req = service(tmp_path)
    before = svc.draft_view(pid)
    doc = deepcopy(before['request'])
    doc['base_v4'].pop('design_hash', None)
    doc['base_v4'].pop('guardrail_hash', None)
    doc['base_v4']['agents'][0]['data_width'] = 128
    saved = svc.put_draft(pid, doc)
    assert saved['design_hash'] != before['design_hash']
    for field in V5_DECLARATIONS:
        assert saved['request'].get(field) == before['request'].get(field)
    assert saved['request']['base_v4']['agents'][0]['data_width'] == 128
    assert svc.design_view_v2(pid, presentation='review', review_snapshot_hash=before['design_hash'])['review_freshness'] == 'STALE'
    with pytest.raises(ControlPlaneError) as caught:
        svc.compile_draft(pid, before['design_hash'])
    assert caught.value.code == ErrorCode.STALE_REVIEW


@pytest.fixture
def api_experiment(tmp_path):
    with TestClient(create_app(GatewayConfig(store_root=tmp_path/'store',
        projects_root=tmp_path/'projects', runs_root=tmp_path/'runs')), raise_server_exceptions=False) as client:
        svc = client.app.state.product
        pid = svc.store.create_project(name='V5', draft_doc={}, workload_id='fixture', source='test')['project_id']
        c, w, p = experiment()
        svc.put_draft(pid, c.request.to_dict())
        revision = svc.compile_draft(pid)
        url = f"/api/v1/projects/{pid}/revisions/{revision['revision_id']}/abstract-experiments"
        yield client, svc, pid, revision, url, c, {'profile': 'ABSTRACT_DATA_MOVEMENT_V1', 'workload': w.to_dict(), 'placement': p.to_dict()}


def test_explicit_api_conserved_success_replay_and_no_generic_promotion(api_experiment):
    client, svc, pid, rev, url, c, doc = api_experiment
    before = svc.store.load_project(pid)
    result = client.post(url, json=doc)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result['status'] == 'DIAGNOSTIC_ABSTRACT' and result['qualification'] is False
    assert result['binding']['revision_id'] == rev['revision_id']
    assert result['binding']['design_hash'] == c.request.design_hash()
    assert result['limits'] == LIMITS
    summary = result['evidence']['summary']
    assert summary['parents_completed'] == len(doc['workload']['operations'])
    assert summary['payload_bytes'] == sum(o['payload_bytes'] for o in doc['workload']['operations'])
    assert summary['fifo_words_written'] == summary['fifo_words_read']
    assert result['evidence']['scope']['booksim_equivalent'] is False
    assert client.post(url, json=doc).json() == result
    assert svc.store.load_project(pid) == before  # not a job/run or active evidence promotion
    with pytest.raises(ControlPlaneError) as caught:
        svc.evaluation_plan(rev['revision_id'])
    assert caught.value.code == ErrorCode.UNSUPPORTED_SEMANTICS


@pytest.mark.parametrize('mutation', [
    'unknown', 'profile', 'missing', 'foreign_workload', 'foreign_placement',
    'unknown_workload', 'unknown_operation', 'bool_service', 'too_many_ops', 'too_many_routers',
    'too_many_bytes', 'bad_dependency', 'missing_clock',
])
def test_explicit_api_strict_counterexamples(api_experiment, mutation):
    client, svc, pid, rev, url, c, original = api_experiment
    doc = deepcopy(original)
    if mutation == 'unknown': doc['backend'] = 'booksim'
    elif mutation == 'profile': doc['profile'] = 'V4_SIMULATION'
    elif mutation == 'missing': doc.pop('placement')
    elif mutation == 'foreign_workload': doc['workload']['design_hash'] = c.request.base_v4.design_hash()
    elif mutation == 'foreign_placement': doc['placement']['resource_graph_id'] = '0'*64
    elif mutation == 'unknown_workload': doc['workload']['path'] = '/etc/passwd'
    elif mutation == 'unknown_operation': doc['workload']['operations'][0]['code'] = 'print(1)'
    elif mutation == 'bool_service': doc['workload']['operations'][0]['service_cycles'] = True
    elif mutation == 'too_many_ops': doc['workload']['operations'] *= 33
    elif mutation == 'too_many_routers': doc['placement']['routers'] *= 17
    elif mutation == 'too_many_bytes': doc['workload']['operations'][0]['payload_bytes'] = 65537
    elif mutation == 'bad_dependency': doc['workload']['operations'][0]['deps'] = ['future']
    elif mutation == 'missing_clock': doc['workload']['network_clock'] = 'undeclared'
    response = client.post(url, json=doc)
    assert response.status_code in (400, 409, 422), response.text
    assert response.json()['code'] != 'INTERNAL_ERROR'
    assert 'evidence' not in response.json()


def test_api_wrong_project_revision_body_and_stored_root(api_experiment):
    client, svc, pid, rev, url, c, doc = api_experiment
    other = svc.store.create_project(name='other', draft_doc={}, workload_id='fixture', source='test')['project_id']
    assert client.post(url.replace(pid, other), json=doc).status_code == 404
    assert client.post(url.replace(rev['revision_id'], 'missing'), json=doc).status_code == 404
    for body in ('{"profile":1,"profile":2}', '{"profile":NaN}', 'x'*262145):
        response = client.post(url, content=body)
        assert response.status_code == 400, response.text
    stored = svc.store.load_revision(pid, rev['revision_id'])
    stored['design_hash'] = 'sha256:' + '0'*64
    path = svc.store.project_dir(pid)/'revisions'/f"{rev['revision_id']}.json"
    path.write_text(json.dumps(stored))
    response = client.post(url, json=doc)
    assert response.json()['code'] == 'EVIDENCE_INVALID'


def test_connected_tensor_reference_runs_through_immutable_revision_api(api_experiment):
    from veritx_dse.application.coupled_tensor import CoupledTensorEvidence
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.coupled_tensor import CoupledTensorWorkload
    from veritx_dse.application.tensor_demand import RemoteDemandPolicy
    from veritx_dse.model.physical_placement import PhysicalPlacement

    client, svc, pid, _rev, _url, _c, _doc = api_experiment
    source = json.loads((__import__('pathlib').Path(__file__).resolve().parents[1] / 'examples/coupled_tensor_v5.json').read_text())
    request = CompileRequestV5.from_dict(source['design'])
    compilation = FabricCompiler().compile(request)
    assert compilation.status == 'COMPILED'
    source['workload']['demand']['design_hash'] = request.design_hash()
    source['workload']['demand']['system_hash'] = compilation.compiled_system.system_hash()
    workload = CoupledTensorWorkload.from_dict(source['workload'])
    policy = RemoteDemandPolicy.from_dict(source['transport'])
    placement = PhysicalPlacement.from_dict(source['placement'])
    svc.put_draft(pid, request.to_dict())
    revision = svc.compile_draft(pid)
    url = f"/api/v1/projects/{pid}/revisions/{revision['revision_id']}/abstract-experiments"
    doc = {'profile': 'COUPLED_TENSOR_REFERENCE_V1', 'workload': workload.to_dict(),
           'transport': policy.to_dict(), 'placement': placement.to_dict()}
    result = client.post(url, json=doc)
    assert result.status_code == 200, result.text
    response = result.json()
    assert response['status'] == 'DIAGNOSTIC_REFERENCE'
    assert response['qualification'] is False
    assert response['support'] == {'reference_execution': 'SUPPORTED',
        'native_execution': 'UNSUPPORTED_NO_CONNECTED_NATIVE_DRIVER',
        'calibrated': False, 'qualified': False}
    assert response['evidence']['status'] == 'COMPLETE'
    project_before = svc.store.load_project(pid)
    assert client.post(url, json=doc).json() == response
    assert svc.store.load_project(pid) == project_before
    with pytest.raises(ControlPlaneError) as blocked:
        svc.evaluation_plan(revision['revision_id'])
    assert blocked.value.code == ErrorCode.UNSUPPORTED_SEMANTICS
    loaded = CoupledTensorEvidence.from_dict(response['evidence'], compilation=compilation,
        workload=workload, policy=policy, placement=placement)
    assert loaded.to_dict() == response['evidence']
    tampered = deepcopy(response['evidence'])
    tampered['summary']['payload_bytes'] += 1
    with pytest.raises(Exception, match='differs from parent-recomputed execution'):
        CoupledTensorEvidence.from_dict(tampered, compilation=compilation,
            workload=workload, policy=policy, placement=placement)
    native = client.post(url, json={**doc, 'profile': 'NATIVE_COUPLED_TENSOR_DIAGNOSTIC_V1'})
    assert native.status_code in (400, 409, 422)
    assert 'native coupled tensor execution is unavailable' in native.text


def test_non_v5_and_incomplete_revision_refuse(api_experiment):
    client, svc, pid, rev, url, c, doc = api_experiment
    svc.put_draft(pid, c.request.base_v4.to_dict())
    legacy = svc.compile_draft(pid)
    response = client.post(url.replace(rev['revision_id'], legacy['revision_id']), json=doc)
    assert response.json()['code'] == 'UNSUPPORTED_SEMANTICS'
    from veritx_dse.model.domain_intent import PowerDomain, PowerPolicy
    blocked = replace(c.request, power_domains=(PowerDomain('p', PowerPolicy.ALWAYS_ON),))
    svc.put_draft(pid, blocked.to_dict())
    declaration = svc.design_view_v2(pid)
    assert declaration['v5_scope']['compilation'] == 'NOT_RUN'
    refused = svc.compile_draft(pid)
    response = client.post(url.replace(rev['revision_id'], refused['revision_id']), json=doc)
    assert response.status_code in (400, 409, 422) and 'evidence' not in response.json()


@pytest.mark.parametrize('mutation', ['unknown', 'bool', 'enum', 'foreign_group'])
def test_invalid_declarations_do_not_replace_draft(tmp_path, mutation):
    svc, pid, _ = service(tmp_path)
    before = svc.draft_view(pid)
    doc = deepcopy(before['request'])
    if mutation == 'unknown': doc['invented'] = []
    elif mutation == 'bool': doc['clock_sources'][0]['frequency_hz'] = True
    elif mutation == 'enum': doc['clock_sources'][0]['kind'] = 'AUTO'
    elif mutation == 'foreign_group': doc['agent_intents'] = [{'agent_group_index': 100000}]
    with pytest.raises(ControlPlaneError): svc.put_draft(pid, doc)
    assert svc.draft_view(pid) == before


def test_base_preview_retains_root_identity_and_validates_untouched_extensions(tmp_path):
    svc, pid, req = service(tmp_path)
    view = svc.preview_design(pid, req.to_dict())
    assert view['design_hash'] == req.design_hash()
    assert view['design_hash'] != req.base_v4.design_hash()
    assert view['scope'] == 'BASE_ONLY' and view['compile_check_status'] == 'NOT_RUN'
    doc = req.to_dict()
    doc['clock_domains'][0]['source_id'] = 'foreign'
    with pytest.raises(ControlPlaneError): svc.preview_design(pid, doc)


def test_structure_only_neutral_root_is_not_reported_abstract_eligible():
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    req = CompileRequestV5(base_v4=_request().base_v4)
    view = build_design_view_v2(canonical_request_doc(req), project_id='p')
    assert view['v5_scope']['abstract_execution'] == 'STRUCTURE_ONLY_EXECUTION_PREREQUISITES_MISSING'
    assert view['v5_scope']['generic_evaluation'] == 'UNSUPPORTED'


def test_unsafe_browser_integer_refuses_authoring_not_strict_json_admission(tmp_path):
    from veritx_dse.core.errors import UnsupportedSemantics
    svc, pid, req = service(tmp_path)
    req = replace(req, migration_provenance={'external_integer': 2**53 + 1})
    saved = svc.put_draft(pid, req.to_dict())
    assert saved['request']['migration_provenance']['external_integer'] == 2**53 + 1
    with pytest.raises(UnsupportedSemantics): svc.design_view_v2(pid)


def test_incomplete_execution_cannot_publish_success_evidence(api_experiment, monkeypatch):
    from veritx_dse.core.errors import EvidenceInvalid
    import veritx_dse.application.abstract_experiment as adapter
    client, svc, pid, rev, url, c, doc = api_experiment
    def incomplete(*args):
        raise EvidenceInvalid('data-movement execution stalled before parent completion')
    monkeypatch.setattr(adapter, 'execute_data_movement', incomplete)
    response = client.post(url, json=doc)
    assert response.json()['code'] == 'EVIDENCE_INVALID'
    assert 'evidence' not in response.json()
