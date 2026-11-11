"""Selected-fabric refinement changes real knobs, never workload or fabric family."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import zipfile

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.optimization.topology_search import make_parameter_proposal, ProposalRefused
from veritx_dse.product.rtl_export import run_rtl_preview
from test_topology_search import _base
from test_catalog_evaluation import _client, _project, _wait


def proposal(base, **changes):
    return {'base_design_hash': base.design_hash(), 'noc_controls': {'allocator_iterations': 2},
            'rationale': 'Explicit test parameter change, not a predicted score.', **changes}


def test_parameters_preserve_workload_inventory_and_family():
    base = _base()
    candidate = make_parameter_proposal(base, proposal(base, topology={'sidebuf_watermark': 8}))
    assert candidate.request.workload == base.workload
    assert candidate.request.agents == base.agents
    assert candidate.request.requirements == base.requirements
    assert candidate.request.compute == base.compute
    assert candidate.request.physical == base.physical
    assert candidate.request.topology.kind == base.topology.kind
    assert candidate.request.noc_controls.allocator_iterations == 2
    assert candidate.request.topology.sidebuf_watermark == 8
    assert candidate.request.design_hash() != base.design_hash()


@pytest.mark.parametrize('field', ['workload', 'agents', 'requirements', 'compute', 'physical', 'objective_values'])
def test_parameter_proposals_cannot_replace_locked_inputs(field):
    base = _base()
    with pytest.raises(ProposalRefused):
        make_parameter_proposal(base, proposal(base, **{field: {}}))


def test_family_change_and_locked_vc_count_are_refused():
    base = _base()
    with pytest.raises(ProposalRefused, match='family'):
        make_parameter_proposal(base, proposal(base, topology={'kind': 'mesh'}))
    with pytest.raises(ProposalRefused, match='locked'):
        make_parameter_proposal(base, proposal(base, noc_controls={'num_vcs': 4}))
    with pytest.raises(ProposalRefused, match='stale'):
        make_parameter_proposal(base, proposal(base, base_design_hash='old'))


def test_huge_shape_is_refused_before_materialization(monkeypatch):
    import veritx_dse.optimization.topology_search as search
    monkeypatch.setattr(search, 'materialize_topology', lambda *_: pytest.fail('Unbounded shape reached materialization'))
    base = _base()
    with pytest.raises(ProposalRefused, match='bounded'):
        make_parameter_proposal(base, proposal(base, topology={'side_length': 1000000}))


def test_actual_rtl_emitter_preview_is_explicitly_not_a_final_noc(tmp_path):
    base = replace(_base(), topology=MeshIntent(side_length=6, concentration=1))
    result = run_rtl_preview(base.to_dict(), tmp_path, {'repo_root': str(REPO)})
    assert result['scope'] == 'TOPOLOGY_ONLY_PREVIEW'
    assert result['final_implementation'] is False
    manifest = json.loads((tmp_path / 'rtl-preview.json').read_text())
    assert manifest['emitted_packet_width_bits'] == 64
    assert manifest['emitted_vcs'] == 2
    assert manifest['limitations']
    with zipfile.ZipFile(tmp_path / 'topology-rtl-preview.zip') as package:
        assert {'rtl/noc_pkg.sv', 'rtl/router.sv', 'rtl/noc_top.sv', 'rtl-preview.json'} <= set(package.namelist())
    assert manifest['lint']['status'] in ('PASS', 'NOT_RUN')
    if manifest['lint']['status'] == 'PASS':
        # A warning-bearing pass must never be presented as clean RTL.
        assert isinstance(manifest['lint']['warning_count'], int)
        assert manifest['lint']['clean'] is (manifest['lint']['warning_count'] == 0)


def test_shared_wire_is_not_silently_replaced_by_point_to_point_rtl(tmp_path):
    with pytest.raises(ValueError, match='shared.*wire'):
        run_rtl_preview(_base().to_dict(), tmp_path, {'repo_root': str(REPO)})
    assert not (tmp_path / 'topology-rtl-preview.zip').exists()


def test_parameter_job_uses_real_backends_and_preserves_catalog_choice(tmp_path, monkeypatch):
    from veritx_dse.gateway.app import resolve_booksim_bin
    if not resolve_booksim_bin():
        pytest.skip('BookSim unavailable')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            envelope = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert 'SELECTED fabric' in envelope['messages'][0]['content']
            context = json.loads(envelope['messages'][1]['content'])
            content = {'base_design_hash': context['base_design_hash'],
                       'noc_controls': {'allocator_iterations': 2},
                       'rationale': 'Controlled test model proposes one real router parameter change.'}
            body = json.dumps({'choices': [{'message': {'content': json.dumps(content)}}]}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    monkeypatch.setenv('VERITX_AI_BASE_URL', f'http://127.0.0.1:{server.server_port}/v1')
    monkeypatch.setenv('VERITX_AI_MODEL', 'controlled-parameter-test')
    monkeypatch.setenv('VERITX_AI_CONFIG', str(tmp_path / 'no-user-model-config.json'))
    monkeypatch.delenv('VERITX_AI_API_KEY', raising=False)
    try:
        with _client(tmp_path) as client:
            pid, draft = _project(client)
            pin = {'expected_draft_design_hash': draft['design_hash']}
            # AI parameter refinement is not offered before measured selection.
            assert client.post(f'/api/v1/projects/{pid}/ai-parameter-search', json=pin).status_code != 202
            submitted = client.post(f'/api/v1/projects/{pid}/catalog-evaluations', json={**pin, 'topology_ids': ['mesh']})
            assert submitted.status_code == 202, submitted.text
            catalog = _wait(client, submitted.json()['job_id'])
            assert catalog['state'] == 'COMPLETED', catalog
            url = f"/api/v1/projects/{pid}/catalog-evaluations/{catalog['job_id']}"
            view = client.get(url).json(); row = view['rows'][0]
            assert row['selectable'], row
            chosen = client.post(url + f"/candidates/{row['candidate_id']}/select", json={**pin, 'acknowledge_incomplete_backends': row['requires_backend_ack']})
            assert chosen.status_code == 200, chosen.text
            baseline = chosen.json()
            submitted = client.post(f'/api/v1/projects/{pid}/ai-parameter-search', json={'expected_draft_design_hash': baseline['design_hash']})
            assert submitted.status_code == 202, submitted.text
            job = _wait(client, submitted.json()['job_id'])
            assert job['kind'] == 'PARAMETER_SEARCH' and job['state'] == 'COMPLETED', job
            result = client.get(f"/api/v1/projects/{pid}/ai-topology-search/{job['job_id']}")
            assert result.status_code == 200, result.text
            attempts = result.json()['attempts']
            candidate = next((a for a in attempts if a['adoptable']), None)
            assert candidate, attempts
            assert client.get(f'/api/v1/projects/{pid}/draft').json()['design_hash'] == baseline['design_hash']
            adopted = client.post(f"/api/v1/projects/{pid}/ai-topology-search/{job['job_id']}/candidates/{candidate['candidate_id']}/adopt", json={'expected_draft_design_hash': baseline['design_hash']})
            assert adopted.status_code == 200, adopted.text
            updated = adopted.json()['request']
            assert updated['workload'] == baseline['request']['workload']
            assert updated['agents'] == baseline['request']['agents']
            assert updated['topology'] == baseline['request']['topology']
            assert updated['noc_controls']['allocator_iterations'] == 2
            assert client.get(f'/api/v1/projects/{pid}/catalog-evaluation-plan').json()['selection']['candidate_id'] == row['candidate_id']
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
