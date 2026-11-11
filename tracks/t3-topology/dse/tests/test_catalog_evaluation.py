"""Catalog campaigns freeze workload intent, execute real adapters, and select explicitly."""
from dataclasses import replace
import copy
import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from veritx_dse.core.paths import REPO
from veritx_dse.gateway.app import (
    GatewayConfig, create_app, resolve_astra_bin, resolve_booksim_bin,
)
from veritx_dse.product.catalog_evaluation import (
    CATALOG, catalog_for, candidate_for, compiled_facts, configuration_of,
    workload_fingerprint,
)
from veritx_dse.product.jobs import TERMINAL_STATES
from veritx_dse.workload.intent_lowering import lower_compile_workload
from test_topology_search import _base


def test_full_catalog_preserves_the_same_workload_and_inputs():
    base = _base()
    rows = catalog_for(base)
    assert len(rows) == 12 and {r['topology_id'] for r in rows} == {key for key, _ in CATALOG}
    for row in rows:
        candidate = candidate_for(base, row)
        assert candidate.request.workload == base.workload
        assert candidate.request.agents == base.agents
        assert candidate.request.compute == base.compute
        assert candidate.request.noc_controls == base.noc_controls
        assert candidate.request.physical == base.physical
        assert candidate.request.requirements == base.requirements
        assert lower_compile_workload(candidate.request).graph.workload_id() == lower_compile_workload(base).graph.workload_id()
        assert workload_fingerprint(candidate.request) == workload_fingerprint(base)
    assert len({candidate_for(base, row).candidate_id for row in rows}) == len(rows)


def test_every_catalog_family_reports_configuration_and_rtl_feasibility():
    """The pre-selection facts come from a topology-only compile, not a guess.

    A row must name the routing law it was compiled with and whether the one
    product RTL emitter can serve it. The VC-scheme refusal is exactly the
    catalogue's multi-VC families (GEC MECS/hybrid, SROTA class isolation).
    """
    base = _base()
    configuration = configuration_of(base)
    assert configuration['controls_id'].startswith('sha256:')
    seen = {}
    for row in catalog_for(base):
        if row['reason']:
            continue
        facts = compiled_facts(candidate_for(base, row).request)
        fabric, support = facts['fabric'], facts['rtl_support']
        assert fabric is not None, row['topology_id']
        assert fabric['router_count'] >= 2, row
        assert fabric['routing_class'], row
        assert support['vc_count'] == fabric['vc_count'], row
        seen[row['topology_id']] = support['code']
    assert seen['torus'] == 'SUPPORTED_CERTIFIED_2VC'
    assert seen['ring_native'] == 'SUPPORTED_CERTIFIED_2VC'
    assert seen['gec_mecs'] == 'UNSUPPORTED_VC_SCHEME'
    assert seen['gec_hybrid'] == 'UNSUPPORTED_VC_SCHEME'
    assert seen['srota'] == 'UNSUPPORTED_SHARED_WIRE'


def _client(tmp_path, *, astra=False):
    return TestClient(create_app(GatewayConfig(store_root=tmp_path / 'store',
        projects_root=tmp_path / 'projects', runs_root=tmp_path / 'runs',
        booksim_bin=resolve_booksim_bin(),
        astra_bin=resolve_astra_bin() if astra else None)),
        raise_server_exceptions=False)


def _project(client):
    return _project_doc(client, _base().to_dict())


def _project_doc(client, request_doc, name='disposable catalog test'):
    response = client.post('/api/v1/projects', json={'name': name})
    assert response.status_code == 200, response.text
    pid = response.json()['project']['project_id']
    saved = client.put(f'/api/v1/projects/{pid}/draft',
                       json={'request': request_doc})
    assert saved.status_code == 200, saved.text
    return pid, saved.json()


def _wait(client, job_id, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f'/api/v1/jobs/{job_id}').json()
        if job['state'] in TERMINAL_STATES:
            return job
        time.sleep(.1)
    pytest.fail(f'catalog job timed out: {job}')


