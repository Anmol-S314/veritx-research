"""veritx_dse.application.views — product-view gateway (P1 integration).

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from typing import Any
from veritx_dse.model.generation import is_any_compile_request  # noqa: E402

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
    staged = getattr(compilation, "staged", None)
    if getattr(compilation, "stopped_at_stage", None) is not None:
        view["stopped_at_stage"] = compilation.stopped_at_stage
    if staged is not None:
        view["staged"] = {
            "stopped_at_stage": staged.stopped_at_stage,
            "produced_stages": list(staged.produced_stages),
            "has_topology": staged.topology is not None,
            "has_attachment": staged.attachment is not None,
            "has_mapping": staged.mapping is not None,
            "has_inventory": staged.inventory is not None,
        }
    if compilation.status != "COMPILED":
        return view
    bundle, certificate = compilation.bundle, compilation.certificate
    root_hashes = {str(k): str(v) for k, v in bundle.root_hashes().items()}
    view.update({
        "resolved_fabric_hash": _h(root_hashes["resolved_fabric_hash"]),
        "certificate_id": certificate.certificate_id(),
        "certificate_overall": certificate.overall,
        "obligations": [o.to_dict() for o in certificate.obligations],
        "artifact_hashes": root_hashes,
    })
    return view

def topology_view(compilation: Any,
                  *, revision_id: str | None = None) -> dict[str, Any] | None:
    """Project a Compilation to TopologyView — the materialized fabric graph.

Rationale: docs/decisions/modules/application.md
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

def staged_topology_view(compilation: Any,
                         *, revision_id: str | None = None
                         ) -> dict[str, Any] | None:
    """Project a STAGED refusal's derived topology (the staged-compilation law).

Rationale: docs/decisions/modules/application.md
    """
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation):
        raise TypeError(
            f"staged_topology_view takes a Compilation, got "
            f"{type(compilation).__name__}")
    staged = getattr(compilation, "staged", None)
    if staged is None or staged.topology is None:
        return None
    topology, attachment = staged.topology, staged.attachment
    endpoints = []
    if attachment is not None:
        endpoints = [
            {
                "endpoint_id": e.endpoint_id,
                "kind": _agent_kind(e.agent.kind),
                "group_index": e.agent.group_index,
                "instance_index": e.agent.instance_index,
                "router_id": e.router_id,
                "port_id": e.port_id,
            }
            for e in attachment.endpoints
        ]
    return {
        "contract_version": 1,
        "revision_id": revision_id,
        "design_hash": _h(compilation.request.design_hash()),
        "topology_hash": _h(topology.topology_hash()),
        "attachment_hash": (_h(attachment.attachment_hash())
                            if attachment is not None else None),
        "family": _agent_kind(topology.family),
        "routers": [r.to_dict() for r in topology.routers],
        "channels": [c.to_dict() for c in topology.channels],
        "physical_links": [p.to_dict() for p in topology.physical_links],
        "endpoints": endpoints,
        "counts": {
            "routers": topology.router_count,
            "channels": topology.channel_count,
            "seats": topology.seat_capacity,
            "endpoints": (attachment.endpoint_count
                          if attachment is not None else 0),
        },
        "staged": True,
        "stopped_at_stage": staged.stopped_at_stage,
        "produced_stages": list(staged.produced_stages),
    }

def _agent_kind(value: Any) -> str:
    return getattr(value, "value", value)

def design_view(request: Any, compilation: Any = None) -> dict[str, Any]:
    """Project a CompileRequest (v2 or v3) to DesignView (contract v1).

Rationale: docs/decisions/modules/application.md
    """
    from veritx_dse.application.fabric_compiler import Compilation
    from veritx_dse.model.compile_model import (
        CompileRequest,
        CompileRequestV3,
    )
    if not is_any_compile_request(request):
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

