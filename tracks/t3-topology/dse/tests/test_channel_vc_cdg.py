"""Wave B3.3b tests — realized (channel, VC) dependency graph + certificate."""
from __future__ import annotations

import pytest

from veritx_dse.core.route_artifact import RouteArtifact
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
from veritx_dse.model.vc_assignment import (
    DEFAULT_ROUTING_CLASS, make_vc_assignment_artifact,
)
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
    att = derive_attachment(inv, derive_mapping(cr), topo)
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
        routing_classes=(DEFAULT_ROUTING_CLASS,),
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
        routing_classes=(DEFAULT_ROUTING_CLASS,),
        endpoint_route_table_hash="b" * 64,
    )
    vc = make_vc_assignment_artifact(
        resolved_route=rra, vc_count=1,
        traffic_class_to_vcs={"A": [0]}, derivation="directed_ring")
    return topo, rr, rra, vc


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


class TestMeshFailsHonestly:
    def test_directed_ring_is_cyclic(self):
        topo, rr, rra, vc = _directed_ring()
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        assert cert.verdict == "FAIL"
        assert cert.evidence["acyclic"] is False
        assert len(cert.evidence["cycle"]) == 4  # 3 channels + closing node

    def test_bidirectional_mesh_is_cyclic(self):
        _cr, topo, rr, rra, vc = _mesh_chain(cycles=1)
        assert vc.vc_count == 2
        cert = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)
        # shortest-path routing over bidirectional links has a physical
        # 2-cycle; VC-preserving transitions do not launder it.
        assert cert.verdict == "FAIL"
        assert cert.evidence["acyclic"] is False
        cycle = cert.evidence["cycle"]
        assert len(cycle) >= 3
        assert cycle[0] == cycle[-1]

    def test_failure_is_deterministic(self):
        _cr, topo, rr, rra, vc = _mesh_chain(cycles=1)
        c1 = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
        c2 = certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
        assert c1.evidence["cycle"] == c2.evidence["cycle"]


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
        for key in ("topology_hash", "attachment_hash", "resolved_route_hash",
                    "vc_assignment_hash", "router_behavior_hash",
                    "proof_method", "evidence", "tool", "scope"):
            assert key in d
        assert d["router_behavior_hash"] == "c" * 64
