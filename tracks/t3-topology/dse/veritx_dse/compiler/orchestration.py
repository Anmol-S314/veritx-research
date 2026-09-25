"""veritx_dse.compiler.orchestration — bundle compiler (orchestration).

The compiler sequences the SEALED Wave-B derivation only:

    CompileRequest -> inventory -> mapping -> topology -> attachment
    -> route -> resolved route -> VC -> vc resource -> routing
    realization -> packet format -> router behavior -> address decode
    -> fabric -> resolved fabric -> validated bundle

It derives NOTHING semantic itself: no routes, no VC assignment, no
packetization, no profile values. New semantic logic here would be a
second authority and is forbidden.

Reclamation note (veritx-integrate): the historical RT-candidate seam
composed FabricArtifact v1 children (resolved_route_hash +
vc_assignment_hash). The canonical FabricArtifact is the single fabric
authority; this seam now derives the two canonical children
(``vc_resources_from_assignment`` and
``make_deterministic_routing_realization``) exactly as
``compiler.canonical.compile_deterministic_candidate`` does and composes
through canonical ``make_deterministic_fabric``. No second artifact
class exists.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.application.errors import ControlPlaneError, map_semantic_error
from veritx_dse.core.errors import VeritXError

# There is no derivation sequencer here. Both entry points build their
# candidate semantics (route / resolved route / VC assignment) and funnel
# through ``compiler.canonical.compose_deterministic_candidate`` (C2.1),
# the one deterministic derivation engine. The baseline hardware settings
# live in ``candidate_policy.BASELINE_FABRIC_SETTINGS``.


def build_resolved_bundle(compile_request: Any):
    """Derive a ResolvedFabricBundle through the ONE canonical compiler.

    The reclaimed Wave-C entry point no longer performs a second v2
    derivation: it generates the declared BASELINE_DETERMINISTIC_V2
    candidate plan and compiles it with
    ``compiler.canonical.compile_deterministic_candidate`` — the same
    compiler the ``SrotaControlPlane`` service uses. Child identities are
    pinned equal by ``tests/test_compiler_path_parity.py``.
    """
    from veritx_dse.compiler.canonical import compile_deterministic_candidate
    from veritx_dse.compiler.candidate_policy import (
        generate_baseline_candidate,
    )
    from veritx_dse.model.resolved_bundle import make_resolved_fabric_bundle

    try:
        plan = generate_baseline_candidate(design=compile_request)
        compiled = compile_deterministic_candidate(
            design=compile_request, inventory=plan.inventory,
            mapping=plan.mapping, routing_policy=plan.routing_policy,
            vc_spec=plan.vc_spec, settings=plan.compile_settings)
        return make_resolved_fabric_bundle(
            design=compiled.design, inventory=compiled.inventory,
            mapping=compiled.mapping, topology=compiled.topology,
            attachment=compiled.attachment,
            router_route=compiled.routing.route,
            resolved_route=compiled.routing.resolved_route,
            vc_assignment=compiled.routing.vc_assignment,
            packet_format=compiled.packet_format,
            router_behavior=compiled.router_behavior,
            address_decode=compiled.address_decode, fabric=compiled.fabric,
            resolved_fabric=compiled.resolved_fabric)
    except ControlPlaneError:
        raise
    except VeritXError as exc:
        # Typed semantic refusal -> product outcome. A programmer fault
        # (AttributeError/TypeError/RuntimeError/NameError) is NOT a
        # semantic result and must propagate, not be laundered into
        # UNSUPPORTED_SEMANTICS.
        raise map_semantic_error(exc, operation="compile") from exc


def build_resolved_bundle_v3(compile_request: Any):
    """Derive and validate a ResolvedFabricBundle from a v3 request.

    P1C phase-2 (Fix 2): makes CompileRequestV3 genuinely compilable
    WITHOUT converting it into a fake v2 request. The sequence is the
    same sealed derivation: every duck-typed stage (inventory, mapping,
    attachment, address decode, packet format, router behavior, fabric,
    resolved fabric/bundle) consumes the v3 request directly through the
    fields it shares with v2 (agents, address_map, workload geometry,
    design_hash, noc_config). The two v2-gated stages take the
    FabricIntentView (the one dispatch seam); VC structure comes from
    the v3 policy (derive_vc_assignment_artifact_v3 — declared classes,
    no concurrent-context floor). No v2 semantics are reinterpreted and
    the v2 path above is untouched.
    """
    from veritx_dse.model.attachment import derive_attachment
    from veritx_dse.model.compile_model import (
        CompileRequestV3,
        derive_vc_assignment_artifact_v3,
        fabric_intent_view,
    )
    from veritx_dse.model.mapping import derive_mapping
    from veritx_dse.model.placement import build_inventory
    from veritx_dse.model.resolved_bundle import make_resolved_fabric_bundle
    from veritx_dse.model.resolved_route import derive_resolved_route
    from veritx_dse.model.routing import derive_route
    from veritx_dse.model.topology_artifact import materialize_topology

    if not isinstance(compile_request, CompileRequestV3):
        raise map_semantic_error(
            TypeError(
                f"build_resolved_bundle_v3 takes a CompileRequestV3, got "
                f"{type(compile_request).__name__}"),
            operation="compile")
    try:
        # v3 intent interpretation produces explicit candidate semantics
        # (inventory/mapping/topology/attachment/route/resolved_route/VC);
        # everything downstream is the ONE canonical derivation engine.
        from veritx_dse.compiler.canonical import (
            compose_deterministic_candidate,
        )
        from veritx_dse.compiler.candidate_policy import (
            BASELINE_FABRIC_SETTINGS,
        )
        view = fabric_intent_view(compile_request)
        inventory = build_inventory(compile_request)
        mapping = derive_mapping(compile_request)
        topology = materialize_topology(inventory, view)
        attachment = derive_attachment(
            design=compile_request, inventory=inventory, topology=topology)
        router_route = derive_route(
            request=view, topology=topology)
        resolved_route = derive_resolved_route(topology, attachment,
                                               router_route)
        vc_assignment = derive_vc_assignment_artifact_v3(
            compile_request, resolved_route)
        compiled = compose_deterministic_candidate(
            design=compile_request, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment, route=router_route,
            resolved_route=resolved_route, vc_assignment=vc_assignment,
            settings=BASELINE_FABRIC_SETTINGS)
        return make_resolved_fabric_bundle(
            design=compiled.design, inventory=compiled.inventory,
            mapping=compiled.mapping, topology=compiled.topology,
            attachment=compiled.attachment,
            router_route=compiled.routing.route,
            resolved_route=compiled.routing.resolved_route,
            vc_assignment=compiled.routing.vc_assignment,
            packet_format=compiled.packet_format,
            router_behavior=compiled.router_behavior,
            address_decode=compiled.address_decode, fabric=compiled.fabric,
            resolved_fabric=compiled.resolved_fabric)
    except ControlPlaneError:
        raise
    except VeritXError as exc:
        # Typed semantic refusal -> product outcome. A programmer fault
        # (AttributeError/TypeError/RuntimeError/NameError) is NOT a
        # semantic result and must propagate, not be laundered into
        # UNSUPPORTED_SEMANTICS.
        raise map_semantic_error(exc, operation="compile") from exc


__all__ = ["build_resolved_bundle", "build_resolved_bundle_v3"]
