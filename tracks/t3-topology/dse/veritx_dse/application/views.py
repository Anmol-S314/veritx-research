"""veritx_dse.application.views — product-view gateway (P1 integration).

The single Studio-facing boundary:

    engine artifacts
      -> this projector
      -> contracts/srota/v1 (JSON Schemas)
      -> Studio (never engine internals)

Rules, shared with every other view projector:
- Engine values are bare digests; this module adds exactly one
  ``sha256:`` prefix per hash at the view boundary.
- Absent engine facts stay absent (keys omitted), never zero-filled or
  guessed. In particular the resolved VC artifact carries no turn
  restriction list, so ``turn_restrictions`` is omitted rather than
  rendered as "none".
- No semantics here: pure projection of already-certified objects.
  Invalid inputs raise TypeError; never a view with half-truths.

Already covered elsewhere and NOT duplicated here: EvaluationView
(``EvaluationOutcome.to_view_dict``), RequirementReport (the evaluator's
report dict), OptimizationStudyView (``OptimizationResult.to_study_view``).
"""
from __future__ import annotations

from typing import Any


def _h(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"hash must be a non-empty string, got {value!r}")
    return value if value.startswith("sha256:") else "sha256:" + value


def compilation_view(compilation: Any) -> dict[str, Any]:
    """Project a Compilation to CompilationView (contract v1)."""
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation):
        raise TypeError(
            f"compilation_view takes a Compilation, got "
            f"{type(compilation).__name__}")
    request = compilation.request
    view: dict[str, Any] = {
        "contract_version": 1,
        "status": compilation.status,
        "design_hash": _h(request.design_hash()),
        "compiler_semantics_version":
            request.compiler_semantics_version,
        "error": compilation.error,
    }
    if compilation.status != "COMPILED":
        return view
    bundle, certificate = compilation.bundle, compilation.certificate
    view.update({
        "resolved_fabric_hash": _h(
            bundle.resolved_fabric.resolved_fabric_hash),
        "certificate_id": certificate.certificate_id(),
        "certificate_overall": certificate.overall,
        "obligations": [o.to_dict() for o in certificate.obligations],
        "artifact_hashes": {
            str(k): str(v)
            for k, v in bundle.root_hashes().items()},
    })
    return view


def topology_view(compilation: Any,
                  *, revision_id: str | None = None) -> dict[str, Any] | None:
    """Project a Compilation to TopologyView — the materialized fabric graph.

    This is the ONLY shape Studio may draw. A topology family name in
    DesignView is intent metadata; the routers, channels and agent
    attachments below are the certified artifact the certificate proved.

    Returns None for a non-COMPILED compilation (a failed proof is not a
    fabric — no empty graph is ever invented in its place).
    """
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation):
        raise TypeError(
            f"topology_view takes a Compilation, got "
            f"{type(compilation).__name__}")
    if compilation.status != "COMPILED":
        return None
    bundle = compilation.bundle
    topology, attachment = bundle.topology, bundle.attachment
    return {
        "contract_version": 1,
        "revision_id": revision_id,
        "design_hash": _h(compilation.request.design_hash()),
        "topology_hash": _h(topology.topology_hash()),
        "attachment_hash": _h(attachment.attachment_hash()),
        "family": _agent_kind(topology.family),
        "routers": [r.to_dict() for r in topology.routers],
        "channels": [c.to_dict() for c in topology.channels],
        "physical_links": [p.to_dict() for p in topology.physical_links],
        "endpoints": [
            {
                "endpoint_id": e.endpoint_id,
                "kind": _agent_kind(e.agent.kind),
                "group_index": e.agent.group_index,
                "instance_index": e.agent.instance_index,
                "router_id": e.router_id,
                "port_id": e.port_id,
            }
            for e in attachment.endpoints
        ],
        "counts": {
            "routers": topology.router_count,
            "channels": topology.channel_count,
            "seats": topology.seat_capacity,
            "endpoints": attachment.endpoint_count,
        },
    }


def _agent_kind(value: Any) -> str:
    return getattr(value, "value", value)


def design_view(request: Any, compilation: Any = None) -> dict[str, Any]:
    """Project a CompileRequest (v2 or v3) to DesignView (contract v1).

    `compilation`, when given, must be a Compilation FOR THIS REQUEST
    (same design_hash); a COMPILED match fills the read-only
    `locked_derived` block, while an unmatched or non-Compilation
    object raises ValueError — never a cross-design projection.
    Nothing (None) leaves locked_derived null: Studio must never let
    users edit derived state, and this projector never invents it.
    """
    from veritx_dse.application.fabric_compiler import Compilation
    from veritx_dse.model.compile_model import (
        CompileRequest,
        CompileRequestV3,
    )
    if not isinstance(request, (CompileRequest, CompileRequestV3)):
        raise TypeError(
            f"design_view takes a CompileRequest, got "
            f"{type(request).__name__}")
    if compilation is not None:
        if not isinstance(compilation, Compilation):
            raise ValueError(
                f"design_view compilation must be a Compilation, got "
                f"{type(compilation).__name__}")
        request_hash = request.design_hash()
        compilation_hash = compilation.request.design_hash()
        if compilation_hash != request_hash:
            raise ValueError(
                f"design_view refuses a cross-design projection: request "
                f"design_hash {request_hash!r} != compilation "
                f"design_hash {compilation_hash!r}")
    workload = request.workload
    source_ref = getattr(workload, "source_ref", None)
    workload_view: dict[str, Any] = {
        "model_family": _agent_kind(workload.model_family),
        "model_name": workload.model_name,
        "parallelism": {
            "tp": workload.tp, "pp": workload.pp,
            "ep": workload.ep, "dp": workload.dp},
        "serving_mode": _agent_kind(workload.serving_mode),
    }
    if source_ref is not None:
        workload_view["workload_source_ref"] = {
            "content_digest": source_ref.content_digest,
            "format": source_ref.format,
            "size_bytes": source_ref.size_bytes,
        }
    noc = request.noc_config
    topo = noc.topology_family
    view: dict[str, Any] = {
        "contract_version": 1,
        "design_hash": _h(request.design_hash()),
        "schema_version": request.schema_version,
        "compiler_semantics_version":
            request.compiler_semantics_version,
        "workload": workload_view,
        "requirements": [{
            "traffic_class": getattr(r, "traffic_class", None),
            "qos_class": _agent_kind(r.qos_class),
            "latency_ceiling_cycles": r.latency_ceiling_cycles,
            "bandwidth_floor_gbps": r.bandwidth_floor_gbps,
            "binding": r.binding,
        } for r in request.requirements],
        "agents": [{
            "kind": _agent_kind(a.kind), "count": a.count,
        } for a in request.agents],
        "noc_guided": {
            "topology_family":
                _agent_kind(topo) if topo is not None else None,
            "radix": noc.radix,
            "concentration": noc.concentration,
            "link_width": noc.link_width,
            "rcu_enabled": noc.rcu_enabled,
            "arbitration": noc.arbitration,
        },
        "locked_derived": None,
    }
    if compilation is not None and \
            compilation.status == "COMPILED":
        vc = compilation.bundle.vc_assignment
        classes = sorted(
            {str(rc) for _, rc in vc.vc_to_routing_class})
        view["locked_derived"] = {
            "routing": ",".join(classes),
            "vc_count": vc.vc_count,
            "certificate_overall": compilation.certificate.overall,
        }
    return view


__all__ = ["compilation_view", "design_view"]
