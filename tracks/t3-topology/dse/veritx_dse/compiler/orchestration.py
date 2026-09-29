"""veritx_dse.compiler.orchestration — bundle compiler (orchestration).

Rationale: docs/decisions/modules/compiler.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.application.errors import (
    ControlPlaneError, ErrorCode, map_semantic_error,
)
from veritx_dse.core.errors import VeritXError


def build_resolved_bundle(compile_request: Any):
    """Derive a ResolvedFabricBundle through the ONE canonical compiler.

Rationale: docs/decisions/modules/compiler.md
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
        raise map_semantic_error(exc, operation="compile") from exc


#: The v3 derivation stages, in order, as (stage, builder). A refusal in
#: any builder leaves the artifacts from earlier stages authoritative.
def _v3_stages(compile_request):
    """Build the ordered stage list for a v3 request.

    Each entry is ``(stage, callable(previous) -> artifact)``. Declaring
    the sequence here (rather than inline) is what makes stage
    preservation generic: any refusal is attributed to a stage, and every
    earlier artifact survives it.
    """
    from veritx_dse.compiler.candidate_policy import (
        BASELINE_FABRIC_SETTINGS,
    )
    from veritx_dse.compiler.canonical import compose_deterministic_candidate
    from veritx_dse.model.attachment import derive_attachment
    from veritx_dse.model.compile_model import (
        derive_vc_assignment_artifact_v3,
        fabric_intent_view,
    )
    from veritx_dse.model.mapping import derive_mapping
    from veritx_dse.model.placement import build_inventory
    from veritx_dse.model.resolved_bundle import make_resolved_fabric_bundle
    from veritx_dse.model.resolved_route import derive_resolved_route
    from veritx_dse.model.routing import derive_route
    from veritx_dse.model.topology_artifact import materialize_topology

    # Stage names are the canonical `CompileStage` vocabulary, so a v3
    # stage refusal speaks the same language as a v2 one.
    from veritx_dse.compiler.canonical import CompileStage as CS

    return (
        (CS.INPUT.value, lambda done: build_inventory(compile_request)),
        (CS.INPUT.value + "_MAPPING",
         lambda done: derive_mapping(compile_request)),
        (CS.TOPOLOGY.value, lambda done: materialize_topology(
            done["INPUT"], done["_view"])),
        (CS.ATTACHMENT.value, lambda done: derive_attachment(
            design=compile_request, inventory=done["INPUT"],
            topology=done[CS.TOPOLOGY.value])),
        (CS.ROUTING.value, lambda done: derive_route(
            request=done["_view"], topology=done[CS.TOPOLOGY.value])),
        (CS.ROUTING_REALIZATION.value, lambda done: derive_resolved_route(
            done[CS.TOPOLOGY.value], done[CS.ATTACHMENT.value],
            done[CS.ROUTING.value])),
        (CS.VC.value, lambda done: derive_vc_assignment_artifact_v3(
            compile_request, done[CS.ROUTING_REALIZATION.value])),
        (CS.FABRIC.value, lambda done: compose_deterministic_candidate(
            design=compile_request, inventory=done["INPUT"],
            mapping=done["INPUT_MAPPING"], topology=done[CS.TOPOLOGY.value],
            attachment=done[CS.ATTACHMENT.value], route=done[CS.ROUTING.value],
            resolved_route=done[CS.ROUTING_REALIZATION.value],
            vc_assignment=done[CS.VC.value],
            settings=BASELINE_FABRIC_SETTINGS)),
        (CS.RESOLVED_FABRIC.value, lambda done: make_resolved_fabric_bundle(
            design=done[CS.FABRIC.value].design,
            inventory=done[CS.FABRIC.value].inventory,
            mapping=done[CS.FABRIC.value].mapping,
            topology=done[CS.FABRIC.value].topology,
            attachment=done[CS.FABRIC.value].attachment,
            router_route=done[CS.FABRIC.value].routing.route,
            resolved_route=done[CS.FABRIC.value].routing.resolved_route,
            vc_assignment=done[CS.FABRIC.value].routing.vc_assignment,
            packet_format=done[CS.FABRIC.value].packet_format,
            router_behavior=done[CS.FABRIC.value].router_behavior,
            address_decode=done[CS.FABRIC.value].address_decode,
            fabric=done[CS.FABRIC.value].fabric,
            resolved_fabric=done[CS.FABRIC.value].resolved_fabric)),
    )


