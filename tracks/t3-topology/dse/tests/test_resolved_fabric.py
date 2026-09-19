"""Wave B3.5b tests — ResolvedFabric: design + mapping bound to hardware.

Uses the real B3.5a chain builder, so the seam is exercised end to end.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_fabric_artifact import build_chain, compose  # noqa: E402

from veritx_dse.model.compile_model import AgentKind, ModelFamily  # noqa: E402
from veritx_dse.model.mapping import (  # noqa: E402
    MappingArtifact, RankPlacement,
)
from veritx_dse.model.placement import AgentInstance, build_inventory  # noqa: E402
from veritx_dse.model.resolved_fabric import (  # noqa: E402
    RESOLVED_FABRIC_SCHEMA_VERSION, ResolvedFabric, ResolvedFabricError,
    make_resolved_fabric,
)
from veritx_dse.model.fabric_artifact import FabricArtifact, FabricArtifactError  # noqa: E402


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def fabric(chain):
    return compose(chain)


def bind(chain, *, fabric=None, **overrides):
    kw = dict(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad,
        fabric=fabric if fabric is not None else compose(chain))
    kw.update(overrides)
    return make_resolved_fabric(**kw)


# ── golden binding ───────────────────────────────────────────────────────

class TestGoldenBinding:
    def test_binds_design_mapping_and_fabric(self, chain, fabric):
        rf = bind(chain, fabric=fabric)
        assert rf.design_hash == chain.cr.design_hash()
        assert rf.mapping_hash == chain.mapping.mapping_hash()
        assert rf.fabric_hash == fabric.fabric_hash()
        assert rf.schema_version == RESOLVED_FABRIC_SCHEMA_VERSION
        assert len(rf.resolved_fabric_hash()) == 64

    def test_idle_compute_agents_remain_legal(self, chain, fabric):
        rf = bind(chain, fabric=fabric)
        assert chain.mapping.rank_count == 1
        assert chain.att.endpoint_count == 4     # 3 idle agents
        assert rf.fabric_hash == fabric.fabric_hash()

    def test_roundtrip_preserves_hash(self, chain, fabric):
        rf = bind(chain, fabric=fabric)
        loaded = ResolvedFabric.from_dict(rf.to_dict())
        assert loaded.resolved_fabric_hash() == rf.resolved_fabric_hash()

    def test_persisted_shape(self, chain, fabric):
        rf = bind(chain, fabric=fabric)
        d = rf.to_dict()
        assert set(d) == {"type", "schema_version", "design_hash",
                          "mapping_hash", "fabric_hash",
                          "resolved_fabric_hash"}
        assert d["resolved_fabric_hash"] == rf.resolved_fabric_hash()


# ── the two golden invariants ────────────────────────────────────────────

class TestSameHardwareDifferentMapping:
    def test_fabric_same_resolved_different(self, chain, fabric):
        other_mapping = MappingArtifact(placements=(
            RankPlacement(
                rank=0,
                agent=AgentInstance(0, 2, AgentKind.COMPUTE_TILE)),))
        rf_a = bind(chain, fabric=fabric)
        rf_b = bind(chain, fabric=fabric, mapping=other_mapping)
        assert other_mapping.mapping_hash() != chain.mapping.mapping_hash()
        assert rf_a.fabric_hash == rf_b.fabric_hash
        assert rf_a.resolved_fabric_hash() != rf_b.resolved_fabric_hash()


class TestUnrelatedDesignChange:
    def test_design_changed_fabric_same_resolved_different(self, chain,
                                                           fabric):
        other = build_chain(model_family=ModelFamily.DENSE_TRANSFORMER)
        assert other.cr.design_hash() != chain.cr.design_hash()
        assert compose(other).fabric_hash() == fabric.fabric_hash()
        rf_a = bind(chain, fabric=fabric)
        rf_b = bind(other, fabric=compose(other))
        assert rf_b.fabric_hash == rf_a.fabric_hash
        assert rf_b.resolved_fabric_hash() != rf_a.resolved_fabric_hash()


class TestInterfaceChange:
    def test_interface_change_moves_fabric_and_resolved(self, chain, fabric):
        other = build_chain(protocol="CHI", data_width=512,
                            clock_domain="clkA")
        rf_a = bind(chain, fabric=fabric)
        rf_b = bind(other, fabric=compose(other))
        assert rf_b.fabric_hash != rf_a.fabric_hash
        assert rf_b.resolved_fabric_hash() != rf_a.resolved_fabric_hash()


# ── seam refusals ────────────────────────────────────────────────────────

class TestSeamRefusals:
    def test_wrong_design_hash_refused(self, chain, fabric):
        rf = ResolvedFabric(
            design_hash="0" * 64,
            mapping_hash=chain.mapping.mapping_hash(),
            fabric_hash=fabric.fabric_hash())
        with pytest.raises(ResolvedFabricError, match="design_hash"):
            rf.validate_against(
                design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb, address_decode=chain.ad,
                fabric=fabric)

    def test_wrong_mapping_hash_refused(self, chain, fabric):
        rf = ResolvedFabric(
            design_hash=chain.cr.design_hash(),
            mapping_hash="0" * 64, fabric_hash=fabric.fabric_hash())
        with pytest.raises(ResolvedFabricError, match="mapping_hash"):
            rf.validate_against(
                design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb, address_decode=chain.ad,
                fabric=fabric)

    def test_wrong_fabric_hash_refused(self, chain, fabric):
        rf = ResolvedFabric(
            design_hash=chain.cr.design_hash(),
            mapping_hash=chain.mapping.mapping_hash(),
            fabric_hash="0" * 64)
        with pytest.raises(ResolvedFabricError, match="fabric_hash"):
            rf.validate_against(
                design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb, address_decode=chain.ad,
                fabric=fabric)

    def test_rank_count_mismatch_refused(self, chain, fabric):
        two_ranks = MappingArtifact(placements=(
            RankPlacement(0, AgentInstance(0, 0, AgentKind.COMPUTE_TILE)),
            RankPlacement(1, AgentInstance(0, 1, AgentKind.COMPUTE_TILE))))
        with pytest.raises(ResolvedFabricError, match="2 ranks"):
            bind(chain, fabric=fabric, mapping=two_ranks)

    def test_unattached_mapped_agent_refused(self, chain, fabric):
        bad = MappingArtifact(placements=(
            RankPlacement(0, AgentInstance(0, 9, AgentKind.COMPUTE_TILE)),))
        with pytest.raises(ResolvedFabricError, match="unattached"):
            bind(chain, fabric=fabric, mapping=bad)

    def test_rank_space_mismatch_refused(self, chain, fabric):
        inventory = build_inventory(chain.cr)
        object.__setattr__(
            inventory, "ranks",
            tuple(replace(r, rank=r.rank + 5) for r in inventory.ranks))
        with pytest.raises(ResolvedFabricError, match="do not match"):
            make_resolved_fabric(
                design=chain.cr, inventory=inventory, mapping=chain.mapping,
                topology=chain.topo, attachment=chain.att,
                router_route=chain.rr, resolved_route=chain.rra,
                vc_assignment=chain.vc, packet_format=chain.pf,
                router_behavior=chain.rb, address_decode=chain.ad,
                fabric=fabric)


class TestParallelismSeam:
    def test_different_shape_same_world_size_refused(self):
        base = build_chain(tp=4)              # TP=4 PP=1
        foreign = build_chain(tp=2, pp=2)     # TP=2 PP=2
        assert base.inv.parallelism.world_size == 4
        assert foreign.inv.parallelism.world_size == 4
        assert base.inv.parallelism != foreign.inv.parallelism
        with pytest.raises(ResolvedFabricError, match="parallelism"):
            make_resolved_fabric(
                design=base.cr, inventory=foreign.inv,
                mapping=foreign.mapping, topology=base.topo,
                attachment=base.att, router_route=base.rr,
                resolved_route=base.rra, vc_assignment=base.vc,
                packet_format=base.pf, router_behavior=base.rb,
                address_decode=base.ad, fabric=compose(base))

    def test_tampered_rank_coordinates_refused(self):
        chain = build_chain(tp=2, pp=2)       # 4 ranks, real coordinates
        inventory = build_inventory(chain.cr)
        ranks = list(inventory.ranks)
        ranks[1] = replace(ranks[1], tp=1 - ranks[1].tp)
        object.__setattr__(inventory, "ranks", tuple(ranks))
        with pytest.raises(ResolvedFabricError,
                           match="canonical rank namespace"):
            make_resolved_fabric(
                design=chain.cr, inventory=inventory,
                mapping=chain.mapping, topology=chain.topo,
                attachment=chain.att, router_route=chain.rr,
                resolved_route=chain.rra, vc_assignment=chain.vc,
                packet_format=chain.pf, router_behavior=chain.rb,
                address_decode=chain.ad, fabric=compose(chain))


class TestAddressMapSeam:
    def test_address_map_change_moves_fabric_and_resolved(self):
        from test_fabric_artifact import _with_hbm
        a = _with_hbm(base=0x1000)
        b = _with_hbm(base=0x8000)
        rf_a = bind(a, fabric=compose(a))
        rf_b = bind(b, fabric=compose(b))
        assert rf_a.fabric_hash != rf_b.fabric_hash
        assert rf_a.resolved_fabric_hash() != rf_b.resolved_fabric_hash()

    def test_foreign_address_decode_refused(self):
        from test_fabric_artifact import _with_hbm
        a = _with_hbm(base=0x1000)
        b = _with_hbm(base=0x8000)
        with pytest.raises(FabricArtifactError,
                           match="address_decode_hash does not match"):
            make_resolved_fabric(
                design=a.cr, inventory=a.inv, mapping=a.mapping,
                topology=a.topo, attachment=a.att, router_route=a.rr,
                resolved_route=a.rra, vc_assignment=a.vc,
                packet_format=a.pf, router_behavior=a.rb,
                address_decode=b.ad, fabric=compose(a))


# ── persistence strictness ───────────────────────────────────────────────

class TestPersistence:
    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(design_hash=""), "design_hash"),
        (lambda d: d.update(resolved_fabric_hash="0" * 64),
         "does not match content"),
    ])
    def test_persisted_mutations_refused(self, chain, fabric, mutate, match):
        d = bind(chain, fabric=fabric).to_dict()
        mutate(d)
        with pytest.raises(ResolvedFabricError, match=match):
            ResolvedFabric.from_dict(d)

    def test_missing_hash_refused(self, chain, fabric):
        d = bind(chain, fabric=fabric).to_dict()
        del d["resolved_fabric_hash"]
        with pytest.raises(ResolvedFabricError, match="resolved_fabric_hash"):
            ResolvedFabric.from_dict(d)


# ── deadlock certificate structural seam (no rewiring) ───────────────────

class TestCertificateSeam:
    def test_certificate_hashes_correspond_to_fabric_components(self, chain,
                                                                fabric):
        from veritx_dse.verification.channel_vc_cdg import (
            certify_channel_vc_deadlock,
        )
        cert = certify_channel_vc_deadlock(
            topology=chain.topo, resolved_route=chain.rra,
            router_route=chain.rr, vc_assignment=chain.vc)
        assert cert.topology_hash == fabric.topology_hash
        assert cert.attachment_hash == fabric.attachment_hash
        assert cert.router_route_hash == chain.rr.artifact_hash
        assert cert.resolved_route_hash == fabric.resolved_route_hash
        assert cert.vc_assignment_hash == fabric.vc_assignment_hash
        # router_behavior binding in live certification is deferred (B3.7)
        assert cert.router_behavior_hash == ""
