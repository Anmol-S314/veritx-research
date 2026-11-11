"""Read-only sweep source selection and gateway contract."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from veritx_dse.core.errors import InvalidInput
from veritx_dse.gateway import app as gateway_app
from veritx_dse.gateway.errors import NotFound
from veritx_dse.gateway.sweeps import latest_topology_sweep


def write_sweep(repo: Path, name: str, rows=None) -> Path:
    path = repo / 'tracks/t3-topology/runs/supported-sweep' / name / 'topology_sweep.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows if rows is not None else [
        {'topology': 'mesh', 'injection_rate': 0.05, 'latency_cycles': 20, 'status': 'ok'}
    ]))
    return path


def test_latest_source_digest_and_no_execution(tmp_path, monkeypatch):
    old = write_sweep(tmp_path, 'old')
    os.utime(old, (1, 1))
    new = write_sweep(tmp_path, 'new')
    monkeypatch.setattr(gateway_app, 'REPO', tmp_path)
    cfg = gateway_app.GatewayConfig(store_root=tmp_path / 'store', runs_root=tmp_path / 'runs', prewarm_capability_probe=False)
    with TestClient(gateway_app.create_app(cfg)) as client:
        response = client.get('/api/v1/analysis/topology-sweep')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    body = response.json()
    assert body['source_path'].endswith('new/topology_sweep.json')
    assert body['sha256'] == hashlib.sha256(new.read_bytes()).hexdigest()
    assert body['rows'][0]['latency_cycles'] == 20
    assert 'not selected project' in body['scope']


def test_absence_and_symlink_escape(tmp_path):
    with pytest.raises(NotFound):
        latest_topology_sweep(tmp_path)
    outside = tmp_path / 'outside.json'
    outside.write_text('[]')
    link = write_sweep(tmp_path, 'escape')
    link.unlink()
    link.symlink_to(outside)
    with pytest.raises(NotFound):
        latest_topology_sweep(tmp_path)


def test_malformed_latest_is_refused_not_silently_replaced(tmp_path):
    old = write_sweep(tmp_path, 'old')
    os.utime(old, (1, 1))
    write_sweep(tmp_path, 'new', [{'topology': 'mesh', 'injection_rate': True}])
    with pytest.raises(InvalidInput):
        latest_topology_sweep(tmp_path)


def test_nonstandard_nan_is_unavailable_not_a_numeric_measurement(tmp_path):
    path = write_sweep(tmp_path, 'nan')
    path.write_text('[{"topology":"mesh","injection_rate":0.1,"latency_cycles":NaN}]')
    assert latest_topology_sweep(tmp_path)['rows'][0]['latency_cycles'] is None
