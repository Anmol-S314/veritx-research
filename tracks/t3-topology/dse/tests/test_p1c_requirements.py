"""P1C requirements tests: verdict matrix over verified fixture results.

Fixtures are built through the REAL authorities (PerformanceModel +
TemporalWorkload + NetworkWindowBinding + schedule_workload +
build_performance_result + reverify_result) — never hand-signed docs.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1c_requirements.py -q
"""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from veritx_dse.core.errors import InvalidInput, MappingInvalid
from veritx_dse.core.time import QTime
from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    QoSClass,
    RequirementV3,
    ServingMode,
    TopologyFamily,
    Workload,
    WorkloadV3,
)
from veritx_dse.performance.model import (
    ClockDef,
    PerformanceModel,
    ResourceDef,
)
from veritx_dse.performance.network import NetworkWindowBinding
from veritx_dse.performance.result import (
    PerformanceEventGraph,
    build_performance_result,
    reverify_result,
)
from veritx_dse.performance.scheduler import schedule_workload
from veritx_dse.performance.workload import (
    TemporalEvent,
    TemporalWorkload,
)
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_passes,
)
from veritx_dse.workload.intent_lowering import lower_compile_workload

US = 10 ** 6
NET_HZ = 10 ** 9


def _model(with_bandwidth=True):
    resources = [ResourceDef("gpu.compute", "EXCLUSIVE", capacity=1)]
    if with_bandwidth:
        resources.append(ResourceDef("hbm", "BANDWIDTH",
                                     bandwidth_bytes_per_s=1200))
    return PerformanceModel(
        clocks=(ClockDef("net", NET_HZ),), resources=tuple(resources),
        memory_source="ANALYTICAL_BANDWIDTH", network_clock="net")


def _net_workload(model, with_memory=False):
    events = [TemporalEvent("K", "COMPUTE", QTime(4000, US), "gpu.compute"),
              TemporalEvent("NET", "NETWORK_TRAFFIC_WINDOW", QTime(0),
                            deps=("K",))]
    if with_memory:
        events.append(TemporalEvent("RD", "MEMORY_READ", QTime(0), "hbm",
                                    deps=("K",), bytes_count=4800))
        tail_deps = ("K", "NET", "RD")
    else:
        tail_deps = ("K", "NET")
    events.append(TemporalEvent("TAIL", "COMPUTE", QTime(1000, US),
                                "gpu.compute", deps=tail_deps))
    return TemporalWorkload(performance_model=model, events=tuple(events),
                            wave_d_operation_ids=("op1",))


def _result(workload, window_us):
    """Verified result with a window of window_us."""
    binding = NetworkWindowBinding(
        workload_parent_id="w", physical_traffic_id="pt",
        backend_config_hash="c", backend_input_hash="i",
        evidence_sha256="e", stats_sha256="s",
        network_clock_hz=NET_HZ, duration=QTime(window_us, US))
    graph = PerformanceEventGraph(workload=workload, network_binding=binding)
    schedule = schedule_workload(
        workload, network_durations={"NET": QTime(window_us, US)})
    res = build_performance_result(graph=graph, schedule=schedule)
    reverify_result(res, workload=workload)
    return res


def _request(collectives, requirements, tp=2, dp=1, pp=1, ep=1):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            tp=tp, dp=dp, pp=pp, ep=ep,
            serving_mode=ServingMode.MIXED,
            collectives=tuple(collectives)),
        requirements=tuple(requirements),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE,
                      count=tp * dp * pp * ep),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _ci(kind="allreduce", dim="TP", payload=2048, tc="tp_collective"):
    return CollectiveIntent(kind=CollectiveKind(kind),
                            dimension=CollectiveDimension(dim),
                            payload_bytes=payload, traffic_class=tc)


def _lat_req(ceiling, binding=True, tc="tp_collective"):
    return RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                         traffic_class=tc, latency_ceiling_cycles=ceiling,
                         binding=binding)


def _schema():
    root = Path(__file__).resolve()
    for parent in [root.parent] + list(root.parent.parents):
        cand = parent / "contracts" / "srota" / "v1" / \
            "requirement.report.schema.json"
        if cand.is_file():
            return json.loads(cand.read_text())
    # dse-root-relative fallback (tests run from tracks/t3-topology/dse)
    cand = Path("..") / ".." / ".." / "contracts" / "srota" / "v1" / \
        "requirement.report.schema.json"
    return json.loads(cand.read_text())


