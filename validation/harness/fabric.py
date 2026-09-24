"""Build the canonical machine + prepared input for an experiment.

This is the VERITX side of a differential experiment: it drives the
canonical compile -> workload -> projection path exactly as the product
does, and returns the prepared BookSim input plus the derived facts
(profile, packet/flit counts, canonical hop count) that the checks
compare against the authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .spec import ExperimentSpec, SpecError


@dataclass(frozen=True)
class BuiltExperiment:
    spec: ExperimentSpec
    bundle: Any
    parents: Any
    prepared: Any
    profile_id: str
    packets: int
    flits: int
    canonical_hops_avg: float | None


def _request_doc(spec: ExperimentSpec) -> dict[str, Any]:
    wl = spec.workload
    # The CompileRequest declares the traffic CLASS structure the fabric
    # must realize. The execution stimulus is the WorkloadGraph below.
    # For a p2p experiment the class representative is an allreduce of the
    # same payload; it never contributes packets to the executed trace.
    if wl.kind == "collective":
        class_kind = wl.collective_kind.lower()
    else:
        class_kind = "allreduce"
    return {
        "schema_version": 3,
        "compiler_semantics_version": 3,
        "workload": {
            "model_family": "dense_transformer",
            "model_name": f"validation-{spec.id.lower()}",
            "tp": spec.fabric.tp, "pp": 1, "ep": 1, "dp": 1,
            "serving_mode": "mixed",
            "collectives": [{
                "kind": class_kind, "dimension": "TP",
                "payload_bytes": wl.payload_bytes,
                "traffic_class": "tp_collective"}],
        },
        "requirements": [{
            "traffic_class": "tp_collective",
            "qos_class": "latency_critical",
            "latency_ceiling_cycles": 10 ** 12,
            "bandwidth_floor_gbps": None, "binding": True}],
        "agents": [{
            "kind": "compute_tile", "count": spec.fabric.compute_tiles,
            "data_width": 256, "addr_width": 64, "protocol": "AXI",
            "clock_domain": None, "power_domain": None}],
        "dependencies": [],
        "noc_config": {
            "topology_family": spec.fabric.topology_family,
            "radix": None, "concentration": spec.fabric.concentration,
            "arbitration": None, "rcu_enabled": None,
            "link_width": spec.fabric.link_width,
            "mcast_groups": None, "mcast_setup_cycles": None,
            "output_formats": ["json"], "obfuscation_level": 0},
        "address_map": {"ranges": []},
        "physical": {"clock_freq_mhz": 1000.0, "data_width": 256,
                     "num_power_domains": 1, "process_node_nm": 7},
    }


def _workload_graph(spec: ExperimentSpec, parallelism: Any) -> Any:
    from veritx_dse.workload.graph import (
        KIND_COLLECTIVE, KIND_COMPUTE, KIND_P2P, OperationNode, WorkloadGraph,
        collective_detail, compute_detail, p2p_detail,
    )
    wl = spec.workload
    participants = spec.fabric.compute_tiles
    ops = [OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                         detail=compute_detail(duration_ns=10000,
                                               participant_count=participants))]
    if wl.kind == "collective":
        ops.append(OperationNode(
            operation_id="c0", kind=KIND_COLLECTIVE, deps=("pre",),
            detail=collective_detail(
                collective_kind=wl.collective_kind,
                participants=tuple(range(participants)),
                payload_bytes=wl.payload_bytes,
                participant_count=participants)))
    else:
        if wl.src_rank is None or wl.dst_rank is None:
            raise SpecError("p2p experiment lost its endpoints")
        ops.append(OperationNode(
            operation_id="p0", kind=KIND_P2P, deps=("pre",),
            detail=p2p_detail(role="TRANSFER", src_rank=wl.src_rank,
                              dst_rank=wl.dst_rank,
                              payload_bytes=wl.payload_bytes,
                              participant_count=participants)))
    return WorkloadGraph(parallelism=parallelism,
                         participant_count=participants, operations=tuple(ops))


def build(spec: ExperimentSpec, *, request_doc: dict[str, Any] | None = None
          ) -> BuiltExperiment:
    from veritx_dse.application.compile import compile_bundle_v3
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionParents, prepare_booksim_input,
        select_booksim_profile,
    )
    from veritx_dse.model.compile_model import CompileRequestV3
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    from veritx_dse.workload.messages import LogicalMessageArtifactV2
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

    doc = request_doc if request_doc is not None else _request_doc(spec)
    request = CompileRequestV3.from_dict(doc)
    bundle = compile_bundle_v3(request)
    graph = _workload_graph(spec, bundle.inventory.parallelism)
    logical = LogicalMessageArtifactV2(graph=graph)
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    vc_resource = vc_resources_from_assignment(bundle.vc_assignment)
    parents = BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resource, vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=traffic)
    prepared = prepare_booksim_input(parents, seed=spec.seed)
    profile = select_booksim_profile(parents)

    packets = sum(len(m.packets) for m in traffic.traffic)
    flits = sum(p.flit_count for m in traffic.traffic for p in m.packets)
    hops = _canonical_hops_avg(prepared, packets)
    return BuiltExperiment(spec=spec, bundle=bundle, parents=parents,
                           prepared=prepared, profile_id=profile.profile_id,
                           packets=packets, flits=flits,
                           canonical_hops_avg=hops)


def _canonical_hops_avg(prepared: Any, packets: int) -> float | None:
    """Mean DOR hop count of the rendered trace, computed independently.

    The trace dialect is ``cyc src cl dst sz``. The hop count is the
    Manhattan distance between the two endpoint ids on the square mesh
    (endpoint i sits on router i; router id = y*k + x). This is arithmetic
    over the stimulus, not a read of any VERITX statistic.
    """
    text = prepared.trace_text
    rows = [line.split() for line in text.splitlines() if line]
    if not rows:
        return None
    endpoints = prepared.endpoint_count
    k = int(round(endpoints ** 0.5))
    if k * k != endpoints:
        return None
    total = 0
    for row in rows:
        src, dst = int(row[1]), int(row[3])
        if not (0 <= src < endpoints and 0 <= dst < endpoints):
            return None
        sx, sy = src % k, src // k
        dx, dy = dst % k, dst // k
        total += abs(sx - dx) + abs(sy - dy)
    return total / len(rows)
