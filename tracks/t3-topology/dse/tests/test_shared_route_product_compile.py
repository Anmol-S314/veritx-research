"""Product admission must handle every qualified route representation."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.fabric_evaluator import _admit_traffic_classes, VCAdmissionError
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.gateway.app import GatewayConfig, create_app


@pytest.mark.parametrize("preset", [
    "srota32", "srota32_islands", "srota32_rank", "srota32_plane_c",
    "gec_mecs16", "gec_hybrid16", "torus25", "flatfly16",
])
def test_product_compile_and_inspection_do_not_crash_on_route_shape(tmp_path, preset):
    client = TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs")),
        raise_server_exceptions=False)
    pid = client.post("/api/v1/projects", json={"name": preset}).json()["project"]["project_id"]
    source = build_typed_preset_request(preset).to_dict()
    response = client.put(f"/api/v1/projects/{pid}/draft", json={"request": source})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/projects/{pid}/compile", json={
        "expected_draft_design_hash": response.json()["design_hash"]})
    assert response.status_code == 200, response.text
    revision = response.json()
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["certificate"]["overall"] == "PASS"
    rid = revision["revision_id"]
    for path in (f"/projects/{pid}", f"/revisions/{rid}/compile-result",
                 f"/revisions/{rid}/preflight", f"/revisions/{rid}/evaluation-plan"):
        response = client.get("/api/v1" + path)
        assert response.status_code == 200, (path, response.text)
    assert client.get(f"/api/v1/projects/{pid}/draft").json()["request"]["topology"] == source["topology"]


def test_shared_route_admission_still_refuses_missing_or_unmaterialized_classes():
    bundle = FabricCompiler().compile(build_typed_preset_request("srota32")).bundle
    logical = SimpleNamespace(messages=(SimpleNamespace(message_id="m", traffic_class="unknown"),))
    with pytest.raises(VCAdmissionError, match="not declared"):
        _admit_traffic_classes(logical, bundle)
    cls = bundle.vc_assignment.traffic_class_to_vcs[0][0]
    logical = SimpleNamespace(messages=(SimpleNamespace(message_id="m", traffic_class=cls),))
    fake_class = "UNMATERIALIZED_ROUTE"
    corrupted_vcs = replace(bundle.vc_assignment, vc_to_routing_class=((0, fake_class),))
    corrupted_route = replace(bundle.resolved_route, routing_classes=(fake_class,), artifact_hash="")
    corrupted = SimpleNamespace(vc_assignment=corrupted_vcs,
        resolved_route=corrupted_route, router_route=bundle.router_route)
    with pytest.raises(VCAdmissionError, match="router route does not materialize"):
        _admit_traffic_classes(logical, corrupted)
