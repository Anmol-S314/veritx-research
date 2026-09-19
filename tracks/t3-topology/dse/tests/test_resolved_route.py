"""Wave B3.2 tests — endpoint-resolved routing + topology-bound router routes."""
from __future__ import annotations

import pytest

from veritx_dse.core.route_artifact import (
    RouteArtifact, RouteArtifactError, route_entries_from_adj,
)
from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, Endpoint, derive_attachment,
)
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.mapping import derive_mapping
from veritx_dse.model.placement import AgentInstance, build_inventory
from veritx_dse.model.resolved_route import (
    LOCAL_EJECTION, ResolvedRouteArtifact, ResolvedRouteError,
    derive_resolved_route,
)
from veritx_dse.model.topology_artifact import materialize_topology


def _cr(agents, family=TopologyFamily.MESH, concentration=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=agents, dependencies=[],
        noc_config=NocConfig(topology_family=family, concentration=concentration),
    )


def _fabric(n=4, **kw):
    cr = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=n)], **kw)
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(inv, derive_mapping(cr), topo)
    rr = RouteArtifact.from_topology(topo, name="t")
    return topo, att, rr


def test_binds_all_three_parents():
    topo, att, rr = _fabric(4)
    rra = derive_resolved_route(topo, att, rr)
    assert rra.topology_hash == topo.topology_hash()
    assert rra.attachment_hash == att.attachment_hash()
    assert rra.router_route_hash == rr.artifact_hash
    assert rra.validate_against(topo, att, rr) is None
    assert len(rra.resolved_route_hash()) == 64


def test_local_ejection_for_same_router_endpoints():
    # one router, four local seats -> every endpoint pair is local
    topo, att, rr = _fabric(4, family=TopologyFamily.CONCENTRATED_MESH,
                            concentration=4)
    assert topo.router_count == 1
    rra = derive_resolved_route(topo, att, rr)
    from veritx_dse.model.resolved_route import _endpoint_route_table
    rows = _endpoint_route_table(rra.endpoint_to_router,
                                 rra.routing_classes, rr.entries)
    assert rows and all(r[3] == LOCAL_EJECTION for r in rows)


def test_same_router_route_different_attachment_differs():
    """The spec's proof case: same topology and router routes, swapped
    endpoint placement must change the resolved binding (and only it)."""
    topo, _att, rr = _fabric(4)
    a0 = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    a1 = AgentInstance(0, 1, AgentKind.COMPUTE_TILE)
    att_a = AgentAttachmentArtifact(
        topology_hash=topo.topology_hash(), mapping_hash="m" * 64,
        endpoints=(Endpoint(0, a0, 0, 0), Endpoint(1, a1, 3, 0)))
    att_b = AgentAttachmentArtifact(
        topology_hash=topo.topology_hash(), mapping_hash="m" * 64,
        endpoints=(Endpoint(0, a0, 3, 0), Endpoint(1, a1, 0, 0)))

    ra = derive_resolved_route(topo, att_a, rr)
    rb = derive_resolved_route(topo, att_b, rr)
    assert ra.topology_hash == rb.topology_hash
    assert ra.router_route_hash == rb.router_route_hash
    assert ra.attachment_hash != rb.attachment_hash
    assert ra.resolved_route_hash() != rb.resolved_route_hash()


def test_validate_against_refuses_wrong_parents():
    topo, att, rr = _fabric(4)
    rra = derive_resolved_route(topo, att, rr)
    other_topo, other_att, _ = _fabric(4, family=TopologyFamily.TORUS)
    with pytest.raises(ResolvedRouteError, match="topology_hash"):
        rra.validate_against(other_topo, att, rr)
    with pytest.raises(ResolvedRouteError, match="attachment_hash"):
        rra.validate_against(topo, other_att, rr)


def test_resolved_self_integrity_on_load():
    topo, att, rr = _fabric(4)
    rra = derive_resolved_route(topo, att, rr)
    d = rra.to_dict()
    assert ResolvedRouteArtifact.from_dict(d).resolved_route_hash() \
        == rra.resolved_route_hash()
    d["endpoint_to_router"][0][1] = 99
    with pytest.raises(ResolvedRouteError):
        ResolvedRouteArtifact.from_dict(d)


def test_unknown_fields_refused():
    topo, att, rr = _fabric(4)
    d = derive_resolved_route(topo, att, rr).to_dict()
    d["router"] = 1
    with pytest.raises(ResolvedRouteError, match="unknown fields"):
        ResolvedRouteArtifact.from_dict(d)


# ── router RouteArtifact ↔ TopologyArtifact binding ─────────────────────────

def test_from_topology_uses_authoritative_topology_hash():
    topo, _att, _rr = _fabric(4)
    rr = RouteArtifact.from_topology(topo, name="mesh")
    assert rr.topology_hash == topo.topology_hash()
    rr.validate_against(topo)


def test_validate_against_refuses_a_different_topology():
    mesh, _att, _rr = _fabric(4)
    torus, _att2, _rr2 = _fabric(4, family=TopologyFamily.TORUS)
    rr = RouteArtifact.from_topology(mesh, name="mesh")
    with pytest.raises(RouteArtifactError, match="topology_hash"):
        rr.validate_against(torus)


def test_public_helper_refuses_disconnected_graphs():
    adj = {0: {1}, 1: {0}, 2: {3}, 3: {2}}
    with pytest.raises(RouteArtifactError, match="disconnected"):
        route_entries_from_adj(adj)
