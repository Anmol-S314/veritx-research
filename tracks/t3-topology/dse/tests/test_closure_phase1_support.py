"""Phase-1 support/readiness gates (RC-02) and conditional BookSim
requirement for optimization studies (RC-12).

- An UNSUPPORTED design is refused with lowering/unsupported semantics.
- A representable design whose producer is BLOCKED still submits (the
  planner owns non-ready rows); the run records the refusal with its
  reason and never executes against an unqualified producer.
- An ASTRA-only or Ramulator-only study submits without a BookSim
  binary; a network study still demands it (503 when absent).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from veritx_dse.product.service import ProductService

from test_product_workflow import _client, _make_project  # noqa: F401

DOMAIN = [{"name": "link_width", "values": [64, 128]}]


def _revision(client: TestClient) -> str:
    pid = _make_project(client)["project"]["project_id"]
    assert client.post(f"/api/v1/projects/{pid}/compile").status_code == 200
    return client.get(f"/api/v1/projects/{pid}").json()[
        "active_revision_id"]


def _study(*questions: str) -> dict:
    return {
        "domain": DOMAIN,
        "objectives": [
            {"metric": f"metric_{i}", "direction": "MIN",
             "question": q} for i, q in enumerate(questions)],
    }


def test_blocked_producer_records_refusal_without_executing(
        tmp_path, monkeypatch):
    """RC-02: support says representable but readiness says BLOCKED —
    submit still becomes a job (the planner owns non-ready rows), and
    the federated executor records the refusal with its reason instead
    of executing against an unqualified producer."""
    from test_gateway_federation import _wait_run
    dummy = tmp_path / "booksim-dummy"
    dummy.write_bytes(b"not-a-real-backend")
    monkeypatch.setenv("VERITX_BOOKSIM_BIN", str(dummy))
    client = _client(tmp_path)
    rid = _revision(client)
    monkeypatch.setattr(
        ProductService, "_assessment_for_revision",
        lambda self, revision: {
            "support": "SUPPORTED", "readiness": "BLOCKED",
            "domain": "backend",
            "reason": "injected unqualified producer"})
    resp = client.post(f"/api/v1/revisions/{rid}/evaluate",
                       json={"backend": None})
    assert resp.status_code == 200, resp.text
    job = _wait_run(client, resp.json()["job_id"])
    run = client.get(f"/api/v1/runs/{job['result']['run_id']}").json()
    analyses = [a for a in run["analyses"]
                if a["question"] == "NETWORK_COMPLETION"]
    assert analyses, run
    analysis = analyses[0]
    assert analysis["status"] != "EVALUATED", analysis
    assert analysis["reason"], analysis
    assert analysis["native_evidence_id"] is None, analysis


def test_unsupported_design_keeps_semantic_refusal(tmp_path, monkeypatch):
    """RC-02: the support failure still maps to lowering/unsupported
    semantics, not to the readiness conflict."""
    client = _client(tmp_path, with_backend=False)
    rid = _revision(client)
    monkeypatch.setattr(
        ProductService, "_assessment_for_revision",
        lambda self, revision: {
            "support": "UNSUPPORTED", "readiness": "BLOCKED",
            "domain": "intent_lowering",
            "reason": "injected lowering refusal"})
    resp = client.post(f"/api/v1/revisions/{rid}/evaluate",
                       json={"backend": None})
    assert resp.status_code in (400, 422), resp.text
    assert resp.json()["code"] == "LOWERING_UNSUPPORTED"


def test_non_network_studies_complete_with_measurements(
        tmp_path, monkeypatch):
    """RC-12, COMPLETED-or-bust: no BookSim binary configured, yet
    ASTRA-only and Ramulator-only studies run to a terminal COMPLETED
    state with measured objective values — accepting FAILED (or any
    other terminal state) as success would mask a deterministically
    broken study. Full provenance assertions live in
    test_closure_phase3_opt_e2e; here every covered non-network study
    must complete with real measurements."""
    from test_closure_phase3_opt_e2e import (
        _assert_measured, _scripted_client, _study,
        _submit_and_wait_completed,
    )
    client, _, _ = _scripted_client(tmp_path, monkeypatch)
    rid = _revision(client)
    for metric, question, backend, fidelity, value in (
            ("system_makespan_cycles", "SYSTEM_MAKESPAN",
             "ASTRA2_EMBEDDED_BOOKSIM", "SYSTEM_SIMULATION", 6070.0),
            ("average_read_latency_cycles", "DRAM_TIMING",
             "RAMULATOR2_HBM3_V1", "MEMORY_CYCLE_SIMULATION", 42.0)):
        study = _submit_and_wait_completed(
            client, rid, _study(metric, "MIN", question))
        candidates = study["study"]["candidates"]
        assert len(candidates) == 2, (question, study)
        for candidate in candidates:
            _assert_measured(candidate, metric, question, backend,
                             fidelity, value)


def test_network_study_still_demands_booksim(tmp_path):
    """RC-12: the legacy network-only study keeps its 503 when no
    BookSim binary is configured."""
    client = _client(tmp_path, with_backend=False)
    rid = _revision(client)
    resp = client.post(
        f"/api/v1/revisions/{rid}/optimize",
        json=_study("NETWORK_COMPLETION"))
    assert resp.status_code == 503, resp.text
