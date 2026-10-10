"""Draft canvas reads current intent, never a local preset or compiled revision."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.gateway.app import GatewayConfig, create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(GatewayConfig(store_root=tmp_path / 'store', runs_root=tmp_path / 'runs')))


@pytest.mark.parametrize('preset', ['gec_hybrid16', 'srota32', 'explicit16', 'flatfly16'])
def test_canvas_preview_uses_canonical_geometry_without_compile_or_save(client, monkeypatch, preset):
    project = client.post('/api/v1/projects', json={'name': 'independent canvas'}).json()
    pid = project['project']['project_id']
    before = client.get(f'/api/v1/projects/{pid}/draft').json()
    def forbidden(*args, **kwargs):
        raise AssertionError('canvas preview must not compile')
    monkeypatch.setattr(FabricCompiler, 'compile', forbidden)
    doc = build_typed_preset_request(preset).to_dict()
    response = client.post(f'/api/v1/projects/{pid}/design-preview', json={'request': doc})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['compile_check_status'] == 'NOT_RUN'
    assert len(result['endpoints']) == sum(a['count'] for a in doc['agents'])
    routers = {r['router_id'] for r in result['topology']['routers']}
    assert all(e['router_id'] in routers for e in result['endpoints'])
    assert client.get(f'/api/v1/projects/{pid}/draft').json() == before
    assert client.get(f'/api/v1/projects/{pid}').json()['active_revision_id'] is None
    if preset in ('gec_hybrid16', 'srota32'):
        assert result['topology']['shared_links']


def test_canvas_distinguishes_routers_endpoint_inventory_and_native_seats(client):
    pid = client.post('/api/v1/projects', json={'name': '64 attached endpoints'}).json()['project']['project_id']
    doc = build_typed_preset_request('gec_hybrid16').to_dict()
    for key in ('design_hash', 'guardrail_hash'):
        doc.pop(key, None)
    doc['topology']['concentration'] = 4
    doc['agents'][0]['count'] = 57
    memory = deepcopy(doc['agents'][0]); memory.update(kind='hbm_controller', count=7)
    doc['agents'].append(memory)
    response = client.post(f'/api/v1/projects/{pid}/design-preview', json={'request': doc})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert len(preview['topology']['routers']) == 16
    assert len(preview['endpoints']) == 64
    assert sum(r['seat_capacity'] for r in preview['topology']['routers']) == 64
    assert sum(e['kind'] == 'hbm_controller' for e in preview['endpoints']) == 7


def test_invalid_preview_refuses_and_extra_fields_are_not_ignored(client):
    pid = client.post('/api/v1/projects', json={'name': 'bad canvas'}).json()['project']['project_id']
    doc = build_typed_preset_request('explicit16').to_dict()
    doc['topology']['graph']['nodes'] = 1
    response = client.post(f'/api/v1/projects/{pid}/design-preview', json={'request': doc})
    assert response.status_code == 400, response.text
    assert response.json()['code'] == 'INVALID_INTENT'
    response = client.post(f'/api/v1/projects/{pid}/design-preview', json={'request': {}, 'unexpected': True})
    assert response.status_code == 422