def test_plan_is_full_and_stale_or_unknown_submissions_launch_nothing(tmp_path):
    with _client(tmp_path) as client:
        pid, draft = _project(client)
        plan = client.get(f'/api/v1/projects/{pid}/catalog-evaluation-plan')
        assert plan.status_code == 200, plan.text
        assert len(plan.json()['topologies']) == 12
        assert plan.json()['backends'] == ['BOOKSIM_STANDALONE', 'ASTRA2_EMBEDDED_BOOKSIM']
        assert client.post(f'/api/v1/projects/{pid}/catalog-evaluations', json={'expected_draft_design_hash': 'old'}).status_code == 409
        assert client.post(f'/api/v1/projects/{pid}/catalog-evaluations', json={'expected_draft_design_hash': draft['design_hash'], 'topology_ids': ['invented']}).status_code == 400
        assert client.get(f'/api/v1/projects/{pid}/jobs?kind=CATALOG_EVALUATION').json()['jobs'] == []
        assert client.get(f'/api/v1/projects/{pid}/draft').json()['request'] == draft['request']


def test_real_catalog_job_trace_download_and_explicit_selection(tmp_path):
    if not resolve_booksim_bin():
        pytest.skip('BookSim binary unavailable')
    with _client(tmp_path) as client:
        pid, draft = _project(client)
        before = client.get(f'/api/v1/projects/{pid}/draft').json()
        response = client.post(f'/api/v1/projects/{pid}/catalog-evaluations', json={
            'expected_draft_design_hash': draft['design_hash'], 'topology_ids': ['mesh', 'concentrated_mesh']})
        assert response.status_code == 202, response.text
        job = _wait(client, response.json()['job_id'])
        assert job['state'] == 'COMPLETED', job
        url = f"/api/v1/projects/{pid}/catalog-evaluations/{job['job_id']}"
        response = client.get(url)
        assert response.status_code == 200, response.text
        view = response.json()
        assert len(view['rows']) == 2
        assert client.get(f'/api/v1/projects/{pid}/draft').json() == before
        assert client.get(f'/api/v1/projects/{pid}').json()['revisions'] == []
        measured = [r for r in view['rows'] if r['selectable']]
        assert measured, view
        # VC count is a selection dimension, not a display-only detail.
        assert all(row.get('vc_count') is not None for row in measured), view
        # Configuration provenance and pre-selection RTL feasibility travel
        # with the row, so a reader can judge comparability and the emitter's
        # slice without opening another page.
        assert view['configuration']['controls_id'].startswith('sha256:'), view
        for row in view['rows']:
            if row.get('status') != 'EVALUATED':
                continue
            assert row['config']['matched'] is True, row
            assert row['config']['controls_id'] == view['configuration']['controls_id'], row
            assert row['fabric']['router_count'] >= 2, row
            assert row['fabric']['routing_class'], row
            assert row['rtl_support']['vc_count'] == row['vc_count'], row
            assert isinstance(row['rtl_support']['supported'], bool), row
        mesh = next(row for row in view['rows'] if row['topology_id'] == 'mesh')
        if mesh['vc_count'] == 1:
            assert mesh['rtl_support']['code'] == 'SUPPORTED_SINGLE_CLASS', mesh
        assert 'router_count' in mesh['rtl_support'], mesh
        for row in view['rows']:
            assert len(row['analyses']) == 2, row
            assert {a['question'] for a in row['analyses']} == {'NETWORK_COMPLETION', 'SYSTEM_MAKESPAN'}
            for analysis in row['analyses']:
                assert analysis['status'] == 'EVALUATED' or analysis.get('reason'), analysis
        traces = [a for a in view['artifacts'] if a['path'].endswith('workload.trace')]
        assert traces, view
        artifact = client.get(url + '/artifact', params={'path': traces[0]['path']})
        assert artifact.status_code == 200 and len(artifact.content.splitlines()) > 0
        # URL normalization can reject the traversal before the route handler
        # runs (422), while other clients reach the explicit path guard (400).
        assert client.get(url + '/artifact', params={'path': '../input.json'}).status_code in (400, 422)
        selected = measured[0]
        body = {'expected_draft_design_hash': before['design_hash'], 'acknowledge_incomplete_backends': selected['requires_backend_ack']}
        adopted = client.post(url + f"/candidates/{selected['candidate_id']}/select", json=body)
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()['request']['workload'] == before['request']['workload']
        assert adopted.json()['request']['agents'] == before['request']['agents']
        plan = client.get(f'/api/v1/projects/{pid}/catalog-evaluation-plan').json()
        assert plan['selection']['candidate_id'] == selected['candidate_id']
        # The manifest is sealed by the job's completion record, not trusted
        # as mutable JSON bearing a successful-looking status.
        directory = client.app.state.product.store.project_dir(pid) / 'job-work' / job['job_id']
        document = json.loads((directory / 'catalog.json').read_text())
        document['rows'][0]['objective_values']['completion_cycles'] = 0
        (directory / 'catalog.json').write_text(json.dumps(document))
        assert client.get(url).status_code in (400, 422)


