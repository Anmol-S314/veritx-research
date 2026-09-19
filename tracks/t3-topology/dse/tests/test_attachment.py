"""Wave B3.1/B3.1c tests — AgentAttachmentArtifact semantics + interface."""
from __future__ import annotations

import pytest

from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, AgentInterfaceDescriptor, AttachmentError,
    Endpoint, derive_attachment,
)
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.mapping import MappingArtifact, RankPlacement, derive_mapping
from veritx_dse.model.placement import AgentInstance, build_inventory
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, materialize_family, materialize_topology,
)

_IFACE = AgentInterfaceDescriptor(
    data_width_bits=256, address_width_bits=64, protocol="AXI",
    clock_domain=None, power_domain=None)


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
    return cr, inv, mapping, topo, derive_attachment(inv, mapping, topo, cr)


def test_every_agent_gets_an_endpoint():
    _cr_a, inv, _m, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert att.endpoint_count == 4 == inv.agent_count
    assert [e.endpoint_id for e in att.endpoints] == [0, 1, 2, 3]


def test_endpoint_ids_follow_router_seat_order():
    _cr_a, _inv, _m, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    got = [(e.router_id, e.port_id) for e in att.endpoints]
    assert got == [(0, 0), (1, 0), (2, 0), (3, 0)]  # mesh 2x2, one seat each


def test_non_compute_agents_attach_too():
    _cr_a, _inv, _m, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=2),
         Agent(kind=AgentKind.HBM_CONTROLLER, count=2)])
    kinds = sorted(e.agent.kind.value for e in att.endpoints)
    assert kinds == ["compute_tile", "compute_tile",
                     "hbm_controller", "hbm_controller"]


def test_idle_compute_instances_attach():
    _cr_a, inv, _m, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert inv.rank_count == 1        # world_size 1
    assert att.endpoint_count == 4    # every hardware agent attached


def test_unknown_mapping_agent_is_refused():
    cr, inv, _m, topo, _att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    bad = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=AgentInstance(99, 0, AgentKind.COMPUTE_TILE)),))
    with pytest.raises(AttachmentError, match="not in the inventory"):
        derive_attachment(inv, bad, topo, cr)


def test_insufficient_seats_refused():
    cr, inv, mapping, _t, _att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    one = materialize_family(MaterializedFamily.RING, endpoint_count=1)
    with pytest.raises(AttachmentError, match="seats"):
        derive_attachment(inv, mapping, one, cr)


def test_artifact_rejects_duplicate_agent_or_seat():
    a = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    b = AgentInstance(0, 1, AgentKind.COMPUTE_TILE)
    with pytest.raises(AttachmentError, match="duplicate agent"):
        AgentAttachmentArtifact(
            design_hash="d", topology_hash="t", mapping_hash="m",
            endpoints=(Endpoint(0, a, 0, 0, _IFACE),
                       Endpoint(1, a, 1, 0, _IFACE)))
    with pytest.raises(AttachmentError, match="duplicate seat"):
        AgentAttachmentArtifact(
            design_hash="d", topology_hash="t", mapping_hash="m",
            endpoints=(Endpoint(0, a, 0, 0, _IFACE),
                       Endpoint(1, b, 0, 0, _IFACE)))


def test_round_trip_and_tamper_detection():
    _cr_a, _inv, _m, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    d = att.to_dict()
    assert AgentAttachmentArtifact.from_dict(d).attachment_hash() \
        == att.attachment_hash()
    d["endpoints"][0]["router_id"] = 9
    with pytest.raises(AttachmentError, match="does not match content"):
        AgentAttachmentArtifact.from_dict(d)


def test_unknown_fields_refused():
    _cr_a, _inv, _m, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    d = att.to_dict()
    d["endpoints"][0]["topology"] = "mesh"
    with pytest.raises(AttachmentError, match="unknown fields"):
        AgentAttachmentArtifact.from_dict(d)


def test_attachment_binds_design_topology_and_mapping_hashes():
    cr, _inv, mapping, topo, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert att.design_hash == cr.design_hash()
    assert att.topology_hash == topo.topology_hash()
    assert att.mapping_hash == mapping.mapping_hash()


def test_attachment_hash_changes_when_mapping_changes():
    cr_a = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    inv = build_inventory(cr_a)
    topo = materialize_topology(inv, cr_a)
    a = derive_attachment(inv, derive_mapping(cr_a), topo, cr_a)
    swapped = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=AgentInstance(0, 1, AgentKind.COMPUTE_TILE)),))
    b = derive_attachment(inv, swapped, topo, cr_a)
    assert a.attachment_hash() != b.attachment_hash()


# ── B3.1c interface authority ────────────────────────────────────────────

