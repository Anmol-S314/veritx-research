"""Bound data-movement experiment over the canonical compiler root.

Abstract store-and-forward, whole-message resource reservations; one flit per
network clock edge. NOT BookSim wormhole/credit behavior, DRAM timing, protocol
verification, power/reset execution, RTL CDC signoff, or physical timing.
Run: python -m veritx_dse.application.data_movement experiment.json
"""
from dataclasses import dataclass, field
from fractions import Fraction
import json
from pathlib import Path
import sys

from veritx_dse.core.artifact import FrozenMap, content_id, thaw, canonical_bytes, require_fields
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics, Refusal
from veritx_dse.application.execution_kernel import (
    ExecutionKernel, EventPriority, TransactionPhase)
from veritx_dse.model.routing_policy_artifact import RoutingContext
from veritx_dse.model.routing_relation import RoutingStateBinding
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.domain_intent import CrossingMechanism, PointerEncoding
from veritx_dse.model.physical_placement import PhysicalPlacement
from veritx_dse.model.transaction_intent import (
    ChildTransaction, TransactionKind, TransactionPolicy, OrderingMode,
    OutstandingTracker, split_transactions,
)
from veritx_dse.simulation.clocked_fifo import clocked_fifo_transfer, edge_at_or_after
from veritx_dse.workload.data_movement import DataMovementWorkload
from veritx_dse.workload.traffic import packetize_message, flitize_packet, payload_width_bits

PROFILE = "ABSTRACT_DATA_MOVEMENT_V1"

# Same-time ordering ranks for fault events, bound to the single authority:
# the reserved EventPriority ranks in application/execution_kernel.py. Phase
# transitions keep PHASE_COMPLETION (0); issue keeps ADMISSION (1); deadlines
# fire at TIMEOUT (3) so a response retiring on the same instant wins the tie,
# and retries schedule at RETRY (5) after every same-time completion.
TIMEOUT_PRIORITY = int(EventPriority.TIMEOUT)
RETRY_PRIORITY = int(EventPriority.RETRY)


