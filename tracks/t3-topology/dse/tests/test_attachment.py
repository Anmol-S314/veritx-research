"""Wave B3.1 tests — AgentAttachmentArtifact semantics."""
from __future__ import annotations

import pytest

from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, AttachmentError, Endpoint, derive_attachment,
)
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.mapping import MappingArtifact, RankPlacement, derive_mapping
from veritx_dse.model.placement import AgentInstance, build_inventory
from veritx_dse.model.topology_artifact import materialize_topology


def _cr(agents, family=TopologyFamily.MESH, concentration=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=agents, dependencies=[],
        noc_config=NocConfig(topology_family=family, concentration=concentration),
    )


def _derive(agents, **kw):
    cr = _cr(agents, **kw)
    inv = build_inventory(cr)
    mapping = derive_mapping(cr)
    topo = materialize_topology(inv, cr)
    return inv, mapping, topo, derive_attachment(inv, mapping, topo)


def test_every_agent_gets_an_endpoint():
    inv, mapping, topo, att = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert att.endpoint_count == 4 == inv.agent_count
    assert [e.endpoint_id for e in att.endpoints] == [0, 1, 2, 3]


def test_endpoint_ids_follow_router_seat_order():
    inv, mapping, topo, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    got = [(e.router_id, e.port_id) for e in att.endpoints]
    assert got == [(0, 0), (1, 0), (2, 0), (3, 0)]  # mesh 2x2, one seat each


def test_non_compute_agents_attach_too():
    inv, mapping, topo, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=2),
         Agent(kind=AgentKind.HBM_CONTROLLER, count=2)])
    kinds = sorted(e.agent.kind.value for e in att.endpoints)
    assert kinds == ["compute_tile", "compute_tile",
                     "hbm_controller", "hbm_controller"]


def test_idle_compute_instances_attach():
    # 2 ranks' worth of compute tiles but the cr has 4 compute agents
    inv, mapping, topo, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert inv.rank_count == 1        # world_size 1
    assert att.endpoint_count == 4    # every hardware agent attached


def test_unknown_mapping_agent_is_refused():
    inv, _, topo, _ = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    bad = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=AgentInstance(99, 0, AgentKind.COMPUTE_TILE)),))
    with pytest.raises(AttachmentError, match="not in the inventory"):
        derive_attachment(inv, bad, topo)


def test_insufficient_seats_refused():
    inv, mapping, _, _ = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    # a ring of 1 router has 1 seat but 4 agents must attach
    from veritx_dse.model.topology_artifact import (MaterializedFamily,
                                                    materialize_family)
    one = materialize_family(MaterializedFamily.RING, endpoint_count=1)
    with pytest.raises(AttachmentError, match="seats"):
        derive_attachment(inv, mapping, one)


def test_artifact_rejects_duplicate_agent_or_seat():
    a = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    b = AgentInstance(0, 1, AgentKind.COMPUTE_TILE)
    with pytest.raises(AttachmentError, match="duplicate agent"):
        AgentAttachmentArtifact(topology_hash="t", mapping_hash="m",
                                endpoints=(Endpoint(0, a, 0, 0),
                                           Endpoint(1, a, 1, 0)))
    with pytest.raises(AttachmentError, match="duplicate seat"):
        AgentAttachmentArtifact(topology_hash="t", mapping_hash="m",
                                endpoints=(Endpoint(0, a, 0, 0),
                                           Endpoint(1, b, 0, 0)))


def test_round_trip_and_tamper_detection():
    _, _, _, att = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    d = att.to_dict()
    assert AgentAttachmentArtifact.from_dict(d).attachment_hash() \
        == att.attachment_hash()
    d["endpoints"][0]["router_id"] = 9
    with pytest.raises(AttachmentError, match="does not match content"):
        AgentAttachmentArtifact.from_dict(d)


def test_unknown_fields_refused():
    _, _, _, att = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    d = att.to_dict()
    d["endpoints"][0]["topology"] = "mesh"
    with pytest.raises(AttachmentError, match="unknown fields"):
        AgentAttachmentArtifact.from_dict(d)


def test_attachment_binds_topology_and_mapping_hashes():
    _, mapping, topo, att = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert att.topology_hash == topo.topology_hash()
    assert att.mapping_hash == mapping.mapping_hash()


def test_attachment_hash_changes_when_mapping_changes():
    cr_a = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    inv = build_inventory(cr_a)
    topo = materialize_topology(inv, cr_a)
    a = derive_attachment(inv, derive_mapping(cr_a), topo)
    swapped = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=AgentInstance(0, 1, AgentKind.COMPUTE_TILE)),))
    b = derive_attachment(inv, swapped, topo)
    assert a.attachment_hash() != b.attachment_hash()
