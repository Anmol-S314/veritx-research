"""Compile-bound Chisel topology preview inputs; never a final router implementation."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.compile_request_v4 import CompileRequestV4

LIMITATIONS = [
    "Topology preview only; neither emitter is a release implementation.",
    "CompiledGecPreview remains SINGLE-flit ready/valid with round-robin queues.",
    "CompiledGecCreditPreview exercises the compiled packet/credit router settings but uses a static route table, not a native adaptive selector.",
    "The credit preview has raw-flit endpoints; protocol adapters, ordering and CDC are not implemented.",
    "Physical multidrop electrical behavior and timing closure are not established.",
]


def source_profile_reason(request: CompileRequestV4) -> str | None:
    top = request.topology
    if getattr(top, "kind", None) != "gec" or getattr(getattr(top, "mode", None), "value", None) != "multidrop":
        return "Chipyard source export requires multidrop GEC."
    if top.concentration != 1:
        return "Chipyard GEC source export requires concentration=1."
    if not 2 <= top.grid_side_length <= 10:
        return "Chipyard GEC source export supports 4–100 routers."
    return None


def binary_contract(doc: dict) -> bytes:
    """Encode route/graph tables as data, not a giant JVM class initializer."""
    routers = len(doc["topology"]["routers"])
    values = [0x56474531, routers, doc["vc_assignment"]["vc_count"],
              doc["packet_format"]["flit_width_bits"],
              doc["router_behavior"]["input_buffer_depth_flits_per_vc"]]

    def vector(items):
        values.append(len(items))
        values.extend(items)

    vector(doc["endpoint_routers"])
    wires = doc["topology"]["shared_links"]
    values.append(len(wires))
    for wire in wires:
        values.extend((wire["src_router"], wire["width_bits"], wire["latency_cycles"]))
        vector(wire["taps"])
    values.append(len(doc["route_table"]))
    for row in doc["route_table"]:
        values.append(len(row))
        for wire, next_router, vc in row:
            values.extend((wire, next_router, vc))
    return struct.pack(">" + "i" * len(values), *values)


def export_contract(request_doc: dict, directory: Path, *, revision_id: str) -> dict:
    request = CompileRequestV4.from_dict(request_doc)
    reason = source_profile_reason(request)
    if reason:
        raise ValueError(reason)
    compiled = FabricCompiler().compile(request)
    if compiled.status != "COMPILED" or compiled.bundle is None:
        raise ValueError(compiled.error or "Compilation failed")
    b = compiled.bundle
    n = len(b.topology.routers)
    if not 4 <= n <= 100 or b.topology.channels:
        raise ValueError("Chipyard GEC preview supports 4–100 routers and shared wires only")
    if b.router_route.routing_class != "DOR_GEC_MECS":
        raise ValueError("Chipyard GEC preview requires deterministic DOR_GEC_MECS")
    wires = b.topology.shared_links
    if [w.shared_link_id for w in wires] != list(range(len(wires))):
        raise ValueError("GEC shared-wire IDs must be dense and match the compiled table")
    if sorted(r.router_id for r in b.topology.routers) != list(range(n)):
        raise ValueError("GEC router IDs must be dense and match the compiled table")
    behavior = b.router_behavior.to_dict()
    if (behavior.get("flow_control") != "credit"
            or behavior.get("buffer_organization") != "per_input_port_per_vc"
            or behavior.get("input_vc_packet_policy") != "one_packet_at_a_time"
            or behavior.get("vc_allocation_scope") != "packet"
            or behavior.get("vc_reuse_policy") != "wait_for_tail_credit"
            or behavior.get("input_speedup") != 1
            or behavior.get("internal_speedup") != 1
            or behavior.get("output_speedup") != 1
            or behavior.get("vc_allocator") != behavior.get("switch_allocator")
            or behavior.get("vc_allocator") not in {"islip", "round_robin"}):
        raise ValueError("Chipyard GEC credit preview cannot realize the compiled router behavior")
    delay_fields = ("route_compute_cycles", "vc_alloc_cycles", "switch_alloc_cycles",
                    "switch_traversal_cycles", "output_delay_cycles")
    if (any(type(behavior.get(name)) is not int or behavior[name] < 0 for name in delay_fields)
            or type(behavior.get("credit_return_latency_cycles")) is not int
            or behavior["credit_return_latency_cycles"] < 1
            or type(behavior.get("allocator_iterations")) is not int
            or behavior["allocator_iterations"] < 1
            or type(behavior.get("output_stage_depth_flits_per_vc")) is not int
            or behavior["output_stage_depth_flits_per_vc"] < 1
            or type(behavior.get("hold_switch_for_packet")) is not bool):
        raise ValueError("Chipyard GEC credit preview requires supported router timing/capacity fields")
    if any(w.width_bits != b.packet_format.flit_width_bits or w.latency_cycles < 1 for w in wires):
        raise ValueError("Chipyard GEC preview requires width-matched wires with positive latency")
    endpoints = sorted(b.attachment.endpoints, key=lambda e: e.endpoint_id)
    if [e.endpoint_id for e in endpoints] != list(range(len(endpoints))):
        raise ValueError("Endpoint IDs must be dense")
    tables = []
    bindings = {}
    for router in range(n):
        row = []
        for destination in range(n):
            if router == destination:
                row.append([-1, router, 0])
                continue
            decision = b.router_route.decisions[router, destination]
            if decision.resource.kind.value != "SHARED_LINK":
                raise ValueError("Nonlocal route does not select a shared resource")
            matches = [w for w in wires if w.src_router == router
                       and decision.tap is not None and 0 <= decision.tap < len(w.taps)
                       and w.taps[decision.tap] == decision.next_router]
            if len(matches) != 1:
                raise ValueError("Route resource/tap identity mismatch")
            wire = matches[0]
            prior = bindings.setdefault(decision.resource.resource_id, wire.shared_link_id)
            if prior != wire.shared_link_id:
                raise ValueError("Route resource aliases multiple physical wires")
            if not 0 <= decision.vc_partition < b.vc_assignment.vc_count:
                raise ValueError("Route VC is outside compiled assignment")
            row.append([wire.shared_link_id, decision.next_router, decision.vc_partition])
        tables.append(row)
    # A deterministic route must reach its destination without a cycle.
    for src in range(n):
        for dst in range(n):
            current, seen = src, set()
            while current != dst:
                if current in seen:
                    raise ValueError("Compiled route loops")
                seen.add(current)
                current = tables[current][dst][1]
    if set(bindings.values()) != {w.shared_link_id for w in wires} or len(bindings) != len(wires):
        raise ValueError("Route resources do not bind physical wires bijectively")
    fields = {f.name: [f.lsb, f.width] for f in b.packet_format.fields}
    for name in ("source_endpoint", "destination_endpoint", "vc_id", "flit_type"):
        if name not in fields:
            raise ValueError(f"Packet field missing: {name}")
    contract = {
        "schema": "veritx/chipyard-gec-preview/1", "revision_id": revision_id,
        "design_hash": request.design_hash(), "scope": "CHIPYARD_TOPOLOGY_PREVIEW",
        "final_implementation": False, "limitations": LIMITATIONS,
        "topology": b.topology.to_dict(), "vc_assignment": b.vc_assignment.to_dict(),
        "packet_format": b.packet_format.to_dict(), "router_behavior": b.router_behavior.to_dict(),
        "attachment": b.attachment.to_dict(), "route_table": tables,
        "route_resource_to_shared_link": bindings,
        "endpoint_routers": [e.router_id for e in endpoints],
        "request": request.to_dict(),
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    contract_hash = hashlib.sha256(encoded).hexdigest()
    binary = binary_contract(contract)
    binary_hash = hashlib.sha256(binary).hexdigest()
    source = ["package veritx.chipyard", "object SelectedGec {",
              f'  val contractHash = "{contract_hash}"',
              f'  private val data = GecContractData.load("/selected-gec.bin", "{binary_hash}")',
              "  val routers = data.routers",
              "  val vcs = data.vcs",
              "  val width = data.width",
              "  val depth = data.depth",
              f"  val sourceLsb = {fields['source_endpoint'][0]}",
              f"  val sourceWidth = {fields['source_endpoint'][1]}",
              f"  val destLsb = {fields['destination_endpoint'][0]}",
              f"  val destWidth = {fields['destination_endpoint'][1]}",
              f"  val vcLsb = {fields['vc_id'][0]}",
              f"  val vcWidth = {fields['vc_id'][1]}",
              f"  val typeLsb = {fields['flit_type'][0]}",
              f"  val typeWidth = {fields['flit_type'][1]}",
              f"  val creditReturnLatency = {behavior['credit_return_latency_cycles']}",
              f"  val allocatorIterations = {behavior['allocator_iterations']}",
              f"  val inputSpeedup = {behavior['input_speedup']}",
              f"  val internalSpeedup = {behavior['internal_speedup']}",
              f"  val outputSpeedup = {behavior['output_speedup']}",
              f"  val inputBufferOrganization = \"{behavior['buffer_organization']}\"",
              f"  val inputVcPacketPolicy = \"{behavior['input_vc_packet_policy']}\"",
              f"  val vcAllocationScope = \"{behavior['vc_allocation_scope']}\"",
              f"  val vcReusePolicy = \"{behavior['vc_reuse_policy']}\"",
              f"  val vcAllocator = \"{behavior['vc_allocator']}\"",
              f"  val switchAllocator = \"{behavior['switch_allocator']}\"",
              f"  val holdSwitchForPacket = {str(behavior['hold_switch_for_packet']).lower()}",
              f"  val routeComputeCycles = {behavior['route_compute_cycles']}",
              f"  val vcAllocCycles = {behavior['vc_alloc_cycles']}",
              f"  val switchAllocCycles = {behavior['switch_alloc_cycles']}",
              f"  val switchTraversalCycles = {behavior['switch_traversal_cycles']}",
              f"  val outputDelayCycles = {behavior['output_delay_cycles']}",
              f"  val outputStageDepth = {behavior['output_stage_depth_flits_per_vc']}",
              "  val endpoints = data.endpoints",
              "  val wires = data.wires.map(w => (w.src, w.taps))",
              "  val wireWidths = data.wires.map(_.width)",
              "  val wireLatencies = data.wires.map(_.latency)",
              "  val routes = data.routes", "}"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "contract.json").write_text(json.dumps(contract, indent=2) + "\n")
    (directory / "SelectedGec.scala").write_text("\n".join(source) + "\n")
    resources = directory / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "selected-gec.bin").write_bytes(binary)
    return {"contract_hash": contract_hash, "binary_hash": binary_hash,
            "routers": n, "vcs": b.vc_assignment.vc_count,
            "shared_wires": len(wires), "endpoints": len(endpoints)}

