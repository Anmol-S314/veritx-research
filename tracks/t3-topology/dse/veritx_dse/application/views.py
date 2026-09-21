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
            bundle.resolved_fabric.resolved_fabric_hash()),
        "certificate_id": certificate.certificate_id(),
        "certificate_overall": certificate.overall,
        "obligations": [o.to_dict() for o in certificate.obligations],
        "artifact_hashes": {
            str(k): str(v)
            for k, v in bundle.root_hashes().items()},
    })
    return view


def _agent_kind(value: Any) -> str:
    return getattr(value, "value", value)


def design_view(request: Any, compilation: Any = None) -> dict[str, Any]:
    """Project a CompileRequest (v2 or v3) to DesignView (contract v1).

    `compilation`, when a COMPILED Compilation for this request, fills
    the read-only `locked_derived` block. Anything else (or nothing)
    leaves it null: Studio must never let users edit derived state,
    and this projector never invents it.
    """
    from veritx_dse.model.compile_model import (
        CompileRequest,
        CompileRequestV3,
    )
    if not isinstance(request, (CompileRequest, CompileRequestV3)):
        raise TypeError(
            f"design_view takes a CompileRequest, got "
            f"{type(request).__name__}")
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
