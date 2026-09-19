"""Wave B3.3b tests — realized (channel, VC) dependency graph + certificate."""
from __future__ import annotations

import pytest

from veritx_dse.core.route_artifact import DOR_XY, ANYNET_MIN_HOPS, RouteArtifact
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, DepKind, Dependency, DependencyGraph,
    ModelFamily, NocConfig, TopologyFamily, Workload,
    derive_vc_assignment_artifact,
)
from veritx_dse.model.mapping import derive_mapping
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import (
    ResolvedRouteArtifact, derive_resolved_route,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_topology,
)
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.verification.channel_vc_cdg import (
    CDGError, CHANNEL_VC_DEPENDENCY_ACYCLIC, DEADLOCK_PROOF_METHODS,
    build_channel_vc_cdg, certify_channel_vc_deadlock,
)


def _mesh_chain(n=4, cycles=1):
    deps = []
    for i in range(cycles):
        deps.append(Dependency(f"A{i}", f"B{i}", DepKind.BLOCKING))
        deps.append(Dependency(f"B{i}", f"A{i}", DepKind.BLOCKING))
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=n)],
        dependencies=DependencyGraph(deps),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(topo, name="mesh")
    rra = derive_resolved_route(topo, att, rr)
    vc = derive_vc_assignment_artifact(cr, rra)
    return cr, topo, rr, rra, vc


def _two_router():
    """0 <-> 1: every packet on a channel ejects at the far end."""
    routers = (Router(0, (0,), 2), Router(1, (1,), 2))
    channels = (
        DirectedChannel(0, 0, 0, 1, 0, 64, 1),
        DirectedChannel(1, 1, 0, 0, 0, 64, 1),
    )
    topo = TopologyArtifact(
        family=MaterializedFamily.MESH, routers=routers, channels=channels)
    rr = RouteArtifact.from_topology(topo, name="two_router")
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(),
        attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=((0, 0), (1, 1)),
        routing_classes=(ANYNET_MIN_HOPS,),
        endpoint_route_table_hash="b" * 64,
    )
    vc = make_vc_assignment_artifact(
        resolved_route=rra, vc_count=2,
        traffic_class_to_vcs={"A": [0], "B": [1]}, derivation="two_router")
    return topo, rr, rra, vc


def _directed_ring():
    """0 -> 1 -> 2 -> 0: strongly connected, every channel is a resource."""
    routers = (Router(0, (0,), 1), Router(1, (1,), 1), Router(2, (2,), 1))
    channels = (
        DirectedChannel(0, 0, 0, 1, 0, 64, 1),
        DirectedChannel(1, 1, 0, 2, 0, 64, 1),
        DirectedChannel(2, 2, 0, 0, 0, 64, 1),
    )
    topo = TopologyArtifact(
        family=MaterializedFamily.RING, routers=routers, channels=channels)
    rr = RouteArtifact.from_topology(topo, name="directed_ring")
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(),
        attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=((0, 0), (1, 1), (2, 2)),
        routing_classes=(ANYNET_MIN_HOPS,),
        endpoint_route_table_hash="b" * 64,
    )
    vc = make_vc_assignment_artifact(
        resolved_route=rra, vc_count=1,
        traffic_class_to_vcs={"A": [0]}, derivation="directed_ring")
    return topo, rr, rra, vc


def _parallel_hop_ring():
    """0 -> 1 -> {2,2} -> 0: the 1->2 hop has two parallel channels."""
    routers = (Router(0, (0,), 1), Router(1, (1,), 1), Router(2, (2,), 1))
    channels = (
        DirectedChannel(0, 0, 0, 1, 0, 64, 1),
        DirectedChannel(1, 1, 0, 2, 0, 64, 1),
        DirectedChannel(2, 1, 1, 2, 1, 64, 1),
        DirectedChannel(3, 2, 0, 0, 0, 64, 1),
    )
    topo = TopologyArtifact(
        family=MaterializedFamily.RING, routers=routers, channels=channels)
    rr = RouteArtifact.from_topology(topo, name="parallel_hop_ring")
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(),
        attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=((0, 0), (1, 1), (2, 2)),
        routing_classes=(ANYNET_MIN_HOPS,),
        endpoint_route_table_hash="b" * 64,
    )
    vc = make_vc_assignment_artifact(
        resolved_route=rra, vc_count=1,
        traffic_class_to_vcs={"A": [0]}, derivation="parallel_hop_ring")
    return topo, rr, rra, vc