def derive_stages_v3(compile_request: Any):
    """Run the v3 derivation, preserving upstream artifacts on refusal.

Rationale: docs/decisions/modules/compiler.md
    """
    from veritx_dse.application.fabric_compiler import StagedDerivation
    from veritx_dse.model.compile_model import fabric_intent_view

    stages = _v3_stages(compile_request)
    done: dict[str, Any] = {}
    try:
        done["_view"] = fabric_intent_view(compile_request)
    except ControlPlaneError:
        raise
    except VeritXError as exc:
        raise map_semantic_error(exc, operation="compile") from exc

    produced: list[str] = []
    for stage, builder in stages:
        try:
            done[stage] = builder(done)
        except ControlPlaneError as exc:
            return None, StagedDerivation(
                stopped_at_stage=stage,
                produced_stages=tuple(produced),
                inventory=done.get("INPUT"),
                mapping=done.get("INPUT_MAPPING"),
                topology=done.get("TOPOLOGY"),
                attachment=done.get("ATTACHMENT"),
                view=done.get("_view"),
            ), exc
        except VeritXError as exc:
            return None, StagedDerivation(
                stopped_at_stage=stage,
                produced_stages=tuple(produced),
                inventory=done.get("INPUT"),
                mapping=done.get("INPUT_MAPPING"),
                topology=done.get("TOPOLOGY"),
                attachment=done.get("ATTACHMENT"),
                view=done.get("_view"),
            ), map_semantic_error(exc, operation="compile")
        produced.append(stage)
    from veritx_dse.compiler.canonical import CompileStage as CS
    return done[CS.RESOLVED_FABRIC.value], None, None


def build_resolved_bundle_v3(compile_request: Any):
    """Derive and validate a ResolvedFabricBundle from a v3 request.

Rationale: docs/decisions/modules/compiler.md
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

    if not isinstance(compile_request, CompileRequestV3) and not (
            getattr(compile_request, "schema_version", None) == 4
            and hasattr(compile_request, "noc_controls")):
        raise map_semantic_error(
            TypeError(
                f"build_resolved_bundle_v3 takes a CompileRequestV3 or a "
                f"CompileRequestV4, got "
                f"{type(compile_request).__name__}"),
            operation="compile")
    try:
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
        raise map_semantic_error(exc, operation="compile") from exc


def probe_direct_materialize(request: Any, intent: Any) -> Any:
    """Materialize directly with the SAME probe intent.

    Used by capability truth when a compilation drops its staged record:
    the materializer is the canonical seam itself (never a parallel
    authority), so a YES here is observed derivation, not a claim.
    Raises the seam's own typed refusal when the bridge is absent.
    """
    from veritx_dse.model.placement import build_inventory
    from veritx_dse.model.topology_artifact import (
        materialize_topology_intent,
    )
    return materialize_topology_intent(
        build_inventory(request), intent)


def probe_direct_route(request: Any, topology: Any) -> Any:
    """Derive the route directly over a materialized topology.

    Same contract as probe_direct_materialize, for the routing seam.
    """
    from veritx_dse.model.compile_model import fabric_intent_view
    from veritx_dse.model.routing import derive_route
    return derive_route(
        request=fabric_intent_view(request), topology=topology)


@dataclass(frozen=True)
class AdaptiveCompileResult:
    """Adaptive overlay derived alongside a deterministic Product bundle.

Rationale: docs/decisions/modules/compiler.md
    """

    policy: Any
    relation: Any
    esc_resource: Any
    binding: Any
    realization: Any
    qualification: Any
    fabric: Any
    resolved_fabric: Any


def derive_adaptive_overlay(request: Any, bundle: Any,
                            policy: Any) -> AdaptiveCompileResult:
    """Derive the MIN_ADAPT_MESH chain over a COMPILED deterministic bundle.