def _check_contract(report):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(_schema()).validate(report)


class TestLatencyVerdicts:
    def test_satisfied_from_window_duration(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)])
        lw = lower_compile_workload(req)
        rep = RequirementEvaluator.evaluate(req, lw.graph, res)
        (entry,) = rep["entries"]
        assert entry["verdict"] == "SATISFIED"
        assert entry["measured"] == pytest.approx(2.5 * 10 ** 6)  # 1GHz
        assert entry["performance_result_id"] == res["resource_id"]
        assert rep["design_hash"] == "sha256:" + req.design_hash()
        _check_contract(rep)
        assert report_passes(rep)

    def test_violated_fabric_wide(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL, traffic_class=None,
            latency_ceiling_cycles=1000, binding=True)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        assert rep["entries"][0]["verdict"] == "VIOLATED"
        assert not report_passes(rep)
        _check_contract(rep)

    def test_makespan_fallback_without_network_binding(self):
        # Compute-only temporal workload: no window event, no binding.
        # The verified result carries makespan only; latency measures
        # against it (conservative superset, stated in the authority).
        model = _model(with_bandwidth=False)
        workload = TemporalWorkload(
            performance_model=model,
            events=(TemporalEvent("K", "COMPUTE", QTime(4000, US),
                                   "gpu.compute"),),
            wave_d_operation_ids=("op1",))
        graph = PerformanceEventGraph(workload=workload)
        schedule = schedule_workload(workload)
        res = build_performance_result(graph=graph, schedule=schedule)
        reverify_result(res, workload=workload)
        assert res["network_binding"] is None
        req = _request([_ci()], [_lat_req(ceiling=10 ** 12)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        entry = rep["entries"][0]
        assert entry["verdict"] == "SATISFIED"
        assert "makespan" in entry["metric_authority"]
        _check_contract(rep)

    def test_multi_class_excess_is_unmeasurable_not_violated(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request(
            [_ci(tc="tp_collective"),
             CollectiveIntent(kind=CollectiveKind.ALLGATHER,
                              dimension=CollectiveDimension.DP,
                              payload_bytes=1024,
                              traffic_class="dp_collective")],
            [_lat_req(ceiling=1000, binding=True)], tp=2, dp=2)
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        entry = rep["entries"][0]
        assert entry["verdict"] == "UNMEASURABLE"
        assert not report_passes(rep)  # binding + UNMEASURABLE never passes
        _check_contract(rep)

    def test_multi_class_satisfied_still_passes(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request(
            [_ci(tc="tp_collective"),
             CollectiveIntent(kind=CollectiveKind.ALLGATHER,
                              dimension=CollectiveDimension.DP,
                              payload_bytes=1024,
                              traffic_class="dp_collective")],
            [_lat_req(ceiling=10 ** 9, binding=True)], tp=2, dp=2)
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        assert rep["entries"][0]["verdict"] == "SATISFIED"
        assert report_passes(rep)


class TestBandwidthVerdicts:
    def test_violated_without_bytes(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [RequirementV3(
            qos_class=QoSClass.BANDWIDTH, traffic_class="tp_collective",
            bandwidth_floor_gbps=0.0001, binding=False)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        entry = rep["entries"][0]
        # hbm moved 0 bytes here: 0 < floor is a real measurement.
        assert entry["verdict"] == "VIOLATED"
        assert report_passes(rep)  # non-binding: advisory only
        _check_contract(rep)

    def test_unmeasurable_without_bandwidth_resource(self):
        res = _result(_net_workload(_model(with_bandwidth=False)),
                      window_us=2500)
        req = _request([_ci()], [RequirementV3(
            qos_class=QoSClass.BANDWIDTH, bandwidth_floor_gbps=1.0,
            binding=True)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        assert rep["entries"][0]["verdict"] == "UNMEASURABLE"
        assert not report_passes(rep)
        _check_contract(rep)

    def test_satisfied_with_moved_bytes(self):
        res = _result(_net_workload(_model(), with_memory=True),
                      window_us=2500)
        req = _request([_ci()], [RequirementV3(
            qos_class=QoSClass.BANDWIDTH, bandwidth_floor_gbps=1e-9,
            binding=True)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        entry = rep["entries"][0]
        assert entry["verdict"] == "SATISFIED"
        assert entry["measured"] > 0
        _check_contract(rep)

    def test_class_scoped_multi_class_unmeasurable(self):
        res = _result(_net_workload(_model(), with_memory=True),
                      window_us=2500)
        req = _request(
            [_ci(tc="tp_collective"),
             CollectiveIntent(kind=CollectiveKind.ALLGATHER,
                              dimension=CollectiveDimension.DP,
                              payload_bytes=1024,
                              traffic_class="dp_collective")],
            [RequirementV3(qos_class=QoSClass.BANDWIDTH,
                           traffic_class="dp_collective",
                           bandwidth_floor_gbps=1e-9, binding=True)],
            tp=2, dp=2)
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        assert rep["entries"][0]["verdict"] == "UNMEASURABLE"
        assert not report_passes(rep)


class TestShapesAndRefusals:
    def test_not_applicable_without_thresholds(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [RequirementV3(
            qos_class=QoSClass.BEST_EFFORT, binding=False)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        entry = rep["entries"][0]
        assert entry["verdict"] == "NOT_APPLICABLE"
        assert entry["required"] is None and entry["measured"] is None
        assert report_passes(rep)
        _check_contract(rep)

    def test_dual_threshold_entry(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            latency_ceiling_cycles=10 ** 9,
            bandwidth_floor_gbps=10 ** 9, binding=True)])
        rep = RequirementEvaluator.evaluate(
            req, lower_compile_workload(req).graph, res)
        entry = rep["entries"][0]
        assert entry["verdict"] == "VIOLATED"  # bandwidth fails
        assert isinstance(entry["required"], str)
        assert isinstance(entry["measured"], str)
        _check_contract(rep)

    def test_unknown_class_scope_refuses(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9, tc="ghost")])
        with pytest.raises(InvalidInput):
            RequirementEvaluator.evaluate(
                req, lower_compile_workload(req).graph, res)

    def test_geometry_mismatch_refuses(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        other = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=4, dp=1)
        with pytest.raises(MappingInvalid):
            RequirementEvaluator.evaluate(
                req, lower_compile_workload(other).graph, res)

    def test_non_v3_request_refuses(self):
        from veritx_dse.workload.canonical_graph import WorkloadGraph
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)])
        graph = lower_compile_workload(req).graph
        v2 = Workload(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, dp=1)
        from veritx_dse.model.compile_model import (
            CompileRequest, AgentKind, Agent, DependencyGraph, NocConfig)
        v2req = CompileRequest(
            workload=v2, requirements=(), agents=(
                Agent(kind=AgentKind.COMPUTE_TILE, count=1),),
            dependencies=DependencyGraph([]), noc_config=NocConfig())
        with pytest.raises(InvalidInput):
            RequirementEvaluator.evaluate(v2req, graph, res)

    def test_missing_result_identity_refuses(self):
        res = _result(_net_workload(_model()), window_us=2500)
        del res["resource_id"]
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)])
        with pytest.raises(InvalidInput):
            RequirementEvaluator.evaluate(
                req, lower_compile_workload(req).graph, res)

    def test_evaluate_is_deterministic(self):
        res = _result(_net_workload(_model()), window_us=2500)
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)])
        graph = lower_compile_workload(req).graph
        assert RequirementEvaluator.evaluate(req, graph, res) == \
            RequirementEvaluator.evaluate(req, graph, res)


class TestMeshDenseEndToEnd:
    """EXIT: v3 request -> WorkloadGraph -> fixture result -> report."""

    def test_dense_8npu_end_to_end(self):
        req = _request(
            [CollectiveIntent(kind=CollectiveKind.ALLREDUCE,
                              dimension=CollectiveDimension.TP,
                              payload_bytes=8192,
                              traffic_class="tp_collective")],
            [RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                           traffic_class="tp_collective",
                           latency_ceiling_cycles=10 ** 9, binding=True)],
            tp=4, dp=2)
        lowered = lower_compile_workload(req)
        assert lowered.graph.participant_count == 8
        assert len(lowered.graph.of_kind("COLLECTIVE")) == 2
        res = _result(_net_workload(_model()), window_us=2500)
        rep = RequirementEvaluator.evaluate(req, lowered.graph, res)
        _check_contract(rep)
        assert rep["entries"][0]["verdict"] == "SATISFIED"
        assert report_passes(rep)