def _dor_mesh(k=3):
    """DOR_XY route authority + endpoint-resolved binding + 1 VC."""
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family,
    )
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=k * k)
    rr = RouteArtifact.from_topology(
        topo, name=f"dor{k}", routing_classes=(DOR_XY,))
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(),
        attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=tuple((i, i) for i in range(k * k)),
        routing_classes=(DOR_XY,),
        endpoint_route_table_hash="b" * 64,
    )
    vc = make_vc_assignment_artifact(
        resolved_route=rra, vc_count=1,
        traffic_class_to_vcs={"A": [0]}, derivation=f"dor_mesh{k}")
    return topo, rr, rra, vc


class TestDORXYGoldenPositive:
    @pytest.mark.parametrize("k", (2, 3, 4))
    def test_dor_xy_mesh_with_one_vc_is_acyclic(self, k):
        """The canonical positive deadlock case: mesh + exact DOR_XY +
        one VC must PASS. If this fails, the CDG is wrong."""
        topo, rr, rra, vc = _dor_mesh(k)
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict == "PASS"
        assert cert.evidence["acyclic"] is True
        assert cert.evidence["cdg_route_classes"] == [DOR_XY]


def _mixed_class_mesh():
    """2x2 mesh with two classes; VC0 -> ANYNET_MIN_HOPS, VC1 -> DOR_XY.

    For (2 -> 1) the two classes pick different first hops:
      ANYNET_MIN_HOPS: 2->0 (channel 4), then 0->1 (channel 0)
      DOR_XY:          2->3 (channel 5), then 3->1 (channel 6)
    """
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family,
    )
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    rr = RouteArtifact.from_topology(
        topo, name="mixed",
        routing_classes=(ANYNET_MIN_HOPS, DOR_XY))
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(),
        attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=((0, 0), (1, 1), (2, 2), (3, 3)),
        routing_classes=(ANYNET_MIN_HOPS, DOR_XY),
        endpoint_route_table_hash="b" * 64,
    )
    vc = make_vc_assignment_artifact(
        resolved_route=rra, vc_count=2,
        traffic_class_to_vcs={"A": [0], "B": [1]},
        vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY},
        allowed_transitions=[(0, 0), (1, 1)],
        derivation="mixed_class_mesh")
    return topo, rr, rra, vc


class TestVCOutClassSelection:
    def test_next_channel_uses_the_class_of_vc_out(self):
        topo, rr, rra, vc = _mixed_class_mesh()
        cdg = build_channel_vc_cdg(topo, rr, vc)
        assert cdg.cdg_route_classes == (ANYNET_MIN_HOPS, DOR_XY)
        # VC0 (ANYNET) on 2->0 toward 1 requests 0->1
        assert ((4, 0), (0, 0)) in cdg.edges
        # VC1 (DOR_XY) on 2->3 toward 1 requests 3->1
        assert ((5, 1), (6, 1)) in cdg.edges
        # ...and neither class leaks into the other VC's edges
        assert ((4, 1), (0, 1)) not in cdg.edges
        assert ((5, 0), (6, 0)) not in cdg.edges
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict in ("PASS", "FAIL")
        assert cert.evidence["cdg_route_classes"] == [
            ANYNET_MIN_HOPS, DOR_XY]

    def test_unknown_vc_class_is_unsupported(self):
        topo, rr, _rra, _vc = _mixed_class_mesh()
        rra = ResolvedRouteArtifact(
            topology_hash=topo.topology_hash(),
            attachment_hash="a" * 64,
            router_route_hash=rr.artifact_hash,
            endpoint_to_router=((0, 0), (1, 1), (2, 2), (3, 3)),
            routing_classes=("ESCAPE",),
            endpoint_route_table_hash="b" * 64,
        )
        vc = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=1,
            traffic_class_to_vcs={"A": [0]},
            vc_to_routing_class={0: "ESCAPE"}, derivation="unit")
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict == "UNSUPPORTED"
        assert "ESCAPE" in cert.evidence["unsupported_reason"]


