"""Wave B3.1/B3.1c/B3.1d tests — attachment identity and interface authority.

B3.1d rule under test: attachment identity is topology-bound hardware
semantics only. DesignRevision and NodeInventory are validation sources;
MappingArtifact is a downstream ResolvedFabric concern. The same hardware
with a different mapping or an unrelated design change must keep the same
attachment_hash.
"""
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


def _cr(agents, family=TopologyFamily.MESH, concentration=None,
        model_family=ModelFamily.MOE):
    return CompileRequest(
        workload=Workload(model_family=model_family, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=agents, dependencies=[],
        noc_config=NocConfig(topology_family=family, concentration=concentration),
    )


def _make(agents, **kw):
    cr = _cr(agents, **kw)
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    return cr, inv, topo


def _derive(agents, **kw):
    cr, inv, topo = _make(agents, **kw)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    return cr, inv, topo, att


# ── B3.1 baseline ────────────────────────────────────────────────────────

def test_every_agent_gets_an_endpoint():
    _cr_a, inv, _t, att = _derive([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert att.endpoint_count == 4 == inv.agent_count
    assert [e.endpoint_id for e in att.endpoints] == [0, 1, 2, 3]


def test_endpoint_ids_follow_router_seat_order():
    _cr_a, _inv, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    got = [(e.router_id, e.port_id) for e in att.endpoints]
    assert got == [(0, 0), (1, 0), (2, 0), (3, 0)]  # mesh 2x2, one seat each


def test_non_compute_agents_attach_too():
    _cr_a, _inv, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=2),
         Agent(kind=AgentKind.HBM_CONTROLLER, count=2)])
    kinds = sorted(e.agent.kind.value for e in att.endpoints)
    assert kinds == ["compute_tile", "compute_tile",
                     "hbm_controller", "hbm_controller"]


def test_idle_compute_instances_attach():
    _cr_a, inv, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    assert inv.rank_count == 1        # world_size 1
    assert att.endpoint_count == 4    # every hardware agent attached