class TestInterfaceAuthority:
    def test_endpoint_carries_parent_group_interface(self):
        _cr_a, _inv, _m, _t, att = _derive([
            Agent(kind=AgentKind.COMPUTE_TILE, count=2, data_width=512,
                  addr_width=48, protocol="CHI", clock_domain="clk_core",
                  power_domain="pd_core"),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=2),
        ])
        by_kind: dict[str, list] = {}
        for e in att.endpoints:
            by_kind.setdefault(e.agent.kind.value, []).append(e.interface)
        assert by_kind["compute_tile"][0] == AgentInterfaceDescriptor(
            data_width_bits=512, address_width_bits=48, protocol="CHI",
            clock_domain="clk_core", power_domain="pd_core")
        assert by_kind["hbm_controller"][0] == _IFACE

    def test_interface_change_changes_attachment_hash(self):
        cr_a = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        inv = build_inventory(cr_a)
        topo = materialize_topology(inv, cr_a)
        a = derive_attachment(inv, derive_mapping(cr_a), topo, cr_a)
        twin = AgentAttachmentArtifact(
            design_hash=a.design_hash, topology_hash=a.topology_hash,
            mapping_hash=a.mapping_hash,
            endpoints=tuple(
                Endpoint(e.endpoint_id, e.agent, e.router_id, e.port_id,
                         AgentInterfaceDescriptor(
                             512, 64, "AXI", None, None))
                for e in a.endpoints))
        assert twin.attachment_hash() != a.attachment_hash()

    def test_wrong_interface_refused(self):
        cr, _inv, mapping, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4, protocol="AXI")])
        bad = AgentInterfaceDescriptor(256, 64, "CHI", None, None)
        twin = AgentAttachmentArtifact(
            design_hash=att.design_hash, topology_hash=att.topology_hash,
            mapping_hash=att.mapping_hash,
            endpoints=tuple(
                Endpoint(e.endpoint_id, e.agent, e.router_id, e.port_id, bad)
                for e in att.endpoints))
        with pytest.raises(AttachmentError, match="interface descriptor"):
            twin.validate_against(cr, topo, mapping)

    def test_group_out_of_range_refused(self):
        cr, _inv, mapping, topo, _att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        twin = AgentAttachmentArtifact(
            design_hash=cr.design_hash(), topology_hash=topo.topology_hash(),
            mapping_hash=mapping.mapping_hash(),
            endpoints=(Endpoint(
                0, AgentInstance(7, 0, AgentKind.COMPUTE_TILE), 0, 0, _IFACE),))
        with pytest.raises(AttachmentError, match="outside the design"):
            twin.validate_against(cr, topo, mapping)

    def test_instance_index_out_of_range_refused(self):
        cr, _inv, mapping, topo, _att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        twin = AgentAttachmentArtifact(
            design_hash=cr.design_hash(), topology_hash=topo.topology_hash(),
            mapping_hash=mapping.mapping_hash(),
            endpoints=(Endpoint(
                0, AgentInstance(0, 9, AgentKind.COMPUTE_TILE), 0, 0, _IFACE),))
        with pytest.raises(AttachmentError, match="outside Agent group"):
            twin.validate_against(cr, topo, mapping)

    def test_kind_mismatch_refused(self):
        cr, _inv, mapping, topo, _att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        twin = AgentAttachmentArtifact(
            design_hash=cr.design_hash(), topology_hash=topo.topology_hash(),
            mapping_hash=mapping.mapping_hash(),
            endpoints=(Endpoint(
                0, AgentInstance(0, 0, AgentKind.HBM_CONTROLLER), 0, 0, _IFACE),))
        with pytest.raises(AttachmentError, match="does not match Agent group"):
            twin.validate_against(cr, topo, mapping)

    def test_seat_out_of_range_refused(self):
        cr, _inv, mapping, topo, _att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        twin = AgentAttachmentArtifact(
            design_hash=cr.design_hash(), topology_hash=topo.topology_hash(),
            mapping_hash=mapping.mapping_hash(),
            endpoints=(Endpoint(
                0, AgentInstance(0, 0, AgentKind.COMPUTE_TILE), 99, 0, _IFACE),))
        with pytest.raises(AttachmentError, match="not in the topology"):
            twin.validate_against(cr, topo, mapping)

    def test_tampered_mapping_wrong_kind_refused(self):
        cr, _inv, mapping, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        object.__setattr__(mapping.placements[0], "agent",
                           AgentInstance(0, 0, AgentKind.HBM_CONTROLLER))
        # rebind the (tampered) mapping hash so the check under test runs
        twin = AgentAttachmentArtifact(
            design_hash=att.design_hash, topology_hash=att.topology_hash,
            mapping_hash=mapping.mapping_hash(), endpoints=att.endpoints)
        with pytest.raises(AttachmentError, match="but the attachment bound"):
            twin.validate_against(cr, topo, mapping)

    def test_wrong_design_refused(self):
        _cr_a, _inv, mapping, _topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        cr_b = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=4,
                          data_width=512)])
        inv_b = build_inventory(cr_b)
        topo_b = materialize_topology(inv_b, cr_b)
        with pytest.raises(AttachmentError, match="design_hash"):
            att.validate_against(cr_b, topo_b, mapping)


class TestSchemaV1Refusal:
    def test_v1_attachment_refused(self):
        _cr_a, _inv, _m, _t, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        d = att.to_dict()
        d["schema_version"] = 1
        with pytest.raises(AttachmentError, match="schema v1|silent migration"):
            AgentAttachmentArtifact.from_dict(d)

    def test_missing_interface_refused(self):
        _cr_a, _inv, _m, _t, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        d = att.to_dict()
        del d["endpoints"][0]["interface"]
        with pytest.raises(AttachmentError, match="interface"):
            AgentAttachmentArtifact.from_dict(d)

    def test_interface_tamper_detected(self):
        _cr_a, _inv, _m, _t, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        d = att.to_dict()
        d["endpoints"][0]["interface"]["protocol"] = "CHI"
        with pytest.raises(AttachmentError, match="does not match content"):
            AgentAttachmentArtifact.from_dict(d)
