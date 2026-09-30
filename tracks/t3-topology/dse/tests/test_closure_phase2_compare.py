"""Phase-2 Compare verdicts (RC-13).

Comparing two analyses returns a closed-vocabulary verdict — never a
raise for expected incomparability:

    COMPARABLE | NOT_COMPARABLE | MODEL_DIFFERENCE
    | MISSING_MEASUREMENT | QUALIFICATION_DIFFERENCE

A non-COMPARABLE row names which field differs and carries both
native evidence identities. No automatic winner, no meaningless
deltas: delta_b_minus_a is emitted only for COMPARABLE rows. A typed
error is raised only for malformed requests (unknown run ids).
"""
from __future__ import annotations

import pytest

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.product.service import ProductConfig, ProductService

WORKLOAD = "llama-dense-8b-64tiles"

VERDICTS = frozenset({
    "COMPARABLE", "NOT_COMPARABLE", "MODEL_DIFFERENCE",
    "MISSING_MEASUREMENT", "QUALIFICATION_DIFFERENCE",
})

def _service(tmp_path) -> tuple[ProductService, str]:
    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    pid = svc.create_project(name="cmp", workload_id=WORKLOAD)[
        "project"]["project_id"]
    rid = svc.compile_draft(pid)["revision_id"]
    return svc, pid, rid

def _metric(key: str, value, unit: str = "cycles",
            dimensions=()) -> dict:
    return {"key": key, "value": value, "unit": unit,
            "source_metric_key": key,
            "dimensions": [list(d) for d in dimensions]}

def _analysis(question: str, backend: str, fidelity: str,
              qualification, evidence: str | None,
              metrics: list[dict]) -> dict:
    return {"question": question, "backend_id": backend,
            "status": "EVALUATED", "model_fidelity": fidelity,
            "qualification": qualification,
            "native_evidence_id": evidence, "reason": None,
            "native_summary": None, "normalized_metrics": metrics,
            "limitations": None}

def _mkrun(svc: ProductService, pid: str, rid: str, run_id: str,
           workload: str, analyses: list[dict]) -> str:
    svc.store.create_run(pid, {
        "schema_version": 1, "run_id": run_id, "project_id": pid,
        "revision_id": rid, "design_hash": "sha256:x",
        "backend": None, "status": "EVALUATED",
        "qualification": "QUALIFIED", "bundle_id": None,
        "evaluation": {"workload_id": workload, "metrics": {}},
        "requirements": None, "producer": None, "evidence": None,
        "display_name": None, "started_at": None, "completed_at": None,
        "requirements_pass": True, "reason": None,
        "evaluation_plan": {"workload_id": workload},
        "analyses": analyses,
    })
    return run_id

def _row(comparison: dict, key: str) -> dict:
    rows = [r for r in comparison["rows"] if r["key"] == key]
    assert len(rows) == 1, comparison["rows"]
    return rows[0]

def test_comparable_row_carries_delta_and_evidence(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("aggregate_cycles", 1000.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-b",
                  [_metric("aggregate_cycles", 1200.0)])])
    row = _row(svc.compare(a, b), "aggregate_cycles")
    assert row["comparable"] is True
    assert row["verdict"] == "COMPARABLE"
    assert row["differs"] is None
    assert row["reason"] is None
    assert row["delta_b_minus_a"] == 200.0
    assert row["a_evidence"] == "ev-a"
    assert row["b_evidence"] == "ev-b"

def test_same_question_different_backend_is_model_difference(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("NETWORK_COMPLETION", "BOOKSIM_STANDALONE",
                  "NETWORK_PACKET_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("completion_cycles", 500.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("NETWORK_COMPLETION", "OTHER_BACKEND",
                  "NETWORK_PACKET_SIMULATION", "QUALIFIED", "ev-b",
                  [_metric("completion_cycles", 500.0)])])
    row = _row(svc.compare(a, b), "completion_cycles")
    assert row["comparable"] is False
    assert row["verdict"] == "MODEL_DIFFERENCE"
    assert row["differs"] == "backend"
    assert row["delta_b_minus_a"] is None
    assert "not a performance winner" in (row["reason"] or "")

def test_missing_metric_is_missing_measurement(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("DRAM_TIMING", "RAMULATOR2_HBM3_V1",
                  "MEMORY_CYCLE_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("average_read_latency_cycles", 42.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("DRAM_TIMING", "RAMULATOR2_HBM3_V1",
                  "MEMORY_CYCLE_SIMULATION", "QUALIFIED", "ev-b", [])])
    comparison = svc.compare(a, b)
    assert comparison["rows"] == [] or all(
        r["verdict"] == "MISSING_MEASUREMENT" for r in comparison["rows"])
    c = _mkrun(svc, pid, rid, "run-c", "wl", [
        _analysis("DRAM_TIMING", "RAMULATOR2_HBM3_V1",
                  "MEMORY_CYCLE_SIMULATION", "QUALIFIED", "ev-c",
                  [_metric("average_read_latency_cycles", None)])])
    row = _row(svc.compare(a, c), "average_read_latency_cycles")
    assert row["verdict"] == "MISSING_MEASUREMENT"
    assert row["differs"] == "value"
    assert row["a"] == 42.0 and row["b"] is None

