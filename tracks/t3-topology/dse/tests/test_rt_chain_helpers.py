"""Shared RT-chain helpers: build_chain / compose / make_bundle."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, RouteArtifact
from veritx_dse.model.address_decode import derive_address_decode
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CompileRequest,
    Dependency, DependencyGraph, DepKind, ModelFamily, NocConfig,
    TopologyFamily, Workload, derive_vc_assignment_artifact,
)
from veritx_dse.model.fabric_artifact import (
    PlaneComposition, make_deterministic_fabric,
)
from veritx_dse.model.mapping import derive_mapping
from veritx_dse.model.packet_format import derive_packet_format
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_fabric import (
    make_resolved_deterministic_fabric,
)
from veritx_dse.model.resolved_bundle import (
    make_resolved_fabric_bundle,
)
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.router_behavior import derive_router_behavior
from veritx_dse.model.routing_realization import (
    make_deterministic_routing_realization,
)
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_resource import (
    vc_resources_from_assignment,
)


# ── veritx-integrate shared RT-chain helpers (canonical-v2 derivation) ──
# Recovered from the RT-candidate test suite (tests/test_fabric_artifact.py
# build_chain/compose) and re-derived onto the canonical FabricArtifact
# composition so Wave-D/E physical tests can share one chain builder.

def build_chain(*, model_family=ModelFamily.MOE, protocol="AXI",
                data_width=256, clock_domain=None, link_width=None,
                max_packet_flits=8, n_agents=4,
                family=TopologyFamily.MESH,
                tp=1, pp=1, ep=1, dp=1,
                hbm_count=0, address_map=None, derive_decode=True,
                compute_clock=None, compute_power=None,
                compute_addr_width=64, hbm_clock=None, hbm_power=None,
                hbm_addr_width=64, mcast_groups=None,
                mcast_setup_cycles=None):
    agents = [Agent(kind=AgentKind.COMPUTE_TILE, count=n_agents,
                    protocol=protocol, data_width=data_width,
                    addr_width=compute_addr_width,
                    clock_domain=compute_clock, power_domain=compute_power)]
    if hbm_count:
        agents.append(Agent(kind=AgentKind.HBM_CONTROLLER, count=hbm_count,
                            addr_width=hbm_addr_width,
                            clock_domain=hbm_clock, power_domain=hbm_power))
    cr = CompileRequest(
        workload=Workload(model_family=model_family, tp=tp, pp=pp, ep=ep,
                          dp=dp),
        requirements=[], agents=agents,
        dependencies=DependencyGraph([
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING)]),
        noc_config=NocConfig(
            topology_family=family, link_width=link_width,
            mcast_groups=mcast_groups, mcast_setup_cycles=mcast_setup_cycles),
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
        pf=derive_packet_format(topo, att,
                                vc_resources_from_assignment(vc),
                                max_packet_flits=max_packet_flits),
        rb=derive_router_behavior(
            vc_resource=vc_resources_from_assignment(vc)),
        ad=(derive_address_decode(design=cr, attachment=att)
            if derive_decode else None),
    )


def _fab(chain, **overrides):
    kw = dict(
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad)
    kw.update(overrides)
    return make_fabric_artifact(**kw)


def compose(chain, *, rr=None, rra=None, vc=None, pf=None, rb=None, ad=None,
            plane=PlaneComposition.SINGLE_PLANE):
    return _fab(chain, router_route=rr or chain.rr,
                resolved_route=rra or chain.rra, vc_assignment=vc or chain.vc,
                packet_format=pf or chain.pf,
                router_behavior=rb or chain.rb,
                address_decode=ad or chain.ad, plane_composition=plane)


def _with_hbm(*, base=0x1000, size=0x1000, hbm=1, name="HBM0",
              hbm_addr_width=64, hbm_clock=None, hbm_power=None):
    return build_chain(
        hbm_count=hbm, hbm_addr_width=hbm_addr_width,
        hbm_clock=hbm_clock, hbm_power=hbm_power,
        address_map=AddressMap(ranges=(
            AddressRange(name=name, base=base, size=size,
                         target_agent_idx=1),)))


def compose(chain, *, rr=None, rra=None, vc=None, pf=None, rb=None, ad=None,
            plane=PlaneComposition.SINGLE_PLANE):
    """Canonical-v2 compose: derive vc_resource + routing_realization from
    the chain's route chain, then compose via make_deterministic_fabric."""
    if plane is not PlaneComposition.SINGLE_PLANE:
        raise ValueError("canonical compose supports SINGLE_PLANE only")
    vc = vc or chain.vc
    pf = pf or chain.pf
    rb = rb or chain.rb
    ad = ad or chain.ad
    vc_resource = vc_resources_from_assignment(vc)
    realization = make_deterministic_routing_realization(
        topology=chain.topo, attachment=chain.att, route=chain.rr,
        resolved_route=chain.rra, vc_assignment=vc, vc_resource=vc_resource)
    return make_deterministic_fabric(
        topology=chain.topo, attachment=chain.att, vc_resource=vc_resource,
        routing_realization=realization, packet_format=pf,
        router_behavior=rb, address_decode=ad, route=chain.rr,
        resolved_route=chain.rra, vc_assignment=vc)


def make_bundle(chain, *, fabric=None, resolved_fabric=None):
    fabric = fabric if fabric is not None else compose(chain)
    rf = resolved_fabric if resolved_fabric is not None else \
        make_resolved_deterministic_fabric(
            design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
            topology=chain.topo, attachment=chain.att,
            vc_resource=vc_resources_from_assignment(chain.vc),
            routing_realization=make_deterministic_routing_realization(
                topology=chain.topo, attachment=chain.att, route=chain.rr,
                resolved_route=chain.rra, vc_assignment=chain.vc,
                vc_resource=vc_resources_from_assignment(chain.vc)),
            packet_format=chain.pf, router_behavior=chain.rb,
            address_decode=chain.ad, fabric=fabric, route=chain.rr,
            resolved_route=chain.rra, vc_assignment=chain.vc)
    return make_resolved_fabric_bundle(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, fabric=fabric, resolved_fabric=rf)


def make_resolved_fabric(*, design, inventory, mapping, topology, attachment,
                         router_route, resolved_route, vc_assignment,
                         packet_format, router_behavior, address_decode,
                         fabric):
    """Canonical resolved-fabric binding (helper for adversarial tests)."""
    return make_resolved_deterministic_fabric(
        design=design, inventory=inventory, mapping=mapping,
        topology=topology, attachment=attachment,
        vc_resource=vc_resources_from_assignment(vc_assignment),
        routing_realization=make_deterministic_routing_realization(
            topology=topology, attachment=attachment, route=router_route,
            resolved_route=resolved_route, vc_assignment=vc_assignment,
            vc_resource=vc_resources_from_assignment(vc_assignment)),
        packet_format=packet_format, router_behavior=router_behavior,
        address_decode=address_decode, fabric=fabric, route=router_route,
        resolved_route=resolved_route, vc_assignment=vc_assignment)
