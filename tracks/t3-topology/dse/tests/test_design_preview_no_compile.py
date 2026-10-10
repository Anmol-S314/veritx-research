"""Opening Design/Review must not compile routes or certify a draft."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.gateway.app import GatewayConfig, create_app


@pytest.mark.parametrize("presentation", ["edit", "review"])
def test_large_qtree_view_does_not_compile_or_change_draft(tmp_path, monkeypatch, presentation):
    def forbidden(*args, **kwargs):
        raise AssertionError("Design/Review implicitly compiled the draft")

    client = TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs")),
        raise_server_exceptions=False)
    pid = client.post("/api/v1/projects", json={"name": "large qtree"}).json()["project"]["project_id"]
    doc = build_typed_preset_request("srota32").to_dict()
    doc["topology"] = {"kind": "structured", "family": "qtree", "params": {"radix": 32, "tiers": 2}}
    response = client.put(f"/api/v1/projects/{pid}/draft", json={"request": doc})
    assert response.status_code == 200, response.text
    before = response.json()
    monkeypatch.setattr(FabricCompiler, "compile", forbidden)
    from veritx_dse.model import routing
    monkeypatch.setattr(routing, "derive_route", forbidden)
    response = client.get(f"/api/v1/projects/{pid}/design", params={"presentation": presentation})
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["compile_check_status"] == "NOT_RUN"
    assert view["derived_summaries"]
    counts = {entry["id"]: entry["value"] for entry in view["derived_summaries"]}
    assert counts["routers"] == 1057
    assert view["draft_identity"]["draft_design_hash"] == before["design_hash"]
    if presentation == "review":
        assert all(view["later_stage_claims"][key] is None for key in
                   ("certificate", "qualification", "measurements", "requirement_verdicts"))
    assert client.get(f"/api/v1/projects/{pid}/draft").json() == before
    assert client.get(f"/api/v1/projects/{pid}").json()["revisions"] == []
