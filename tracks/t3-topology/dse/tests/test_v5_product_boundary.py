"""Identity-preserving JSON product modelling; not Studio/backend qualification."""
from dataclasses import replace
import json
import time

import pytest
from fastapi.testclient import TestClient

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.data_movement import execute_data_movement, DataMovementEvidence
from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.model.compile_request_v5 import CompileRequestV5, AgentIntentV5
from veritx_dse.model.domain_intent import (
    AssertionMode, DeassertionMode, PowerDomain, PowerPolicy, ResetChannel,
)
from veritx_dse.model.ip_catalog import InterfaceRole
from veritx_dse.product.jobs import TERMINAL_STATES
from veritx_dse.product.service import ProductConfig, ProductService, canonical_request_doc, parse_request_doc
from veritx_dse.verification.certificate import VerificationCertificate
from test_v5_design_binding import _request
from test_data_movement_execution import experiment


def service(tmp_path):
    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    req = _request(records=True)
    pid = svc.store.create_project(name="V5 modelling", draft_doc={},
                                   workload_id="fixture", source="test")["project_id"]
    svc.put_draft(pid, req.to_dict())
    return svc, pid, req


@pytest.mark.parametrize("supplied", [True, False])
def test_strict_ingress_accepts_matching_or_absent_identity(supplied):
    req = _request(records=True)
    doc = req.to_dict() if supplied else canonical_request_doc(req)
    parsed = parse_request_doc(json.loads(json.dumps(doc)))
    assert isinstance(parsed, CompileRequestV5)
    assert parsed == req and parsed.design_hash() == req.design_hash()
    assert "design_hash" not in canonical_request_doc(parsed)


@pytest.mark.parametrize("change", [
    {"design_hash": "0" * 64}, {"guardrail_hash": "0" * 64},
    {"invented_extension": []}, {"clock_domains": "not a list"},
    {"compiler_semantics_version": 999},
])
def test_invalid_v5_is_typed_invalid_not_silently_canonicalized(change):
    with pytest.raises(ControlPlaneError) as caught:
        parse_request_doc({**_request().to_dict(), **change})
    assert caught.value.code == ErrorCode.INVALID_INTENT


def assert_revision(svc, pid, req, view):
    rev = svc.store.load_revision(pid, view["revision_id"])
    identity = "sha256:" + req.design_hash()
    compiled = FabricCompiler().compile(req)
    assert rev["request"] == canonical_request_doc(req)
    assert rev["design_hash"] == rev["design"]["design_hash"] == identity
    assert rev["design"]["schema_version"] == 5
    assert rev["design"]["v5_intent"] == req.to_dict()
    assert rev["compilation"]["status"] == "COMPILED"
    assert rev["compilation"]["design_hash"] == identity
    assert rev["compilation"]["request"] == req.to_dict()
    cert = VerificationCertificate.from_dict(rev["compilation"]["certificate"])
    assert cert.certificate_id() == rev["certificate"]["certificate_id"]
    assert cert.design_binding == compiled.certificate.design_binding
    assert rev["simulation"]["support"] == "UNSUPPORTED"
    assert rev["simulation"]["readiness"] == "BLOCKED"
    assert "ABSTRACT_DATA_MOVEMENT_V1" in rev["simulation"]["reason"]
    rid = rev["revision_id"]
    assert svc.get_revision_topology(rid)["design_hash"] == identity
    nodes = {row["artifact"]: row for row in svc.get_revision_artifact_chain(rid)["nodes"]}
    assert nodes["v5_design"]["hash"] == identity
    assert nodes["design"]["hash"] == "sha256:" + req.base_v4.design_hash()
    result = svc.get_revision_compile_result(rid)
    assert result["design_binding"] == cert.design_binding
    assert result["design_extensions"] == rev["compilation"]["design_extensions"]
    for name, extension in cert.design_binding["extensions"].items():
        if extension is not None:
            assert nodes[name]["hash"] == "sha256:" + extension
        else:
            assert name not in nodes
    assert svc.revision_preflight(rid)["ready"] is False
    with pytest.raises(ControlPlaneError) as caught:
        svc.evaluation_plan(rid)
    assert caught.value.code == ErrorCode.UNSUPPORTED_SEMANTICS
    assert "ABSTRACT_DATA_MOVEMENT_V1" in caught.value.message
    assert parse_request_doc(rev["request"]).design_hash() == req.design_hash()


