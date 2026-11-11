"""Class-scoped requirement evaluation over real per-class evidence.

The aggregate window is not a per-class reading.  When the verified
result carries per-class latency/byte movement, a class-scoped bound is
measured against ITS class; when the class or the reading is absent the
verdict is honestly UNMEASURABLE (the aggregate upper bound rule still
applies to latency when only aggregate evidence exists).
"""
from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from tools.sweep_intent_knobs import baseline  # noqa: E402
from veritx_dse.application.authenticated_evaluation import (  # noqa: E402
    authenticate_backend_evaluation,
    verify_authenticated_backend_evaluation,
)
from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    EvaluationOutcome,
)
from veritx_dse.application.requirements import (  # noqa: E402
    RequirementEvaluator,
    verify_performance_result,
)
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BookSimAdapter, normalize_booksim_outcome,
)
from veritx_dse.backend.evidence import (  # noqa: E402
    BOOKSIM_BUILD_RECIPE_VERSION, PARSER_VERSION,
    ScientificBackendEvidence, stats_sha256_of, write_evidence,
)
from veritx_dse.core.time import QTime  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    QoSClass, RequirementV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.performance.model import (  # noqa: E402
    ClockDef, PerformanceModel, ResourceDef,
)
from veritx_dse.performance.network import (  # noqa: E402
    WINDOW_KIND_BARRIER, NetworkWindowBinding,
)
from veritx_dse.performance.result import (  # noqa: E402
    PerformanceEventGraph, build_performance_result,
)
from veritx_dse.performance.scheduler import schedule_workload  # noqa: E402
from veritx_dse.performance.traffic_class import (  # noqa: E402
    build_traffic_class_metrics,
)
from veritx_dse.performance.workload import (  # noqa: E402
    EVENT_NETWORK_TRAFFIC_WINDOW, TemporalEvent, TemporalWorkload,
)
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
CLOCK_HZ = Fraction(10 ** 9)
FLIT_WIDTH_BITS = 64


def _two_class_request(*requirements: RequirementV3) -> CompileRequestV4:
    doc = baseline()
    for key in ("design_hash", "guardrail_hash"):
        doc.pop(key, None)
    doc["dependencies"] = [
        {"source": "a0", "target": "b0", "kind": "blocking"},
        {"source": "b0", "target": "a0", "kind": "blocking"},
    ]
    first = doc["workload"]["collectives"][0]
    first["traffic_class"] = "a0"
    second = deepcopy(first)
    second["traffic_class"] = "b0"
    doc["workload"]["collectives"].append(second)
    return replace(
        CompileRequestV4.from_dict(doc), requirements=tuple(requirements))


def _latency_req(cls: str, ceiling: float) -> RequirementV3:
    return RequirementV3(
        qos_class=QoSClass.LATENCY_CRITICAL, traffic_class=cls,
        latency_ceiling_cycles=ceiling, binding=True)


def _bandwidth_req(cls: str, floor: float) -> RequirementV3:
    return RequirementV3(
        qos_class=QoSClass.BANDWIDTH, traffic_class=cls,
        bandwidth_floor_gbps=floor, binding=True)


def _stats(cycles: int = 100) -> dict:
    return {
        "loaded_trace_packets": 20,
        "injected_trace_packets": 20,
        "delivered_packets": 20,
        "completion_cycles": cycles,
        "flits_injected": 300,
        "flits_accepted": 300,
        "flits_by_class": {
            0: {"injected": 100, "accepted": 100},
            1: {"injected": 200, "accepted": 200},
        },
        "latency_by_class": {
            0: {"packet_latency_avg": 10.0, "p99": 12.0},
            1: {"packet_latency_avg": 30.0, "p99": 40.0},
        },
    }


