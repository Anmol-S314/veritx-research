"""Pinned writes, safe bundle bytes, and live job-event contracts."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.core.run_bundle import RunBundleError, finalize_run_bundle, read_verified_file

@pytest.fixture
def client(tmp_path):
    config = GatewayConfig(store_root=tmp_path/'store', runs_root=tmp_path/'runs', projects_root=tmp_path/'projects', prewarm_capability_probe=False)
    with TestClient(create_app(config)) as value:
        yield value

def project(client):
    response = client.post('/api/v1/projects', json={'name': 'closure-test', 'workload_id': 'llama-dense-8b-64tiles'})
    assert response.status_code == 200, response.text
    return response.json()['project']['project_id']

def test_pinned_put_is_atomic_and_legacy_put_remains_compatible(client):
    pid = project(client)
    draft = client.get(f'/api/v1/projects/{pid}/draft').json()
    barrier = Barrier(2)
    def write(clock):
        request = copy.deepcopy(draft['request']); request['physical']['clock_freq_mhz'] = clock
        barrier.wait()
        return client.put(f'/api/v1/projects/{pid}/draft', json={'request': request, 'expected_draft_design_hash': draft['design_hash']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(write, [1100, 1200]))
    assert sum(r.status_code == 200 for r in responses) == 1
    assert 'STALE_REVIEW' in next(r.text for r in responses if r.status_code != 200)
    assert client.put(f'/api/v1/projects/{pid}/draft', json={'request': draft['request']}).status_code == 200

def test_candidate_adoption_refuses_unverifiable_legacy_study(client):
    pid = project(client)
    compiled = client.post(f'/api/v1/projects/{pid}/compile').json()
    svc = client.app.state.product
    svc.store.create_optimization(pid, {'optimization_id': 'opt-test', 'project_id': pid, 'base_revision_id': compiled['revision_id'], 'created_at': '2026-01-01', 'study': {'candidates': [{'candidate_id': 'c1', 'compilation_status': 'COMPILED', 'guided_patch': {'link_width': 128}}]}, 'candidate_runs': [], 'selected_candidate_id': 'c1'})
    draft = client.get(f'/api/v1/projects/{pid}/draft').json()
    endpoint = '/api/v1/optimizations/opt-test/candidates/c1/use'
    refused = client.post(endpoint, json={'expected_draft_design_hash': 'sha256:stale'})
    assert refused.status_code != 200 and 'STALE_REVIEW' in refused.text
    refused = client.post(endpoint, json={'expected_draft_design_hash': draft['design_hash']})
    assert refused.status_code != 200
    assert 'contract-v2 evaluation evidence' in refused.text
    history = client.get(f'/api/v1/projects/{pid}/draft-history').json()['snapshots']
    assert history == []
    assert client.get(f'/api/v1/projects/{pid}/draft').json()['design_hash'] == draft['design_hash']
    assert client.get(f'/api/v1/projects/{pid}').json()['active_revision_id'] == compiled['revision_id']

def sealed_run(client, tmp_path):
    pid = project(client); svc = client.app.state.product; rid = 'run-bytes'
    root = svc.store.run_bundle_dir(pid, rid); root.mkdir(parents=True)
    (root/'example.json').write_bytes(b'{"actual":true}\n')
    (root/'workload.trace').write_bytes(b'0 0 0 1 8\n2 1 0 0 4\n')
    summary = finalize_run_bundle(root)
    svc.store.create_run(pid, {'run_id': rid, 'project_id': pid, 'status': 'EVALUATED', 'bundle_id': 'sha256:'+summary['bundle_id']})
    return root, rid

def test_download_returns_exact_verified_bytes_and_rejects_unsealed_paths(client, tmp_path):
    root, rid = sealed_run(client, tmp_path)
    response = client.get(f'/api/v1/runs/{rid}/artifact', params={'path': 'example.json'})
    assert response.status_code == 200, response.text
    assert response.content == (root/'example.json').read_bytes()
    assert response.headers['x-content-sha256'] == hashlib.sha256(response.content).hexdigest()
    for path in ['../draft.json', '/etc/passwd', 'checksums.json', 'unsealed.json']:
        assert client.get(f'/api/v1/runs/{rid}/artifact', params={'path': path}).status_code != 200
    (root/'example.json').write_bytes(b'tampered')
    assert client.get(f'/api/v1/runs/{rid}/artifact', params={'path': 'example.json'}).status_code != 200

def test_verified_reader_bounds_bytes_and_refuses_parent_symlinks(tmp_path):
    root = tmp_path/'bundle'; root.mkdir(); (root/'a').mkdir(); (root/'a'/'data').write_bytes(b'12345')
    finalize_run_bundle(root)
    with pytest.raises(RunBundleError, match='cap'):
        read_verified_file(root, 'a/data', max_bytes=4)
    (root/'a').rename(tmp_path/'outside'); (root/'a').symlink_to(tmp_path/'outside', target_is_directory=True)
    with pytest.raises(RunBundleError):
        read_verified_file(root, 'a/data')

def test_job_events_are_real_state_records_and_close_at_terminal(client, monkeypatch):
    pid = project(client)
    product = client.app.state.product
    product.store.create_job(pid, {'job_id': 'job-events', 'project_id': pid, 'kind': 'EVALUATION', 'state': 'COMPLETED', 'revision_id': None, 'submitted_at': '2026-01-01', 'updated_at': '2026-01-01'})
    original_get_job = product.get_job
    reads = 0
    def counted_get_job(job_id):
        nonlocal reads
        reads += 1
        return original_get_job(job_id)
    monkeypatch.setattr(product, 'get_job', counted_get_job)
    response = client.get('/api/v1/jobs/job-events/events')
    assert reads == 1
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    line = next(line for line in response.text.splitlines() if line.startswith('data: '))
    assert json.loads(line[6:])['state'] == 'COMPLETED'
    assert client.get('/api/v1/jobs/missing/events').status_code == 404

def test_job_log_is_bounded_and_streams_from_the_job_work_directory(client):
    pid = project(client); svc = client.app.state.product
    job = {'job_id': 'job-log', 'project_id': pid, 'kind': 'EVALUATION',
           'state': 'COMPLETED', 'revision_id': None,
           'submitted_at': '2026-01-01', 'updated_at': '2026-01-01'}
    svc.store.create_job(pid, job)
    directory = svc.store.project_dir(pid) / 'job-work' / 'job-log'
    directory.mkdir(parents=True)
    (directory / 'worker.log').write_text('first line\nsecond line\n')
    first = client.get('/api/v1/jobs/job-log/log',
                       params={'max_bytes': 11}).json()
    assert first['available'] is True and first['text'] == 'first line\n'
    assert first['offset'] == 0 and first['next_offset'] == 11
    assert first['truncated'] is True and first['eof'] is False
    second = client.get('/api/v1/jobs/job-log/log',
                        params={'offset': 11}).json()
    assert second['text'] == 'second line\n'
    assert second['eof'] is True and second['truncated'] is False
    assert client.get('/api/v1/jobs/job-log/log',
                      params={'offset': -1}).status_code == 400
    assert client.get('/api/v1/jobs/job-log/log',
                      params={'max_bytes': 0}).status_code == 400
    assert client.get('/api/v1/jobs/missing/log').status_code == 404
    stream = client.get('/api/v1/jobs/job-log/log/events')
    assert stream.status_code == 200
    assert any(line == 'event: log' for line in stream.text.splitlines())
    assert any(line == 'event: end' for line in stream.text.splitlines())

def test_project_obligations_are_design_specific_not_capability_gaps(client):
    pid = project(client)
    response = client.get(f'/api/v1/projects/{pid}/obligations')
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['source'] == 'product.project_obligations.v1'
    assert payload['project_id'] == pid
    assert payload['revision_id'] is None
    ids = {row['obligation_id'] for row in payload['obligations']}
    assert {'OBL-TXN-01', 'OBL-CDC-01', 'OBL-RTL-01',
            'OBL-TGT-01', 'OBL-QUAL-01'} <= ids
    assert payload['counts']['OPEN'] >= 4
    assert payload['counts']['blocking_open'] >= 3
    cdc = next(row for row in payload['obligations']
               if row['obligation_id'] == 'OBL-CDC-01')
    assert cdc['state'] == 'OPEN' and cdc['blocking'] is True
    assert 'design obligations' in payload['note']
    assert client.get('/api/v1/projects/missing/obligations').status_code == 404

def test_comparison_gate_requires_configuration_window_and_definitions(client):
    svc = client.app.state.product

    def run(run_id, config='cfg-1', window=4096,
            metrics=None):
        return {
            'run_id': run_id, 'backend': 'BOOKSIM_STANDALONE',
            'qualification': 'QUALIFIED',
            'producer': {'config_hash': config,
                         'producer_identity': 'binary-1'},
            'evaluation': {
                'workload_id': 'wl-1',
                'metrics': metrics if metrics is not None else {
                    'completion_cycles': 100, 'delivered_packets': 10},
                'sample_window_cycles': window,
            },
        }

    same = svc._compare_compatibility(run('a'), run('b'))
    assert same['compatible'] is True
    assert same['metadata_complete'] is True
    assert same['backend_configuration_state'] == 'MATCH'
    assert same['measurement_window_state'] == 'MATCH'
    assert same['metric_definitions_complete'] is True
    assert same['metric_definition_issues'] == []

    config = svc._compare_compatibility(
        run('a'), run('b', config='cfg-2'))
    assert config['compatible'] is False
    assert config['backend_configuration_state'] == 'DIFFERENT'
    assert any('backend configuration' in reason
               for reason in config['reasons'])

    window = svc._compare_compatibility(
        run('a'), run('b', window=8192))
    assert window['compatible'] is False
    assert window['measurement_window_state'] == 'DIFFERENT'
    assert any('measurement window' in reason
               for reason in window['reasons'])

    unknown_metrics = {'completion_cycles': 100, 'invented_cycles': 7}
    unknown = svc._compare_compatibility(
        run('a', metrics=unknown_metrics),
        run('b', metrics=unknown_metrics))
    assert unknown['compatible'] is False
    assert unknown['metric_definitions_complete'] is False
    issue = unknown['metric_definition_issues'][0]
    assert issue['metric'] == 'invented_cycles'
    assert issue['issue'] == 'MISSING_DEFINITION'

def test_in_process_jobs_write_progress_to_their_worker_log(client):
    pid = project(client); svc = client.app.state.product
    def work(progress):
        progress('RUNNING')
        return 'COMPLETED', {'ok': True}
    submitted = svc.jobs.submit(pid, kind='EVALUATION', revision_id='rid', fn=work)
    for _ in range(200):
        current = svc.get_job(submitted['job_id'])
        if current['state'] == 'COMPLETED':
            break
        time.sleep(0.01)
    assert current['state'] == 'COMPLETED'
    log = client.get(f"/api/v1/jobs/{submitted['job_id']}/log").json()
    assert log['available'] is True
    assert 'state=PREPARING' in log['text']
    assert 'state=RUNNING' in log['text']
    assert 'state=COMPLETED' in log['text']
    assert log['eof'] is True