def _multiclass_request():
    return json.loads(
        (REPO / 'tracks/t3-topology/examples/'
         'qwen3_moe_tp2_ep4_16tiles-v4.json').read_text())


def _multiclass_request_64():
    base = _multiclass_request()
    scaled = json.loads(
        (REPO / 'tracks/t3-topology/examples/'
         'moe_tp4_ep4_64tiles-v3.json').read_text())
    base = copy.deepcopy(base)
    base['workload'] = copy.deepcopy(scaled['workload'])
    base['requirements'] = copy.deepcopy(scaled['requirements'])
    base['agents'] = [{
        'kind': 'compute_tile', 'count': 64, 'data_width': 256,
        'addr_width': 64, 'protocol': 'AXI',
        'clock_domain': None, 'power_domain': None,
    }]
    for key in ('design_hash', 'guardrail_hash'):
        base.pop(key, None)
    return base


def _assert_multiclass_catalog_rows(tmp_path, request_doc, topology_ids):
    if not resolve_booksim_bin() or not resolve_astra_bin():
        pytest.skip('BookSim/ASTRA binaries unavailable')
    with _client(tmp_path, astra=True) as client:
        pid, draft = _project_doc(client, request_doc,
                                  name='multi-class catalog test')
        response = client.post(
            f'/api/v1/projects/{pid}/catalog-evaluations',
            json={'expected_draft_design_hash': draft['design_hash'],
                  'topology_ids': topology_ids})
        assert response.status_code == 202, response.text
        job = _wait(client, response.json()['job_id'], timeout=300)
        assert job['state'] == 'COMPLETED', job
        view = client.get(
            f"/api/v1/projects/{pid}/catalog-evaluations/{job['job_id']}"
        ).json()
        assert {row['topology_id'] for row in view['rows']} == set(topology_ids)
        for row in view['rows']:
            assert row['status'] == 'EVALUATED', (row['topology_id'],
                                                  row.get('reason'))
            assert len(row['analyses']) == 2, row
            for analysis in row['analyses']:
                if analysis['status'] == 'EVALUATED':
                    continue
                # A dirty ASTRA producer is a DIAGNOSTIC tree state, not a
                # multi-class capability result. The catalog must keep the
                # exact refusal visible and require backend acknowledgement;
                # it must not pretend the ASTRA row completed.
                reason = (analysis.get('reason') or '').lower()
                if analysis.get('backend_id') == 'ASTRA2_EMBEDDED_BOOKSIM' \
                        and ('dirty' in reason or 'producer' in reason):
                    continue
                raise AssertionError((row['topology_id'], analysis))
        return view


def test_multiclass_catalog_evaluates_every_seatable_family_on_both_backends(
        tmp_path):
    """The catalog's own job, on both real backends, preserves every class.

    Nine families can seat the 22 attached agents. The native 64-terminal
    trees/fly are covered by the exact-64 inventory test below.
    """
    view = _assert_multiclass_catalog_rows(
        tmp_path, _multiclass_request(),
        ['mesh', 'concentrated_mesh', 'torus', 'fattree', 'flatfly',
         'srota', 'gec_mecs', 'gec_hybrid', 'ring_native'])
    assert all(row['selectable'] for row in view['rows']), view


def test_multiclass_catalog_evaluates_the_three_64_terminal_fabrics(
        tmp_path):
    view = _assert_multiclass_catalog_rows(
        tmp_path, _multiclass_request_64(),
        ['qtree_native', 'tree4_native', 'fly_native'])
    assert all(row['selectable'] for row in view['rows']), view


def test_job_listing_without_kind_returns_every_kind(tmp_path):
    with _client(tmp_path) as client:
        pid, _ = _project(client)
        # A natural request without a filter must not be refused as invalid.
        plain = client.get(f'/api/v1/projects/{pid}/jobs')
        assert plain.status_code == 200, plain.text
        assert plain.json()['jobs'] == []
        assert client.get(f'/api/v1/projects/{pid}/jobs?kind=CATALOG_EVALUATION').json()['jobs'] == []