@dataclass(frozen=True)
class FaultProfile:
    """Deterministic, authored loss for the fault-recovery reference envelope.

    Drops are declared per (parent, child sequence, attempt number, direction),
    so a run is reproducible without a random source. This models channel loss,
    an unacknowledged tail and a retry deadline in the EXISTING whole-message
    phase reservations only. It is not native transport reliability, not link
    hardware behaviour, and not a claim about real fabrics.
    """
    dropped_requests: FrozenMap
    dropped_responses: FrozenMap
    timeout_cycles: int
    max_attempts: int
    dropped_protocol_messages: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self):
        for name in ("timeout_cycles", "max_attempts"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise InvalidInput(f"fault {name} must be an exact positive int")
        if self.max_attempts > 16:
            raise UnsupportedSemantics("physical attempts per child are bounded at 16")
        for name in ("dropped_requests", "dropped_responses", "dropped_protocol_messages"):
            rows = getattr(self, name)
            if not isinstance(rows, FrozenMap):
                raise InvalidInput(f"fault {name} must be an immutable map")
            for key, attempts in rows.items():
                if not isinstance(key, str) or not isinstance(attempts, tuple) or not attempts:
                    raise InvalidInput(f"fault {name} must map identities to attempt tuples")
                if name == "dropped_protocol_messages":
                    parts = key.split(":", 2)
                    suffix = (parts[2][len("protocol-"):]
                              if len(parts) == 3 and parts[2].startswith("protocol-")
                              else "")
                    # Generated ordinals are canonical positive decimals; bound their width.
                    valid_suffix = (1 <= len(suffix) <= 9
                                    and suffix[0] in "123456789"
                                    and all(character in "0123456789"
                                            for character in suffix))
                    valid_key = (len(parts) == 3 and bool(parts[0])
                                 and parts[1].isdigit() and valid_suffix)
                else:
                    parts = key.split(":", 1)
                    valid_key = len(parts) == 2 and bool(parts[0]) and parts[1].isdigit()
                if not valid_key:
                    raise InvalidInput(
                        "fault key must be '<operation_id>:<sequence>' or "
                        "'<operation_id>:<sequence>:protocol-N'")
                if any(type(a) is not int or a < 1 or a > self.max_attempts for a in attempts):
                    raise InvalidInput("fault drop attempts must be within max_attempts")

    def to_dict(self):
        result = {"dropped_requests": {k: list(v) for k, v in self.dropped_requests.items()},
                  "dropped_responses": {k: list(v) for k, v in self.dropped_responses.items()},
                  "timeout_cycles": self.timeout_cycles, "max_attempts": self.max_attempts}
        if self.dropped_protocol_messages:
            result["dropped_protocol_messages"] = {
                k: list(v) for k, v in self.dropped_protocol_messages.items()}
        return result

    @classmethod
    def from_dict(cls, doc):
        if not isinstance(doc, dict):
            raise InvalidInput("fault profile must be an object")
        required = {"dropped_requests", "dropped_responses", "timeout_cycles", "max_attempts"}
        require_fields(doc, required, "fault profile")
        if set(doc) - required - {"dropped_protocol_messages"}:
            raise InvalidInput("fault profile has unknown fields")
        maps = []
        for name in ("dropped_requests", "dropped_responses", "dropped_protocol_messages"):
            value = doc.get(name, {})
            maps.append(value if isinstance(value, FrozenMap) else FrozenMap(value))
        return cls(*maps[:2], doc["timeout_cycles"], doc["max_attempts"], maps[2])


class AccessDenied(Refusal):
    code = "ACCESS_DENIED"

    def __init__(self, message, authorization):
        super().__init__(message)
        self.authorization = FrozenMap(authorization)


def refusal_document(exc):
    doc = {"status": "REFUSED", "profile": PROFILE, "reason": str(exc)}
    if isinstance(exc, AccessDenied):
        doc.update({"code": exc.code, "authorization": thaw(exc.authorization)})
    return doc


def ratio(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


@dataclass(frozen=True)
class DataMovementEvidence:
    data: FrozenMap

    def artifact_id(self):
        return content_id("veritx/DataMovementEvidence/v1", self.data)

    def to_dict(self):
        return {**thaw(self.data), "artifact_id": self.artifact_id()}

    def revalidate(self, compilation, workload, placement, *, _faults=None):
        expected = execute_data_movement(compilation, workload, placement, _faults=_faults)
        if self != expected:
            raise EvidenceInvalid("data-movement evidence differs from parent-recomputed execution")

    @classmethod
    def from_dict(cls, doc, *, compilation, workload, placement, _faults=None):
        expected = execute_data_movement(compilation, workload, placement, _faults=_faults)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("stored data-movement evidence differs from parent-recomputed execution")
        return expected


def execute_data_movement(compilation, workload, placement, *, _runtime=None,
                          _faults=None, _kernel=None):
    """Execute an explicit V5 workload; never bypass the generic V5 refusal."""
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation) or compilation.status != "COMPILED":
        raise InvalidInput("data movement requires a successful Compilation")
    root = compilation.compiled_system
    root.revalidate()
    request, bundle = root.request, root.fabric
    if not isinstance(request, CompileRequestV5) or root.execution_contract is None:
        raise UnsupportedSemantics("explicit V5 transaction policies must be compiled first")
    if not isinstance(workload, DataMovementWorkload) or workload.design_hash != request.design_hash():
        raise EvidenceInvalid("data-movement workload does not bind to the V5 design")
    if not isinstance(placement, PhysicalPlacement):
        raise InvalidInput("explicit physical placement is required")
    placement.validate_against(root.resource_graph)
    multi_plane = compilation.multi_plane_vc
    control_plane = compilation.control_plane
    if (root.adaptive is not None or root.routing_policy is None
            or any(r.ref.is_shared for r in root.resource_graph.resources)
            or any(len(rule.actions) != 1 for rule in root.routing_policy.rules)
            or tuple(d.name for d in root.routing_policy.state_domains) != ("class",)):
        raise UnsupportedSemantics("abstract data movement supports deterministic P2P routing only")
    if (root.control_plane is not None) != (multi_plane is not None):
        raise UnsupportedSemantics(
            "multi-plane execution requires a compiled control plane and its "
            "traffic-class subnet binding")
    if multi_plane is not None:
        if (control_plane is None or root.control_plane is None
                or control_plane.content_hash() != root.control_plane.content_hash()
                or control_plane.routing != "xy" or control_plane.subnet != 1
                or multi_plane.subnets() != (0, 1)):
            raise UnsupportedSemantics(
                "reference multi-plane execution supports only the compiled "
                "Plane-D/Plane-C plain-XY binding")
    if (request.sideband_interfaces or request.sideband_connections
            or request.power_domains or request.reset_channels):
        if _runtime is None or not getattr(_runtime, "power_policies", None):
            raise UnsupportedSemantics(
                "power, reset and sideband execution require an explicit coupled "
                "DomainPowerPolicy profile; plain data movement supports none")
    clocks = {d.id: d.frequency_hz for d in root.clock_domains.domains} if root.clock_domains else {}
    if workload.network_clock not in clocks:
        raise InvalidInput("network clock is undeclared")
    endpoints = {e.endpoint_id: e for e in bundle.attachment.endpoints}
    endpoint_contract = {row["endpoint_id"]: row for row in root.execution_contract.endpoints}
    policies = {eid: TransactionPolicy.from_dict(thaw(row["transaction_policy"]))
                for eid, row in endpoint_contract.items() if row["transaction_policy"] is not None}
    pf = bundle.packet_format
    channels = {r.ref.resource_id: r for r in root.resource_graph.resources}
    route_rules = {r.context: r.actions[0] for r in root.routing_policy.rules}
    class_vcs = dict(bundle.vc_assignment.traffic_class_to_vcs)
    vc_class = dict(bundle.vc_assignment.vc_to_routing_class)
    xy_channel_by_edge = {}
    if multi_plane is not None:
        from veritx_dse.model.resource_graph import resource_graph_from_topology
        plane_c_graph = resource_graph_from_topology(
            bundle.topology, plane="c")
        if plane_c_graph.topology_hash != root.resource_graph.topology_hash:
            raise EvidenceInvalid(
                "Plane-C resource graph differs from the compiled topology")
        coordinates = {router.router_id: router.coordinates
                       for router in bundle.topology.routers}
        if (len(coordinates) != control_plane.k * control_plane.k
                or any(len(xy) != 2 for xy in coordinates.values())
                or len(set(coordinates.values())) != len(coordinates)):
            raise UnsupportedSemantics(
                "Plane-C execution requires a square, uniquely addressed 2-D mesh")
        for channel in plane_c_graph.resources:
            if channel.ref.is_shared:
                raise UnsupportedSemantics(
                    "Plane-C XY execution refuses shared-link routing")
            edge = (channel.source, channel.destinations[0])
            if edge in xy_channel_by_edge:
                raise UnsupportedSemantics(
                    "Plane-C XY execution refuses parallel or ambiguous links")
            xy_channel_by_edge[edge] = channel.ref.resource_id
    crossings = {}
    for c in root.execution_contract.crossings:
        key = (c.src_clock, c.dst_clock)
        if key in crossings:
            raise InvalidInput("ambiguous crossing for a directed clock pair")
        crossings[key] = c
    # Validate every declared mechanism; unused unsupported intent is not dropped.
    for c in crossings.values():
        if c.mechanism is not CrossingMechanism.ASYNC_FIFO:
            raise UnsupportedSemantics("data movement requires resolved ASYNC_FIFO crossings")
        if c.async_fifo.pointer_encoding is not PointerEncoding.GRAY:
            raise UnsupportedSemantics("two-clock execution supports GRAY pointers only")
        if c.async_fifo.write_width != pf.flit_width_bits or c.async_fifo.read_width != pf.flit_width_bits:
            raise UnsupportedSemantics("FIFO width must equal the compiled flit width; no width conversion model")

    def endpoint_clock(eid):
        if eid not in endpoints:
            raise InvalidInput(f"unknown endpoint {eid}")
        name = endpoint_contract[eid]["transaction_clock_domain"]
        if name not in clocks:
            raise InvalidInput(f"endpoint {eid} has no declared executable clock domain")
        return name

    def endpoint_fabric_clock(eid):
        if eid not in endpoints:
            raise InvalidInput(f"unknown endpoint {eid}")
        name = endpoint_contract[eid]["fabric_clock_domain"]
        if name not in clocks:
            raise InvalidInput(f"endpoint {eid} has no declared executable fabric clock")
        if endpoints[eid].interface.clock_domain != name:
            raise EvidenceInvalid(
                f"endpoint {eid} fabric clock differs from its compiled interface clock")
        return name

    for endpoint_id in endpoints:
        endpoint_clock(endpoint_id)
        endpoint_fabric_clock(endpoint_id)

    def path(src, dst, cls):
        if cls not in class_vcs:
            raise InvalidInput(f"undeclared traffic class {cls}")
        subnet = multi_plane.subnet_of(cls) if multi_plane is not None else 0
        router, target = endpoints[src].router_id, endpoints[dst].router_id
        hops, seen = [], set()
        while router != target:
            if router in seen:
                raise EvidenceInvalid("compiled route contains a cycle")
            seen.add(router)
            if subnet == 1:
                x, y = coordinates[router]
                tx, ty = coordinates[target]
                if x != tx:
                    next_xy = (x + (1 if tx > x else -1), y)
                else:
                    next_xy = (x, y + (1 if ty > y else -1))
                next_router = next((rid for rid, xy in coordinates.items()
                                    if xy == next_xy), None)
                if next_router is None:
                    raise UnsupportedSemantics(
                        "Plane-C XY route crosses a missing mesh coordinate")
                try:
                    channel_id = xy_channel_by_edge[(router, next_router)]
                except KeyError:
                    raise UnsupportedSemantics(
                        "Plane-C XY route lacks an authored directed link") from None
                hops.append((channel_id, subnet))
                router = next_router
            else:
                routing_classes = {vc_class[v] for v in class_vcs[cls]}
                if len(routing_classes) != 1:
                    raise UnsupportedSemantics(
                        "a traffic class must resolve to one routing class")
                rc = next(iter(routing_classes))
                context = RoutingContext(
                    router, target, (RoutingStateBinding("class", rc),))
                action = route_rules[context]
                if action.eject:
                    raise EvidenceInvalid(
                        "route ejects before reaching the target router")
                hops.append((action.resource.resource_id, subnet))
                router = action.next_router
        return tuple(hops)

    def interface_phases(eid, direction, flits):
        transaction_clock = endpoint_clock(eid)
        fabric_clock = endpoint_fabric_clock(eid)
        network_clock = workload.network_clock
        clock_path = ([transaction_clock, fabric_clock, network_clock]
                      if direction == "out"
                      else [network_clock, fabric_clock, transaction_clock])
        compact = [clock_path[0]]
        for clock in clock_path[1:]:
            if clock != compact[-1]:
                compact.append(clock)
        if len(compact) == 1:
            compact.append(compact[0])
        phases = []
        for source_clock, destination_clock in zip(compact, compact[1:]):
            if (source_clock != destination_clock
                    and (source_clock, destination_clock) not in crossings):
                raise UnsupportedSemantics(
                    f"missing explicit crossing {source_clock}->{destination_clock} "
                    f"at endpoint {eid} {direction} interface")
            phases.append(("interface", eid, direction, source_clock,
                           destination_clock, flits))
        return phases

    def wire_phases(src, dst, count, cls):
        packets = packetize_message(count * 8, pf)
        flits = sum(flitize_packet(bits, pf)[0] for bits in packets)
        phases = interface_phases(src, "out", flits)
        for cid, subnet in path(src, dst, cls):
            phases.append(("channel", cid, flits, cls, subnet)
                          if multi_plane is not None else
                          ("channel", cid, flits, cls))
        phases.extend(interface_phases(dst, "in", flits))
        return phases, flits, len(packets)

    pending, operation_children, deps, trackers = [], {}, {}, {}
    authorizations = []
    previous = []
    if len(workload.operations) > 10_000:
        raise UnsupportedSemantics("abstract data movement supports <=10k operations")
    demand_bits = expected_children = 0
    total_flits = total_packets = total_payload = 0
    plane_route_flits = {subnet: 0 for subnet in multi_plane.subnets()} if multi_plane else {}
    plane_link_flits = {subnet: 0 for subnet in multi_plane.subnets()} if multi_plane else {}
    planned_plane_link_flits = {subnet: 0 for subnet in multi_plane.subnets()} if multi_plane else {}
    for op in workload.operations:
        endpoint_clock(op.initiator)
        dc = endpoint_clock(op.target)
        policy = policies.get(op.initiator)
        if policy is None or policy.outstanding is None or policy.ordering is None:
            raise UnsupportedSemantics("each initiator must declare outstanding and ordering policies")
        if policy.reordering is not None and policy.reordering.enabled:
            raise UnsupportedSemantics("reorder-window execution is not modeled")
        if op.address + op.payload_bytes > 1 << endpoints[op.target].interface.address_width_bits:
            raise InvalidInput("transaction address range exceeds the target address width")
        if root.access_system is not None:
            if op.address_space is None:
                raise InvalidInput(f"operation {op.operation_id!r} must declare address_space for access enforcement")
            path(op.initiator, op.target, op.traffic_class)
            path(op.target, op.initiator,
                 op.response_traffic_class or op.traffic_class)
            spans = root.access_system.range_decisions(
                operation=op.kind.value.lower(), initiator=f"group:{endpoints[op.initiator].agent.group_index}",
                target=f"group:{endpoints[op.target].agent.group_index}", address=op.address,
                byte_length=op.payload_bytes, address_space=op.address_space,
                endpoint_exists=True, route_exists=True, observed=False)
            authorization = {
                "operation_id": op.operation_id, "kind": op.kind.value,
                "initiator": op.initiator, "target": op.target, "address_space": op.address_space.value,
                "policy_hash": root.access_system.policy_hash,
                "spans": [{"address_start": start, "address_end": stop, "decision": decision.to_dict()}
                          for start, stop, decision in spans]}
            denied = next((d for _a, _b, d in spans if d.permitted is not True), None)
            if denied is not None:
                raise AccessDenied(f"operation {op.operation_id!r} denied: {denied.reason}", {
                    **authorization, "design_hash": request.design_hash(), "system_hash": root.system_hash(),
                    "workload_id": workload.workload_id(), "issued_children": 0})
            authorizations.append(authorization)
        trackers.setdefault(op.initiator, OutstandingTracker(policy.outstanding))
        needed = set(op.deps)
        for older, old_policy in previous:
            same_domain = (older.initiator == op.initiator and
                           old_policy.ordering.ordering_domain == policy.ordering.ordering_domain)
            if not same_domain:
                continue
            if (older.target == op.target and policy.ordering.mode is not OrderingMode.STRONG
                    and policy.ordering.enforced_hazards
                    and (older.address_space is None) != (op.address_space is None)):
                raise UnsupportedSemantics("hazard ordering cannot mix declared and undeclared address spaces")
            overlap = (older.target == op.target and older.address_space is op.address_space
                       and older.address < op.address + op.payload_bytes
                       and op.address < older.address + older.payload_bytes)
            hazard = ("RAW" if older.kind is TransactionKind.WRITE and op.kind is TransactionKind.READ else
                      "WAR" if older.kind is TransactionKind.READ and op.kind is TransactionKind.WRITE else
                      "WAW" if older.kind is op.kind is TransactionKind.WRITE else None)
            if policy.ordering.mode is OrderingMode.STRONG or (overlap and hazard in policy.ordering.enforced_hazards):
                needed.add(older.operation_id)
        previous.append((op, policy))
        deps[op.operation_id] = needed
        count = op.payload_bytes // policy.splitting.boundary_bytes if policy.splitting else 1
        expected_children += count
        demand_bits += 8 * (op.payload_bytes + count * op.control_bytes)
        if expected_children > 10_000 or demand_bits > 1_000_000 * payload_width_bits(pf):
            raise UnsupportedSemantics("abstract data-movement envelope: <=10k children and <=1M flits")
        children = (split_transactions(parent_id=op.operation_id, address_base=op.address,
                    payload_bytes=op.payload_bytes, splitting=policy.splitting,
                    ordering_domain=policy.ordering.ordering_domain, traffic_class=op.traffic_class)
                    if policy.splitting is not None else
                    (ChildTransaction(0, op.address, op.address + op.payload_bytes, op.payload_bytes,
                                      op.operation_id, policy.ordering.ordering_domain, op.traffic_class, True),))
        operation_children[op.operation_id] = len(children)
        for child in children:
            req_bytes = child.byte_length if op.kind is TransactionKind.WRITE else op.control_bytes
            rsp_bytes = child.byte_length if op.kind is TransactionKind.READ else op.control_bytes
            response_class = op.response_traffic_class or op.traffic_class
            outgoing, rf, rp = wire_phases(op.initiator, op.target, req_bytes, op.traffic_class)
            incoming, sf, sp = wire_phases(op.target, op.initiator, rsp_bytes, response_class)
            if multi_plane is not None:
                plane_route_flits[multi_plane.subnet_of(op.traffic_class)] += rf
                plane_route_flits[multi_plane.subnet_of(response_class)] += sf
                for subnet in multi_plane.subnets():
                    planned_plane_link_flits[subnet] += sum(
                        phase[2] for phase in outgoing + incoming
                        if phase[0] == "channel" and phase[4] == subnet)
            total_flits += rf + sf
            total_packets += rp + sp
            total_payload += child.byte_length
            pending.append((op, child, outgoing + [("service", op.target, dc, op.service_cycles)] + incoming))
    if len(pending) > 10_000 or total_flits > 1_000_000:
        raise UnsupportedSemantics("abstract data-movement envelope: <=10k children and <=1M flits")

    # Event order: completions/phase arrivals before issue on simultaneous
    # edges — the full named contract (PHASE_COMPLETION=0, ADMISSION=1,
    # STATE_TRANSITION=2, TIMEOUT=3, CANCELLATION=4, RETRY=5,
    # FAULT_INJECTION=6) lives in execution_kernel.EventPriority. The kernel
    # also owns resource lanes and transaction identities for this run.
    if _kernel is not None and not isinstance(_kernel, ExecutionKernel):
        raise InvalidInput("_kernel must be an ExecutionKernel")
    kernel = _kernel if _kernel is not None else ExecutionKernel()
    events, scheduled_issue, resources = kernel.queue.events, {}, kernel.resources
    records, completed_ops = [], set()
    peak_live = {eid: 0 for eid in trackers}
    next_issue = {eid: Fraction(0) for eid in trackers}
    push = kernel.queue.push

    def wake(eid, time):
        period = Fraction(1, clocks[endpoint_clock(eid)])
        time = edge_at_or_after(max(time, next_issue[eid]), period)
        if eid not in scheduled_issue or time < scheduled_issue[eid]:
            scheduled_issue[eid] = time
            push(time, EventPriority.ADMISSION, ("issue", eid))

    if _runtime is not None:
        _runtime.bind(deps=deps, push=push, wake=wake, trackers=trackers, lane_free=resources)
    for eid in trackers:
        wake(eid, Fraction(0))
    if _faults is not None and not isinstance(_faults, FaultProfile):
        raise InvalidInput("fault recovery requires an explicit FaultProfile")
    def _retry(op, record, now, phases, reason):
        """Automatic bounded retry: one more physical attempt, same identity."""
        attempt = record["attempt"]
        record["attempt_log"].append({"event": reason, "attempt": attempt, "time_s": ratio(now)})
        if attempt >= _faults.max_attempts:
            kernel.identities.transition(
                f'{op.operation_id}#{record["child"]["sequence"]}',
                TransactionPhase.FAILED)
            raise EvidenceInvalid(
                f'child {op.operation_id}:{record["child"]["sequence"]} sealed after '
                f'{attempt} physical attempts ({reason})')
        # A request retry re-runs the request flight; a response retry resumes
        # after the service phase so memory is never mutated or committed twice.
        start = 0 if not record.get("service_done") else record["service_phase"] + 1
        record["attempt"] = attempt + 1
        kernel.identities.repeat(f'{op.operation_id}#{record["child"]["sequence"]}')
        record["attempt_log"].append({"event": "attempt_retry", "attempt": record["attempt"],
                                      "time_s": ratio(now), "resume_phase": start})
        if record.get("service_done"):
            # Each response flight gets its own bounded deadline. The original
            # service-commit path arms attempt 1; retries resume after service.
            push(now + _faults.timeout_cycles * Fraction(1, clocks[workload.network_clock]),
                 TIMEOUT_PRIORITY, ("deadline", op, phases, start, record, record["attempt"]))
        push(now, RETRY_PRIORITY, ("phase", op, phases, start, record, record["attempt"]))

    phase_records, fifo_writes, fifo_reads = [], 0, 0
    routed_flit_um = Fraction(0)
    protocol_control_bytes = 0
    while events:
        if _runtime is not None and _runtime.finished:
            break
        queued_event = kernel.queue.pop()
        now, _, _, event = queued_event
        if _runtime is not None:
            if now > _runtime.horizon:
                kernel.queue.requeue(queued_event)
                break
            _runtime.now = now
            if event[0] == "runtime":
                _runtime.handle(event[1], now)
                continue
        if event[0] == "issue":
            eid = event[1]
            if scheduled_issue.get(eid) != now:
                continue
            del scheduled_issue[eid]
            candidate = next((i for i, (op, _c, _p) in enumerate(pending)
                              if op.initiator == eid and deps[op.operation_id] <= completed_ops
                              and (_runtime is None or _runtime.ready(op.operation_id))), None)
            if candidate is None:
                continue
            op, child, phases = pending[candidate]
            tracker = trackers[eid]
            if not tracker.try_issue(op.kind):
                continue  # completion releases a credit and wakes issue
            pending.pop(candidate)
            peak_live[eid] = max(peak_live[eid], tracker.live_total)
            record = {"child": child.to_dict(), "kind": op.kind.value,
                      "initiator": eid, "target": op.target, "issued_s": ratio(now)}
            records.append(record)
            if _faults is not None:
                record.update({"attempt": 1, "attempt_log": [],
                               "service_done": False, "responded": False,
                               "service_phase": next(i for i, p in enumerate(phases) if p[0] == "service")})
            if _runtime is not None:
                kernel.identities.epoch = _runtime.epoch
                _runtime.issued(op, record, now, phases)
            identity = kernel.identities.issue(
                logical_transaction_id=f'{op.operation_id}#{record["child"]["sequence"]}',
                source=op.initiator, destination=op.target,
                operation=op.kind.value, dependency_ids=deps[op.operation_id])
            if _runtime is not None:
                record["state"] = identity.current_state
            push(now, EventPriority.PHASE_COMPLETION,
                 ("phase", op, phases, 0, record, record.get("attempt", 1)))
            next_issue[eid] = now + Fraction(1, clocks[endpoint_clock(eid)])
            wake(eid, next_issue[eid])
        else:
            _, op, phases, index, record, attempt_of_event = event
            identity_id = f'{op.operation_id}#{record["child"]["sequence"]}'
            if event[0] == "deadline":
                # A response deadline only fires while THIS attempt still lacks
                # a response; a superseded or already-retired attempt is ignored.
                if not record["responded"] and attempt_of_event == record["attempt"]:
                    _retry(op, record, now, phases, "response_timeout")
                continue
            if _faults is not None and attempt_of_event != record["attempt"]:
                # A superseded attempt's already-queued phases are void: the
                # retry owns the child. First response still wins.
                continue
            if _faults is None or not record.get("service_done", False):
                # MSI ownership changes commit only after all authored
                # post-service protocol messages (notably ownership grants)
                # have retired. Legacy transactions still commit immediately
                # after their service phase.
                response_phase = record.get("response_phase")
                commit_now = (index == response_phase if response_phase is not None
                              else bool(index and phases[index - 1][0] == "service"))
                if commit_now:
                    if _runtime is not None:
                        _runtime.commit(op, record, now)
                    identity = kernel.identities.transition(
                        identity_id, TransactionPhase.RESPONSE_INFLIGHT)
                    if _runtime is not None:
                        record["state"] = identity.current_state
                    if _faults is not None:
                        record["service_done"] = True
                        # Arm this attempt's response deadline exactly once.
                        push(now + _faults.timeout_cycles * Fraction(1, clocks[workload.network_clock]),
                             TIMEOUT_PRIORITY, ("deadline", op, phases, index, record, record["attempt"]))
            if _faults is not None:
                key = f'{op.operation_id}:{record["child"]["sequence"]}'
                attempt = record["attempt"]
                if index == record["service_phase"]:
                    if attempt in _faults.dropped_requests.get(key, ()):
                        _retry(op, record, now, phases, "request_dropped")
                        continue
                elif index == record.get("response_phase", record["service_phase"] + 1):
                    # The service phase has now run: memory committed exactly once.
                    if attempt in _faults.dropped_responses.get(key, ()):
                        _retry(op, record, now, phases, "response_dropped")
                        continue
            if index == len(phases):
                record["completed_s"] = ratio(now)
                identity = kernel.identities.retire(identity_id)
                if _runtime is not None:
                    record["state"] = identity.current_state
                if _faults is not None:
                    record["responded"] = True
                    record["attempt_log"].append({"event": "response_retired", "attempt": record["attempt"],
                                                  "time_s": ratio(now)})
                trackers[op.initiator].complete(op.kind)
                trackers[op.initiator].assert_invariants()
                operation_children[op.operation_id] -= 1
                if operation_children[op.operation_id] == 0:
                    completed_ops.add(op.operation_id)
                if _runtime is not None:
                    _runtime.responded(op, record, now, operation_children[op.operation_id] == 0)
                for eid in sorted(trackers):
                    wake(eid, now)
                continue
            phase = phases[index]
            if phase[0] == "protocol_request_arrived":
                _, fault_key = phase
                if (_faults is not None
                        and record["attempt"] in _faults.dropped_requests.get(fault_key, ())):
                    _retry(op, record, now, phases, "request_dropped")
                    continue
                push(now, EventPriority.PHASE_COMPLETION,
                     ("phase", op, phases, index + 1, record, attempt_of_event))
                continue
            if phase[0] == "protocol_message":
                _, message_id, fault_id, is_ack, message_bytes = phase
                protocol_control_bytes += message_bytes
                if (is_ack and _faults is not None
                        and fault_id in _faults.dropped_protocol_messages
                        and record["attempt"] in _faults.dropped_protocol_messages[fault_id]):
                    record["attempt_log"].append({
                        "event": "protocol_ack_dropped", "message_id": message_id,
                        "attempt": record["attempt"], "time_s": ratio(now)})
                    _retry(op, record, now, phases, "protocol_ack_dropped")
                    continue
                if _runtime is not None:
                    _runtime.protocol_message_completed(
                        record, message_id, record.get("attempt", 1), now)
                push(now, EventPriority.PHASE_COMPLETION,
                     ("phase", op, phases, index + 1, record, attempt_of_event))
                continue
            fifo = None
            if phase[0] == "interface":
                _, eid, direction, source_clock, dest_clock, words = phase
                crossing = crossings.get((source_clock, dest_clock))
                key = ("crossing", crossing.id) if crossing else ("interface", eid, direction)
                available = resources.free_at(key)
                resource_wait = max(Fraction(0), available - now)
                start = max(now, available)
                if crossing:
                    edge_alignment_wait = max(
                        edge_at_or_after(start, Fraction(1, clocks[clock])) - start
                        for clock in (source_clock, dest_clock))
                    fifo = clocked_fifo_transfer(config=crossing.async_fifo,
                        write_hz=clocks[source_clock], read_hz=clocks[dest_clock], words=words, start_s=start)
                    end, free = fifo.completed_s, fifo.reusable_s
                    fifo_writes += fifo.writes
                    fifo_reads += fifo.reads
                else:
                    period = Fraction(1, clocks[source_clock])
                    aligned_start = edge_at_or_after(start, period)
                    edge_alignment_wait = aligned_start - start
                    start = aligned_start
                    end = free = start + words * period
            elif phase[0] == "channel":
                if len(phase) == 5:
                    _, cid, words, traffic_class, subnet = phase
                    key = ("channel", subnet, cid)
                    plane_link_flits[subnet] += words
                else:
                    _, cid, words, traffic_class = phase
                    key = ("channel", cid)
                ch = channels[cid]
                period = Fraction(1, clocks[workload.network_clock])
                available = resources.free_at(key)
                resource_wait = max(Fraction(0), available - now)
                earliest_start = max(now, available)
                start = edge_at_or_after(earliest_start, period)
                edge_alignment_wait = start - earliest_start
                # Whole-message store-and-forward, not wormhole/VC flow control.
                cycles = (words * pf.flit_width_bits + ch.width_bits - 1) // ch.width_bits
                end = start + (cycles + ch.latency_cycles) * period
                free = end
            else:
                _, eid, clock, authored_cycles = phase
                key = ("service", eid)
                period = Fraction(1, clocks[clock])
                available = resources.free_at(key)
                resource_wait = max(Fraction(0), available - now)
                earliest_start = max(now, available)
                start = edge_at_or_after(earliest_start, period)
                edge_alignment_wait = start - earliest_start
                identity = kernel.identities.get(identity_id)
                if identity.current_state == TransactionPhase.REQUEST_INFLIGHT:
                    identity = kernel.identities.transition(
                        identity_id, TransactionPhase.MEMORY_QUEUED_OR_SERVICING)
                cycles = authored_cycles
                if _runtime is not None:
                    cycles = _runtime.service_cycles(op, record, authored_cycles)
                    if not record.get("protocol_phases_expanded"):
                        messages = _runtime.protocol_messages(op, record)
                        before, after = [], []
                        if _faults is not None and messages:
                            before.append(("protocol_request_arrived",
                                           f'{op.operation_id}:{record["child"]["sequence"]}'))
                        for message in messages:
                            message_phases, message_flits, message_packets = wire_phases(
                                message["source"], message["destination"],
                                message["payload_bytes"], message["traffic_class"])
                            marker = ("protocol_message", message["message_id"],
                                      f'{op.operation_id}:{record["child"]["sequence"]}:'
                                      f'{message["message_id"]}', message["acknowledgement"],
                                      message["payload_bytes"])
                            target = before if message["before_service"] else after
                            target.extend(message_phases)
                            target.append(marker)
                            total_flits += message_flits
                            total_packets += message_packets
                            if multi_plane is not None:
                                subnet = multi_plane.subnet_of(message["traffic_class"])
                                plane_route_flits[subnet] += message_flits
                                planned_plane_link_flits[subnet] += sum(
                                    p[2] for p in message_phases if p[0] == "channel")
                        if total_flits > 1_000_000:
                            raise UnsupportedSemantics(
                                "abstract data-movement envelope: <=1M flits including coherence traffic")
                        phases = (phases[:index] + before + [phase] + after
                                  + phases[index + 1:])
                        if before or after:
                            # Protocol-phase bookkeeping exists only when real
                            # protocol messages were inserted (MSI profile);
                            # feature-absent children keep their legacy bytes.
                            record["protocol_phases_expanded"] = True
                            record["service_phase"] = index + len(before)
                            record["response_phase"] = record["service_phase"] + 1 + len(after)
                            push(now, EventPriority.PHASE_COMPLETION,
                                 ("phase", op, phases, index, record, attempt_of_event))
                            continue
                end = free = start + cycles * period
                if _runtime is not None:
                    _runtime.service_accepted(op, record, now, start, end)
                    record["state"] = kernel.identities.get(identity_id).current_state
                    if "owner_cache_plan" in record:
                        record["owner_service_cycles"] = cycles
            resources.reserve(key, arrival=now, start=start, end=end,
                              free_at=free, owner=identity_id)
            kernel.identities.own(identity_id, key)
            entry = {"parent": op.operation_id, "sequence": record["child"]["sequence"],
                     "resource": list(key), "start_s": ratio(start), "completed_s": ratio(end),
                     "queued_s": ratio(start - now)}
            if multi_plane is not None:
                # Blocking/alignment evidence is bound into the compiled
                # multi-plane profile only: a single-plane run must keep the
                # exact evidence bytes it had before these fields existed.
                entry.update({"resource_wait_s": ratio(resource_wait),
                              "edge_alignment_wait_s": ratio(edge_alignment_wait)})
            if _runtime is not None:
                entry["reusable_s"] = ratio(free)
            if phase[0] == "service" and _runtime is not None:
                if "owner_service_cycles" in record:
                    entry["service_cycles"] = record["owner_service_cycles"]
                elif "msi_service_cycles" in record:
                    entry["service_cycles"] = record["msi_service_cycles"]
            if phase[0] == "interface":
                _, endpoint_id, direction, source_clock, destination_clock, words = phase
                if multi_plane is not None:
                    # Endpoint clock binding is multi-plane evidence (W2/W6
                    # two-rate proof); absent from single-plane evidence.
                    entry.update({"endpoint_id": endpoint_id, "direction": direction,
                                  "source_clock": source_clock,
                                  "destination_clock": destination_clock,
                                  "fabric_clock_domain": endpoint_fabric_clock(endpoint_id)})
            if phase[0] == "channel":
                length = placement.length_um(ch.source, ch.destinations[0])
                routed_flit_um += words * length
                entry.update({"flits": words, "length_um": ratio(length),
                              "traffic_class": traffic_class})
                if multi_plane is not None:
                    entry["subnet"] = subnet
            if fifo:
                entry.update({"writes": fifo.writes, "reads": fifo.reads,
                              "peak_occupancy": fifo.peak_occupancy, "blocked_write_cycles": fifo.blocked_write_cycles})
            phase_records.append(entry)
            push(end, EventPriority.PHASE_COMPLETION,
                 ("phase", op, phases, index + 1, record, record.get("attempt", 0)))
    if multi_plane is not None:
        observed_link_flits = {subnet: sum(
            row.get("flits", 0) for row in phase_records
            if row["resource"][:2] == ["channel", subnet])
            for subnet in multi_plane.subnets()}
        if observed_link_flits != plane_link_flits:
            raise EvidenceInvalid(
                "multi-plane per-plane channel ledger differs from reservations")
        if _faults is None and observed_link_flits != planned_plane_link_flits:
            raise EvidenceInvalid(
                "multi-plane planned and reserved per-plane link flits do not conserve")
    if _runtime is not None:
        evidence = _runtime.finish(pending=pending, events=events, children=records,
                                   phases=phase_records, completed_ops=completed_ops,
                                   peak_live=peak_live, authorizations=authorizations,
                                   total_payload=total_payload, total_flits=total_flits,
                                   fifo_writes=fifo_writes, fifo_reads=fifo_reads,
                                   protocol_control_bytes=protocol_control_bytes,
                                   plane_traffic=({
                                       str(subnet): {
                                           "routed_flits": plane_route_flits[subnet],
                                           "planned_link_flits": planned_plane_link_flits[subnet],
                                           "link_flits": plane_link_flits[subnet]}
                                       for subnet in multi_plane.subnets()}
                                       if multi_plane is not None else None))
        kernel.assert_invariants()
        return evidence
    if pending or len(completed_ops) != len(workload.operations):
        raise EvidenceInvalid("data-movement execution stalled before parent completion")
    if total_payload != sum(op.payload_bytes for op in workload.operations) or fifo_writes != fifo_reads:
        raise EvidenceInvalid("data-movement conservation failed")
    kernel.assert_invariants()
    wire_lengths = [{"channel_id": c.ref.resource_id,
                     "length_um": ratio(placement.length_um(c.source, c.destinations[0]))}
                    for c in root.resource_graph.resources]
    finish = max(Fraction(r["completed_s"]["numerator"], r["completed_s"]["denominator"]) for r in records)
    for authorization in authorizations:
        for span in authorization["spans"]:
            span["decision"]["observed"] = True
    return DataMovementEvidence(FrozenMap({
        "type": "veritx/DataMovementEvidence", "schema_version": 1, "profile": PROFILE,
        "design_hash": request.design_hash(), "system_hash": root.system_hash(),
        "workload_id": workload.workload_id(), "placement_id": placement.artifact_id(),
        "scope": {"timing": "ABSTRACT_STORE_AND_FORWARD_TWO_CLOCK_FIFO",
                  "physical": "AUTHORED_ROUTER_GEOMETRY_NOT_PPA", "signoff_verified": False,
                  "booksim_equivalent": False, "memory_contents_modeled": False,
                  "power_reset_execution": "NOT_MODELED",
                  **({"retry": "BOUNDED_FAULT_PROFILE_ATTEMPT_DEADLINES_AND_DEDUP"}
                     if _faults is not None else {}),
                  **({"plane_execution": "REFERENCE_CONCURRENT_PLANE_LANES"}
                     if multi_plane is not None else {}),
                  **({"access_authorization": "ABSTRACT_POLICY_ENFORCED_NOT_FIREWALL"}
                     if root.access_system is not None else {})},
        **({"multi_plane_binding_hash": multi_plane.content_hash()}
           if multi_plane is not None else {}),
        **({"fault_profile": _faults.to_dict()} if _faults is not None else {}),
        "summary": {"parents_completed": len(completed_ops), "children_completed": len(records),
                    "payload_bytes": total_payload, "packets": total_packets, "flits": total_flits,
                    "fifo_words_written": fifo_writes, "fifo_words_read": fifo_reads,
                    "completion_s": ratio(finish), "routed_flit_um": ratio(routed_flit_um),
                    "peak_outstanding": {str(e): n for e, n in peak_live.items()},
                    **({"plane_traffic": {
                        str(subnet): {"routed_flits": plane_route_flits[subnet],
                                      "planned_link_flits": planned_plane_link_flits[subnet],
                                      "link_flits": plane_link_flits[subnet]}
                        for subnet in multi_plane.subnets()}
                       } if multi_plane is not None else {})},
        "children": records, "phases": phase_records, "wire_lengths": wire_lengths,
        **({"authorizations": authorizations} if root.access_system is not None else {}),
    }))


def evaluate_experiment(doc):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    require_fields(doc, {"design", "workload", "placement"}, "data-movement experiment")
    if set(doc) != {"design", "workload", "placement"}:
        raise InvalidInput("experiment requires design, workload and placement")
    request = CompileRequestV5.from_dict(doc["design"])
    compilation = FabricCompiler().compile(request)
    return execute_data_movement(compilation, DataMovementWorkload.from_dict(doc["workload"]),
                                 PhysicalPlacement.from_dict(doc["placement"]))


def main(argv=None):
    from veritx_dse.core.errors import Refusal, SemanticError
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("usage: python -m veritx_dse.application.data_movement experiment.json")
    try:
        result = evaluate_experiment(json.loads(Path(argv[0]).read_text()))
    except (Refusal, SemanticError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps(refusal_document(exc)))
        raise SystemExit(1) from None
    print(json.dumps(result.to_dict(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
