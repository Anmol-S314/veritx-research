"""System composition/revalidation using authoritative parent derivations.

No subsystem advances execution/qualification merely because it is a child.
Legacy adaptive rederivation stays behind its existing compiler adapter until
Phase B; this preserves its common-hardware and escape qualification logic.
"""
from __future__ import annotations

from veritx_dse.core.artifact import canonical_bytes
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput, UnsupportedSemantics
from veritx_dse.model.compiled_system import CompiledSystemArtifact, _identity
from veritx_dse.model.resource_graph import resource_graph_from_topology
from veritx_dse.model.resource_allocation import allocation_from_assignment
from veritx_dse.model.routing_policy_artifact import normalize_legacy_route
from veritx_dse.verification.certificate import VerificationCertificate, verify_compiled_fabric, verify_v5_compilation
from veritx_dse.verification.dependency_proof import prove_dependencies


def _validate_parents(request, bundle, certificate, access, sidebands, clocks, control, adaptive):
    from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3, fabric_intent_view
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.resolved_bundle import ResolvedFabricBundle
    from veritx_dse.model.routing import derive_route
    from veritx_dse.model.routing_realization import route_artifact_identity
    if type(request) not in (CompileRequest, CompileRequestV3, CompileRequestV4, CompileRequestV5):
        raise InvalidInput("system requires a supported versioned design root")
    checked = type(request).from_dict(request.to_dict())
    base = checked.base_v4 if isinstance(checked, CompileRequestV5) else checked
    if not isinstance(bundle, ResolvedFabricBundle) or base.design_hash() != bundle.design.design_hash():
        raise EvidenceInvalid("system hardware base does not bind to the authored design")
    bundle.revalidate()
    # Stronger than hashes: the locked algorithm is re-materialized from
    # authored intent. A caller cannot prune/replace derived policy data and
    # reseal only the descendant hashes to turn it into trusted intent.
    expected_route = derive_route(request=fabric_intent_view(base), topology=bundle.topology)
    if route_artifact_identity(expected_route) != route_artifact_identity(bundle.router_route):
        raise EvidenceInvalid("system routing differs from parent-recomputed authored policy")
    if isinstance(checked, CompileRequestV5):
        expected_certificate = verify_v5_compilation(
            checked, bundle, access_policy=access, sideband_set=sidebands, clock_domains=clocks)
    else:
        if any(obj is not None for obj in (access, sidebands, clocks)):
            raise EvidenceInvalid("legacy design has undeclared V5 subsystem children")
        expected_certificate = verify_compiled_fabric(bundle)
    if (type(certificate) is not VerificationCertificate or expected_certificate.overall != "PASS"
            or certificate.certificate_id() != expected_certificate.certificate_id()):
        raise EvidenceInvalid("system certificate differs from parent-recomputed obligations")
    from veritx_dse.model.control_plane import materialize_control_plane
    expected_control = materialize_control_plane(bundle.topology) if "c" in bundle.topology.planes else None
    if control != expected_control:
        raise EvidenceInvalid("control-plane child differs from the declared topology")
    if adaptive is not None:
        # Retained adapter: never duplicate the escape/common-hardware recipe.
        from veritx_dse.compiler.orchestration import derive_adaptive_overlay
        expected = derive_adaptive_overlay(base, bundle, adaptive.policy)
        for name, accessor in (("relation", "relation_hash"), ("esc_resource", "artifact_hash"),
                               ("binding", "binding_hash"), ("realization", "routing_realization_hash"),
                               ("fabric", "fabric_hash"), ("resolved_fabric", "resolved_fabric_hash")):
            if _identity(getattr(adaptive, name), accessor) != _identity(getattr(expected, name), accessor):
                raise EvidenceInvalid(f"adaptive {name} differs from parent rederivation")
        if adaptive.qualification != expected.qualification:
            raise EvidenceInvalid("adaptive qualification differs from recomputed escape proof")


def materialize_compiled_system(*, request, bundle, certificate, access_policy=None,
                                sideband_set=None, clock_domains=None, control_plane=None,
                                adaptive=None):
    _validate_parents(request, bundle, certificate, access_policy, sideband_set,
                      clock_domains, control_plane, adaptive)
    graph = resource_graph_from_topology(bundle.topology)
    rb = bundle.router_behavior
    allocation = allocation_from_assignment(bundle.vc_assignment, bundle.router_route,
        buffer_policy={"source_router_behavior": _identity(rb, "router_behavior_hash"),
                       "organization": rb.buffer_organization.value,
                       "input_depth_flits_per_vc": rb.input_buffer_depth_flits_per_vc,
                       "output_depth_flits_per_vc": rb.output_stage_depth_flits_per_vc,
                       "flow_control": rb.flow_control.value})
    policy = proof = None
    refusal = None
    if adaptive is not None:
        refusal = "legacy adaptive/escape adapter retained; generic migration is Phase B"
    else:
        try:
            policy = normalize_legacy_route(bundle.topology, bundle.router_route, allocation, graph)
        except UnsupportedSemantics as exc:
            refusal = str(exc)
        if policy is not None:
            proof = prove_dependencies(graph, policy, allocation)
            if proof.verdict != "PASS":
                raise EvidenceInvalid("normalized routing fails its generic dependency obligation")
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.execution_contract import materialize_execution_contract
    contract = materialize_execution_contract(request, bundle) if isinstance(request, CompileRequestV5) else None
    return CompiledSystemArtifact(request, bundle, certificate, graph, allocation, policy, proof,
                                  access_policy, sideband_set, clock_domains, control_plane, adaptive, refusal,
                                  execution_contract=contract)


def revalidate_compiled_system(system):
    if not isinstance(system, CompiledSystemArtifact):
        raise InvalidInput("revalidation requires a CompiledSystemArtifact")
    expected = materialize_compiled_system(
        request=system.request, bundle=system.fabric, certificate=system.network_certificate,
        access_policy=system.access_system, sideband_set=system.sidebands, clock_domains=system.clock_domains,
        control_plane=system.control_plane, adaptive=system.adaptive)
    if (system.resource_graph != expected.resource_graph or system.allocation != expected.allocation
            or system.routing_policy != expected.routing_policy or system.dependency_proof != expected.dependency_proof
            or system.execution_contract != expected.execution_contract
            or system.system_hash() != expected.system_hash()):
        raise EvidenceInvalid("compiled system children differ from full parent recomputation")
