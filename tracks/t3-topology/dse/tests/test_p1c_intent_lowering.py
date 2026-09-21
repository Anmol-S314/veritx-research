"""P1C intent-lowering tests: deterministic groups, refusals, sidecars.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1c_intent_lowering.py -q
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from veritx_dse.core.artifact import thaw
from veritx_dse.core.errors import (
    InvalidInput,
    MappingInvalid,
    UnsupportedSemantics,
    UnsupportedSchedule,
)
from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequest,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    RequirementV3,
    QoSClass,
    ServingMode,
    TopologyFamily,
    Workload,
    WorkloadV3,
)
from veritx_dse.workload.intent_lowering import (
    LoweredWorkload,
    assert_traffic_classes_bound,
    build_single_class_messages,
    lower_compile_workload,
)


def _intent(kind="allreduce", dimension="TP", payload=8192, tc="tp_collective",
            **kw):
    return CollectiveIntent(kind=CollectiveKind(kind),
                            dimension=CollectiveDimension(dimension),
                            payload_bytes=payload, traffic_class=tc, **kw)


def _request(collectives, tp=8, dp=4, pp=1, ep=1, family="dense_transformer",
             serving="mixed", requirements=()):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily(family), tp=tp, pp=pp, ep=ep, dp=dp,
            serving_mode=ServingMode(serving),
            collectives=tuple(collectives)),
        requirements=tuple(requirements),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * pp * ep * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _detail(op):
    return thaw(op.detail)


class TestDimensionExpansion:
    """B4: participants derived from dimensions, never guessed."""

    def test_tp_8_dp_4_gives_four_groups_of_eight(self):
        lw = lower_compile_workload(_request([_intent()]))
        g = lw.graph
        assert g.participant_count == 32
        ops = g.of_kind("COLLECTIVE")
        assert len(ops) == 4
        assert [tuple(_detail(o)["participants"]) for o in ops] == [
            tuple(range(0, 8)), tuple(range(8, 16)),
            tuple(range(16, 24)), tuple(range(24, 32))]
        for o in ops:
            assert _detail(o)["payload_bytes"] == 8192

    def test_dp_collective_groups(self):
        lw = lower_compile_workload(
            _request([_intent(kind="allgather", dimension="DP", payload=1024,
                              tc="dp_collective")]))
        ops = lw.graph.of_kind("COLLECTIVE")
        assert len(ops) == 8  # tp(8) x pp(1) x ep(1) groups of dp(4)
        for o in ops:
            assert len(_detail(o)["participants"]) == 4

    def test_global_single_group(self):
        lw = lower_compile_workload(
            _request([_intent(dimension="GLOBAL", payload=2048,
                              tc="global")], tp=4, dp=2))
        ops = lw.graph.of_kind("COLLECTIVE")
        assert len(ops) == 1
        assert tuple(_detail(ops[0])["participants"]) == tuple(range(8))

    def test_ep_groups(self):
        lw = lower_compile_workload(
            _request([_intent(kind="alltoall", dimension="EP", payload=2048,
                              tc="epx")], tp=2, dp=1, ep=4))
        ops = lw.graph.of_kind("COLLECTIVE")
        assert len(ops) == 2  # tp(2) groups of ep(4)
        assert all(len(_detail(o)["participants"]) == 4 for o in ops)

    def test_pp_geometry_scopes_tp_within_stages(self):
        lw = lower_compile_workload(_request([_intent(payload=2048)],
                                             tp=2, dp=1, pp=2))
        parts = [_detail(o)["participants"]
                 for o in lw.graph.of_kind("COLLECTIVE")]
        assert [tuple(p) for p in parts] == [(0, 1), (2, 3)]  # stages


class TestOrderingAndMetadata:
    def test_declared_order_becomes_explicit_chain(self):
        lw = lower_compile_workload(_request([
            _intent(payload=2048),
            _intent(kind="allgather", dimension="DP", payload=1024,
                     tc="dp_collective")], tp=4, dp=2))
        g = lw.graph
        ordered = g.require_total_order()  # unique order or refusal
        assert [o.operation_id for o in ordered] == [
            o.operation_id for o in g.operations]
        for prev, cur in zip(g.operations, g.operations[1:]):
            assert cur.deps == (prev.operation_id,)
        assert g.operations[0].deps == ()

    def test_no_fabricated_scope_or_phase(self):
        for serving in ("mixed", "prefill_heavy", "decode_heavy"):
            lw = lower_compile_workload(
                _request([_intent(payload=2048)], tp=4, dp=1,
                         serving=serving))
            for o in lw.graph.operations:
                assert _detail(o)["scope"] is None
                assert o.phase is None
            assert lw.graph.semantics.phase is None

    def test_deterministic_across_runs(self):
        r = _request([_intent(), _intent(kind="allgather", dimension="DP",
                                         payload=1024, tc="dp")])
        a, b = lower_compile_workload(r), lower_compile_workload(r)
        assert a.graph.workload_id() == b.graph.workload_id()
        assert a.graph.to_dict() == b.graph.to_dict()
        assert a.traffic_class_by_operation == b.traffic_class_by_operation


class TestBroadcastRoots:
    def test_global_broadcast_with_root(self):
        lw = lower_compile_workload(
            _request([_intent(kind="broadcast", dimension="GLOBAL",
                              payload=512, tc="bcast", source_rank=3)],
                     tp=4, dp=1))
        ops = lw.graph.of_kind("COLLECTIVE")
        assert len(ops) == 1
        assert _detail(ops[0])["source"] == 3

    def test_multi_group_broadcast_refuses(self):
        # One declared root cannot serve four TP groups: no invented roots.
        with pytest.raises(InvalidInput):
            lower_compile_workload(
                _request([_intent(kind="broadcast", dimension="TP",
                                  payload=512, tc="bcast", source_rank=0)]))


class TestRefusals:
    def test_v2_request_refused(self):
        v2 = CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER),
            requirements=(), agents=(Agent(kind=AgentKind.COMPUTE_TILE,
                                           count=1),),
            dependencies=DependencyGraph([]), noc_config=NocConfig())
        with pytest.raises(InvalidInput):
            lower_compile_workload(v2)

    def test_non_dense_family_refused(self):
        with pytest.raises(UnsupportedSemantics):
            lower_compile_workload(
                _request([_intent()], family="mixture_of_experts"))

    def test_pp_dimension_collective_refused(self):
        with pytest.raises(UnsupportedSemantics):
            lower_compile_workload(
                _request([_intent(dimension="PP", payload=2048)], tp=2,
                         pp=2))

    def test_empty_intent_refused(self):
        with pytest.raises(InvalidInput):
            lower_compile_workload(_request([]))

    def test_indivisible_payload_refused(self):
        # ALLREDUCE k=8 needs B % 8 == 0 under the pinned schedule.
        with pytest.raises(UnsupportedSchedule):
            lower_compile_workload(_request([_intent(payload=1001)]))

    def test_single_member_group_refused(self):
        # dp=1 DP-dimension collective: groups of one are not collectives.
        with pytest.raises(UnsupportedSemantics):
            lower_compile_workload(
                _request([_intent(kind="allgather", dimension="DP",
                                  payload=1024, tc="dp")], tp=4, dp=1))


class TestTrafficSidecar:
    def test_sidecar_covers_every_collective_op(self):
        lw = lower_compile_workload(_request([
            _intent(payload=2048),
            _intent(kind="allgather", dimension="DP", payload=1024,
                     tc="dp_collective")], tp=4, dp=2))
        assert lw.classes == ("dp_collective", "tp_collective")
        assert lw.unified_traffic_class is None
        for op in lw.graph.of_kind("COLLECTIVE"):
            assert lw.class_for(op.operation_id) in lw.classes
        with pytest.raises(InvalidInput):
            lw.class_for("no-such-op")

    def test_single_class_fast_path(self):
        lw = lower_compile_workload(_request([_intent(payload=2048)],
                                             tp=4, dp=1))
        assert lw.unified_traffic_class == "tp_collective"
        msgs = build_single_class_messages(lw)
        assert msgs.traffic_class == "tp_collective"
        assert {m.traffic_class for m in msgs.messages} == {"tp_collective"}
        msgs.validate_conservation()

    def test_multi_class_fast_path_refuses(self):
        lw = lower_compile_workload(_request([
            _intent(payload=2048),
            _intent(kind="allgather", dimension="DP", payload=1024,
                     tc="dp_collective")], tp=4, dp=2))
        with pytest.raises(UnsupportedSemantics):
            build_single_class_messages(lw)

    def test_vc_admission_gate(self):
        lw = lower_compile_workload(_request([_intent(payload=2048)],
                                             tp=4, dp=1))
        bound = SimpleNamespace(
            traffic_class_to_vcs=(("tp_collective", (0,)),))
        assert_traffic_classes_bound(lw, bound)  # no raise
        unbound = SimpleNamespace(
            traffic_class_to_vcs=(("other", (0,)),))
        with pytest.raises(MappingInvalid):
            assert_traffic_classes_bound(lw, unbound)
        with pytest.raises(InvalidInput):
            assert_traffic_classes_bound(lw, SimpleNamespace())