_ARTIFACT_CHAIN: tuple[dict[str, Any], ...] = (
    {
        "artifact": "design", "label": "Design intent",
        "parents": (),
        "hash_key": "design_hash",
        "obligations": (),
    },
    {
        "artifact": "inventory_mapping", "label": "Inventory & mapping",
        "parents": ("design",),
        "hash_key": "mapping_hash",
        "obligations": ("MAPPING_VALID",),
    },
    {
        "artifact": "topology", "label": "Topology",
        "parents": ("inventory_mapping",),
        "hash_key": "topology_hash",
        "obligations": ("TOPOLOGY_CONNECTED",),
    },
    {
        "artifact": "attachment", "label": "Agent attachment",
        "parents": ("topology",),
        "hash_key": "attachment_hash",
        "obligations": ("ATTACHMENT_COMPLETE", "MAPPING_VALID"),
    },
    {
        "artifact": "router_route", "label": "Router route table",
        "parents": ("topology",),
        "hash_key": "router_route_hash",
        "obligations": ("ROUTE_COMPLETE", "ROUTE_LEGAL"),
    },
    {
        "artifact": "resolved_route", "label": "Resolved route",
        "parents": ("attachment", "router_route"),
        "hash_key": "resolved_route_hash",
        "obligations": ("ROUTE_COMPLETE",),
    },
    {
        "artifact": "vc_assignment", "label": "VC assignment",
        "parents": ("resolved_route",),
        "hash_key": "vc_assignment_hash",
        "obligations": ("VC_ASSIGNMENT_VALID", "DEADLOCK_FREE"),
    },
    {
        "artifact": "packet_format", "label": "Packet format",
        "parents": ("vc_assignment",),
        "hash_key": "packet_format_hash",
        "obligations": ("PACKET_FORMAT_VALID",),
    },
    {
        "artifact": "router_behavior", "label": "Router behavior",
        "parents": ("vc_assignment",),
        "hash_key": "router_behavior_hash",
        "obligations": ("DEADLOCK_FREE",),
    },
    {
        "artifact": "address_decode", "label": "Address decode",
        "parents": ("attachment",),
        "hash_key": "address_decode_hash",
        "obligations": ("ADDRESS_DECODE_VALID",),
    },
    {
        "artifact": "fabric", "label": "Fabric",
        "parents": ("topology", "attachment", "vc_assignment",
                    "packet_format", "router_behavior", "address_decode",
                    "router_route", "resolved_route"),
        "hash_key": "fabric_hash",
        "obligations": ("FABRIC_DAG_VALID",),
    },
    {
        "artifact": "resolved_fabric", "label": "Resolved fabric",
        "parents": ("fabric",),
        "hash_key": "resolved_fabric_hash",
        "obligations": ("FABRIC_DAG_VALID",),
    },
)

def artifact_chain_view(compilation: Any) -> dict[str, Any] | None:
    """Project a Compilation's canonical artifact DAG (contract v1).

Rationale: docs/decisions/modules/application.md
    """
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation):
        raise TypeError(
            f"artifact_chain_view takes a Compilation, got "
            f"{type(compilation).__name__}")
    if compilation.status != "COMPILED":
        return None
    hashes = {str(k): str(v)
              for k, v in compilation.bundle.root_hashes().items()}
    passed = {o.obligation for o in compilation.certificate.obligations
              if o.status == "PASS"}
    nodes = []
    for spec in _ARTIFACT_CHAIN:
        hash_value = hashes.get(spec["hash_key"])
        if hash_value is None:
            continue
        nodes.append({
            "artifact": spec["artifact"],
            "label": spec["label"],
            "parents": list(spec["parents"]),
            "hash": _h(hash_value),
            "proved_by": [o for o in spec["obligations"] if o in passed],
        })
    return {
        "contract_version": 1,
        "design_hash": _h(compilation.request.design_hash()),
        "certificate_id": compilation.certificate.certificate_id(),
        "nodes": nodes,
    }