def _case(request: CompileRequestV4, *, stats: dict | None = None,
          classes: tuple[str, ...] = ("a0", "b0")):
    """(graph, verified result, stats, raw evidence, compilation)."""
    stats = _stats() if stats is None else stats
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    context = build_evaluation_context(compilation)
    resolved = compilation.bundle.resolved_fabric.resolved_fabric_hash
    raw = json.dumps({"placeholder": True}).encode()
    evidence_sha = hashlib.sha256(raw).hexdigest()
    graph = lower_compile_workload(request).graph
    model = PerformanceModel(
        clocks=(ClockDef("network", CLOCK_HZ),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    event = TemporalEvent("network_traffic_window",
                          EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero())
    temporal = TemporalWorkload(performance_model=model, events=(event,))
    chain = {
        "design_hash": request.design_hash(),
        "workload_graph_id": graph.workload_id(),
        "physical_traffic_id": "test-traffic",
        "resolved_fabric_hash": resolved,
    }
    binding = NetworkWindowBinding(
        workload_parent_id=graph.workload_id(), schema_version=2,
        physical_traffic_id="test-traffic",
        backend_config_hash="0" * 64, backend_input_hash="1" * 64,
        evidence_sha256=evidence_sha, stats_sha256=stats_sha256_of(stats),
        network_clock_hz=CLOCK_HZ, window_kind=WINDOW_KIND_BARRIER,
        duration=QTime.from_cycles(int(stats["completion_cycles"]),
                                   CLOCK_HZ))
    graph_obj = PerformanceEventGraph(
        workload=temporal, network_binding=binding, wave_d_chain=chain)
    schedule = schedule_workload(
        temporal, network_durations=graph_obj.network_durations())
    perf = build_performance_result(graph=graph_obj, schedule=schedule)
    block = build_traffic_class_metrics(
        stats=stats, class_names=classes,
        flit_width_bits=FLIT_WIDTH_BITS,
        evidence_sha256=evidence_sha, stats_sha256=stats_sha256_of(stats))
    if block is not None:
        perf["traffic_class_metrics"] = block
    return (graph, verify_performance_result(perf, workload=temporal),
            stats, raw, compilation)


def _entry(report: dict, index: int) -> dict:
    return next(e for e in report["entries"]
                if e["requirement_index"] == index)


def test_class_latency_satisfied_and_violated():
    request = _two_class_request(
        _latency_req("a0", 20), _latency_req("b0", 20))
    graph, verified, _stats_doc, _raw, _compilation = _case(request)
    report = RequirementEvaluator.evaluate(request, graph, verified)

    satisfied = _entry(report, 0)
    assert satisfied["verdict"] == "SATISFIED"
    assert satisfied["measured"] == 10.0
    assert "traffic_class_metrics.classes['a0']" in \
        satisfied["metric_authority"]

    violated = _entry(report, 1)
    assert violated["verdict"] == "VIOLATED"
    assert violated["measured"] == 30.0
    assert "class 'b0'" in violated["reason"]


def test_class_bandwidth_satisfied_and_violated():
    # 100 a0 flits * 64 bits / 8 = 800 bytes over 100 cycles at 1 GHz
    # (1e-7 s) = 8 Gbps.  b0: 1600 bytes / 1e-7 s = 16 Gbps.
    request = _two_class_request(
        _bandwidth_req("a0", 4), _bandwidth_req("b0", 20))
    graph, verified, _stats_doc, _raw, _compilation = _case(request)
    report = RequirementEvaluator.evaluate(request, graph, verified)

    satisfied = _entry(report, 0)
    assert satisfied["verdict"] == "SATISFIED"
    assert satisfied["measured"] == pytest.approx(8.0)
    assert "bytes_accepted" in satisfied["metric_authority"]

    violated = _entry(report, 1)
    assert violated["verdict"] == "VIOLATED"
    assert violated["measured"] == pytest.approx(16.0)


def test_a_missing_class_is_unmeasurable_not_zero_filled():
    request = _two_class_request(
        _latency_req("a0", 20), _latency_req("b0", 50),
        _bandwidth_req("b0", 1))
    stats = _stats() | {
        "flits_by_class": {
            0: {"injected": 100, "accepted": 100},
        },
        "latency_by_class": {0: {"packet_latency_avg": 10.0}},
    }
    graph, verified, _stats_doc, _raw, _compilation = _case(
        request, stats=stats)
    report = RequirementEvaluator.evaluate(request, graph, verified)

    # a0 has its own reading.
    assert _entry(report, 0)["verdict"] == "SATISFIED"
    # b0 has no latency row: the aggregate window (100 cycles) still
    # bounds it, and 100 > 50 so the honest verdict is UNMEASURABLE.
    missing_latency = _entry(report, 1)
    assert missing_latency["verdict"] == "UNMEASURABLE"
    assert missing_latency["measured"] == 100.0
    assert "aggregate" in missing_latency["reason"]
    # b0 has no counters either: its bandwidth is not zero, it is absent.
    missing_bandwidth = _entry(report, 2)
    assert missing_bandwidth["verdict"] == "UNMEASURABLE"
    assert missing_bandwidth["measured"] is None


def test_an_aggregate_only_result_keeps_the_old_class_semantics():
    request = _two_class_request(
        _latency_req("a0", 200), _latency_req("b0", 50),
        _bandwidth_req("a0", 1))
    stats = _stats()
    stats.pop("flits_by_class")
    stats.pop("latency_by_class")
    graph, verified, _stats_doc, _raw, _compilation = _case(
        request, stats=stats)
    assert "traffic_class_metrics" not in verified
    report = RequirementEvaluator.evaluate(request, graph, verified)

    # Aggregate completion 100 <= 200 is a sound upper bound: SATISFIED.
    assert _entry(report, 0)["verdict"] == "SATISFIED"
    # Aggregate completion 100 > 50 cannot be attributed to b0.
    assert _entry(report, 1)["verdict"] == "UNMEASURABLE"
    # No per-class bytes at all.
    assert _entry(report, 2)["verdict"] == "UNMEASURABLE"
    assert _entry(report, 2)["measured"] is None


def test_the_federated_normalization_attaches_two_class_evidence(
        tmp_path):
    request = _two_class_request(
        _latency_req("b0", 20), _bandwidth_req("a0", 4))
    stats = _stats()
    compilation = FabricCompiler().compile(request)
    context = build_evaluation_context(compilation)
    adapter = BookSimAdapter()
    native = adapter._prepare_native(
        context, NETWORK, traffic_class=context.unified_traffic_class)
    evidence = ScientificBackendEvidence(
        prepared_id=native.realization_digest, profile_id=native.profile_id,
        projection_semantics_version="booksim2-fork/v2",
        config_sha256=native.config_hash, trace_sha256=native.input_hash,
        topology_sha256=None,
        resolved_fabric_hash=compilation.bundle.resolved_fabric
        .resolved_fabric_hash,
        physical_traffic_id=native.physical_traffic_id,
        message_artifact_id=native.message_artifact_id,
        binary_sha256=hashlib.sha256(b"binary").hexdigest(), binary_size=1,
        producer_source_revision="abc", producer_dirty=False,
        seed=native.prepared.seed, parser_version=PARSER_VERSION,
        execution_fidelity="QUALIFIED",
        route_observation="EXECUTED_ROUTE_OBSERVED", stats=stats,
        exit_status=0, transport="SUPERVISED_PROCESS",
        build_manifest_sha256=hashlib.sha256(b"manifest").hexdigest(),
        build_recipe_version=BOOKSIM_BUILD_RECIPE_VERSION,
        route_dump_sha256=hashlib.sha256(b"route").hexdigest())
    ref = write_evidence(tmp_path, evidence.to_dict())
    graph = lower_compile_workload(request).graph
    model = PerformanceModel(
        clocks=(ClockDef("network", CLOCK_HZ),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    temporal = TemporalWorkload(
        performance_model=model,
        events=(TemporalEvent("network_traffic_window",
                              EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero()),))
    binding = NetworkWindowBinding(
        workload_parent_id=graph.workload_id(), schema_version=2,
        physical_traffic_id=native.physical_traffic_id,
        backend_config_hash=native.config_hash,
        backend_input_hash=native.input_hash,
        evidence_sha256=ref.sha256, stats_sha256=stats_sha256_of(stats),
        network_clock_hz=CLOCK_HZ, window_kind=WINDOW_KIND_BARRIER,
        duration=QTime.from_cycles(100, CLOCK_HZ))
    chain = {
        "design_hash": request.design_hash(),
        "workload_graph_id": graph.workload_id(),
        "physical_traffic_id": native.physical_traffic_id,
        "resolved_fabric_hash":
            compilation.bundle.resolved_fabric.resolved_fabric_hash,
    }
    graph_obj = PerformanceEventGraph(
        workload=temporal, network_binding=binding, wave_d_chain=chain)
    schedule = schedule_workload(
        temporal, network_durations=graph_obj.network_durations())
    perf = verify_performance_result(
        build_performance_result(graph=graph_obj, schedule=schedule),
        workload=temporal)
    outcome = EvaluationOutcome(
        status="EVALUATED", design_hash=context.design_hash,
        resolved_fabric_hash=chain["resolved_fabric_hash"],
        workload_id=context.workload_id,
        message_artifact_id=native.message_artifact_id,
        physical_traffic_id=native.physical_traffic_id,
        backend_config_hash=native.config_hash,
        backend_input_hash=native.input_hash,
        realization_digest=native.realization_digest,
        producer_identity=evidence.binary_sha256,
        raw_evidence_digest=ref.sha256, stats_digest=stats_sha256_of(stats),
        evidence_path=ref.path, performance_result=perf)
    normalize_booksim_outcome(context, outcome)

    block = outcome.performance_result["traffic_class_metrics"]
    assert [row["traffic_class"] for row in block["classes"]] == \
        ["a0", "b0"]
    assert block["flit_width_bits"] == \
        native.physical_traffic.packet_format.flit_width_bits

    report = RequirementEvaluator.evaluate(
        request, context.workload, outcome.performance_result)
    # b0's own packet latency is 30 cycles > 20 (VIOLATED); a0's own
    # 800 bytes / 1e-7 s = 8 Gbps >= 4 (SATISFIED).
    assert _entry(report, 0)["verdict"] == "VIOLATED"
    assert _entry(report, 0)["measured"] == 30.0
    assert _entry(report, 1)["verdict"] == "SATISFIED"
    assert _entry(report, 1)["measured"] == pytest.approx(8.0)


def test_authentication_derives_class_metrics_from_evidence(tmp_path):
    request = _two_class_request(
        _latency_req("a0", 20), _latency_req("b0", 20))
    stats = _stats()
    compilation = FabricCompiler().compile(request)
    context = build_evaluation_context(compilation)
    adapter = BookSimAdapter()
    native = adapter._prepare_native(
        context, NETWORK, traffic_class=context.unified_traffic_class)
    evidence = ScientificBackendEvidence(
        prepared_id=native.realization_digest, profile_id=native.profile_id,
        projection_semantics_version="booksim2-fork/v2",
        config_sha256=native.config_hash, trace_sha256=native.input_hash,
        topology_sha256=None,
        resolved_fabric_hash=compilation.bundle.resolved_fabric
        .resolved_fabric_hash,
        physical_traffic_id=native.physical_traffic_id,
        message_artifact_id=native.message_artifact_id,
        binary_sha256=hashlib.sha256(b"binary").hexdigest(), binary_size=1,
        producer_source_revision="abc", producer_dirty=False,
        seed=native.prepared.seed, parser_version=PARSER_VERSION,
        execution_fidelity="QUALIFIED",
        route_observation="EXECUTED_ROUTE_OBSERVED", stats=stats,
        exit_status=0, transport="SUPERVISED_PROCESS",
        build_manifest_sha256=hashlib.sha256(b"manifest").hexdigest(),
        build_recipe_version=BOOKSIM_BUILD_RECIPE_VERSION,
        route_dump_sha256=hashlib.sha256(b"route").hexdigest())
    ref = write_evidence(tmp_path, evidence.to_dict())
    graph = lower_compile_workload(request).graph
    model = PerformanceModel(
        clocks=(ClockDef("network", CLOCK_HZ),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    temporal = TemporalWorkload(
        performance_model=model,
        events=(TemporalEvent("network_traffic_window",
                              EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero()),))
    binding = NetworkWindowBinding(
        workload_parent_id=graph.workload_id(), schema_version=2,
        physical_traffic_id=native.physical_traffic_id,
        backend_config_hash=native.config_hash,
        backend_input_hash=native.input_hash,
        evidence_sha256=ref.sha256, stats_sha256=stats_sha256_of(stats),
        network_clock_hz=CLOCK_HZ, window_kind=WINDOW_KIND_BARRIER,
        duration=QTime.from_cycles(100, CLOCK_HZ))
    chain = {
        "design_hash": request.design_hash(),
        "workload_graph_id": graph.workload_id(),
        "physical_traffic_id": native.physical_traffic_id,
        "resolved_fabric_hash":
            compilation.bundle.resolved_fabric.resolved_fabric_hash,
    }
    graph_obj = PerformanceEventGraph(
        workload=temporal, network_binding=binding, wave_d_chain=chain)
    schedule = schedule_workload(
        temporal, network_durations=graph_obj.network_durations())
    perf = verify_performance_result(
        build_performance_result(graph=graph_obj, schedule=schedule),
        workload=temporal)
    proof = authenticate_backend_evaluation(
        compilation=compilation, workload=graph, verified_result=perf,
        evidence_path=ref.path,
        producer_identity=evidence.binary_sha256)
    report = proof.requirement_report
    assert _entry(report, 0)["verdict"] == "SATISFIED"
    assert _entry(report, 1)["verdict"] == "VIOLATED"

    # The consumption-time re-proof reopens the evidence, re-derives the
    # class readings from its stats, and returns the same report.
    claims = verify_authenticated_backend_evaluation(request, proof)
    assert _entry(claims.requirement_report, 0)["verdict"] == "SATISFIED"
    assert _entry(claims.requirement_report, 1)["verdict"] == "VIOLATED"
