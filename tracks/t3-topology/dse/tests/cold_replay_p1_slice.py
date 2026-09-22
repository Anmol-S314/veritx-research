"""Cold replay of the P1 product vertical slice (RT-3).

Run as a SUBPROCESS by tests/test_p1_product_vertical_slice.py:

    python3 tests/cold_replay_p1_slice.py <persist_dir>

It loads ONLY the persisted bytes under <persist_dir> plus the evidence
path named in <persist_dir>/manifest.json, rebuilds the whole chain
through the canonical authorities (compiler, lowering, messages,
traffic, temporal workload) and REQUIRES
performance/result.py::reverify_result to accept the persisted
PerformanceResult — the rigorous verifier that reconstructs the event
graph, re-runs the deterministic scheduler, re-derives every summary
and recomputes the resource id. It prints one canonical JSON object
describing what it verified; any failure raises (non-zero exit).

This module is deliberately NOT named test_*.py: pytest must not
collect it as a test (it is a transport script executed in a fresh
interpreter, so no warm Python object from the live phase can leak in).
"""
from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_passes,
    verify_performance_result,
)
from veritx_dse.backend.evidence import (
    EvidenceRef,
    read_verified_evidence,
    validate_evidence_document,
)
from veritx_dse.core.spec import canonical_json
from veritx_dse.core.time import QTime
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.performance.model import (
    ClockDef,
    PerformanceModel,
    ResourceDef,
)
from veritx_dse.performance.network import stats_sha256
from veritx_dse.performance.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW,
    TemporalEvent,
    TemporalWorkload,
)
from veritx_dse.verification.certificate import VerificationCertificate
from veritx_dse.workload.canonical_graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import (
    LoweredWorkload,
    build_single_class_messages,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

_PERSISTED = ("request", "certificate", "workload_graph", "sidecar",
              "performance_result", "requirement_report", "manifest")


def _read_json(path: Path):
    return json.loads(path.read_text())


def load_persisted(persist_dir) -> dict:
    """Every persisted document, read from bytes (no live objects)."""
    persist = Path(persist_dir)
    return {name: _read_json(persist / f"{name}.json")
            for name in _PERSISTED}


def rebuild_temporal_workload(perf_doc: dict) -> TemporalWorkload:
    """Rebuild the exact TemporalWorkload ``reverify_result`` needs.

    A PerformanceResult persists its PerformanceModel only by id, so the
    parents are reconstructed from the AUTHENTICATED window: the bound
    network clock (exact, from the binding) and the single
    NETWORK_TRAFFIC_WINDOW event id (from the persisted schedule). This
    mirrors the constructor path in
    application/fabric_evaluator.py (one window event, the EXCLUSIVE
    fabric.network_window resource, network_clock="network"). Callers
    MUST prove ``temporal_workload_id()`` equals the result's before
    treating the rebuild as the verified parent.
    """
    if not isinstance(perf_doc, dict):
        raise ValueError("performance result must be an object")
    binding = perf_doc.get("network_binding")
    if not isinstance(binding, dict):
        raise ValueError(
            "cold replay expects a bound network window (the slice is a "
            "single-window P1 evaluation)")
    hz_raw = binding.get("network_clock_hz")
    if not isinstance(hz_raw, dict) or set(hz_raw) != {"num", "den"}:
        raise ValueError(
            f"binding network_clock_hz must be {{num, den}}, got "
            f"{hz_raw!r}")
    hz = Fraction(hz_raw["num"], hz_raw["den"])
    schedule = perf_doc.get("schedule")
    if not isinstance(schedule, dict) or \
            not isinstance(schedule.get("events"), list) or \
            len(schedule["events"]) != 1:
        raise ValueError(
            "cold replay expects exactly ONE scheduled event (the "
            "aggregate network window)")
    event_id = schedule["events"][0]["event_id"]
    model = PerformanceModel(
        clocks=(ClockDef("network", hz),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    event = TemporalEvent(event_id, EVENT_NETWORK_TRAFFIC_WINDOW,
                          QTime.zero())
    return TemporalWorkload(performance_model=model, events=(event,))


def verify_cold(persist_dir) -> dict:
    """Rebuild + re-verify everything from the persisted directory."""
    docs = load_persisted(persist_dir)
    request = CompileRequestV3.from_dict(docs["request"])

    # ── certificate re-derives from the request bytes ──────────────
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    certificate_id = compilation.certificate.certificate_id()
    reopened = VerificationCertificate.from_dict(docs["certificate"])
    assert reopened.overall == "PASS"
    assert reopened.certificate_id() == certificate_id

    # ── graph/lowering/messages/traffic re-derive, byte-for-byte ───
    graph = WorkloadGraph.from_dict(docs["workload_graph"])
    sidecar = docs["sidecar"]
    assert sidecar["design_hash"] == request.design_hash()
    lowered = LoweredWorkload(
        graph=graph,
        traffic_class_by_operation=tuple(
            (op, cls) for op, cls in sidecar["traffic_class_by_operation"]),
        design_hash=sidecar["design_hash"])
    messages = build_single_class_messages(lowered)
    roundtrip = LogicalMessageArtifactV2.from_dict(
        json.loads(json.dumps(messages.to_dict())), graph=graph)
    assert roundtrip.message_artifact_id() == messages.message_artifact_id()
    traffic = PhysicalTrafficArtifactV2(
        logical=messages, bundle=compilation.bundle)

    perf = docs["performance_result"]
    chain = perf["wave_d_chain"]
    assert graph.workload_id() == chain["workload_graph_id"]
    assert messages.message_artifact_id() == chain["message_artifact_id"]
    assert traffic.physical_traffic_id() == chain["physical_traffic_id"]

    # ── evidence bytes: digest + re-derived stats digest ───────────
    manifest = docs["manifest"]
    evidence_path = manifest["evidence_path"]
    raw = Path(evidence_path).read_bytes()
    evidence_digest = hashlib.sha256(raw).hexdigest()
    binding = perf["network_binding"]
    assert evidence_digest == binding["evidence_sha256"]
    parsed = validate_evidence_document(read_verified_evidence(
        EvidenceRef(path=evidence_path, sha256=evidence_digest)))
    assert stats_sha256(parsed["stats"]) == binding["stats_sha256"]

    # ── the rigorous verifier: reverify_result over the rebuilt parents
    temporal = rebuild_temporal_workload(perf)
    assert temporal.temporal_workload_id() == perf["temporal_workload_id"]
    # The verified boundary: reverify_result raises on any tamper; the
    # wrapper it returns is the only input RequirementEvaluator accepts.
    verified = verify_performance_result(perf, workload=temporal)

    # ── requirements over the rebuilt triple ───────────────────────
    report = RequirementEvaluator.evaluate(request, graph, verified)
    persisted_report = docs["requirement_report"]
    verdicts = [e["verdict"] for e in report["entries"]]
    assert report["design_hash"] == persisted_report["design_hash"]
    assert perf["resource_id"] == persisted_report["performance_result_id"]
    assert report["performance_result_id"] == perf["resource_id"]
    assert verdicts == [e["verdict"] for e in persisted_report["entries"]]

    return {
        "ok": True,
        "reverified": True,
        "design_hash": report["design_hash"],
        "certificate_id": certificate_id,
        "workload_id": graph.workload_id(),
        "message_artifact_id": messages.message_artifact_id(),
        "physical_traffic_id": traffic.physical_traffic_id(),
        "temporal_workload_id": temporal.temporal_workload_id(),
        "performance_result_id": perf["resource_id"],
        "evidence_digest": evidence_digest,
        "stats_digest": binding["stats_sha256"],
        "requirements_pass": report_passes(report),
        "verdicts": verdicts,
    }


def main(argv) -> int:
    persist_dir = argv[1]
    result = verify_cold(persist_dir)
    sys.stdout.write(canonical_json(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