def lowering_view(request: Any) -> dict[str, Any]:
    """Project a request's workload lowering (contract v1): the canonical
    WorkloadGraph -> LogicalMessageArtifactV2 chain, aggregated for human
    inspection.

Rationale: docs/decisions/modules/application.md
    """
    from veritx_dse.model.compile_model import (
        CompileRequest,
        CompileRequestV3,
    )
    if not is_any_compile_request(request):
        raise TypeError(
            f"lowering_view takes a CompileRequest, got "
            f"{type(request).__name__}")
    from veritx_dse.workload.intent_lowering import lower_compile_workload
    from veritx_dse.workload.messages import LogicalMessageArtifactV2

    lowered = lower_compile_workload(request)
    artifact = LogicalMessageArtifactV2(lowered.graph)
    identity = artifact.identity_dict()

    schedules = identity["schedules"]
    flows: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    steps: dict[str, int] = {}
    for m in identity["messages"]:
        key = (m["operation_id"], m["src_rank"], m["dst_rank"],
               m["traffic_class"])
        flow = flows.get(key)
        if flow is None:
            flow = {
                "operation_id": m["operation_id"],
                "src_rank": m["src_rank"],
                "dst_rank": m["dst_rank"],
                "traffic_class": m["traffic_class"],
                "message_count": 0,
                "payload_bytes": 0,
                "max_step": 0,
            }
            flows[key] = flow
        flow["message_count"] += 1
        flow["payload_bytes"] += m["payload_bytes"]
        flow["max_step"] = max(flow["max_step"], m["step"])
        steps[m["operation_id"]] = max(
            steps.get(m["operation_id"], 0), m["step"])

    graph = lowered.graph
    from veritx_dse.core.artifact import thaw
    operations: list[dict[str, Any]] = []
    memory_ops = 0
    memory_bytes = 0
    compute_ops = 0
    for op in getattr(graph, "operations", ()):
        detail = thaw(op.detail) if op.detail is not None else {}
        row: dict[str, Any] = {
            "operation_id": op.operation_id,
            "kind": op.kind,
            "deps": list(op.deps),
            "owner": op.owner,
            "phase": op.phase,
            "step": op.step,
            "label": op.label,
        }
        if op.kind == "COMPUTE":
            compute_ops += 1
            total = sum(int(detail.get(k) or 0)
                        for k in ("input_bytes", "weight_bytes",
                                  "output_bytes"))
            row["memory"] = {
                "input_bytes": detail.get("input_bytes"),
                "weight_bytes": detail.get("weight_bytes"),
                "output_bytes": detail.get("output_bytes"),
                "input_loc": detail.get("input_loc"),
                "weight_loc": detail.get("weight_loc"),
                "output_loc": detail.get("output_loc"),
                "duration_ns": detail.get("duration_ns"),
                "batch_tag": detail.get("batch_tag"),
            }
            row["memory_bytes"] = total
            if total:
                memory_ops += 1
            memory_bytes += total
        operations.append(row)

    compute = getattr(request, "compute", None)
    source = getattr(compute, "source", None)
    compute_source = source.to_dict() if source is not None else {
        "kind": "unspecified"}
    compute_source["specified"] = bool(
        getattr(source, "specified", False))

    return {
        "contract_version": 1,
        "workload_id": identity["workload_id"],
        "compute_source": compute_source,
        "message_artifact_id":
            artifact.message_artifact_id(),
        "participant_count": identity["participant_count"],
        "traffic_class": identity["traffic_class"],
        "collectives": schedules,
        "flows": sorted(
            flows.values(),
            key=lambda f: (f["operation_id"], f["src_rank"], f["dst_rank"])),
        "operations": operations,
        "memory_demand": {
            "operation_count": len(operations),
            "compute_count": compute_ops,
            "memory_demand_ops": memory_ops,
            "total_operand_bytes": memory_bytes,
            "has_memory_demand": memory_ops > 0,
        },
        "totals": {
            "collectives": len(schedules),
            "messages": len(identity["messages"]),
            "flows": len(flows),
            "payload_bytes": sum(
                s["aggregate_payload"] for s in schedules),
        },
    }

__all__ = ["compilation_view", "design_view", "artifact_chain_view",
           "topology_view", "lowering_view"]
