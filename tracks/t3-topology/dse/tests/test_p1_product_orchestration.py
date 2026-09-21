"""Stage-2 orchestration tests: v3 request -> compile -> lower -> P1B
evaluate -> P1C requirements, with the traffic-class law enforced.

No semantics live here; these tests pin the wiring: compilation stops
before backend work, single-class evaluates under the lowered class,
multi-class refuses without backend work, and no relabel knob exists.
"""
from __future__ import annotations

import inspect

import pytest

from veritx_dse.application.product_evaluator import (
    ProductEvaluation,
    evaluate_product,
)
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


def _intent(kind="allreduce", dimension="TP", payload=2048, tc="tp_collective"):
    return CollectiveIntent(kind=CollectiveKind(kind),
                            dimension=CollectiveDimension(dimension),
                            payload_bytes=payload, traffic_class=tc)


def _request(collectives, tp=4, dp=1, topo="mesh"):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, dp=dp,
            collectives=tuple(collectives)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=10 ** 9, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(
            topology_family=TopologyFamily(topo)))


def _single():
    return _request([_intent()])


def test_no_relabel_knob_on_product_path():
    params = inspect.signature(evaluate_product).parameters
    assert "traffic_class" not in params, (
        "eval-time relabeling must stay inexpressible on the product path")


def test_unprovisioned_stops_at_backend_unavailable(tmp_path):
    prod = evaluate_product(
        _single(), binary=str(tmp_path / "no-such-booksim"),
        run_dir=str(tmp_path / "run"))
    assert isinstance(prod, ProductEvaluation)
    assert prod.compilation.status == "COMPILED"
    assert prod.lowered is not None
    assert prod.status == "BACKEND_UNAVAILABLE", prod.reason
    assert prod.outcome is not None
    assert prod.outcome.performance_result is None
    assert prod.requirement_report is None
    assert prod.requirements_pass is None


def test_provisioned_single_class_evaluates_and_reports(tmp_path):
    from veritx_dse.simulation.booksim import find_booksim_bin
    from veritx_dse.core.paths import REPO
    binary = find_booksim_bin(REPO)
    prod = evaluate_product(
        _single(), binary=str(binary), run_dir=str(tmp_path / "run"),
        network_clock_hz=10 ** 9, timeout_s=300)
    assert prod.status == "EVALUATED", prod.reason
    assert prod.outcome.backend_profile == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert prod.outcome.performance_result is not None
    assert prod.requirement_report is not None
    assert prod.requirements_pass is True
    entries = prod.requirement_report["entries"]
    assert entries and all(e["verdict"] == "SATISFIED" for e in entries)


def test_multi_class_refuses_before_backend_work(tmp_path):
    req = _request(
        [_intent(tc="tp_collective"),
         _intent(kind="allgather", dimension="DP", payload=1024,
                 tc="dp_collective")],
        tp=8, dp=4)
    run = tmp_path / "run"
    prod = evaluate_product(
        req, binary=str(tmp_path / "no-such-booksim"),
        run_dir=str(run))
    assert prod.compilation.status == "COMPILED"
    assert prod.status == "UNSUPPORTED"
    assert "tp_collective" in (prod.reason or "") or \
        "dp_collective" in (prod.outcome.reason or "")
    assert prod.outcome.performance_result is None
    assert prod.requirement_report is None


def test_invalid_compilation_stops_before_lowering():
    prod = evaluate_product(_request([_intent()], topo="torus"))
    assert prod.compilation.status in ("INVALID", "UNSUPPORTED")
    assert prod.status == prod.compilation.status
    assert prod.lowered is None
    assert prod.outcome is None


def test_lowering_refusal_is_typed_not_raised():
    """RT-9: a request that COMPILES but is outside the lowering domain
    returns ProductEvaluation(UNSUPPORTED) instead of raising."""
    pp = CollectiveIntent(kind=CollectiveKind.ALLREDUCE,
                          dimension=CollectiveDimension.PP,
                          payload_bytes=2048,
                          traffic_class="tp_collective")
    prod = evaluate_product(_request([pp]))
    assert prod.compilation.status == "COMPILED"
    assert prod.status == "UNSUPPORTED"
    assert prod.lowered is None
    assert prod.outcome is None
    assert prod.requirement_report is None
    assert prod.requirements_pass is None
    assert "UnsupportedSemantics" in (prod.reason or "")
    assert "PP-dimension" in (prod.reason or "")


def test_invalid_lowering_input_maps_to_invalid():
    """RT-9: malformed lowering input (BROADCAST root outside the
    expanded group) is INVALID, still never raised."""
    bad_root = CollectiveIntent(kind=CollectiveKind.BROADCAST,
                                dimension=CollectiveDimension.TP,
                                payload_bytes=1024,
                                traffic_class="tp_collective",
                                source_rank=99)
    prod = evaluate_product(_request([bad_root]))
    assert prod.compilation.status == "COMPILED"
    assert prod.status == "INVALID"
    assert prod.lowered is None
    assert prod.outcome is None
    assert "InvalidInput" in (prod.reason or "")