def test_same_key_different_question_is_model_difference(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("completion_cycles", 100.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("NETWORK_COMPLETION", "BOOKSIM_STANDALONE",
                  "NETWORK_PACKET_SIMULATION", "QUALIFIED", "ev-b",
                  [_metric("other_metric", 1.0)])])
    comparison = svc.compare(a, b)
    assert all(r["comparable"] is False for r in comparison["rows"])
    assert all(r["verdict"] in VERDICTS for r in comparison["rows"])

def test_qualification_mismatch_is_qualification_difference(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("aggregate_cycles", 1000.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "UNQUALIFIED", "ev-b",
                  [_metric("aggregate_cycles", 900.0)])])
    row = _row(svc.compare(a, b), "aggregate_cycles")
    assert row["comparable"] is False
    assert row["verdict"] == "QUALIFICATION_DIFFERENCE"
    assert row["differs"] == "qualification"

def test_fidelity_mismatch_is_model_difference(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("aggregate_cycles", 1000.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "ANALYTICAL_ESTIMATE", "QUALIFIED", "ev-b",
                  [_metric("aggregate_cycles", 800.0)])])
    row = _row(svc.compare(a, b), "aggregate_cycles")
    assert row["verdict"] == "MODEL_DIFFERENCE"
    assert row["differs"] == "model_fidelity"

def test_unit_mismatch_is_not_comparable(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("aggregate_cycles", 1000.0, unit="cycles")])])
    b = _mkrun(svc, pid, rid, "run-b", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-b",
                  [_metric("aggregate_cycles", 1.0, unit="ms")])])
    row = _row(svc.compare(a, b), "aggregate_cycles")
    assert row["verdict"] == "NOT_COMPARABLE"
    assert row["differs"] == "unit"

def test_different_workload_is_not_comparable(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl-a", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("aggregate_cycles", 1000.0)])])
    b = _mkrun(svc, pid, rid, "run-b", "wl-b", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-b",
                  [_metric("aggregate_cycles", 1000.0)])])
    comparison = svc.compare(a, b)
    assert comparison["compatibility"]["compatible"] is False
    assert all(r["verdict"] == "NOT_COMPARABLE" for r in comparison["rows"])
    assert all(r["differs"] == "workload" for r in comparison["rows"])

def test_unknown_run_raises_not_found(tmp_path):
    svc, pid, rid = _service(tmp_path)
    a = _mkrun(svc, pid, rid, "run-a", "wl", [
        _analysis("SYSTEM_MAKESPAN", "ASTRA2_EMBEDDED_BOOKSIM",
                  "SYSTEM_SIMULATION", "QUALIFIED", "ev-a",
                  [_metric("aggregate_cycles", 1000.0)])])
    with pytest.raises(ControlPlaneError) as excinfo:
        svc.compare(a, "run-does-not-exist")
    assert excinfo.value.code == ErrorCode.NOT_FOUND

def test_legacy_rows_carry_verdicts(tmp_path):
    """The pre-federation path speaks the same closed vocabulary."""
    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    pid = svc.create_project(name="cmp", workload_id=WORKLOAD)[
        "project"]["project_id"]
    rid = svc.compile_draft(pid)["revision_id"]

    def mkrun(run_id: str, workload: str) -> str:
        svc.store.create_run(pid, {
            "schema_version": 1, "run_id": run_id, "project_id": pid,
            "revision_id": rid, "design_hash": "sha256:x",
            "backend": "BOOKSIM_STANDALONE", "status": "EVALUATED",
            "qualification": "QUALIFIED", "bundle_id": None,
            "evaluation": {"workload_id": workload,
                           "metrics": {"completion_cycles": 100}},
            "requirements": None, "producer": None, "evidence": None,
            "display_name": None, "started_at": None, "completed_at": None,
            "requirements_pass": True, "reason": None,
        })
        return run_id

    a = mkrun("run-a", "wl")
    d = mkrun("run-d", "wl")
    same = svc.compare(a, d)
    assert same["rows"][0]["verdict"] == "QUALIFICATION_DIFFERENCE"
    assert same["rows"][0]["differs"] == "qualification"
    e = mkrun("run-e", "other")
    cross = svc.compare(a, e)
    assert all(r["verdict"] == "NOT_COMPARABLE" for r in cross["rows"])
