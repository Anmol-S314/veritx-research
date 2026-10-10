"""Topology templates and unsaved edits preserve the rest of the design."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.model.topology_intent import topology_intent_from_dict, capability_family_label


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs")))


def test_catalog_covers_all_supported_families_with_real_templates(client):
    catalog = client.get("/api/v1/catalog/fabric-presets").json()["presets"]
    expected = {"mesh", "concentrated_mesh", "torus", "explicit", "flatfly",
                "fattree", "fat_tree", "dragonfly", "flattened_butterfly",
                "qtree", "tree4", "srota", "gec_mesh", "gec_express",
                "gec_multidrop", "gec_hybrid"}
    assert {entry["family"] for entry in catalog} == expected
    for entry in catalog:
        assert capability_family_label(topology_intent_from_dict(entry["topology"])) == entry["family"]


def test_preview_preserves_workload_agents_controls_and_dependencies(client):
    project = client.post("/api/v1/projects", json={"name": "topology-editor"}).json()
    pid = project["project"]["project_id"]
    before = client.get(f"/api/v1/projects/{pid}/draft").json()
    source = build_typed_preset_request("explicit16").to_dict()
    source["noc_controls"]["link_width"] = 128
    target = build_typed_preset_request("torus25").topology.to_dict()
    response = client.post(f"/api/v1/projects/{pid}/topology-preview", json={
        "request": source, "topology": target})
    assert response.status_code == 200, response.text
    result = response.json()["request"]
    assert result["topology"] == target
    for key in ("workload", "agents", "noc_controls", "dependencies", "physical", "requirements", "address_map"):
        assert result[key] == source[key]
    assert result["dependencies"] == []  # never silently add the torus policy
    assert client.get(f"/api/v1/projects/{pid}/draft").json() == before
    saved = client.put(f"/api/v1/projects/{pid}/draft", json={"request": result})
    assert saved.status_code == 200, saved.text
    assert saved.json()["request"]["topology"] == target


def test_legacy_preview_uses_canonical_migration_and_does_not_save(client):
    from veritx_dse.application.presets import build_versioned_preset_request
    project = client.post("/api/v1/projects", json={"name": "legacy-editor"}).json()
    pid = project["project"]["project_id"]
    request, _ = build_versioned_preset_request("mesh4")
    response = client.post(f"/api/v1/projects/{pid}/topology-preview", json={
        "request": request.to_dict(),
        "topology": build_typed_preset_request("flatfly16").topology.to_dict()})
    assert response.status_code == 200, response.text
    out = response.json()["request"]
    assert out["schema_version"] == 4
    assert out["topology"]["kind"] == "flatfly"
    assert out["agents"] == request.to_dict()["agents"]
    assert out["dependencies"] == request.to_dict()["dependencies"]


def test_save_review_compile_binds_the_typed_topology(client):
    project = client.post("/api/v1/projects", json={"name": "compile-editor"}).json()
    pid = project["project"]["project_id"]
    request = build_typed_preset_request("flatfly16").to_dict()
    request["noc_controls"]["link_width"] = 64
    saved = client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
    assert saved.status_code == 200, saved.text
    review = client.get(f"/api/v1/projects/{pid}/design?presentation=review").json()
    response = client.post(f"/api/v1/projects/{pid}/compile", json={
        "expected_draft_design_hash": review["draft_identity"]["draft_design_hash"]})
    assert response.status_code == 200, response.text
    revision = response.json()
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["certificate"]["overall"] == "PASS"
    assert revision["design_hash"] == saved.json()["design_hash"]


def test_invalid_topology_and_extra_request_fields_refuse(client):
    project = client.post("/api/v1/projects", json={"name": "invalid-editor"}).json()
    pid = project["project"]["project_id"]
    body = {"request": build_typed_preset_request("flatfly16").to_dict(),
            "topology": {"kind": "flatfly", "radix_per_dimension": 0}}
    response = client.post(f"/api/v1/projects/{pid}/topology-preview", json=body)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_INTENT"
    body["unexpected"] = True
    assert client.post(f"/api/v1/projects/{pid}/topology-preview", json=body).status_code == 422