Rationale: docs/decisions/modules/compiler.md
    """
    from veritx_dse.model.routing_policy import RoutingPolicyDefinition
    if not isinstance(policy, RoutingPolicyDefinition):
        raise TypeError(
            f"routing_policy must be a RoutingPolicyDefinition, got "
            f"{type(policy).__name__} — routing stays LOCKED: no raw "
            f"routing_function string is ever accepted")
    try:
        from veritx_dse.compiler.canonical import (
            _derive_common_hardware,
        )
        from veritx_dse.compiler.candidate_policy import (
            BASELINE_FABRIC_SETTINGS,
        )
        from veritx_dse.model.fabric_artifact import make_adaptive_fabric
        from veritx_dse.model.resolved_fabric import (
            make_resolved_adaptive_fabric,
        )
        from veritx_dse.model.routing_realization import (
            make_adaptive_routing_realization,
        )
        from veritx_dse.model.routing_relation_materialize import (
            materialize_routing_relation,
        )
        from veritx_dse.model.routing_resource_binding import (
            RoutingResourceBindingArtifact,
        )
        from veritx_dse.model.vc_resource import (
            adaptive_escape_vc_resource,
            vc_resources_from_assignment,
        )
        from veritx_dse.verification.adaptive_escape import (
            qualify_min_adapt,
        )
        topology = bundle.topology
        attachment = bundle.attachment
        # Exact min_adapt profile gate: UGAL/Valiant/Chaos/planar/ROMM
        # and non-mesh topologies refuse inside materialization.
        relation = materialize_routing_relation(topology, policy)
        base_vcr = vc_resources_from_assignment(bundle.vc_assignment)
        if base_vcr.vc_count < 2:
            raise ControlPlaneError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"MIN_ADAPT_MESH needs vc_count >= 2 for the escape "
                f"partition (escape VC0 + adaptive 1..N), got "
                f"{base_vcr.vc_count} — no room for escape resources",
                operation="compile")
        carried = tuple(
            cls for cls, _vcs in base_vcr.traffic_class_to_vcs)
        esc = adaptive_escape_vc_resource(
            base_vcr, escape_vcs=(0,),
            adaptive_vcs=tuple(range(1, base_vcr.vc_count)),
            traffic_classes=carried)
        binding = RoutingResourceBindingArtifact(
            policy_hash=policy.policy_hash,
            vc_resource_hash=esc.artifact_hash,
            role_to_vcs=(("escape", (0,)),
                          ("adaptive",
                           tuple(range(1, base_vcr.vc_count)))))
        realization = make_adaptive_routing_realization(
            topology=topology, policy=policy, relation=relation,
            vc_resource=esc, binding=binding)
        qualification = qualify_min_adapt(
            topology=topology, policy=policy, relation=relation,
            vc_resource=esc, binding=binding,
            realization_hash=realization.routing_realization_hash)
        if getattr(qualification, "verdict", None) != "QUALIFIED":
            raise ControlPlaneError(
                ErrorCode.POLICY_REJECTED,
                f"MIN_ADAPT_MESH escape-subfunction proof did not pass "
                f"(verdict {getattr(qualification, 'verdict', None)!r}) "
                f"— refusing a failed proof, never an uncertified fabric",
                operation="compile")
        packet_format, router_behavior, address_decode = \
            _derive_common_hardware(
                design=request, topology=topology, attachment=attachment,
                vc_resource=esc, settings=BASELINE_FABRIC_SETTINGS)
        fabric = make_adaptive_fabric(
            topology=topology, attachment=attachment, vc_resource=esc,
            routing_realization=realization, packet_format=packet_format,
            router_behavior=router_behavior, address_decode=address_decode,
            policy=policy, relation=relation, binding=binding)
        resolved = make_resolved_adaptive_fabric(
            design=request, inventory=bundle.inventory,
            mapping=bundle.mapping, topology=topology,
            attachment=attachment, vc_resource=esc,
            routing_realization=realization, packet_format=packet_format,
            router_behavior=router_behavior, address_decode=address_decode,
            fabric=fabric, policy=policy, relation=relation,
            binding=binding)
        return AdaptiveCompileResult(
            policy=policy, relation=relation, esc_resource=esc,
            binding=binding, realization=realization,
            qualification=qualification, fabric=fabric,
            resolved_fabric=resolved)
    except ControlPlaneError:
        raise
    except VeritXError as exc:
        raise map_semantic_error(exc, operation="compile") from exc


__all__ = ["build_resolved_bundle", "build_resolved_bundle_v3",
           "derive_adaptive_overlay", "AdaptiveCompileResult"]
