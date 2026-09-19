"""Wave B3.5a/B3.5d tests — FabricArtifact: root hardware identity.

The primary golden test builds a REAL chain: CompileRequest → NodeInventory
→ MappingArtifact → TopologyArtifact → attachment v3 → RouteArtifact v2 →
ResolvedRouteArtifact v2 → VCAssignmentArtifact → PacketFormatArtifact →
RouterBehaviorArtifact v2 → AddressDecodeArtifact → FabricArtifact v2.
No synthetic parent hashes in the composition path.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, RouteArtifact
from veritx_dse.model.address_decode import derive_address_decode
from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, Endpoint, derive_attachment,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CompileRequest, Dependency,
    DependencyGraph, DepKind, ModelFamily, NocConfig, TopologyFamily, Workload,
    derive_vc_assignment_artifact,
)
from veritx_dse.model.fabric_artifact import (
    FABRIC_SCHEMA_VERSION, FabricArtifact, FabricArtifactError,
    PlaneComposition, make_fabric_artifact,
)
from veritx_dse.model.mapping import derive_mapping
from veritx_dse.model.packet_format import derive_packet_format
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.router_behavior import derive_router_behavior
from veritx_dse.model.topology_artifact import materialize_topology


def build_chain(*, model_family=ModelFamily.MOE, protocol="AXI",
                data_width=256, clock_domain=None, link_width=None,
                max_packet_flits=8, n_agents=4,
                family=TopologyFamily.MESH,
                tp=1, pp=1, ep=1, dp=1,
                hbm_count=0, address_map=None, derive_decode=True):
    agents = [Agent(kind=AgentKind.COMPUTE_TILE, count=n_agents,
                    protocol=protocol, data_width=data_width,
                    clock_domain=clock_domain)]
    if hbm_count:
        agents.append(Agent(kind=AgentKind.HBM_CONTROLLER, count=hbm_count))
    cr = CompileRequest(
        workload=Workload(model_family=model_family, tp=tp, pp=pp, ep=ep,
                          dp=dp),
        requirements=[], agents=agents,
        dependencies=DependencyGraph([
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING)]),
        noc_config=NocConfig(topology_family=family, link_width=link_width),
        address_map=address_map if address_map is not None else AddressMap())
    inv = build_inventory(cr)
    mapping = derive_mapping(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(
        topo, name="chain", routing_classes=(ANYNET_MIN_HOPS,))
    rra = derive_resolved_route(topo, att, rr)
    vc = derive_vc_assignment_artifact(cr, rra)
    return SimpleNamespace(
        cr=cr, inv=inv, mapping=mapping, topo=topo, att=att, rr=rr,
        rra=rra, vc=vc,
        pf=derive_packet_format(topology=topo, attachment=att,
                                vc_assignment=vc,
                                max_packet_flits=max_packet_flits),
        rb=derive_router_behavior(vc_assignment=vc),
        ad=(derive_address_decode(design=cr, attachment=att)
            if derive_decode else None),
    )


def _fab(chain, **overrides):
    kw = dict(
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, address_map=chain.cr.address_map)
    kw.update(overrides)
    return make_fabric_artifact(**kw)


def compose(chain, *, rr=None, rra=None, vc=None, pf=None, rb=None, ad=None,
            plane=PlaneComposition.SINGLE_PLANE):
    return _fab(chain, router_route=rr or chain.rr,
                resolved_route=rra or chain.rra, vc_assignment=vc or chain.vc,
                packet_format=pf or chain.pf,
                router_behavior=rb or chain.rb,
                address_decode=ad or chain.ad, plane_composition=plane)


def _with_hbm(*, base=0x1000, size=0x1000, hbm=1):
    return build_chain(
        hbm_count=hbm,
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=base, size=size,
                         target_agent_idx=1),)))


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def fabric(chain):
    return compose(chain)


# ── golden composition ───────────────────────────────────────────────────

class TestGoldenComposition:
    def test_real_chain_composes(self, chain, fabric):
        assert fabric.topology_hash == chain.topo.topology_hash()
        assert fabric.attachment_hash == chain.att.attachment_hash()
        assert fabric.resolved_route_hash == chain.rra.resolved_route_hash()
        assert fabric.vc_assignment_hash == chain.vc.vc_assignment_hash()
        assert fabric.packet_format_hash == chain.pf.packet_format_hash()
        assert fabric.router_behavior_hash \
            == chain.rb.router_behavior_hash()
        assert fabric.address_decode_hash == chain.ad.address_decode_hash()
        assert fabric.plane_composition is PlaneComposition.SINGLE_PLANE
        assert len(fabric.fabric_hash()) == 64
        assert fabric.schema_version == FABRIC_SCHEMA_VERSION == 2

    def test_hash_domain_is_srota_fabric_v2(self, fabric):
        import hashlib
        from veritx_dse.core.spec import canonical_json
        body = ("srota/Fabric/v2\0"
                + canonical_json(fabric.identity_dict()))
        assert fabric.fabric_hash() == hashlib.sha256(body.encode()).hexdigest()

    def test_roundtrip_preserves_hash(self, fabric):
        loaded = FabricArtifact.from_dict(fabric.to_dict())
        assert loaded.fabric_hash() == fabric.fabric_hash()

    def test_persisted_shape(self, fabric):
        d = fabric.to_dict()
        assert set(d) == {
            "type", "schema_version", "topology_hash", "attachment_hash",
            "resolved_route_hash", "vc_assignment_hash", "packet_format_hash",
            "router_behavior_hash", "address_decode_hash",
            "plane_composition", "fabric_hash"}
        assert d["fabric_hash"] == fabric.fabric_hash()

    def test_no_design_mapping_or_evidence_fields(self, fabric):
        blob = repr(fabric.identity_dict()).lower()
        for token in ("design", "mapping", "workload", "candidate",
                      "backend", "booksim", "seed", "git", "timestamp",
                      "verdict", "certificate", "area", "power"):
            assert token not in blob, f"{token!r} leaked into fabric identity"


# ── identity mutations ───────────────────────────────────────────────────

class TestIdentityMutations:
    @pytest.mark.parametrize("field", [
        "topology_hash", "attachment_hash", "resolved_route_hash",
        "vc_assignment_hash", "packet_format_hash", "router_behavior_hash",
        "address_decode_hash",
    ])
    def test_child_hash_mutation_changes_fabric_hash(self, fabric, field):
        twin = replace(fabric, artifact_hash="", **{field: "f" * 64})
        assert twin.fabric_hash() != fabric.fabric_hash()

    def test_interface_change_changes_fabric_hash(self, chain):
        other = build_chain(protocol="CHI", data_width=512,
                            clock_domain="clkA")
        assert other.att.attachment_hash != chain.att.attachment_hash
        assert compose(other).fabric_hash() != compose(chain).fabric_hash()

    def test_topology_change_changes_fabric_hash(self, chain):
        other = build_chain(link_width=128)
        assert other.topo.topology_hash() != chain.topo.topology_hash()
        assert compose(other).fabric_hash() != compose(chain).fabric_hash()

    def test_route_change_changes_fabric_hash(self, chain):
        entries = dict(chain.rr.entries)
        by_hop: dict[tuple[int, int], list[int]] = {}
        for c in chain.topo.channels:
            by_hop.setdefault((c.src_router, c.dst_router), []).append(
                c.channel_id)
        old = entries[(ANYNET_MIN_HOPS, 0, 3)]
        alt = next(cid for (_s, _d), ids in by_hop.items() if _s == 0
                   for cid in ids if cid != old)
        entries[(ANYNET_MIN_HOPS, 0, 3)] = alt
        rr2 = RouteArtifact(
            schema_version=2, name=chain.rr.name,
            topology_hash=chain.rr.topology_hash,
            routing_classes=chain.rr.routing_classes, entries=entries)
        rr2.validate_against(chain.topo)
        rra2 = derive_resolved_route(chain.topo, chain.att, rr2)
        vc2 = derive_vc_assignment_artifact(chain.cr, rra2)
        pf2 = derive_packet_format(topology=chain.topo, attachment=chain.att,
                                   vc_assignment=vc2)
        rb2 = derive_router_behavior(vc_assignment=vc2)
        assert rr2.artifact_hash != chain.rr.artifact_hash
        assert compose(chain, rr=rr2, rra=rra2, vc=vc2, pf=pf2,
                       rb=rb2).fabric_hash() != compose(chain).fabric_hash()

    def test_packet_change_changes_fabric_hash(self, chain):
        other = build_chain(max_packet_flits=16)
        assert other.pf.packet_format_hash() != chain.pf.packet_format_hash()
        assert compose(other).fabric_hash() != compose(chain).fabric_hash()

    def test_router_behavior_change_changes_fabric_hash(self, chain):
        rb2 = replace(chain.rb, artifact_hash="",
                      input_buffer_depth_flits_per_vc=16)
        assert rb2.router_behavior_hash() != chain.rb.router_behavior_hash()
        assert compose(chain, rb=rb2).fabric_hash() \
            != compose(chain).fabric_hash()


# ── address decode identity (B3.5d) ──────────────────────────────────────

class TestAddressDecodeIdentity:
    def test_empty_address_map_is_legal(self, chain):
        assert chain.ad.entries == ()
        assert chain.ad.address_decode_hash()

    def test_singleton_entry_resolves_endpoint(self):
        c = _with_hbm()
        hbm_endpoint = next(e for e in c.att.endpoints
                            if e.agent.kind is AgentKind.HBM_CONTROLLER)
        assert len(c.ad.entries) == 1
        entry = c.ad.entries[0]
        assert entry.name == "HBM0"
        assert entry.base == 0x1000 and entry.size == 0x1000
        assert entry.target_agent_group == 1
        assert entry.target_endpoint_id == hbm_endpoint.endpoint_id

    def test_address_map_change_changes_only_fabric_via_decode(self):
        a = _with_hbm(base=0x1000)
        b = _with_hbm(base=0x8000)
        # every other child hash is identical...
        assert a.topo.topology_hash() == b.topo.topology_hash()
        assert a.att.attachment_hash() == b.att.attachment_hash()
        assert a.rra.resolved_route_hash() == b.rra.resolved_route_hash()
        assert a.vc.vc_assignment_hash() == b.vc.vc_assignment_hash()
        assert a.pf.packet_format_hash() == b.pf.packet_format_hash()
        assert a.rb.router_behavior_hash() == b.rb.router_behavior_hash()
        # ...so this collision is exactly what B3.5d closes
        assert a.ad.address_decode_hash() != b.ad.address_decode_hash()
        assert compose(a).fabric_hash() != compose(b).fabric_hash()

    def test_multi_instance_target_group_unsupported(self):
        from veritx_dse.model.address_decode import AddressDecodeError
        with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
            _with_hbm(hbm=2)


# ── Frankenstein refusal ─────────────────────────────────────────────────

class TestFrankensteinRefusal:
    def test_foreign_attachment_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="resolved_route does not bind"):
            _fab(chain, attachment=other.att, address_decode=other.ad)

    def test_foreign_vc_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="vc_assignment does not bind resolved_route"):
            _fab(chain, vc_assignment=other.vc)

    def test_foreign_packet_format_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="packet_format does not bind"):
            _fab(chain, packet_format=other.pf)

    def test_foreign_router_behavior_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="router_behavior does not bind"):
            _fab(chain, router_behavior=other.rb)

    def test_foreign_address_decode_refused(self):
        a = _with_hbm(base=0x1000)
        b = _with_hbm(base=0x8000)
        with pytest.raises(FabricArtifactError,
                           match="address_decode is not legal"):
            _fab(a, address_decode=b.ad)

    def test_attachment_from_other_topology_refused(self, chain):
        other = build_chain(link_width=128)
        with pytest.raises(FabricArtifactError,
                           match="attachment is not legal for topology"):
            _fab(chain, attachment=other.att)


# ── sealing validation (B3.5c) ───────────────────────────────────────────

class TestSealingValidation:
    def _looping_route(self, chain):
        entries = dict(chain.rr.entries)
        by_hop: dict[tuple[int, int], list[int]] = {}
        for c in chain.topo.channels:
            by_hop.setdefault((c.src_router, c.dst_router), []).append(
                c.channel_id)
        entries[(ANYNET_MIN_HOPS, 0, 3)] = min(by_hop[(0, 1)])
        entries[(ANYNET_MIN_HOPS, 1, 3)] = min(by_hop[(1, 0)])
        return RouteArtifact(
            schema_version=2, name="looping",
            topology_hash=chain.topo.topology_hash(),
            routing_classes=chain.rr.routing_classes, entries=entries)

    def test_illegal_router_route_refused(self, chain):
        rr_bad = self._looping_route(chain)
        rra_bad = derive_resolved_route(chain.topo, chain.att, rr_bad)
        vc_bad = derive_vc_assignment_artifact(chain.cr, rra_bad)
        pf_bad = derive_packet_format(
            topology=chain.topo, attachment=chain.att,
            vc_assignment=vc_bad)
        rb_bad = derive_router_behavior(vc_assignment=vc_bad)
        with pytest.raises(FabricArtifactError,
                           match="router_route is not legal for topology"):
            _fab(chain, router_route=rr_bad, resolved_route=rra_bad,
                 vc_assignment=vc_bad, packet_format=pf_bad,
                 router_behavior=rb_bad)

    def test_invalid_attachment_seat_refused_without_design(self, chain):
        bad_att = AgentAttachmentArtifact(
            topology_hash=chain.att.topology_hash,
            endpoints=tuple(
                Endpoint(e.endpoint_id, e.agent, e.router_id,
                         99 if e.endpoint_id == 0 else e.port_id, e.interface)
                for e in chain.att.endpoints))
        # no DesignRevision / NodeInventory is supplied anywhere here
        with pytest.raises(FabricArtifactError,
                           match="attachment is not legal for topology"):
            _fab(chain, attachment=bad_att)


# ── self-integrity vs parent legality ────────────────────────────────────

class TestSelfIntegrityVsLegality:
    def _fake(self):
        return FabricArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            resolved_route_hash="c" * 64, vc_assignment_hash="d" * 64,
            packet_format_hash="e" * 64, router_behavior_hash="f" * 64,
            address_decode_hash="g" * 64,
            plane_composition=PlaneComposition.SINGLE_PLANE)

    def test_fake_passes_self_integrity(self):
        fake = self._fake()
        assert FabricArtifact.from_dict(fake.to_dict()).fabric_hash() \
            == fake.fabric_hash()

    def test_fake_fails_parent_validation(self, chain):
        fake = self._fake()
        with pytest.raises(FabricArtifactError, match="does not match"):
            fake.validate_against(
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb, address_decode=chain.ad,
                address_map=chain.cr.address_map)


# ── persistence strictness ───────────────────────────────────────────────

class TestPersistence:
    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=3), "schema_version"),
        (lambda d: d.update(schema_version=1), "schema v1|silent migration"),
        (lambda d: d.update(plane_composition="dual_plane"),
         "unknown plane composition"),
        (lambda d: d.update(fabric_hash="0" * 64), "does not match content"),
        (lambda d: d.update(topology_hash=""), "topology_hash"),
        (lambda d: d.update(address_decode_hash=""), "address_decode_hash"),
    ])
    def test_persisted_mutations_refused(self, fabric, mutate, match):
        d = fabric.to_dict()
        mutate(d)
        with pytest.raises(FabricArtifactError, match=match):
            FabricArtifact.from_dict(d)

    def test_missing_fabric_hash_refused(self, fabric):
        d = fabric.to_dict()
        del d["fabric_hash"]
        with pytest.raises(FabricArtifactError, match="fabric_hash"):
            FabricArtifact.from_dict(d)

    def test_plane_enum_construction_refused(self):
        with pytest.raises(FabricArtifactError, match="plane_composition"):
            FabricArtifact(
                topology_hash="a" * 64, attachment_hash="b" * 64,
                resolved_route_hash="c" * 64, vc_assignment_hash="d" * 64,
                packet_format_hash="e" * 64, router_behavior_hash="f" * 64,
                address_decode_hash="g" * 64,
                plane_composition="single_plane")
