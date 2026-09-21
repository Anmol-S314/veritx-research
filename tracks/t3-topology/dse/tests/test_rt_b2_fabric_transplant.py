"""RT-final Worker B — B2: same-geometry transplants never authorize.

Requests A and B are identical in TP/PP/EP/DP, world size and topology
dimensions but differ in semantics (collective payload / traffic class /
ordered intent). Compilation A + Workload B must refuse at the
FabricEvaluator seam BEFORE any lowering or backend work — geometry
equality is not authority; content identity is. Missing workload
provenance is not a pass either (fail closed).
"""
from __future__ import annotations

import pytest

from veritx_dse.application.errors import ControlPlaneError
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.fabric_evaluator import (
    BACKEND_UNAVAILABLE,
    EvaluationOptions,
    FabricEvaluator,
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
    TopologyFamily,
    WorkloadV3,
)
from veritx_dse.workload.canonical_graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import lower_compile_workload


# ── builders ────────────────────────────────────────────────────────────

def _intent(*, kind="allreduce", dim="TP", payload=2048,
            tc="tp_collective", source=None):
    return CollectiveIntent(kind=CollectiveKind(kind),
                            dimension=CollectiveDimension(dim),
                            payload_bytes=payload, traffic_class=tc,
                            source_rank=source)


def _request(collectives, *, tp=4, dp=1,
             requirement_classes=("tp_collective",)):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, dp=dp,
            collectives=tuple(collectives)),
        requirements=tuple(
            RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                          traffic_class=tc,
                          latency_ceiling_cycles=10 ** 9, binding=True)
            for tc in requirement_classes),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _compiled(request):
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    return compilation


class TestFabricTransplant:
    @pytest.mark.parametrize("variant", ["payload", "traffic_class",
                                         "ordered_intent"])
    def test_compilation_a_with_workload_b_refuses_before_backend(
            self, tmp_path, variant):
        req_a = _request([_intent(payload=2048),
                          _intent(kind="allgather", payload=1024)])
        if variant == "payload":
            req_b = _request([_intent(payload=4096),
                              _intent(kind="allgather", payload=1024)])
        elif variant == "traffic_class":
            req_b = _request([_intent(payload=2048, tc="dp_collective"),
                              _intent(kind="allgather", payload=1024,
                                      tc="dp_collective")],
                             requirement_classes=("dp_collective",))
        else:
            req_b = _request([_intent(kind="allgather", payload=1024),
                              _intent(payload=2048)])
        compilation_a = _compiled(req_a)
        graph_a = lower_compile_workload(req_a).graph
        graph_b = lower_compile_workload(req_b).graph
        # Geometry equality is real, not assumed: same TP/PP/EP/DP and
        # same world size, different semantics -> different identity.
        assert graph_b.parallelism.sizes() == graph_a.parallelism.sizes()
        assert (req_a.workload.tp, req_a.workload.pp, req_a.workload.ep,
                req_a.workload.dp) == (
            req_b.workload.tp, req_b.workload.pp, req_b.workload.ep,
            req_b.workload.dp)
        assert req_a.design_hash() != req_b.design_hash()
        if variant == "traffic_class":
            # Traffic class is sidecar semantics: the canonical graph id
            # cannot distinguish the two designs, so only the design
            # provenance binding can (and does) refuse.
            assert graph_a.workload_id() == graph_b.workload_id()
        else:
            assert graph_a.workload_id() != graph_b.workload_id()
        run = tmp_path / "run"
        never_used = tmp_path / "never-spawned-booksim"
        with pytest.raises(ControlPlaneError) as excinfo:
            FabricEvaluator().evaluate(
                compilation_a, graph_b,
                EvaluationOptions(traffic_class="tp_collective",
                                  run_dir=str(run),
                                  binary=str(never_used)))
        message = str(excinfo.value)
        assert excinfo.value.code.value == "INVALID_INTENT"
        assert req_a.design_hash() in message
        assert req_b.design_hash() in message
        assert graph_b.workload_id() in message
        assert "transplanted" in message
        assert not run.exists()
        assert not never_used.exists()

    def test_compilation_b_with_workload_a_refuses(self, tmp_path):
        req_a = _request([_intent(payload=2048)])
        req_b = _request([_intent(payload=4096)])
        compilation_b = _compiled(req_b)
        graph_a = lower_compile_workload(req_a).graph
        with pytest.raises(ControlPlaneError) as excinfo:
            FabricEvaluator().evaluate(
                compilation_b, graph_a,
                EvaluationOptions(traffic_class="tp_collective",
                                  run_dir=str(tmp_path / "run")))
        assert excinfo.value.code.value == "INVALID_INTENT"
        assert not (tmp_path / "run").exists()

    def test_workload_without_provenance_refuses(self, tmp_path):
        request = _request([_intent(payload=2048)])
        compilation = _compiled(request)
        lowered = lower_compile_workload(request)
        bare = WorkloadGraph(
            parallelism=lowered.graph.parallelism,
            participant_count=lowered.graph.participant_count,
            operations=lowered.graph.operations,
            semantics=lowered.graph.semantics, provenance=None)
        with pytest.raises(ControlPlaneError) as excinfo:
            FabricEvaluator().evaluate(
                compilation, bare,
                EvaluationOptions(traffic_class="tp_collective",
                                  run_dir=str(tmp_path / "run")))
        assert excinfo.value.code.value == "INVALID_INTENT"
        assert "provenance" in str(excinfo.value)

    def test_matching_identity_reaches_availability_not_refusal(
            self, tmp_path):
        """Positive control: identity passes; only the missing binary is
        reported (geometry alone is never the gate)."""
        request = _request([_intent(payload=2048)])
        compilation = _compiled(request)
        graph = lower_compile_workload(request).graph
        outcome = FabricEvaluator().evaluate(
            compilation, graph,
            EvaluationOptions(
                traffic_class="tp_collective",
                run_dir=str(tmp_path / "run"),
                binary=str(tmp_path / "no-such-booksim")))
        assert outcome.status == BACKEND_UNAVAILABLE, outcome.reason
        assert outcome.design_hash == request.design_hash()
        assert outcome.workload_id == graph.workload_id()