class TestTwoRouterPasses:
    def test_acyclic_fabric_passes(self):
        topo, rr, rra, vc = _two_router()
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict == "PASS"
        assert cert.proof_method == CHANNEL_VC_DEPENDENCY_ACYCLIC
        assert cert.evidence["acyclic"] is True
        assert cert.topology_hash == topo.topology_hash()
        assert cert.attachment_hash == rra.attachment_hash
        assert cert.resolved_route_hash == rra.resolved_route_hash()
        assert cert.vc_assignment_hash == vc.vc_assignment_hash()

    def test_node_count_is_channels_times_vcs(self):
        topo, rr, _rra, vc = _two_router()
        cdg = build_channel_vc_cdg(topo, rr, vc)
        assert cdg.node_count == topo.channel_count * vc.vc_count
        assert cdg.edge_count == 0  # both channels eject at the far end

    def test_identity_transitions_never_cross_vcs(self):
        topo, rr, _rra, vc = _two_router()
        cdg = build_channel_vc_cdg(topo, rr, vc)
        assert all(src[1] == dst[1] for src, dst in cdg.edges)


class TestObservedVerdicts:
    """Verdicts here are OBSERVED for these fixtures, not general theorems.

    The pre-B3.3c builder had an edge-construction bug (dependencies landed
    on the exits of the NEXT router, one hop too far), so the earlier
    mesh/ring FAILs were not valid evidence. B3.2d/B3.3d re-certify with
    exact per-routing-class channel realization and DOR_XY golden cases.
    """

    def test_directed_ring_is_cyclic(self):
        topo, rr, rra, vc = _directed_ring()
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict == "FAIL"
        assert cert.evidence["acyclic"] is False
        assert len(cert.evidence["cycle"]) == 4  # 3 channels + closing node

    def test_two_by_two_mesh_shortest_path_is_acyclic_here(self):
        _cr, topo, rr, rra, vc = _mesh_chain(cycles=1)
        assert vc.vc_count == 2
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        # Observed: AnyNet shortest paths on this 2x2 fixture form two
        # disjoint channel chains. NOT a general mesh claim — arbitrary
        # shortest-path meshes may cycle, and VC-preserving transitions do
        # not break a physical cycle.
        assert cert.verdict == "PASS"
        assert cert.evidence["acyclic"] is True
        assert cert.evidence["route_realization"] == "v2_channel_id"

    def test_mesh_verdict_is_deterministic(self):
        _cr, topo, rr, rra, vc = _mesh_chain(cycles=1)
        c1 = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
        c2 = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
        assert c1.evidence == c2.evidence

    def test_cycle_witness_is_deterministic(self):
        topo, rr, rra, vc = _directed_ring()
        c1 = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
        c2 = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
        assert c1.evidence["cycle"] == c2.evidence["cycle"]

    def test_wraparound_anynet_fixtures_are_observed_not_blessed(self):
        """Torus wraparound with the AnyNet replica is acyclic at 2x2/3x3
        (cross-checked against deadlock_routing.build_cdg_and_check).

        This is NOT a wraparound safety theorem and NOT DOR_XY (which
        refuses torus entirely); wraparound needs its own class plus an
        escape/VC discipline before any torus claim is made.
        """
        from veritx_dse.model.topology_artifact import (
            MaterializedFamily, materialize_family,
        )
        for k in (2, 3):
            topo = materialize_family(
                MaterializedFamily.TORUS, endpoint_count=k * k)
            rr = RouteArtifact.from_topology(
                topo, name=f"torus{k}",
                routing_classes=(ANYNET_MIN_HOPS,))
            rra = ResolvedRouteArtifact(
                topology_hash=topo.topology_hash(),
                attachment_hash="a" * 64,
                router_route_hash=rr.artifact_hash,
                endpoint_to_router=tuple((i, i) for i in range(k * k)),
                routing_classes=(ANYNET_MIN_HOPS,),
                endpoint_route_table_hash="b" * 64,
            )
            vc = make_vc_assignment_artifact(
                resolved_route=rra, vc_count=1,
                traffic_class_to_vcs={"A": [0]}, derivation="torus")
            cert = certify_channel_vc_deadlock(
                topology=topo, resolved_route=rra, router_route=rr,
                vc_assignment=vc)
            assert cert.verdict == "PASS"
            assert cert.evidence["acyclic"] is True


