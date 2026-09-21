"""P1C phase-2 fix 2 tests: v3 genuinely compilable, v2 byte-identical.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1c_v3_compile.py -q
"""
from __future__ import annotations

import pytest

from veritx_dse.application.errors import ControlPlaneError
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.compile import compile_bundle
from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequest,
    CompileRequestV3,
    Dependency,
    DependencyGraph,
    DepKind,
    FabricIntentView,
    ModelFamily,
    NocConfig,
    QoSClass,
    Requirement,
    RequirementV3,
    ServingMode,
    TopologyFamily,
    Workload,
    WorkloadV3,
    derive_v3_traffic_classes,
    derive_vc_assignment,
    derive_vc_assignment_v3,
    fabric_intent_view,
)


def _v3(tp=4, dp=1, collectives=None, dependencies=None):
    if collectives is None:
        collectives = (CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE,
            dimension=CollectiveDimension.TP,
            payload_bytes=2048, traffic_class="tp_collective"),)
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, dp=dp,
            collectives=tuple(collectives)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=10 ** 9, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * dp),),
        dependencies=dependencies or DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _v2(dependencies=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                          tp=4, dp=1),
        requirements=(Requirement(
            qos_class=QoSClass.LATENCY_CRITICAL,
            latency_ceiling_cycles=10 ** 9, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=dependencies or DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


class TestFabricIntentView:
    def test_v3_view_fields(self):
        req = _v3()
        view = fabric_intent_view(req)
        assert isinstance(view, FabricIntentView)
        assert (view.tp, view.pp, view.ep, view.dp) == (4, 1, 1, 1)
        assert view.world_size == 4
        assert view.traffic_classes == ("tp_collective",)
        assert view.design_hash == req.design_hash()
        assert view.source_generation == "v3"
        assert view.noc_config is req.noc_config
        assert view.agents == req.agents

    def test_v2_view_uses_dependency_namespace(self):
        deps = DependencyGraph([
            Dependency(source="a", target="b", kind=DepKind.BLOCKING)])
        view = fabric_intent_view(_v2(dependencies=deps))
        assert view.source_generation == "v2"
        assert view.traffic_classes == ("a", "b")

    def test_view_is_non_persisted(self):
        assert not hasattr(fabric_intent_view(_v3()), "to_dict")

    def test_garbage_refused(self):
        with pytest.raises(Exception):
            fabric_intent_view(object())


class TestV3VCPolicy:
    def test_declared_class_present_even_at_vc0(self):
        va = derive_vc_assignment_v3(_v3())
        assert va.vc_count == 1
        assert va.per_class_vc == {"tp_collective": 0}
        assert va.routing_function == "dim_order"

    def test_no_concurrent_context_floor(self):
        # Two intents, sequential v3 chain: v2 would floor at 2
        # (two multi-rank collectives); v3 derives 1 (no cycles).
        from veritx_dse.model.compile_model import CollectiveOp
        req = _v3(collectives=(
            CollectiveIntent(kind=CollectiveKind.ALLREDUCE,
                             dimension=CollectiveDimension.TP,
                             payload_bytes=2048,
                             traffic_class="tp_collective"),
            CollectiveIntent(kind=CollectiveKind.ALLGATHER,
                             dimension=CollectiveDimension.TP,
                             payload_bytes=2048,
                             traffic_class="tp_collective2")))
        assert derive_vc_assignment_v3(req).vc_count == 1

    def test_cycle_separation_and_routing_parity_with_v2(self):
        deps = DependencyGraph([
            Dependency(source="x", target="y", kind=DepKind.BLOCKING),
            Dependency(source="y", target="x", kind=DepKind.BLOCKING)])
        v3va = derive_vc_assignment_v3(_v3(dependencies=deps))
        v2va = derive_vc_assignment(_v2(dependencies=deps))
        assert v3va.vc_count == v2va.vc_count == 2
        assert v3va.routing_function == v2va.routing_function == "dor"
        # Declared class rides along at VC0 next to separated victims.
        assert v3va.per_class_vc["tp_collective"] == 0
        assert sorted(v3va.per_class_vc) == ["tp_collective", "x", "y"]

    def test_over_limit_is_unsupported(self):
        from veritx_dse.core.constants import PLANE_C_MAX_VC
        from veritx_dse.model.vc_assignment import VCAssignmentError
        deps = DependencyGraph([
            d for i in range(PLANE_C_MAX_VC)
            for d in (Dependency(source=f"a{i}", target=f"b{i}",
                                 kind=DepKind.BLOCKING),
                      Dependency(source=f"b{i}", target=f"a{i}",
                                 kind=DepKind.BLOCKING))])
        with pytest.raises(VCAssignmentError):
            derive_vc_assignment_v3(_v3(dependencies=deps))

    def test_v3_policy_refuses_v2_requests(self):
        with pytest.raises(Exception):
            derive_vc_assignment_v3(_v2())


class TestV3CompileEndToEnd:
    def test_v3_compiles_with_passing_certificate(self):
        req = _v3()
        out = FabricCompiler().compile(req)
        assert out.status == "COMPILED", out.error
        assert out.certificate.overall == "PASS"
        assert out.bundle.resolved_fabric.design_hash == req.design_hash()
        assert out.request is req

    def test_vc_artifact_serves_declared_classes(self):
        out = FabricCompiler().compile(_v3())
        tc = dict((c, tuple(v))
                  for c, v in out.bundle.vc_assignment.traffic_class_to_vcs)
        assert tc == {"tp_collective": (0,)}

    def test_v2_path_never_consumes_v3(self):
        # compile_bundle (v2 fn) fails closed on a v3 request instead of
        # silently interpreting it — no fake-v2 conversion anywhere.
        with pytest.raises(ControlPlaneError):
            compile_bundle(_v3())
        assert not isinstance(_v3(), CompileRequest)


class TestGateGeneralization:
    def test_route_gate_accepts_view_and_refuses_garbage(self):
        from veritx_dse.model.placement import build_inventory
        from veritx_dse.model.routing import derive_route
        from veritx_dse.model.topology_artifact import materialize_topology
        from veritx_dse.model.routing import derive_route
        req = _v2()
        inv = build_inventory(req)
        topo = materialize_topology(inv, req.noc_config)
        via_view = derive_route(request=fabric_intent_view(req),
                                topology=topo)
        via_v2 = derive_route(request=req, topology=topo)
        assert via_view.routing_classes == via_v2.routing_classes
        with pytest.raises(Exception):
            derive_route(request=object(), topology=topo)

    def test_topology_gate_accepts_view(self):
        from veritx_dse.model.placement import build_inventory
        from veritx_dse.model.topology_artifact import materialize_topology
        req = _v3()
        inv = build_inventory(req)  # duck-typed: v3 flows through
        assert inv.rank_count == 4
        topo = materialize_topology(inv, fabric_intent_view(req))
        assert topo.router_count == 4