def test_insufficient_seats_refused():
    cr, inv, _t = _make([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    one = materialize_family(MaterializedFamily.RING, endpoint_count=1)
    with pytest.raises(AttachmentError, match="seats"):
        derive_attachment(design=cr, inventory=inv, topology=one)


def test_artifact_rejects_duplicate_agent_or_seat():
    a = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    b = AgentInstance(0, 1, AgentKind.COMPUTE_TILE)
    with pytest.raises(AttachmentError, match="duplicate agent"):
        AgentAttachmentArtifact(
            topology_hash="t",
            endpoints=(Endpoint(0, a, 0, 0, _IFACE),
                       Endpoint(1, a, 1, 0, _IFACE)))
    with pytest.raises(AttachmentError, match="duplicate seat"):
        AgentAttachmentArtifact(
            topology_hash="t",
            endpoints=(Endpoint(0, a, 0, 0, _IFACE),
                       Endpoint(1, b, 0, 0, _IFACE)))


def test_round_trip_and_tamper_detection():
    _cr_a, _inv, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    d = att.to_dict()
    assert AgentAttachmentArtifact.from_dict(d).attachment_hash() \
        == att.attachment_hash()
    d["endpoints"][0]["router_id"] = 9
    with pytest.raises(AttachmentError, match="does not match content"):
        AgentAttachmentArtifact.from_dict(d)


def test_unknown_fields_refused():
    _cr_a, _inv, _t, att = _derive(
        [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    d = att.to_dict()
    d["endpoints"][0]["topology"] = "mesh"
    with pytest.raises(AttachmentError, match="unknown fields"):
        AgentAttachmentArtifact.from_dict(d)


# ── B3.1d identity boundary ──────────────────────────────────────────────

class TestIdentityBoundary:
    def test_attachment_binds_topology_only(self):
        _cr_a, _inv, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        assert att.topology_hash == topo.topology_hash()
        assert set(att.canonical_dict()) == {
            "type", "schema_version", "topology_hash", "endpoints"}

    def test_same_hardware_different_mapping_same_attachment_hash(self):
        cr, inv, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        mapping_a = derive_mapping(cr)
        mapping_b = MappingArtifact(placements=(
            RankPlacement(
                rank=0, agent=AgentInstance(0, 3, AgentKind.COMPUTE_TILE)),))
        assert mapping_a.mapping_hash() != mapping_b.mapping_hash()
        again = derive_attachment(design=cr, inventory=inv, topology=topo)
        assert again.attachment_hash() == att.attachment_hash()

    def test_unrelated_design_change_keeps_attachment_hash(self):
        agents = [Agent(kind=AgentKind.COMPUTE_TILE, count=4)]
        cr_a, inv_a, topo_a = _make(agents, model_family=ModelFamily.MOE)
        cr_b, inv_b, topo_b = _make(agents,
                                    model_family=ModelFamily.DENSE_TRANSFORMER)
        assert cr_a.design_hash() != cr_b.design_hash()
        assert topo_a.topology_hash() == topo_b.topology_hash()
        a = derive_attachment(design=cr_a, inventory=inv_a, topology=topo_a)
        b = derive_attachment(design=cr_b, inventory=inv_b, topology=topo_b)
        assert a.attachment_hash() == b.attachment_hash()

    @pytest.mark.parametrize("field,value", [
        ("data_width", 512), ("addr_width", 32), ("protocol", "CHI"),
        ("clock_domain", "clk1"), ("power_domain", "pd1"),
    ])
    def test_each_interface_field_changes_attachment_hash(self, field, value):
        base = Agent(kind=AgentKind.COMPUTE_TILE, count=4)
        changed = Agent(kind=AgentKind.COMPUTE_TILE, count=4, **{field: value})
        cr_a, inv_a, topo_a = _make([base])
        cr_b, inv_b, topo_b = _make([changed])
        a = derive_attachment(design=cr_a, inventory=inv_a, topology=topo_a)
        b = derive_attachment(design=cr_b, inventory=inv_b, topology=topo_b)
        assert a.attachment_hash() != b.attachment_hash()

    def test_interface_descriptor_is_carried_not_hashed_parent(self):
        _cr_a, _inv, _t, att = _derive([
            Agent(kind=AgentKind.COMPUTE_TILE, count=2, data_width=512,
                  addr_width=48, protocol="CHI", clock_domain="clkA",
                  power_domain="pd0"),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=2),
        ])
        by_kind: dict[str, list] = {}
        for e in att.endpoints:
            by_kind.setdefault(e.agent.kind.value, []).append(e.interface)
        assert by_kind["compute_tile"][0] == AgentInterfaceDescriptor(
            data_width_bits=512, address_width_bits=48, protocol="CHI",
            clock_domain="clkA", power_domain="pd0")
        assert by_kind["hbm_controller"][0] == _IFACE


# ── B3.1d completeness + malformed-input proof ───────────────────────────

class TestCompleteness:
    def test_missing_idle_agent_refused(self):
        cr, inv, topo = _make(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4),
             Agent(kind=AgentKind.HBM_CONTROLLER, count=2)])
        object.__setattr__(inv, "agents", inv.agents[:-2])  # drop HBM
        with pytest.raises(AttachmentError, match="inventory does not match"):
            derive_attachment(design=cr, inventory=inv, topology=topo)

    def test_extra_fabricated_agent_refused(self):
        cr, inv, topo = _make([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        object.__setattr__(
            inv, "agents",
            inv.agents + (AgentInstance(99, 0, AgentKind.COMPUTE_TILE),))
        with pytest.raises(AttachmentError, match="inventory does not match"):
            derive_attachment(design=cr, inventory=inv, topology=topo)

    def test_malformed_inventory_is_attachment_error_not_index_error(self):
        cr, inv, topo = _make([Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        object.__setattr__(
            inv, "agents", (AgentInstance(99, 0, AgentKind.COMPUTE_TILE),))
        with pytest.raises(AttachmentError):
            derive_attachment(design=cr, inventory=inv, topology=topo)

    def test_attachment_missing_agent_refused(self):
        cr, inv, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4),
             Agent(kind=AgentKind.HBM_CONTROLLER, count=2)])
        truncated = AgentAttachmentArtifact(
            topology_hash=att.topology_hash, endpoints=att.endpoints[:-2])
        with pytest.raises(AttachmentError, match="attachment does not match"):
            truncated.validate_against(cr, inv, topo)

    def test_extra_fabricated_endpoint_refused(self):
        cr, inv, topo = _make([Agent(kind=AgentKind.COMPUTE_TILE, count=2)])
        att = derive_attachment(design=cr, inventory=inv, topology=topo)
        extra = Endpoint(
            2, AgentInstance(0, 2, AgentKind.COMPUTE_TILE), 2, 0, _IFACE)
        inflated = AgentAttachmentArtifact(
            topology_hash=att.topology_hash,
            endpoints=att.endpoints + (extra,))
        with pytest.raises(AttachmentError, match="attachment does not match"):
            inflated.validate_against(cr, inv, topo)

    def test_wrong_interface_refused(self):
        cr, inv, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4, protocol="AXI")])
        bad = AgentInterfaceDescriptor(256, 64, "CHI", None, None)
        twin = AgentAttachmentArtifact(
            topology_hash=att.topology_hash,
            endpoints=tuple(
                Endpoint(e.endpoint_id, e.agent, e.router_id, e.port_id, bad)
                for e in att.endpoints))
        with pytest.raises(AttachmentError, match="interface descriptor"):
            twin.validate_against(cr, inv, topo)

    def test_seat_out_of_range_refused(self):
        cr, inv, topo, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        twin = AgentAttachmentArtifact(
            topology_hash=att.topology_hash,
            endpoints=tuple(
                Endpoint(i, AgentInstance(0, i, AgentKind.COMPUTE_TILE),
                         99 if i == 0 else i, 0, _IFACE)
                for i in range(4)))
        with pytest.raises(AttachmentError, match="not in the topology"):
            twin.validate_against(cr, inv, topo)


class TestSchemaRefusal:
    @pytest.mark.parametrize("version", [1, 2])
    def test_old_schema_refused(self, version):
        _cr_a, _inv, _t, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        d = att.to_dict()
        d["schema_version"] = version
        with pytest.raises(AttachmentError,
                           match=f"schema v{version}|silent migration"):
            AgentAttachmentArtifact.from_dict(d)

    def test_missing_interface_refused(self):
        _cr_a, _inv, _t, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        d = att.to_dict()
        del d["endpoints"][0]["interface"]
        with pytest.raises(AttachmentError, match="interface"):
            AgentAttachmentArtifact.from_dict(d)

    def test_interface_tamper_detected(self):
        _cr_a, _inv, _t, att = _derive(
            [Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
        d = att.to_dict()
        d["endpoints"][0]["interface"]["protocol"] = "CHI"
        with pytest.raises(AttachmentError, match="does not match content"):
            AgentAttachmentArtifact.from_dict(d)
