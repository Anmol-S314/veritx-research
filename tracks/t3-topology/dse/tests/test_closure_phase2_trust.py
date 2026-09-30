"""Phase-2/6 evidence trust (RC-03): anti-transplant binding at
normalize time, reproduce-divergence parity, PARTIAL failure naming.

- BookSim and ASTRA normalizers must refuse evidence that does not
  claim exactly the prepared machine/projection/namespace/config
  identities — never stamp parents from context blindly.
- Ramulator reproduction divergence must raise RunBundleError like the
  BookSim and ASTRA reproducers (never a quiet ``matched: False``).
- A mixed EVALUATED+FAILED run must name the failed analysis in its
  top-level reason.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from veritx_dse.application.evaluation_question import EvaluationQuestion

def _h(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()

def _booksim_ids():
    return {
        "prepared": _h("prepared"),
        "config": _h("config"),
        "trace": _h("trace"),
        "message": _h("message"),
        "traffic": _h("traffic"),
        "fabric": _h("fabric"),
        "binary": _h("binary"),
        "manifest": _h("manifest"),
    }

def _booksim_evidence_doc(ids, **over):
    from veritx_dse.backend.evidence import ScientificBackendEvidence
    fields = {
        "prepared_id": ids["prepared"],
        "profile_id": "CERTIFIED_BOOKSIM_MESH_DOR",
        "projection_semantics_version": "booksim2-fork/v2",
        "config_sha256": ids["config"],
        "trace_sha256": ids["trace"],
        "topology_sha256": None,
        "resolved_fabric_hash": ids["fabric"],
        "physical_traffic_id": ids["traffic"],
        "message_artifact_id": ids["message"],
        "binary_sha256": ids["binary"],
        "binary_size": 12345,
        "producer_source_revision": "abc123",
        "producer_dirty": False,
        "seed": 7,
        "parser_version": "veritx/booksim-stats-parser/v2",
        "execution_fidelity": "QUALIFIED",
        "route_observation": "EXECUTED_ROUTE_OBSERVED",
        "stats": {"completion_cycles": 100},
        "exit_status": 0,
        "transport": "SUPERVISED_PROCESS",
        "build_manifest_sha256": ids["manifest"],
        "build_recipe_version": "booksim2-fork/v2",
        "route_dump_sha256": _h("routedump"),
    }
    fields.update(over)
    return ScientificBackendEvidence(**fields).to_dict()

def _booksim_native(ids):
    from veritx_dse.backend.booksim_adapter import BookSimPreparation
    return BookSimPreparation(
        prepared=object(), physical_traffic=object(),
        message_artifact_id=ids["message"],
        physical_traffic_id=ids["traffic"],
        profile_id="CERTIFIED_BOOKSIM_MESH_DOR",
        config_hash=ids["config"], input_hash=ids["trace"],
        realization_digest=ids["prepared"])

def _booksim_prepared(native):
    from veritx_dse.backend.adapter import PreparedExecution
    return PreparedExecution(
        backend_id="BOOKSIM_STANDALONE", projection_identity="x",
        qualification_identity="CERTIFIED_BOOKSIM_MESH_DOR",
        backend_config=None, backend_input=None, producer=None,
        native_prepared=native)

def _context(ids):
    return SimpleNamespace(
        design_hash="sha256:" + _h("design"),
        workload_id="workload-1",
        bundle=SimpleNamespace(resolved_fabric=SimpleNamespace(
            resolved_fabric_hash=ids.get("fabric") or _h("fabric"))))

def _booksim_result():
    from veritx_dse.backend.booksim_adapter import BookSimExecutionResult
    return BookSimExecutionResult(
        record=SimpleNamespace(ref="dummy"), producer=object())

@pytest.mark.parametrize("field", [
    "prepared_id", "config_sha256", "trace_sha256",
    "message_artifact_id", "physical_traffic_id",
    "resolved_fabric_hash",
])
def test_booksim_normalize_refuses_transplanted_evidence(
        monkeypatch, field):
    """Every persisted identity must match the preparation — a single
    transplanted id refuses, never normalizes under blind parents."""
    import veritx_dse.backend.evidence as evidence_mod
    from veritx_dse.backend.booksim_adapter import BookSimAdapter
    from veritx_dse.backend.evidence import BackendEvidenceError
    ids = _booksim_ids()
    doc = _booksim_evidence_doc(ids, **{field: _h("transplanted")})
    monkeypatch.setattr(evidence_mod, "read_verified_evidence",
                        lambda ref: {"evidence": doc})
    adapter = BookSimAdapter()
    with pytest.raises(BackendEvidenceError, match="transplanted"):
        adapter.normalize(
            _context(ids), EvaluationQuestion.NETWORK_COMPLETION,
            _booksim_prepared(_booksim_native(ids)), _booksim_result())

def test_booksim_normalize_accepts_bound_evidence(monkeypatch):
    """The control: exactly-bound evidence normalizes with the bound
    parents (no false refusal from the new gate)."""
    import veritx_dse.backend.evidence as evidence_mod
    from veritx_dse.backend.booksim_adapter import BookSimAdapter
    ids = _booksim_ids()
    doc = _booksim_evidence_doc(ids)
    monkeypatch.setattr(evidence_mod, "read_verified_evidence",
                        lambda ref: {"evidence": doc})
    adapter = BookSimAdapter()
    envelope = adapter.normalize(
        _context(ids), EvaluationQuestion.NETWORK_COMPLETION,
        _booksim_prepared(_booksim_native(ids)), _booksim_result())
    assert envelope.native_evidence_id is not None
    assert ids["fabric"] in envelope.canonical_parent_ids
    assert ids["message"] in envelope.canonical_parent_ids

def test_booksim_outcome_transplant_refused(tmp_path):
    """The federated outcome path: a design the context did not compile
    refuses, as does evidence transplanted under a bound outcome, as
    does an EVALUATED outcome with no binding identities."""
    from veritx_dse.application.fabric_evaluator import EvaluationOutcome
    from veritx_dse.backend.booksim_adapter import (
        normalize_booksim_outcome,
    )
    from veritx_dse.backend.evidence import BackendEvidenceError
    ids = _booksim_ids()

    def _outcome(digest, **over):
        base = {
            "status": "EVALUATED", "design_hash": "sha256:" + _h("design"),
            "resolved_fabric_hash": ids["fabric"],
            "workload_id": "workload-1",
            "message_artifact_id": ids["message"],
            "physical_traffic_id": ids["traffic"],
            "backend_config_hash": ids["config"],
            "backend_input_hash": ids["trace"],
            "realization_digest": ids["prepared"],
            "producer_identity": ids["binary"],
            "raw_evidence_digest": digest,
            "metrics": {"completion_cycles": 100},
        }
        base.update(over)
        return EvaluationOutcome(**base)

    def _write(doc):
        raw = json.dumps(doc).encode("utf-8")
        path = tmp_path / "evidence.json"
        path.write_bytes(raw)
        return str(path), hashlib.sha256(raw).hexdigest()

    doc = _booksim_evidence_doc(ids)
    path, digest = _write(doc)
    bad_design = _outcome(
        digest, design_hash="sha256:" + _h("other-design"))
    bad_design = EvaluationOutcome(
        **{**bad_design.__dict__, "evidence_path": path})
    with pytest.raises(BackendEvidenceError, match="transplanted"):
        normalize_booksim_outcome(_context(ids), bad_design)

    tx_ids = dict(ids, config=_h("transplanted-config"))
    tx_doc = _booksim_evidence_doc(tx_ids)
    tx_path, tx_digest = _write(tx_doc)
    bound = _outcome(tx_digest)
    bound = EvaluationOutcome(
        **{**bound.__dict__, "evidence_path": tx_path})
    with pytest.raises(BackendEvidenceError, match="transplanted"):
        normalize_booksim_outcome(_context(ids), bound)

    unbound = _outcome(digest, realization_digest=None)
    unbound = EvaluationOutcome(
        **{**unbound.__dict__, "evidence_path": path})
    with pytest.raises(BackendEvidenceError, match="unbound"):
        normalize_booksim_outcome(_context(ids), unbound)

def _astra_ids():
    return {
        "machine": _h("machine"),
        "workload": _h("workload"),
        "namespace": _h("namespace"),
        "prepared": _h("astra-prepared"),
        "rankmap": ((0, 1), (1, 0)),
    }

def _astra_native(ids):
    from veritx_dse.backend.astra_adapter import Astra2Preparation
    machine_id, workload_id = ids["machine"], ids["workload"]
    namespace_id = ids["namespace"]
    return Astra2Preparation(
        workload_projection=SimpleNamespace(
            projection_id=lambda: workload_id,
            traffic_classes=lambda: ("tp_collective",)),
        machine=SimpleNamespace(
            machine_id=lambda: machine_id,
            embedded_network_class_abi_version=0),
        namespace=SimpleNamespace(namespace_id=lambda: namespace_id),
        workload_projection_id=ids["workload"],
        machine_id=ids["machine"],
        prepared_id=ids["prepared"],
        standalone_config_sha256=_h("standalone"),
        embedded_fabric_abi_version="v1",
        rank_to_endpoint=ids["rankmap"])

def _astra_evidence(ids, **over):
    from veritx_dse.backend.astra_execution import (
        ASTRA_BUILD_RECIPE_VERSION,
        AstraRuntimeEvidence,
    )
    fields = {
        "status": "EXECUTED",
        "evidence_tier": "ASTRA_OWNED_COLLECTIVE_EXECUTION",
        "expansion_authority": "astra_comm_coll",
        "workload_evidence_scope": "collective",
        "machine_id": ids["machine"],
        "prepared_id": ids["prepared"],
        "workload_projection_id": ids["workload"],
        "network_config_abi": "v1",
        "embedded_fabric_abi_version": "v1",
        "embedded_network_class_abi_version": 0,
        "astra_build_recipe_version": ASTRA_BUILD_RECIPE_VERSION,
        "astra_build_manifest_sha256": "1" * 64,
        "astra_binary_sha256": _h("astra-bin"),
        "astra_binary_size": 999,
        "astra_source_revision": "rev",
        "astra_dirty": False,
        "binary_accepts_legacy_json_abi": True,
        "book_sim_source_has_json_unwrap": True,
        "packetization_fidelity": "exact",
        "flit_bytes": 16,
        "participant_count": 2,
        "autonomous_injection_packets": 0,
        "per_rank_cycles": ((0, 10), (1, 10)),
        "per_rank_exposed_comm": ((0, 4), (1, 4)),
        "per_rank_compute": ((0, 6), (1, 6)),
        "aggregate_cycles": 10,
        "aggregate_exposed_comm": 4,
        "rank_count": 2,
        "rank_to_endpoint": ids["rankmap"],
        "namespace_id": ids["namespace"],
        "namespace_binding": "b",
        "endpoint_count": 2,
        "astra_sys_count": 1,
        "idle_fabric_endpoints": (),
        "participant_statistics_present": True,
        "per_endpoint_cycles": ((0, 10), (1, 10)),
        "per_endpoint_exposed_comm": ((0, 4), (1, 4)),
        "transport": "SUPERVISED_PROCESS",
    }
    fields.update(over)
    return AstraRuntimeEvidence(**fields)

def _astra_prepared(native):
    from veritx_dse.backend.adapter import PreparedExecution
    return PreparedExecution(
        backend_id="ASTRA2_EMBEDDED_BOOKSIM", projection_identity="x",
        qualification_identity=None, backend_config=None,
        backend_input=None, producer=None, native_prepared=native)

@pytest.mark.parametrize("field", [
    "machine_id", "workload_projection_id", "namespace_id",
    "prepared_id", "rank_to_endpoint",
])
def test_astra_normalize_refuses_transplanted_evidence(field):
    """machine / workload / namespace / prepared / rank-map transplants
    refuse — the normalize-time gate matches the reproduce-time one."""
    from veritx_dse.backend.astra_adapter import Astra2Adapter
    from veritx_dse.backend.astra_execution import AstraExecutionError
    ids = _astra_ids()
    evil = _h("transplanted-" + field)
    if field == "rank_to_endpoint":
        evil = ((0, 0), (1, 1))
    evidence = _astra_evidence(ids, **{field: evil})
    adapter = Astra2Adapter()
    with pytest.raises(AstraExecutionError, match="transplanted"):
        adapter.normalize(
            _context(ids), EvaluationQuestion.SYSTEM_MAKESPAN,
            _astra_prepared(_astra_native(ids)), evidence)

def test_astra_normalize_accepts_bound_evidence():
    """Control: exactly-bound evidence normalizes (no false refusal)."""
    from veritx_dse.backend.astra_adapter import Astra2Adapter
    ids = _astra_ids()
    envelope = Astra2Adapter().normalize(
        _context(ids), EvaluationQuestion.SYSTEM_MAKESPAN,
        _astra_prepared(_astra_native(ids)), _astra_evidence(ids))
    assert envelope.native_evidence_id is not None
    assert ids["machine"] in envelope.canonical_parent_ids

def _ram_bundle(monkeypatch, tmp_path):
    from test_ramulator_adapter import _execute_offline
    from veritx_dse.application.federated_evaluator import (
        _persist_ramulator_inputs,
    )
    _, _, prepared, _, run_dir = _execute_offline(monkeypatch, tmp_path)
    _persist_ramulator_inputs(run_dir, prepared)
    return run_dir

def _stored_ram_evidence(run_dir):
    from veritx_dse.simulation import ramulator as sim
    doc = json.loads(
        (run_dir / "ramulator" / "memory-evidence.json").read_text(
            encoding="utf-8"))
    return sim.MemoryEvidence(
        status=doc["status"], producer=doc["producer"],
        fidelity=doc["fidelity"],
        memory_artifact_hash=doc["memory_artifact_hash"],
        lowering_manifest_hash=doc["lowering_manifest_hash"],
        backend_input_hash=doc["backend_input_hash"],
        backend_config_hash=doc["backend_config_hash"],
        metrics=doc.get("metrics", {}),
        assumptions=tuple(doc.get("assumptions", ())),
        semantic_losses=tuple(doc.get("semantic_losses", ())),
        failure_reason=doc.get("failure_reason", ""), raw={})

def test_ramulator_reproduction_divergence_raises(monkeypatch, tmp_path):
    """Divergent science raises RunBundleError — parity with the
    BookSim and ASTRA reproducers, never a quiet matched:False."""
    from veritx_dse.backend.reproduce_ramulator import (
        reproduce_ramulator_run_bundle,
    )
    from veritx_dse.core.run_bundle import RunBundleError
    from veritx_dse.simulation import ramulator as sim
    run_dir = _ram_bundle(monkeypatch, tmp_path)
    stored = _stored_ram_evidence(run_dir)
    assert stored.status == "PASS"
    drifted = sim.MemoryEvidence(
        status=stored.status, producer=stored.producer,
        fidelity=stored.fidelity,
        memory_artifact_hash=stored.memory_artifact_hash,
        lowering_manifest_hash=stored.lowering_manifest_hash,
        backend_input_hash=stored.backend_input_hash,
        backend_config_hash=stored.backend_config_hash,
        metrics={**stored.metrics, "completed_requests": -1},
        assumptions=stored.assumptions,
        semantic_losses=stored.semantic_losses,
        failure_reason=stored.failure_reason, raw={})
    monkeypatch.setattr(
        sim, "discover",
        lambda *a, **k: SimpleNamespace(ready=True))
    monkeypatch.setattr(sim, "execute", lambda *a, **k: drifted)
    with pytest.raises(RunBundleError, match="diverges"):
        reproduce_ramulator_run_bundle(run_dir)

def test_ramulator_reproduction_match_still_returns_true(
        monkeypatch, tmp_path):
    """The matching path keeps its shape: matched True with the stored
    evidence identity."""
    from veritx_dse.backend.reproduce_ramulator import (
        reproduce_ramulator_run_bundle,
    )
    from veritx_dse.simulation import ramulator as sim
    run_dir = _ram_bundle(monkeypatch, tmp_path)
    stored = _stored_ram_evidence(run_dir)
    monkeypatch.setattr(
        sim, "discover",
        lambda *a, **k: SimpleNamespace(ready=True))
    monkeypatch.setattr(sim, "execute", lambda *a, **k: stored)
    result = reproduce_ramulator_run_bundle(run_dir)
    assert result["matched"] is True
    assert result["evidence_id"]

def test_mixed_run_names_failed_analysis_in_reason():
    """EVALUATED + FAILED mixes are overall FAILED (a crash is never
    masked as PARTIAL) and the top-level reason names the failed
    question with its reason."""
    from veritx_dse.application.federated_evaluator import (
        ANALYSIS_EVALUATED, ANALYSIS_FAILED, _aggregate,
    )
    from veritx_dse.product.service import ProductService
    net = SimpleNamespace(
        question=EvaluationQuestion.NETWORK_COMPLETION,
        backend_id="BOOKSIM_STANDALONE", status=ANALYSIS_EVALUATED,
        reason=None)
    broken = SimpleNamespace(
        question=EvaluationQuestion.SYSTEM_MAKESPAN,
        backend_id="ASTRA2_EMBEDDED_BOOKSIM", status=ANALYSIS_FAILED,
        reason="injected backend crash")
    assert _aggregate((net, broken)) == "FAILED"
    reason = ProductService._federated_reason(
        SimpleNamespace(analyses=[net, broken]))
    assert reason is not None
    assert reason.startswith("FAILED SYSTEM_MAKESPAN on "
                             "ASTRA2_EMBEDDED_BOOKSIM:")
    assert "SYSTEM_MAKESPAN" in reason
    assert "injected backend crash" in reason
