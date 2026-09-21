"""P1 RT-2: RequirementEvaluator provenance-transplant refusals.

Geometry equality (TP/PP/EP/DP) is necessary but NOT sufficient: two v3
requests with identical geometry can lower to different collectives
(payload bytes, traffic class, kind), and a same-shape transplant would
otherwise produce a report carrying B's design_hash over A's
measurements. These tests pin the three-way binding:

    request.design_hash() == workload.provenance["design_hash"]
    performance["wave_d_chain"]["workload_graph_id"] == workload.workload_id()

Fixtures are verified results built through the REAL authorities
(PerformanceModel + TemporalWorkload + NetworkWindowBinding +
schedule_workload + build_performance_result + reverify_result) — never
hand-signed documents.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1_requirements_provenance.py -q
"""
from __future__ import annotations

import pytest

from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_passes,
)
from veritx_dse.core.errors import EvidenceInvalid, MappingInvalid
from veritx_dse.workload.canonical_graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import lower_compile_workload

# One shared fixture authority: the verified-result builders already
# exercise the canonical authorities; a second copy here would drift.
from test_p1c_requirements import (  # noqa: E402
    _bound_result,
    _ci,
    _lat_req,
    _net_workload,
    _model,
    _request,
)


def _design_pair():
    """Two SAME-GEOMETRY v3 requests with different collectives.

    A: ALLREDUCE over TP, 2048 B, class "tp_collective".
    B: ALLGATHER over TP, 4096 B, class "dp_collective" (different kind,
       payload and traffic class — the geometry is byte-identical).
    """
    req_a = _request([_ci(kind="allreduce", dim="TP", payload=2048,
                          tc="tp_collective")],
                     [_lat_req(ceiling=10 ** 9)], tp=4, dp=2)
    req_b = _request([_ci(kind="allgather", dim="TP", payload=4096,
                          tc="dp_collective")],
                     [_lat_req(ceiling=10 ** 9, tc="dp_collective")],
                     tp=4, dp=2)
    graph_a = lower_compile_workload(req_a).graph
    graph_b = lower_compile_workload(req_b).graph
    return req_a, req_b, graph_a, graph_b


class TestSameGeometryTransplants:
    def test_performance_from_other_same_geometry_design_refuses(self):
        """A's measurements cannot stand in for B's design hash."""
        req_a, req_b, graph_a, graph_b = _design_pair()
        # Preconditions: same geometry, different identities.
        assert graph_a.parallelism.sizes() == graph_b.parallelism.sizes()
        assert req_a.design_hash() != req_b.design_hash()
        assert graph_a.workload_id() != graph_b.workload_id()

        perf_a, bound_graph = _bound_result(
            req_a, _net_workload(_model()), 2500)
        assert bound_graph.workload_id() == graph_a.workload_id()

        with pytest.raises(MappingInvalid) as ei:
            RequirementEvaluator.evaluate(req_b, graph_b, perf_a)
        message = str(ei.value)
        assert "workload_graph_id" in message
        assert graph_a.workload_id() in message
        assert graph_b.workload_id() in message

    def test_same_kind_different_payload_refuses(self):
        """Even same kind/class/dimension: payload bytes are design."""
        req_a = _request([_ci(kind="allreduce", dim="TP", payload=2048)],
                         [_lat_req(ceiling=10 ** 9)], tp=4, dp=2)
        req_b = _request([_ci(kind="allreduce", dim="TP", payload=4096)],
                         [_lat_req(ceiling=10 ** 9)], tp=4, dp=2)
        graph_b = lower_compile_workload(req_b).graph
        assert req_a.design_hash() != req_b.design_hash()
        perf_a, _ = _bound_result(req_a, _net_workload(_model()), 2500)
        with pytest.raises(MappingInvalid):
            RequirementEvaluator.evaluate(req_b, graph_b, perf_a)

    def test_transplanted_workload_refuses(self):
        """Same request, workload lowered from ANOTHER design."""
        req_a, req_b, graph_a, graph_b = _design_pair()
        assert req_b.design_hash() in \
            graph_b.provenance["design_hash"]
        perf_a, _ = _bound_result(req_a, _net_workload(_model()), 2500)

        with pytest.raises(MappingInvalid) as ei:
            RequirementEvaluator.evaluate(req_a, graph_b, perf_a)
        message = str(ei.value)
        assert "design_hash" in message
        assert req_a.design_hash() in message
        assert req_b.design_hash() in message

    def test_honest_triple_is_satisfied(self):
        req_a, _, graph_a, _ = _design_pair()
        perf_a, bound_graph = _bound_result(
            req_a, _net_workload(_model()), 2500)
        assert bound_graph.workload_id() == graph_a.workload_id()

        report = RequirementEvaluator.evaluate(req_a, graph_a, perf_a)
        assert report["design_hash"] == "sha256:" + req_a.design_hash()
        assert report["performance_result_id"] == perf_a["resource_id"]
        assert all(e["verdict"] == "SATISFIED"
                   for e in report["entries"])
        assert report_passes(report) is True


class TestMissingProvenanceRefuses:
    def test_result_without_wave_d_chain_refuses(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        perf = {k: v for k, v in perf.items() if k != "wave_d_chain"}
        with pytest.raises(EvidenceInvalid) as ei:
            RequirementEvaluator.evaluate(req, graph, perf)
        assert "wave_d_chain" in str(ei.value)

    def test_chain_without_workload_graph_id_refuses(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        perf = dict(perf)
        perf["wave_d_chain"] = {"physical_traffic_id": "pt"}
        with pytest.raises(EvidenceInvalid) as ei:
            RequirementEvaluator.evaluate(req, graph, perf)
        assert "workload_graph_id" in str(ei.value)

    def test_workload_without_provenance_refuses(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        bare = WorkloadGraph(
            parallelism=graph.parallelism,
            participant_count=graph.participant_count,
            operations=graph.operations,
            semantics=graph.semantics,
            provenance=None)
        assert bare.workload_id() == graph.workload_id()  # provenance is not identity
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        with pytest.raises(EvidenceInvalid) as ei:
            RequirementEvaluator.evaluate(req, bare, perf)
        assert "provenance" in str(ei.value)

    def test_provenance_without_design_hash_refuses(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        bare = WorkloadGraph(
            parallelism=graph.parallelism,
            participant_count=graph.participant_count,
            operations=graph.operations,
            semantics=graph.semantics,
            provenance={"lowerer": "someone-else"})
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        with pytest.raises(EvidenceInvalid) as ei:
            RequirementEvaluator.evaluate(req, bare, perf)
        assert "design_hash" in str(ei.value)
