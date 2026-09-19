"""Wave B3.5a tests — FabricArtifact: root hardware identity composition.

The primary golden test builds a REAL chain: CompileRequest → NodeInventory
→ MappingArtifact → TopologyArtifact → attachment v3 → RouteArtifact v2 →
ResolvedRouteArtifact v2 → VCAssignmentArtifact → PacketFormatArtifact →
RouterBehaviorArtifact v2 → FabricArtifact. No synthetic parent hashes in
the composition path.
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
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, Dependency, DependencyGraph, DepKind,
    ModelFamily, NocConfig, TopologyFamily, Workload,
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
                family=TopologyFamily.MESH):
    cr = CompileRequest(
        workload=Workload(model_family=model_family, tp=1, pp=1, ep=1, dp=1),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=n_agents,
                      protocol=protocol, data_width=data_width,
                      clock_domain=clock_domain)],
        dependencies=DependencyGraph([
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING)]),
        noc_config=NocConfig(topology_family=family, link_width=link_width))
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
    )


def compose(chain, *, rr=None, rra=None, vc=None, pf=None, rb=None,
            plane=PlaneComposition.SINGLE_PLANE):
    rr = rr or chain.rr
    rra = rra or chain.rra
    vc = vc or chain.vc
    pf = pf or chain.pf
    rb = rb or chain.rb
    return make_fabric_artifact(
        topology=chain.topo, attachment=chain.att, router_route=rr,
        resolved_route=rra, vc_assignment=vc, packet_format=pf,
        router_behavior=rb, plane_composition=plane)


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
        assert fabric.plane_composition is PlaneComposition.SINGLE_PLANE
        assert len(fabric.fabric_hash()) == 64
        assert fabric.schema_version == FABRIC_SCHEMA_VERSION

    def test_hash_domain_is_srota_fabric_v1(self, fabric):
        import hashlib
        from veritx_dse.core.spec import canonical_json
        body = ("srota/Fabric/v1\0"
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
            "router_behavior_hash", "plane_composition", "fabric_hash"}
        assert d["fabric_hash"] == fabric.fabric_hash()

    def test_no_design_mapping_or_evidence_fields(self, chain, fabric):
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


# ── Frankenstein refusal ─────────────────────────────────────────────────

class TestFrankensteinRefusal:
    def test_foreign_attachment_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="resolved_route does not bind"):
            make_fabric_artifact(
                topology=chain.topo, attachment=other.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb)

    def test_foreign_vc_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="vc_assignment|resolved_route"):
            make_fabric_artifact(
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=other.vc, packet_format=chain.pf,
                router_behavior=chain.rb)

    def test_foreign_packet_format_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="packet_format does not bind"):
            make_fabric_artifact(
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=other.pf,
                router_behavior=chain.rb)

    def test_foreign_router_behavior_refused(self, chain):
        other = build_chain(protocol="CHI", data_width=512)
        with pytest.raises(FabricArtifactError,
                           match="router_behavior does not bind"):
            make_fabric_artifact(
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=other.rb)

    def test_attachment_from_other_topology_refused(self, chain):
        other = build_chain(link_width=128)
        with pytest.raises(FabricArtifactError,
                           match="does not bind this topology"):
            make_fabric_artifact(
                topology=chain.topo, attachment=other.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb)


# ── self-integrity vs parent legality ────────────────────────────────────

class TestSelfIntegrityVsLegality:
    def _fake(self):
        return FabricArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            resolved_route_hash="c" * 64, vc_assignment_hash="d" * 64,
            packet_format_hash="e" * 64, router_behavior_hash="f" * 64,
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
                router_behavior=chain.rb)


# ── persistence strictness ───────────────────────────────────────────────

class TestPersistence:
    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(plane_composition="dual_plane"),
         "unknown plane composition"),
        (lambda d: d.update(fabric_hash="0" * 64), "does not match content"),
        (lambda d: d.update(topology_hash=""), "topology_hash"),
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
                plane_composition="single_plane")