class TestCDGEdgeConstruction:
    def test_dependency_targets_the_next_channel_not_the_exit_of_nxt(self):
        """Regression: the edge is (u->v, vc) -> (v->nxt, vc), never
        (u->v, vc) -> (nxt->*, vc)."""
        topo, rr, _rra, vc = _directed_ring()
        cdg = build_channel_vc_cdg(topo, rr, vc)
        # 0->1 toward 2 requests the channel 1->2 (id 1), not 2->0 (id 2)
        assert ((0, 0), (1, 0)) in cdg.edges
        assert ((0, 0), (2, 0)) not in cdg.edges

    def test_parallel_hop_uses_the_declared_min_channel(self):
        topo, rr, rra, vc = _parallel_hop_ring()
        # the 1->2 hop has channels 1 and 2; ANYNET_MIN_HOPS declares
        # min_channel_id, so the realization is exact and declared.
        assert rr.entries[(ANYNET_MIN_HOPS, 1, 2)] == 1
        cdg = build_channel_vc_cdg(topo, rr, vc)
        assert cdg.cdg_route_classes == (ANYNET_MIN_HOPS,)
        assert ((0, 0), (1, 0)) in cdg.edges
        assert ((0, 0), (2, 0)) not in cdg.edges
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.evidence["route_realization"] == "v2_channel_id"
        assert cert.evidence["cdg_route_classes"] == [ANYNET_MIN_HOPS]


class TestFailClosed:
    def test_tampered_vc_binding_refused(self):
        topo, rr, rra, vc = _two_router()
        object.__setattr__(vc, "resolved_route_hash", "0" * 64)
        with pytest.raises(CDGError, match="VC assignment"):
            certify_channel_vc_deadlock(
                topology=topo, resolved_route=rra, router_route=rr,
                vc_assignment=vc)

    def test_tampered_topology_binding_refused(self):
        _cr, topo, rr, rra, vc = _mesh_chain(cycles=1)
        other = _mesh_chain(n=9, cycles=1)[1]
        with pytest.raises(CDGError, match="topology"):
            certify_channel_vc_deadlock(
                topology=other, resolved_route=rra, router_route=rr,
                vc_assignment=vc)

    def test_uninterpretable_class_is_unsupported(self):
        topo, rr, _rra, _vc = _two_router()
        rra = ResolvedRouteArtifact(
            topology_hash=topo.topology_hash(),
            attachment_hash="a" * 64,
            router_route_hash=rr.artifact_hash,
            endpoint_to_router=((0, 0), (1, 1), (2, 2)),
            routing_classes=("ESCAPE",),
            endpoint_route_table_hash="b" * 64,
        )
        vc = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=1,
            traffic_class_to_vcs={"A": [0]},
            vc_to_routing_class={0: "ESCAPE"}, derivation="unit")
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict == "UNSUPPORTED"
        assert "ESCAPE" in cert.evidence["unsupported_reason"]

    def test_vocabulary_is_closed(self):
        assert CHANNEL_VC_DEPENDENCY_ACYCLIC in DEADLOCK_PROOF_METHODS
        assert len(DEADLOCK_PROOF_METHODS) == 4

    def test_certificate_binds_all_hashes(self):
        topo, rr, rra, vc = _two_router()
        d = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc, router_behavior_hash="c" * 64).to_dict()
        for key in ("topology_hash", "attachment_hash", "router_route_hash",
                    "resolved_route_hash",
                    "vc_assignment_hash", "router_behavior_hash",
                    "proof_method", "evidence", "tool", "scope"):
            assert key in d
        assert d["router_behavior_hash"] == "c" * 64
        assert d["router_route_hash"] == rr.artifact_hash
