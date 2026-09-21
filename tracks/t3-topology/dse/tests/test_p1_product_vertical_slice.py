"""Stage-4 product vertical slice: mesh_dense_64_v3.

Part 1 (live objects): v3 fixture -> compile -> cert PASS -> lower ->
P1B VC admission -> certified DOR BookSim -> route equivalence ->
quiescence -> evidence auth -> PerformanceResult -> RequirementReport,
persisting every intermediate to disk.

Part 2 (cold reopen): ALL part-1 objects are deleted first. Everything is
reloaded/reconstructed from persisted bytes only, then re-verified:
request identity, certificate, graph/messages/traffic determinism,
evidence digest, requirement verdicts. This proves stored products, not
warm Python objects agreeing with themselves.
"""
from __future__ import annotations

import hashlib
import json

import jsonschema
import pytest

from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.application.requirements import RequirementEvaluator
from veritx_dse.backend.evidence import EvidenceRef, read_verified_evidence
from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.simulation.booksim import find_booksim_bin
from veritx_dse.verification.certificate import VerificationCertificate
from veritx_dse.workload.canonical_graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import (
    LoweredWorkload,
    build_single_class_messages,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

FIXTURE = (REPO / "tracks" / "t3-topology" / "examples" /
           "llama_dense_64tiles-v3.json")


def _load_request() -> tuple[CompileRequestV3, dict]:
    doc = json.loads(FIXTURE.read_text())
    return CompileRequestV3.from_dict(doc), doc


def _norm_digest(value: str) -> str:
    return value[7:] if value.startswith("sha256:") else value


def test_mesh_dense_64_v3_vertical_slice(tmp_path):
    request, request_doc = _load_request()
    design_hash = request.design_hash()
    binary = find_booksim_bin(REPO)
    run_dir = tmp_path / "run"
    persist = tmp_path / "persist"
    persist.mkdir()

    # ── Part 1: live chain ──────────────────────────────────────────
    prod = evaluate_product(
        request, binary=str(binary), run_dir=str(run_dir),
        network_clock_hz=10 ** 9, timeout_s=900)
    assert prod.compilation.status == "COMPILED", prod.compilation.error
    obligations = prod.compilation.certificate.obligations
    assert len(obligations) == 10
    assert prod.compilation.certificate.overall == "PASS"
    assert all(o.status == "PASS" for o in obligations)
    assert prod.lowered.graph.participant_count == 8
    assert prod.lowered.unified_traffic_class == "tp_collective"
    assert prod.status == "EVALUATED", prod.reason
    assert prod.outcome.backend_profile == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert prod.outcome.performance_result is not None
    assert prod.requirements_pass is True
    assert all(e["verdict"] == "SATISFIED"
               for e in prod.requirement_report["entries"])
    jsonschema.validate(
        prod.outcome.to_view_dict(),
        json.loads((REPO / "contracts" / "srota" / "v1" /
                    "evaluation.view.schema.json").read_text()))
    jsonschema.validate(
        prod.requirement_report,
        json.loads((REPO / "contracts" / "srota" / "v1" /
                    "requirement.report.schema.json").read_text()))

    # Persist every intermediate (evidence bytes already persisted by the
    # evaluator under run_dir; record its path, never its object).
    saved = {
        "request": persist / "request.json",
        "certificate": persist / "certificate.json",
        "graph": persist / "workload_graph.json",
        "sidecar": persist / "sidecar.json",
        "performance": persist / "performance_result.json",
        "report": persist / "requirement_report.json",
    }
    saved["request"].write_text(json.dumps(request_doc, indent=2))
    saved["certificate"].write_text(json.dumps(
        prod.compilation.certificate.to_dict(), indent=2))
    saved["graph"].write_text(json.dumps(prod.lowered.graph.to_dict()))
    saved["sidecar"].write_text(json.dumps({
        "traffic_class_by_operation":
            [list(p) for p in prod.lowered.traffic_class_by_operation],
        "design_hash": prod.lowered.design_hash,
    }))
    saved["performance"].write_text(json.dumps(
        prod.outcome.performance_result, indent=2))
    saved["report"].write_text(json.dumps(prod.requirement_report, indent=2))
    scalars = {
        "design_hash": design_hash,
        "certificate_id":
            prod.compilation.certificate.certificate_id(),
        "workload_id": prod.lowered.graph.workload_id(),
        "performance_result_id": prod.outcome.performance_result_id,
        "raw_evidence_digest": prod.outcome.raw_evidence_digest,
        "evidence_path": prod.outcome.evidence_path,
    }
    # Message/traffic IDs are bound by the outcome; persist the scalars.
    scalars["message_artifact_id"] = prod.outcome.message_artifact_id
    scalars["physical_traffic_id"] = prod.outcome.physical_traffic_id

    # ── Part 2: cold reopen (no warm objects past this line) ───────
    del prod, request
    import gc
    gc.collect()

    request2 = CompileRequestV3.from_dict(
        json.loads(saved["request"].read_text()))
    assert request2.design_hash() == scalars["design_hash"]

    # Recompile deterministically; certificate must re-derive identically.
    from veritx_dse.application.fabric_compiler import FabricCompiler
    comp2 = FabricCompiler().compile(request2)
    assert comp2.status == "COMPILED", comp2.error
    assert comp2.certificate.overall == "PASS"
    assert comp2.certificate.certificate_id() == scalars["certificate_id"]
    reopened_cert = VerificationCertificate.from_dict(
        json.loads(saved["certificate"].read_text()))
    assert reopened_cert.overall == "PASS"
    assert reopened_cert.certificate_id() == scalars["certificate_id"]

    graph2 = WorkloadGraph.from_dict(
        json.loads(saved["graph"].read_text()))
    assert graph2.workload_id() == scalars["workload_id"]
    sidecar = json.loads(saved["sidecar"].read_text())
    lowered2 = LoweredWorkload(
        graph=graph2,
        traffic_class_by_operation=tuple(
            (op, cls) for op, cls in
            sidecar["traffic_class_by_operation"]),
        design_hash=sidecar["design_hash"])
    assert lowered2.unified_traffic_class == "tp_collective"

    # Deterministic rebuild: message/traffic IDs must match exactly.
    messages2 = build_single_class_messages(lowered2)
    assert messages2.message_artifact_id() == \
        scalars["message_artifact_id"]
    roundtrip = LogicalMessageArtifactV2.from_dict(
        json.loads(json.dumps(messages2.to_dict())), graph=graph2)
    assert roundtrip.message_artifact_id() == \
        scalars["message_artifact_id"]
    traffic2 = PhysicalTrafficArtifactV2(
        logical=messages2, bundle=comp2.bundle)
    assert traffic2.physical_traffic_id() == \
        scalars["physical_traffic_id"]

    # Evidence bytes unchanged + parseable under their bound digest.
    ev_bytes = open(scalars["evidence_path"], "rb").read()
    assert hashlib.sha256(ev_bytes).hexdigest() == \
        _norm_digest(scalars["raw_evidence_digest"])
    parsed = read_verified_evidence(EvidenceRef(
        path=scalars["evidence_path"],
        sha256=_norm_digest(scalars["raw_evidence_digest"])))
    assert isinstance(parsed, dict) and parsed

    # Performance + requirements re-verified as consumers of the doc.
    perf_doc = json.loads(saved["performance"].read_text())
    assert perf_doc.get("resource_id") == \
        scalars["performance_result_id"]
    report2 = RequirementEvaluator.evaluate(request2, graph2, perf_doc)
    assert [e["verdict"] for e in report2["entries"]] == \
        [e["verdict"] for e in
         json.loads(saved["report"].read_text())["entries"]]
    assert all(e["verdict"] == "SATISFIED" for e in report2["entries"])
