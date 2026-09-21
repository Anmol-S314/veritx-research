"""P1 RT-4 / RT-6: caller clock must not rescale cycles verdicts.

FabricEvaluator converts BookSim completion cycles -> wall seconds with
the CALLER's EvaluationOptions.network_clock_hz. RequirementEvaluator
used to convert those seconds back to cycles with the DESIGN's
default_clock_freq_mhz, so a 2x caller clock halved the "measured
cycles" with no fabric change. The cycles path now reads the
AUTHENTICATED cycles: the bound network window records the exact pair
(duration seconds, network_clock_hz) produced by completion_time /
network_clock_hz, so their product is the backend's integer
completion_time and the caller clock cancels.

RT-6 lesson pinned here too: FabricEvaluator never produces the
impossible state EVALUATED + cycles_only + wall_time null — without a
valid clock the outcome is UNSUPPORTED with a cycles-only window and NO
PerformanceResult, so a fixture cannot drift back into that state.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1_clock_semantics.py -q
"""
from __future__ import annotations

import json
from fractions import Fraction

import pytest

from veritx_dse.application.fabric_evaluator import (
    EVALUATED,
    UNSUPPORTED,
    EvaluationOptions,
    FabricEvaluator,
)
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_passes,
)
from veritx_dse.core.errors import EvidenceInvalid
from veritx_dse.core.paths import REPO
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
    WorkloadV3,
)
from veritx_dse.performance.model import (
    ClockDef,
    PerformanceModel,
    ResourceDef,
)
from veritx_dse.performance.network import (
    NetworkWindowBinding,
    bind_network_window,
)
from veritx_dse.performance.result import (
    PerformanceEventGraph,
    build_performance_result,
    reverify_result,
)
from veritx_dse.performance.scheduler import schedule_workload
from veritx_dse.performance.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW,
    TemporalEvent,
    TemporalWorkload,
)
from veritx_dse.simulation.booksim import find_booksim_bin
from veritx_dse.workload.intent_lowering import lower_compile_workload

DESIGN_HZ = 10 ** 9          # the request's own clock: 1000 MHz
COMPLETION_CYCLES = 16161    # the backend's authenticated integer cycles


def _request(*, ceiling):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            tp=4, dp=2,
            serving_mode=ServingMode.MIXED,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=8192,
                traffic_class="tp_collective"),)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=ceiling, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=8),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


class _Evidence:
    """Minimal stand-in carrying BookSim stats for bind_network_window."""

    def __init__(self, completion_time):
        self.stats = {"completion_time": completion_time,
                      "delivered": 683, "pkt_count": 683}


