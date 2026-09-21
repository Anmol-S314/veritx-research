"""Wave B3.7a tests — ResolvedFabricBundle is a real validation carrier.

Uses the real B3.5 chain builder: the bundle is constructed from actual
semantic objects and revalidates the full hardware DAG + design/mapping
seam.
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

from veritx_dse.model.resolved_bundle import (  # noqa: E402
    ResolvedFabricBundleError, make_resolved_fabric_bundle,
)
from veritx_dse.model.resolved_fabric import make_resolved_fabric  # noqa: E402


@pytest.fixture(scope="module")
def chain():
    return build_chain()


def make_bundle(chain, *, fabric=None, resolved_fabric=None):
    fabric = fabric if fabric is not None else compose(chain)
    rf = resolved_fabric if resolved_fabric is not None else \
        make_resolved_fabric(
            design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
            topology=chain.topo, attachment=chain.att,
            router_route=chain.rr, resolved_route=chain.rra,
            vc_assignment=chain.vc, packet_format=chain.pf,
            router_behavior=chain.rb, address_decode=chain.ad, fabric=fabric)
    return make_resolved_fabric_bundle(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, fabric=fabric, resolved_fabric=rf)


class TestBundledValidation:
    def test_real_chain_bundle_validates(self, chain):
        bundle = make_bundle(chain)
        hashes = bundle.root_hashes()
        assert hashes["fabric_hash"] == compose(chain).fabric_hash()
        assert hashes["resolved_fabric_hash"] \
            == bundle.resolved_fabric.resolved_fabric_hash()
        assert set(hashes) >= {
            "design_hash", "mapping_hash", "topology_hash",
            "attachment_hash", "router_route_hash", "resolved_route_hash",
            "vc_assignment_hash", "packet_format_hash",
            "router_behavior_hash", "address_decode_hash"}

    def test_revalidate_after_child_swap_refused(self, chain):
        bundle = make_bundle(chain)
        other = build_chain(link_width=128)
        assert other.topo.topology_hash() != chain.topo.topology_hash()
        tampered = replace(bundle, topology=other.topo)
        with pytest.raises(ValueError):
            tampered.revalidate()
        # The original bundle is unaffected.
        bundle.revalidate()

    def test_resolved_fabric_from_other_fabric_refused(self, chain):
        other = build_chain(hbm_count=1)
        other_fab = compose(other)
        other_rf = make_resolved_fabric(
            design=other.cr, inventory=other.inv, mapping=other.mapping,
            topology=other.topo, attachment=other.att, router_route=other.rr,
            resolved_route=other.rra, vc_assignment=other.vc,
            packet_format=other.pf, router_behavior=other.rb,
            address_decode=other.ad, fabric=other_fab)
        with pytest.raises(ValueError):
            make_bundle(chain, fabric=compose(chain),
                        resolved_fabric=other_rf)

    def test_hash_only_bundle_is_impossible(self, chain):
        # make_resolved_fabric_bundle demands the objects; a caller cannot
        # pass hashes. This is a signature-level guarantee, pinned here so
        # a future refactor cannot weaken it silently.
        import inspect
        sig = inspect.signature(make_resolved_fabric_bundle)
        assert "fabric" in sig.parameters
        assert "resolved_fabric" in sig.parameters
        assert "design" in sig.parameters
        assert "inventory" in sig.parameters
        assert "mapping" in sig.parameters
