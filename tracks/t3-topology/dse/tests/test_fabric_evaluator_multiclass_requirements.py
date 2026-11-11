"""Direct FabricEvaluator results carry class-scoped requirement evidence.

The catalog path re-derives per-class readings from authenticated evidence
in ``authenticated_evaluation._ensure_traffic_class_metrics``. These tests
pin that the direct ``FabricEvaluator``/``evaluate_product`` path now uses
the SAME authority: a real multi-class BookSim run attaches the
digest-bound class block, class-scoped latency/bandwidth requirements
measure each class, and a missing canonical map or class row stays
honestly UNMEASURABLE instead of being zero-filled or blamed on a class.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from tools.sweep_intent_knobs import baseline  # noqa: E402
from veritx_dse.application import evaluation_context  # noqa: E402
from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    BACKEND_UNAVAILABLE, EVALUATED, EvaluationOptions, FabricEvaluator,
)
from veritx_dse.application.product_evaluator import evaluate_product  # noqa: E402
from veritx_dse.application.requirements import RequirementEvaluator  # noqa: E402
from veritx_dse.backend import booksim_adapter  # noqa: E402
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    normalize_booksim_outcome,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import QoSClass, RequirementV3  # noqa: E402
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402

CLOCK_HZ = 1_000_000_000
_DIRTY_MARKERS = ("producer tree is DIRTY", "no verified build-time manifest")


@pytest.fixture(scope="module")
def binary() -> Path:
    try:
        return find_booksim_bin(REPO)
    except FileNotFoundError as exc:
        pytest.skip(f"no qualified BookSim producer: {exc}")


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


def _latency_req(cls: str, ceiling: float,
                 qos: QoSClass = QoSClass.LATENCY_CRITICAL) -> RequirementV3:
    return RequirementV3(
        qos_class=qos, traffic_class=cls,
        latency_ceiling_cycles=ceiling, binding=True)


def _bandwidth_req(cls: str, floor: float,
                   qos: QoSClass = QoSClass.LATENCY_CRITICAL
                   ) -> RequirementV3:
    return RequirementV3(
        qos_class=qos, traffic_class=cls,
        bandwidth_floor_gbps=floor, binding=True)


def _skip_or_fail(status: str, reason: str | None) -> None:
    if status == EVALUATED:
        return
    text = reason or ""
    if status == BACKEND_UNAVAILABLE and any(
            marker in text for marker in _DIRTY_MARKERS):
        pytest.skip(f"pinned producer unqualified in this worktree: {text}")
    pytest.fail(f"direct evaluation did not run: {status}: {text}")


def _evaluate(tmp_path: Path, request: CompileRequestV4, binary: Path, *,
              traffic_class: str = "DEFAULT"):
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    lowered = lower_compile_workload(request)
    outcome = FabricEvaluator().evaluate(
        compilation, lowered.graph,
        EvaluationOptions(
            binary=binary, repo_root=str(REPO),
            network_clock_hz=CLOCK_HZ, timeout_s=600,
            traffic_class=traffic_class,
            run_dir=str(tmp_path / "eval")))
    _skip_or_fail(outcome.status, outcome.reason)
    return compilation, lowered, outcome


def _entry(report: dict, index: int) -> dict:
    return next(e for e in report["entries"]
                if e["requirement_index"] == index)


def _rows(block: dict) -> dict[str, dict]:
    return {row["traffic_class"]: row for row in block["classes"]}


def test_evaluate_product_measures_each_class_not_the_aggregate(
        tmp_path, binary):
    request = _two_class_request(
        _latency_req("a0", 10 ** 9, QoSClass.BANDWIDTH),
        _bandwidth_req("a0", 1e-9, QoSClass.BANDWIDTH),
        _latency_req("b0", 1, QoSClass.LATENCY_CRITICAL),
        _bandwidth_req("b0", 1e9, QoSClass.LATENCY_CRITICAL),
    )
    product = evaluate_product(
        request, binary=binary, network_clock_hz=CLOCK_HZ,
        timeout_s=600, run_dir=tmp_path / "product", repo_root=str(REPO))
    _skip_or_fail(product.status, product.reason)
    assert product.outcome is not None
    outcome = product.outcome

    block = outcome.performance_result["traffic_class_metrics"]
    assert block["class_names"] == ["a0", "b0"]
    assert block["flit_width_bits"] == \
        product.compilation.bundle.packet_format.flit_width_bits
    rows = _rows(block)
    assert set(rows) == {"a0", "b0"}

    report = product.requirement_report
    assert report is not None
    a0_latency = _entry(report, 0)
    a0_bandwidth = _entry(report, 1)
    b0_latency = _entry(report, 2)
    b0_bandwidth = _entry(report, 3)

    assert a0_latency["verdict"] == "SATISFIED"
    assert a0_latency["measured"] == pytest.approx(
        rows["a0"]["latency"]["packet_latency_avg"])
    assert "classes['a0'].latency.packet_latency_avg" in \
        a0_latency["metric_authority"]

    assert a0_bandwidth["verdict"] == "SATISFIED"
    assert a0_bandwidth["measured"] > 0
    assert "classes['a0'].bytes_accepted" in \
        a0_bandwidth["metric_authority"]

    assert b0_latency["verdict"] == "VIOLATED"
    assert b0_latency["measured"] == pytest.approx(
        rows["b0"]["latency"]["packet_latency_avg"])
    assert b0_latency["measured"] != \
        outcome.network_traffic_window["window_cycles"]

    assert b0_bandwidth["verdict"] == "VIOLATED"
    assert b0_bandwidth["measured"] > 0
    assert "classes['b0'].bytes_accepted" in \
        b0_bandwidth["metric_authority"]
    assert product.requirements_pass is False


def test_a_class_missing_from_the_block_is_unmeasurable(tmp_path, binary):
    request = _two_class_request(
        _latency_req("a0", 10 ** 9),
        _latency_req("b0", 1),
        _bandwidth_req("b0", 1e9),
    )
    _compilation, lowered, outcome = _evaluate(tmp_path, request, binary)
    block = outcome.performance_result["traffic_class_metrics"]
    assert set(_rows(block)) == {"a0", "b0"}
    # A class the authenticated block omits is absent, never zero.
    block["classes"] = [row for row in block["classes"]
                        if row["traffic_class"] != "b0"]
    assert set(_rows(block)) == {"a0"}

    report = RequirementEvaluator.evaluate(
        request, lowered.graph, outcome.performance_result)
    assert _entry(report, 0)["verdict"] == "SATISFIED"
    missing_latency = _entry(report, 1)
    assert missing_latency["verdict"] == "UNMEASURABLE"
    assert missing_latency["measured"] == \
        outcome.network_traffic_window["window_cycles"]
    assert "aggregate" in missing_latency["reason"]
    missing_bandwidth = _entry(report, 2)
    assert missing_bandwidth["verdict"] == "UNMEASURABLE"
    assert missing_bandwidth["measured"] is None


def test_without_a_canonical_class_map_nothing_is_attached(
        tmp_path, binary, monkeypatch):
    request = _two_class_request(
        _latency_req("a0", 10 ** 9),
        _latency_req("b0", 1),
        _bandwidth_req("b0", 1e9),
    )
    real_build = evaluation_context.build_evaluation_context
    calls = {"count": 0}

    def unavailable_after_evaluation(compilation):
        calls["count"] += 1
        if calls["count"] > 1:
            raise RuntimeError("canonical class map unavailable")
        return real_build(compilation)

    # The evaluator builds its context once; the enrichment rebuild is the
    # second call and fails, exactly like an unavailable canonical map.
    monkeypatch.setattr(evaluation_context, "build_evaluation_context",
                        unavailable_after_evaluation)
    _compilation, lowered, outcome = _evaluate(tmp_path, request, binary)
    assert "traffic_class_metrics" not in outcome.performance_result

    report = RequirementEvaluator.evaluate(
        request, lowered.graph, outcome.performance_result)
    # Aggregate latency above the ceiling is a sound upper bound: SATISFIED.
    assert _entry(report, 0)["verdict"] == "SATISFIED"
    # Aggregate latency above the ceiling cannot name b0: UNMEASURABLE.
    assert _entry(report, 1)["verdict"] == "UNMEASURABLE"
    assert "aggregate" in _entry(report, 1)["reason"]
    # No class byte movement exists to measure.
    assert _entry(report, 2)["verdict"] == "UNMEASURABLE"
    assert _entry(report, 2)["measured"] is None


def test_federated_normalization_reuses_the_direct_class_block(
        tmp_path, binary, monkeypatch):
    request = _two_class_request(_latency_req("a0", 10 ** 9))
    compilation, _lowered, outcome = _evaluate(tmp_path, request, binary)
    block = deepcopy(outcome.performance_result["traffic_class_metrics"])

    def _must_not_rederive(**_kwargs):
        raise AssertionError("normalization re-derived an existing block")

    monkeypatch.setattr(
        booksim_adapter, "_traffic_class_metrics_from_evidence",
        _must_not_rederive)
    normalize_booksim_outcome(build_evaluation_context(compilation), outcome)
    assert outcome.performance_result["traffic_class_metrics"] == block


def test_single_class_direct_result_keeps_aggregate_semantics(
        tmp_path, binary):
    request = replace(
        CompileRequestV4.from_dict(baseline()),
        requirements=(
            _latency_req("tp_collective", 10 ** 9),
        ))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    lowered = lower_compile_workload(request)
    outcome = FabricEvaluator().evaluate(
        compilation, lowered.graph,
        EvaluationOptions(
            binary=binary, repo_root=str(REPO),
            network_clock_hz=CLOCK_HZ, timeout_s=600,
            traffic_class=lowered.unified_traffic_class,
            run_dir=str(tmp_path / "single")))
    _skip_or_fail(outcome.status, outcome.reason)

    assert "traffic_class_metrics" not in outcome.performance_result
    report = RequirementEvaluator.evaluate(
        request, lowered.graph, outcome.performance_result)
    entry = _entry(report, 0)
    assert entry["verdict"] == "SATISFIED"
    assert entry["metric_authority"].startswith(
        "performance_result.network_binding.duration")
