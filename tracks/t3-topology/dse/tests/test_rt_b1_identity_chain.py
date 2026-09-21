"""RT-final Worker B — B1: identity chain + substitution refusals.

Proves the full identity chain on a REAL BookSim run:

    request.design_hash
      -> LoweredWorkload.design_hash / graph provenance
      -> workload_id -> physical_traffic_id
      -> PerformanceResult.wave_d_chain -> performance_result_id
      -> RequirementReport.design_hash / performance_result_id

and that each substitution refuses at the earliest boundary that can
decide: Request B + PerformanceResult A -> MappingInvalid at
RequirementEvaluator; missing provenance/chain binding -> EvidenceInvalid;
Request B + RequirementReport/parents A -> report identity carries A.
"""
from __future__ import annotations

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_identity,
)
from veritx_dse.core.errors import EvidenceInvalid, MappingInvalid
from veritx_dse.core.paths import REPO
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
from veritx_dse.simulation.booksim import find_booksim_bin
from veritx_dse.workload.canonical_graph import (
    WorkloadGraph,
)
from veritx_dse.workload.intent_lowering import (
    build_single_class_messages,
    lower_compile_workload,
)
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2


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


def _hermetic_performance(request, window_us=2500):
    """A verified result bound to ``request``'s lowered graph (hermetic).

    Reuses the RT-2 fixture builders (real PerformanceModel +
    TemporalWorkload + NetworkWindowBinding + schedule + build +
    reverify) so this file never hand-signs a result document.
    """
    from test_p1c_requirements import _bound_result, _model, _net_workload
    return _bound_result(request, _net_workload(_model()), window_us)


class TestIdentityChain:
    def test_lowering_stamps_request_identity_on_sidecar_and_graph(self):
        request = _request([_intent(payload=2048)])
        lowered = lower_compile_workload(request)
        assert lowered.design_hash == request.design_hash()
        assert lowered.graph.provenance["design_hash"] == \
            request.design_hash()
        # Provenance is not content identity: the same canonical content
        # keeps its workload_id when provenance is absent.
        bare = WorkloadGraph(
            parallelism=lowered.graph.parallelism,
            participant_count=lowered.graph.participant_count,
            operations=lowered.graph.operations,
            semantics=lowered.graph.semantics, provenance=None)
        assert bare.workload_id() == lowered.graph.workload_id()

    def test_physical_traffic_binds_message_and_workload_identity(self):
        request = _request([_intent(payload=2048)])
        compilation = _compiled(request)
        lowered = lower_compile_workload(request)
        messages = build_single_class_messages(lowered)
        physical = PhysicalTrafficArtifactV2(
            logical=messages, bundle=compilation.bundle)
        identity = physical.identity_dict()
        assert messages.identity_dict()["workload_id"] == \
            lowered.graph.workload_id()
        assert identity["message_artifact_id"] == \
            messages.message_artifact_id()
        assert identity["resolved_fabric_hash"] == \
            compilation.bundle.resolved_fabric.resolved_fabric_hash()
        assert physical.physical_traffic_id() == \
            physical.physical_traffic_id()
        # Different workload content -> different physical traffic id.
        other = _request([_intent(payload=4096)])
        other_compilation = _compiled(other)
        other_physical = PhysicalTrafficArtifactV2(
            logical=build_single_class_messages(
                lower_compile_workload(other)),
            bundle=other_compilation.bundle)
        assert physical.physical_traffic_id() != \
            other_physical.physical_traffic_id()

    def test_report_refuses_performance_from_same_geometry_design(self):
        """Request B + PerformanceResult A: the chain binds A's workload."""
        req_a = _request([_intent(payload=2048)])
        req_b = _request([_intent(payload=4096)])
        graph_b = lower_compile_workload(req_b).graph
        perf_a, graph_a = _hermetic_performance(req_a)
        assert req_a.design_hash() != req_b.design_hash()
        assert graph_a.workload_id() != graph_b.workload_id()
        assert graph_b.parallelism.sizes() == graph_a.parallelism.sizes()
        with pytest.raises(MappingInvalid) as excinfo:
            RequirementEvaluator.evaluate(req_b, graph_b, perf_a)
        message = str(excinfo.value)
        assert "workload_graph_id" in message
        assert graph_a.workload_id() in message
        assert graph_b.workload_id() in message

    def test_report_identity_does_not_survive_a_design_transplant(self):
        """Request B + RequirementReport/parents A: report A carries A's
        design hash and A's result id; it is never B's report."""
        req_a = _request([_intent(payload=2048)])
        req_b = _request([_intent(payload=4096)])
        graph_a = lower_compile_workload(req_a).graph
        perf_a, _ = _hermetic_performance(req_a)
        report_a = RequirementEvaluator.evaluate(req_a, graph_a, perf_a)
        assert report_a["design_hash"] == \
            "sha256:" + req_a.design_hash()
        assert report_a["design_hash"] != \
            "sha256:" + req_b.design_hash()
        assert report_a["performance_result_id"] == \
            perf_a["resource_id"]
        graph_b = lower_compile_workload(req_b).graph
        report_b = RequirementEvaluator.evaluate(
            req_b, graph_b, _hermetic_performance(req_b)[0])
        assert report_identity(report_a) != report_identity(report_b)

    def test_missing_provenance_or_chain_is_not_a_pass(self):
        """An absent binding refuses (EvidenceInvalid), never passes."""
        request = _request([_intent(payload=2048)])
        graph = lower_compile_workload(request).graph
        perf, _ = _hermetic_performance(request)
        bare = WorkloadGraph(
            parallelism=graph.parallelism,
            participant_count=graph.participant_count,
            operations=graph.operations,
            semantics=graph.semantics, provenance=None)
        with pytest.raises(EvidenceInvalid):
            RequirementEvaluator.evaluate(request, bare, perf)
        without_chain = {k: v for k, v in perf.items()
                         if k != "wave_d_chain"}
        with pytest.raises(EvidenceInvalid):
            RequirementEvaluator.evaluate(request, graph, without_chain)


class TestValidPath:
    def test_valid_matching_path_evaluates_with_full_chain(self, tmp_path):
        """Mandatory valid path: real BookSim, real report, and the whole
        identity chain bound end to end."""
        request = _request([_intent(payload=2048)])
        binary = find_booksim_bin(REPO)
        product = evaluate_product(
            request, binary=str(binary), run_dir=str(tmp_path / "run"),
            network_clock_hz=10 ** 9, timeout_s=300)
        assert product.status == "EVALUATED", product.reason
        assert product.requirements_pass is True
        graph = product.lowered.graph
        outcome = product.outcome
        report = product.requirement_report
        chain = outcome.performance_result["wave_d_chain"]
        assert product.lowered.design_hash == request.design_hash()
        assert graph.provenance["design_hash"] == request.design_hash()
        assert outcome.design_hash == request.design_hash()
        assert outcome.workload_id == graph.workload_id()
        assert chain["design_hash"] == request.design_hash()
        assert chain["workload_graph_id"] == graph.workload_id()
        assert chain["message_artifact_id"] == \
            outcome.message_artifact_id
        assert chain["physical_traffic_id"] == \
            outcome.physical_traffic_id
        assert chain["resolved_fabric_hash"] == \
            outcome.resolved_fabric_hash
        assert outcome.performance_result_id == \
            outcome.performance_result["resource_id"]
        assert report["design_hash"] == "sha256:" + request.design_hash()
        assert report["performance_result_id"] == \
            outcome.performance_result_id
        assert all(entry["verdict"] == "SATISFIED"
                   for entry in report["entries"])
