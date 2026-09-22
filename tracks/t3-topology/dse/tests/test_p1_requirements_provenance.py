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

import copy

import pytest

from veritx_dse.application.requirements import (
    RequirementEvaluator,
    VerifiedPerformanceResult,
    report_passes,
    verify_performance_result,
)
from veritx_dse.core.errors import (
    EvidenceInvalid,
    InvalidInput,
    MappingInvalid,
)
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

    def test_same_geometry_different_traffic_class_refuses(self):
        """Traffic class lives in the lowering sidecar, NOT in the
        canonical workload identity: two designs differing only in
        traffic class lower to the SAME workload_id, so the chain's
        design_hash binding is the only thing that can refuse."""
        req_a = _request([_ci(kind="allreduce", dim="TP", payload=2048,
                              tc="tp_collective")],
                         [_lat_req(ceiling=10 ** 9, tc="tp_collective")],
                         tp=4, dp=2)
        req_b = _request([_ci(kind="allreduce", dim="TP", payload=2048,
                              tc="dp_collective")],
                         [_lat_req(ceiling=10 ** 9, tc="dp_collective")],
                         tp=4, dp=2)
        graph_a = lower_compile_workload(req_a).graph
        graph_b = lower_compile_workload(req_b).graph
        assert req_a.design_hash() != req_b.design_hash()
        assert graph_a.workload_id() == graph_b.workload_id()
        perf_a, _ = _bound_result(req_a, _net_workload(_model()), 2500)
        with pytest.raises(MappingInvalid) as ei:
            RequirementEvaluator.evaluate(req_b, graph_b, perf_a)
        message = str(ei.value)
        assert "design_hash" in message
        assert req_a.design_hash() in message
        assert req_b.design_hash() in message

    def test_transplanted_workload_refuses(self):
        """Same request, workload lowered from ANOTHER design."""
        req_a, req_b, graph_a, graph_b = _design_pair()
        assert req_b.design_hash() in \
            graph_b.provenance["design_hash"]
        perf_a, _ = _bound_result(req_a, _net_workload(_model()), 2500)

        with pytest.raises(MappingInvalid) as ei:
            RequirementEvaluator.evaluate(req_a, graph_b, perf_a)
        message = str(ei.value)
        assert "not the lowering" in message
        assert graph_a.workload_id() in message
        assert graph_b.workload_id() in message

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


class TestVerifiedBoundaryRefuses:
    def test_naked_result_dict_is_not_authentication(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        with pytest.raises(InvalidInput) as ei:
            RequirementEvaluator.evaluate(req, graph, dict(perf))
        assert "VerifiedPerformanceResult" in str(ei.value)

    def test_result_without_wave_d_chain_refuses(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        without_chain = {k: v for k, v in perf.items()
                         if k != "wave_d_chain"}
        with pytest.raises(EvidenceInvalid) as ei:
            verify_performance_result(
                without_chain, workload=perf.temporal_workload)
        assert "reverify_result" in str(ei.value)

    def test_chain_without_workload_graph_id_refuses(self):
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        tampered = dict(perf)
        tampered["wave_d_chain"] = {"physical_traffic_id": "pt"}
        # Stale resource_id/event_graph_id untouched: the verified
        # boundary refuses the mutation.
        with pytest.raises(EvidenceInvalid):
            verify_performance_result(
                tampered, workload=perf.temporal_workload)
        forged = VerifiedPerformanceResult(
            tampered, temporal_workload=perf.temporal_workload)
        with pytest.raises(EvidenceInvalid):
            RequirementEvaluator.evaluate(req, graph, forged)

    @pytest.mark.parametrize(
        "mutation", ["chain_design_hash", "chain_workload_graph_id",
                     "makespan_summary"])
    def test_stale_resource_id_after_mutation_refuses(self, mutation):
        """Verifier-named test: a mutation that keeps the stale
        ``resource_id`` untouched refuses at the verified boundary —
        for chain identity fields AND a re-derived summary field."""
        req = _request([_ci()], [_lat_req(ceiling=10 ** 9)], tp=2, dp=1)
        graph = lower_compile_workload(req).graph
        perf, _ = _bound_result(req, _net_workload(_model()), 2500)
        tampered = copy.deepcopy(dict(perf))
        if mutation == "chain_design_hash":
            tampered["wave_d_chain"]["design_hash"] = "0" * 64
        elif mutation == "chain_workload_graph_id":
            tampered["wave_d_chain"]["workload_graph_id"] = "0" * 64
        else:
            tampered["makespan"] = {"numerator": 1, "denominator": 1}
        assert tampered["resource_id"] == perf["resource_id"]
        with pytest.raises(EvidenceInvalid):
            verify_performance_result(
                tampered, workload=perf.temporal_workload)
        # Even a hand-forged wrapper is re-verified by the evaluator.
        forged = VerifiedPerformanceResult(
            tampered, temporal_workload=perf.temporal_workload)
        with pytest.raises(EvidenceInvalid):
            RequirementEvaluator.evaluate(req, graph, forged)

    def test_foreign_graph_with_forged_provenance_refuses(self):
        """Provenance is metadata: forging a matching design_hash onto a
        foreign semantic graph cannot pass the re-derivation gate."""
        req_a, req_b, graph_a, graph_b = _design_pair()
        forged = WorkloadGraph(
            parallelism=graph_b.parallelism,
            participant_count=graph_b.participant_count,
            operations=graph_b.operations,
            semantics=graph_b.semantics,
            provenance={"design_hash": req_a.design_hash()})
        assert forged.workload_id() == graph_b.workload_id()
        perf_a, _ = _bound_result(req_a, _net_workload(_model()), 2500)
        with pytest.raises(MappingInvalid) as ei:
            RequirementEvaluator.evaluate(req_a, forged, perf_a)
        assert "not the lowering" in str(ei.value)

    def test_same_content_provenance_is_not_authority(self):
        """A provenance-free copy of the EXACT lowering is accepted:
        content identity, not provenance, is the authority."""
        req_a, _, graph_a, _ = _design_pair()
        bare = WorkloadGraph(
            parallelism=graph_a.parallelism,
            participant_count=graph_a.participant_count,
            operations=graph_a.operations,
            semantics=graph_a.semantics,
            provenance=None)
        assert bare.workload_id() == graph_a.workload_id()
        perf_a, _ = _bound_result(req_a, _net_workload(_model()), 2500)
        report = RequirementEvaluator.evaluate(req_a, bare, perf_a)
        assert report["design_hash"] == "sha256:" + req_a.design_hash()
        assert report_passes(report) is True