@pytest.mark.parametrize("kind", ["neutral", "records", "transactions"])
def test_sync_revision_reload_and_rederived_views_preserve_root(tmp_path, kind):
    svc, pid, req = service(tmp_path)
    if kind == "neutral":
        req = CompileRequestV5(base_v4=req.base_v4)
    elif kind == "transactions":
        req = experiment()[0].request
    draft = svc.put_draft(pid, req.to_dict())
    rev = svc.compile_draft(pid, draft["design_hash"])
    assert_revision(svc, pid, req, rev)
    assert svc.draft_view(pid)["request"] == canonical_request_doc(req)
    assert svc.draft_view(pid)["dirty"] is False
    # Exercise persisted-view reconstruction, not just cached views.
    stored = svc.store.load_revision(pid, rev["revision_id"])
    for key in ("topology", "artifact_chain", "compile_result"):
        stored.pop(key)
    path = svc.store.project_dir(pid) / "revisions" / f"{rev['revision_id']}.json"
    path.write_text(json.dumps(stored))
    reloaded = ProductService(svc.config)
    assert_revision(reloaded, pid, req, reloaded.get_revision(rev["revision_id"]))
    # Root drift must not be mistaken for a matching hardware-base identity.
    stored["design_hash"] = "sha256:" + req.base_v4.design_hash()
    path.write_text(json.dumps(stored))
    with pytest.raises(ControlPlaneError) as caught:
        reloaded.get_revision_compile_result(rev["revision_id"])
    assert caught.value.code == ErrorCode.EVIDENCE_INVALID


def test_real_worker_compiles_v5_snapshot_without_mutating_draft(tmp_path):
    svc, pid, req = service(tmp_path)
    before = svc.draft_view(pid)
    try:
        job = svc.submit_compile(pid, before["design_hash"])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            done = svc.get_job(job["job_id"])
            if done["state"] in TERMINAL_STATES:
                break
            time.sleep(.05)
        assert done["state"] == "COMPLETED", done
        assert_revision(svc, pid, req, svc.get_revision(done["result"]["revision_id"]))
        after = svc.draft_view(pid)
        assert after["request"] == before["request"]
        assert after["updated_at"] == before["updated_at"]
    finally:
        svc.jobs.shutdown()


