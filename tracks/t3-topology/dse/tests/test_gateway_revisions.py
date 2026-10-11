"""Live Studio revision continuity (R3.2/R3.4/R3.6/R3.11).

A compile produces an immutable revision; the Studio names the revision in
later stages instead of resubmitting raw engine JSON. Editing the design must
produce a different revision so an old Run can never be shown as current.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from test_p2_real_adapter import _base  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

@pytest.fixture()
def client(tmp_path):
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg), raise_server_exceptions=False)

def _compile(client, request):
    response = client.post("/compile", json={"request": request})
    assert response.status_code == 200, response.text
    return response.json()

def test_v3_compile_returns_views_and_an_immutable_revision(client):
    body = _compile(client, _base().to_dict())
    assert body["revision_id"]
    assert body["resolved_fabric_hash"]
    assert body["design_view"]["design_hash"] == \
        f"sha256:{body['design_hash']}"
    assert body["compilation_view"]["status"] == "COMPILED"
    assert body["compilation_view"]["resolved_fabric_hash"] == \
        f"sha256:{body['resolved_fabric_hash']}"
    assert body["compilation_view"]["certificate_overall"] == "PASS"
    assert body["compilation_view"]["obligations"]

def test_revision_is_reloadable_by_id_with_the_same_identity(client):
    body = _compile(client, _base().to_dict())
    rid = body["revision_id"]
    listed = client.get("/revisions").json()["revisions"]
    assert any(entry["revision_id"] == rid for entry in listed)
    loaded = client.get(f"/revisions/{rid}").json()
    assert loaded["revision_id"] == rid
    assert loaded["design_hash"] == body["design_hash"]
    assert loaded["resolved_fabric_hash"] == body["resolved_fabric_hash"]
    assert loaded["compilation_view"]["status"] == "COMPILED"

def test_editing_the_design_produces_a_different_revision(client):
    first = _compile(client, _base().to_dict())
    edited = _compile(client, _base(noc={"concentration": 2}).to_dict())
    assert first["revision_id"] != edited["revision_id"]
    assert first["design_hash"] != edited["design_hash"]
    assert first["resolved_fabric_hash"] != edited["resolved_fabric_hash"]
    old = client.get(f"/revisions/{first['revision_id']}").json()
    assert old["resolved_fabric_hash"] == first["resolved_fabric_hash"]

def test_hbm3e_stamp_is_an_immutable_draft_edit_and_compiles(client):
    import json
    from dataclasses import replace

    from veritx_dse.model.compile_request_v5 import CompileRequestV5

    example = Path(__file__).resolve().parents[1] / "examples/tensor_demand_v5.json"
    doc = json.loads(example.read_text())
    request = CompileRequestV5.from_dict(doc["design"])
    request = replace(request, base_v4=replace(
        request.base_v4, topology=replace(request.base_v4.topology,
                                           concentration=2)))
    created = client.post("/api/v1/projects", json={"name": "ip-stamp"})
    assert created.status_code == 200, created.text
    project_id = created.json()["project"]["project_id"]
    put = client.put(f"/api/v1/projects/{project_id}/draft",
                     json={"request": request.to_dict()})
    assert put.status_code == 200, put.text
    original_hash = put.json()["design_hash"]
    body = {
        "expected_draft_design_hash": original_hash,
        "template_id": "hbm3e-memory", "instance_id": "mem0",
        "address_base": 0xA000, "address_size": 16,
        "clock_domain": "network", "power_domain": "DEFAULT",
        "initiator_group_index": 0, "access_permission": "RW",
    }
    stamped = client.post(
        f"/api/v1/projects/{project_id}/draft/ip-templates/stamp", json=body)
    assert stamped.status_code == 200, stamped.text
    stamped_hash = stamped.json()["design_hash"]
    assert stamped_hash != original_hash
    loaded = client.get(f"/api/v1/projects/{project_id}/draft").json()
    assert loaded["design_hash"] == stamped_hash
    persisted = CompileRequestV5.from_dict(loaded["request"])
    assert persisted.base_v4.agents[-1].ip_instance_id == "mem0"
    assert persisted.design_hash() == stamped_hash.removeprefix("sha256:")
    stale = client.post(
        f"/api/v1/projects/{project_id}/draft/ip-templates/stamp", json=body)
    assert stale.status_code == 409
    compiled = client.post(
        f"/api/v1/projects/{project_id}/compile",
        json={"expected_draft_design_hash": stamped_hash})
    assert compiled.status_code == 200, compiled.text
    assert compiled.json()["compilation"]["status"] == "COMPILED"
    revision = client.get(
        f"/api/v1/revisions/{compiled.json()['revision_id']}")
    assert revision.status_code == 200
    saved = CompileRequestV5.from_dict(
        revision.json()["design"]["v5_intent"])
    assert saved.design_hash() == stamped_hash.removeprefix("sha256:")
    assert saved.base_v4.agents[-1].ip_instance_id == "mem0"


def test_unknown_revision_is_404(client):
    response = client.get("/revisions/deadbeef")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"

def test_compile_requires_a_preset_or_a_request(client):
    response = client.post("/compile", json={})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"
