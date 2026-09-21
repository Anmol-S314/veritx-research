"""veritx_dse.application.compile — Wave-C bundle compiler (orchestration).

The compiler sequences the SEALED Wave-B derivation only:

    CompileRequest -> inventory -> mapping -> topology -> attachment
    -> route -> resolved route -> VC -> packet format -> router behavior
    -> address decode -> fabric -> resolved fabric -> validated bundle

It derives NOTHING semantic itself: no routes, no VC assignment, no
packetization, no profile values. New semantic logic here would be a
second authority and is forbidden.
"""
from __future__ import annotations

from typing import Any

from .errors import map_semantic_error


def compile_bundle(compile_request: Any):
    """Derive and validate a ResolvedFabricBundle from a CompileRequest."""
    from veritx_dse.model.resolved_bundle import make_resolved_fabric_bundle
    from veritx_dse.model.address_decode import derive_address_decode
    from veritx_dse.model.attachment import derive_attachment
    from veritx_dse.model.compile_model import derive_vc_assignment_artifact
    from veritx_dse.model.fabric_artifact import make_fabric_artifact
    from veritx_dse.model.mapping import derive_mapping
    from veritx_dse.model.packet_format import derive_packet_format
    from veritx_dse.model.placement import build_inventory
    from veritx_dse.model.resolved_fabric import make_resolved_fabric
    from veritx_dse.model.resolved_route import derive_resolved_route
    from veritx_dse.model.router_behavior import derive_router_behavior
    from veritx_dse.model.routing import derive_route
    from veritx_dse.model.topology_artifact import materialize_topology

    try:
        inventory = build_inventory(compile_request)
        mapping = derive_mapping(compile_request)
        topology = materialize_topology(inventory, compile_request)
        attachment = derive_attachment(
            design=compile_request, inventory=inventory, topology=topology)
        # P1.2: the route is compiler-derived (LOCKED) — never a
        # hardcoded class beside a separately derived routing string.
        router_route = derive_route(
            request=compile_request, topology=topology)
        resolved_route = derive_resolved_route(topology, attachment,
                                               router_route)
        vc_assignment = derive_vc_assignment_artifact(
            compile_request, resolved_route)
        packet_format = derive_packet_format(
            topology=topology, attachment=attachment,
            vc_assignment=vc_assignment)
        router_behavior = derive_router_behavior(
            vc_assignment=vc_assignment)
        address_decode = derive_address_decode(
            design=compile_request, attachment=attachment)
        fabric = make_fabric_artifact(
            topology=topology, attachment=attachment,
            router_route=router_route, resolved_route=resolved_route,
            vc_assignment=vc_assignment, packet_format=packet_format,
            router_behavior=router_behavior, address_decode=address_decode)
        resolved_fabric = make_resolved_fabric(
            design=compile_request, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment,
            router_route=router_route, resolved_route=resolved_route,
            vc_assignment=vc_assignment, packet_format=packet_format,
            router_behavior=router_behavior, address_decode=address_decode,
            fabric=fabric)
        return make_resolved_fabric_bundle(
            design=compile_request, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment,
            router_route=router_route, resolved_route=resolved_route,
            vc_assignment=vc_assignment, packet_format=packet_format,
            router_behavior=router_behavior, address_decode=address_decode,
            fabric=fabric, resolved_fabric=resolved_fabric)
    except Exception as exc:
        from .errors import ControlPlaneError
        if isinstance(exc, ControlPlaneError):
            raise
        raise map_semantic_error(exc, operation="compile") from exc


__all__ = ["compile_bundle"]