def test_stale_review_and_worker_publication_do_not_replace_revision(tmp_path, monkeypatch):
    svc, pid, req = service(tmp_path)
    active = svc.compile_draft(pid)
    old = svc.draft_view(pid)
    changed = replace(req, base_v4=replace(req.base_v4,
                      workload=replace(req.base_v4.workload, model_name="changed")))
    svc.put_draft(pid, canonical_request_doc(changed))
    for op in (svc.compile_draft, svc.submit_compile):
        with pytest.raises(ControlPlaneError) as caught:
            op(pid, old["design_hash"])
        assert caught.value.code == ErrorCode.STALE_REVIEW
    svc.put_draft(pid, canonical_request_doc(req))
    callbacks = {}
    def capture(_pid, **kwargs):
        callbacks.update(kwargs)
        return {"job_id": "captured", "project_id": _pid, "kind": "COMPILE",
                "state": "QUEUED", "revision_id": None,
                "submitted_at": None, "updated_at": None}
    monkeypatch.setattr(svc.jobs, "submit_process", capture)
    svc.submit_compile(pid, old["design_hash"])
    snapshot = svc._compile_snapshot(pid, svc.store.load_draft(pid), 99)
    svc.put_draft(pid, canonical_request_doc(changed))
    with pytest.raises(ControlPlaneError) as caught:
        callbacks["publish"]({"revision": snapshot})
    assert caught.value.code == ErrorCode.STALE_REVIEW
    assert svc.store.load_project(pid)["active_revision_id"] == active["revision_id"]
    svc.put_draft(pid, canonical_request_doc(req))
    snapshot["design_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ControlPlaneError) as caught:
        callbacks["publish"]({"revision": snapshot})
    assert caught.value.code == ErrorCode.EVIDENCE_INVALID


@pytest.mark.parametrize("field,value,stage", [
    ("agent_intents", (AgentIntentV5(0, interface_role=InterfaceRole.INITIATOR),), "ATTACHMENT"),
    ("power_domains", (PowerDomain("power", PowerPolicy.ALWAYS_ON),), "COMPOSE"),
    ("reset_channels", (ResetChannel("rst", "por", "core", AssertionMode.SYNC, DeassertionMode.SYNC),), "COMPOSE"),
])
def test_extension_owned_refusals_are_persisted_without_promoting(tmp_path, field, value, stage):
    svc, pid, req = service(tmp_path)
    active = svc.compile_draft(pid)
    req = replace(req, **{field: value})
    svc.put_draft(pid, req.to_dict())
    refused = svc.compile_draft(pid)
    stored = svc.store.load_revision(pid, refused["revision_id"])
    assert refused["compilation"]["status"] == "UNSUPPORTED"
    assert refused["compilation"]["stopped_at_stage"] == stage
    assert field in refused["compilation"]["error"]
    assert stored["request"] == canonical_request_doc(req)
    assert refused["design_hash"] == "sha256:" + req.design_hash()
    assert stored["simulation"]["readiness"] == "BLOCKED"
    assert svc.store.load_project(pid)["active_revision_id"] == active["revision_id"]
    assert ProductService(svc.config).store.load_revision(pid, refused["revision_id"])["request"] == canonical_request_doc(req)


def test_product_revision_replay_reuses_addressed_runner(tmp_path):
    svc, pid, _ = service(tmp_path)
    compilation, workload, placement = experiment()
    svc.put_draft(pid, compilation.request.to_dict())
    revision = svc.compile_draft(pid)
    stored = svc.store.load_revision(pid, revision["revision_id"])
    replay = FabricCompiler().compile(parse_request_doc(stored["request"]))
    expected = execute_data_movement(compilation, workload, placement)
    actual = execute_data_movement(replay, workload, placement)
    assert actual == expected
    assert DataMovementEvidence.from_dict(json.loads(json.dumps(actual.to_dict())),
        compilation=replay, workload=workload, placement=placement) == actual
    assert actual.to_dict()["scope"]["signoff_verified"] is False
    assert actual.to_dict()["scope"]["booksim_equivalent"] is False


@pytest.mark.parametrize("field", ["base_v4", "compiler_semantics_version"])
def test_missing_required_v5_field_is_typed_invalid(field):
    doc = canonical_request_doc(_request())
    doc.pop(field)
    with pytest.raises(ControlPlaneError) as caught:
        parse_request_doc(doc)
    assert caught.value.code == ErrorCode.INVALID_INTENT
    assert "missing required field" in caught.value.message


def test_invalid_save_preserves_draft(tmp_path):
    svc, pid, req = service(tmp_path)
    before = svc.draft_view(pid)
    with pytest.raises(ControlPlaneError) as caught:
        svc.put_draft(pid, {**req.to_dict(), "design_hash": "0" * 64})
    assert caught.value.code == ErrorCode.INVALID_INTENT
    assert svc.draft_view(pid) == before


def test_studio_v5_authoring_preserves_root_and_exposes_declarations(tmp_path):
    with TestClient(create_app(GatewayConfig(store_root=tmp_path / "store",
        projects_root=tmp_path / "projects", runs_root=tmp_path / "runs")),
        raise_server_exceptions=False) as client:
        svc = client.app.state.product
        pid = svc.store.create_project(name="V5", draft_doc={}, workload_id="fixture", source="test")["project_id"]
        response = client.put(f"/api/v1/projects/{pid}/draft", json={"request": _request(records=True).to_dict()})
        assert response.status_code == 200, response.text
        response = client.get(f"/api/v1/projects/{pid}/design")
        assert response.status_code == 200, response.text
        view = response.json()
        assert view['draft_identity']['draft_design_hash'] == 'sha256:' + _request(records=True).design_hash()
        assert view['v5_scope']['base_preview'] == 'BASE_ONLY'
        declarations = next(s for s in view['sections'] if s['id'] == 'v5_declarations')
        assert {e['field'] for e in declarations['entries']} >= {'CompileRequestV5.clock_domains', 'CompileRequestV5.sideband_connections'}
        compiled = client.post(f"/api/v1/projects/{pid}/compile")
        assert compiled.status_code == 200, compiled.text
        revision = compiled.json()
        assert revision["compilation"]["status"] == "COMPILED"
        assert revision["design_hash"] == "sha256:" + _request(records=True).design_hash()
        assert_revision(svc, pid, _request(records=True), revision)