def _verified_window_doc(request, *, completion_cycles, caller_clock_hz):
    """A verified PerformanceResult for one window, exactly as the P1B
    evaluator builds it (same event, model, binding, chain, reverify)."""
    lw = lower_compile_workload(request)
    chain = {"chain_schema_version": 2,
             "workload_graph_id": lw.graph.workload_id(),
             "physical_traffic_id": "pt",
             "backend_config_hash": "c", "backend_input_hash": "i"}
    binding, _window = bind_network_window(
        evidence=_Evidence(completion_cycles), chain=chain,
        network_clock_hz=caller_clock_hz, evidence_sha256="e" * 64)
    model = PerformanceModel(
        clocks=(ClockDef("network", caller_clock_hz),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    temporal = TemporalWorkload(
        performance_model=model,
        events=(TemporalEvent("network_traffic_window",
                              EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero()),))
    graph = PerformanceEventGraph(
        workload=temporal,
        network_binding=NetworkWindowBinding.from_dict(binding.to_dict()),
        wave_d_chain={"workload_graph_id": lw.graph.workload_id(),
                      "design_hash": request.design_hash(),
                      "physical_traffic_id": "pt"})
    schedule = schedule_workload(
        temporal, network_durations=graph.network_durations())
    result = build_performance_result(graph=graph, schedule=schedule)
    reverify_result(result, workload=temporal)
    return lw.graph, result


def _measured(request, caller_factor):
    graph, result = _verified_window_doc(
        request, completion_cycles=COMPLETION_CYCLES,
        caller_clock_hz=DESIGN_HZ * Fraction(caller_factor))
    report = RequirementEvaluator.evaluate(request, graph, result)
    return report["entries"][0], result


class TestCallerClockInvariance:
    @pytest.mark.parametrize("factor", [Fraction(1, 2), Fraction(1), 2])
    def test_identical_measured_cycles_at_half_and_double_clock(self, factor):
        request = _request(ceiling=100000.0)
        entry, _ = _measured(request, factor)
        assert entry["verdict"] == "SATISFIED"
        # The backend's authenticated cycles, not a caller-clock image.
        assert entry["measured"] == float(COMPLETION_CYCLES)

    def test_measured_and_verdict_identical_across_clocks(self):
        request = _request(ceiling=100000.0)
        entries = [_measured(request, f)[0]
                   for f in (Fraction(1, 2), Fraction(1), 2)]
        assert {e["measured"] for e in entries} == \
            {float(COMPLETION_CYCLES)}
        assert {e["verdict"] for e in entries} == {"SATISFIED"}
        assert {e["metric_authority"] for e in entries} == \
            {entries[0]["metric_authority"]}

    def test_violation_verdict_is_also_clock_invariant(self):
        request = _request(ceiling=10000.0)   # below 16161 cycles
        for factor in (Fraction(1, 2), Fraction(1), 2):
            entry, _ = _measured(request, factor)
            assert entry["verdict"] == "VIOLATED"
            assert entry["measured"] == float(COMPLETION_CYCLES)
            assert entry["binding"] is True

    def test_report_measured_equals_backend_authenticated_cycles(self):
        request = _request(ceiling=100000.0)
        for factor in (Fraction(1, 2), Fraction(1), 2):
            graph, result = _verified_window_doc(
                request, completion_cycles=COMPLETION_CYCLES,
                caller_clock_hz=DESIGN_HZ * factor)
            # The binding is the authenticated source; its exact product
            # must be the backend's integer completion_time (no rescale).
            binding = result["network_binding"]
            seconds = Fraction(binding["duration"]["numerator"],
                               binding["duration"]["denominator"])
            hz = Fraction(binding["network_clock_hz"]["num"],
                          binding["network_clock_hz"]["den"])
            assert seconds * hz == COMPLETION_CYCLES
            report = RequirementEvaluator.evaluate(request, graph, result)
            entry = report["entries"][0]
            assert entry["measured"] == float(COMPLETION_CYCLES)
            assert "authenticated" in entry["metric_authority"]
            assert "default_clock_freq_mhz" not in entry["metric_authority"]

    def test_wall_duration_actually_moves_with_caller_clock(self):
        """Guard against a test that proves invariance by ignoring the
        clock: the persisted wall duration must scale."""
        request = _request(ceiling=100000.0)
        _, slow = _verified_window_doc(
            request, completion_cycles=COMPLETION_CYCLES,
            caller_clock_hz=DESIGN_HZ * Fraction(1, 2))
        _, fast = _verified_window_doc(
            request, completion_cycles=COMPLETION_CYCLES,
            caller_clock_hz=DESIGN_HZ * 2)
        slow_s = Fraction(slow["network_binding"]["duration"]["numerator"],
                          slow["network_binding"]["duration"]["denominator"])
        fast_s = Fraction(fast["network_binding"]["duration"]["numerator"],
                          fast["network_binding"]["duration"]["denominator"])
        assert slow_s == 4 * fast_s


class TestWallTimeRefuses:
    def test_duration_without_its_clock_refuses(self):
        """A wall duration without the clock that produced it cannot
        authenticate cycles — refuse, never rescale with the design clock."""
        request = _request(ceiling=100000.0)
        graph, result = _verified_window_doc(
            request, completion_cycles=COMPLETION_CYCLES,
            caller_clock_hz=DESIGN_HZ)
        result = json.loads(json.dumps(result))
        result["network_binding"]["network_clock_hz"] = None
        with pytest.raises(EvidenceInvalid) as ei:
            RequirementEvaluator.evaluate(request, graph, result)
        assert "clock" in str(ei.value)

    def test_non_integral_cycle_product_refuses(self):
        """BookSim completion_time is integral; a (duration, clock) pair
        that does not reconstruct one is not the authenticated window."""
        request = _request(ceiling=100000.0)
        graph, result = _verified_window_doc(
            request, completion_cycles=COMPLETION_CYCLES,
            caller_clock_hz=DESIGN_HZ)
        result = json.loads(json.dumps(result))
        # duration = 1/3 s at 1e9 Hz -> 1e9/3 cycles: not integral.
        result["network_binding"]["duration"] = \
            QTime.from_seconds(Fraction(1, 3)).to_dict()
        with pytest.raises(EvidenceInvalid) as ei:
            RequirementEvaluator.evaluate(request, graph, result)
        assert "integer cycle" in str(ei.value)


class TestRealBackendAuthenticatedCycles:
    """The real BookSim chain: the report's measured cycles ARE the
    outcome's authenticated window_cycles, at ANY caller clock."""

    @pytest.mark.parametrize(
        "caller_clock",
        [DESIGN_HZ * Fraction(1, 2), DESIGN_HZ * 2])
    def test_report_measured_equals_window_cycles(self, tmp_path, caller_clock):
        request = _llama_request()
        prod = evaluate_product(
            request, binary=str(find_booksim_bin(REPO)),
            run_dir=str(tmp_path / "run"),
            network_clock_hz=caller_clock, timeout_s=900)
        assert prod.status == EVALUATED, prod.reason
        window_cycles = prod.outcome.network_traffic_window["window_cycles"]
        assert isinstance(window_cycles, int) and window_cycles > 0
        (entry,) = prod.requirement_report["entries"]
        assert entry["measured"] == float(window_cycles)
        assert entry["verdict"] == "SATISFIED"
        assert "authenticated" in entry["metric_authority"]

    def test_half_and_double_clock_agree_with_each_other(self, tmp_path):
        request = _llama_request()
        measured = {}
        for name, caller_clock in (("half", DESIGN_HZ * Fraction(1, 2)),
                                   ("double", DESIGN_HZ * 2)):
            prod = evaluate_product(
                request, binary=str(find_booksim_bin(REPO)),
                run_dir=str(tmp_path / name),
                network_clock_hz=caller_clock, timeout_s=900)
            assert prod.status == EVALUATED, prod.reason
            measured[name] = prod.requirement_report["entries"][0]["measured"]
        assert measured["half"] == measured["double"]


def _llama_request():
    fixture = (REPO / "tracks" / "t3-topology" / "examples" /
               "llama_dense_64tiles-v3.json")
    return CompileRequestV3.from_dict(json.loads(fixture.read_text()))


class TestNoClockImpossibleState:
    """RT-6 lesson: EVALUATED + cycles_only + wall_time null is NOT a
    state FabricEvaluator can produce — pin the refusal."""

    def test_no_clock_is_unsupported_cycles_only_without_result(self, tmp_path):
        request = _llama_request()
        binary = find_booksim_bin(REPO)
        prod = evaluate_product(
            request, binary=str(binary), run_dir=str(tmp_path / "run"),
            network_clock_hz=None, timeout_s=900)
        assert prod.status == UNSUPPORTED
        outcome = prod.outcome
        assert outcome is not None
        window = outcome.network_traffic_window
        assert window["cycles_only"] is True
        assert window["wall_time_ns"] is None
        assert isinstance(window["window_cycles"], int) and \
            window["window_cycles"] > 0
        # The impossible combination: no PerformanceResult, no report.
        assert outcome.status != EVALUATED
        assert outcome.performance_result is None
        assert prod.requirement_report is None
        assert prod.requirements_pass is None

    def test_no_clock_manager_directly_refuses_wall_time(self, tmp_path):
        """Same pin at the FabricEvaluator boundary (the orchestrator
        must not be the only thing standing between the states)."""
        request = _llama_request()
        from veritx_dse.application.fabric_compiler import FabricCompiler
        from veritx_dse.workload.intent_lowering import (
            lower_compile_workload,
        )
        compilation = FabricCompiler().compile(request)
        assert compilation.status == "COMPILED"
        lowered = lower_compile_workload(request)
        outcome = FabricEvaluator().evaluate(
            compilation, lowered.graph,
            EvaluationOptions(
                binary=str(find_booksim_bin(REPO)),
                run_dir=str(tmp_path / "run2"),
                traffic_class=lowered.unified_traffic_class,
                network_clock_hz=None, timeout_s=900))
        assert outcome.status == UNSUPPORTED
        assert outcome.network_traffic_window == {
            "window_cycles": outcome.network_traffic_window["window_cycles"],
            "wall_time_ns": None, "cycles_only": True}
        assert outcome.performance_result is None
