"""Bound data-movement experiment over the canonical compiler root.

Abstract store-and-forward, whole-message resource reservations; one flit per
network clock edge. NOT BookSim wormhole/credit behavior, DRAM timing, protocol
verification, power/reset execution, RTL CDC signoff, or physical timing.
Run: python -m veritx_dse.application.data_movement experiment.json
"""
from dataclasses import dataclass
from fractions import Fraction
import heapq
import json
from pathlib import Path
import sys

from veritx_dse.core.artifact import FrozenMap, content_id, thaw, canonical_bytes, require_fields
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics, Refusal
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

    def __post_init__(self):
        for name in ("timeout_cycles", "max_attempts"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise InvalidInput(f"fault {name} must be an exact positive int")
        if self.max_attempts > 16:
            raise UnsupportedSemantics("physical attempts per child are bounded at 16")
        for name in ("dropped_requests", "dropped_responses"):
            rows = getattr(self, name)
            if not isinstance(rows, FrozenMap):
                raise InvalidInput(f"fault {name} must be an immutable map")
            for key, attempts in rows.items():
                if not isinstance(key, str) or key.count(":") != 1:
                    raise InvalidInput("fault drop key must be '<operation_id>:<sequence>'")
                op, sequence = key.split(":", 1)
                if not op or not sequence.isdigit() or not isinstance(attempts, tuple) or not attempts:
                    raise InvalidInput("fault drop key must be '<operation_id>:<sequence>'")
                if any(type(a) is not int or a < 1 or a > self.max_attempts for a in attempts):
                    raise InvalidInput("fault drop attempts must be within max_attempts")

    def to_dict(self):
        return {"dropped_requests": {k: list(v) for k, v in self.dropped_requests.items()},
                "dropped_responses": {k: list(v) for k, v in self.dropped_responses.items()},
                "timeout_cycles": self.timeout_cycles, "max_attempts": self.max_attempts}

    @classmethod
    def from_dict(cls, doc):
        require_fields(doc, cls.__dataclass_fields__, "fault profile")
        if set(doc) != set(cls.__dataclass_fields__):
            raise InvalidInput("fault profile has unknown fields")
        return cls(*(doc[name] if isinstance(doc[name], FrozenMap) else FrozenMap(doc[name])
                     for name in ("dropped_requests", "dropped_responses")),
                   doc["timeout_cycles"], doc["max_attempts"])


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

    def revalidate(self, compilation, workload, placement):
        expected = execute_data_movement(compilation, workload, placement)
        if self != expected:
            raise EvidenceInvalid("data-movement evidence differs from parent-recomputed execution")

    @classmethod
    def from_dict(cls, doc, *, compilation, workload, placement):
        expected = execute_data_movement(compilation, workload, placement)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("stored data-movement evidence differs from parent-recomputed execution")
        return expected


def execute_data_movement(compilation, workload, placement, *, _runtime=None, _faults=None):
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
    if (root.adaptive is not None or root.control_plane is not None or root.routing_policy is None
            or any(r.ref.is_shared for r in root.resource_graph.resources)
            or any(len(rule.actions) != 1 for rule in root.routing_policy.rules)
            or tuple(d.name for d in root.routing_policy.state_domains) != ("class",)):
        raise UnsupportedSemantics("abstract data movement supports deterministic single-plane P2P routing only")
    if request.sideband_interfaces or request.sideband_connections:
        raise UnsupportedSemantics("sideband execution is outside this experiment envelope")
    clocks = {d.id: d.frequency_hz for d in root.clock_domains.domains} if root.clock_domains else {}
    if workload.network_clock not in clocks:
        raise InvalidInput("network clock is undeclared")
    endpoints = {e.endpoint_id: e for e in bundle.attachment.endpoints}
    endpoint_contract = {row["endpoint_id"]: row for row in root.execution_contract.endpoints}
    policies = {eid: TransactionPolicy.from_dict(thaw(row["transaction_policy"]))
                for eid, row in endpoint_contract.items() if row["transaction_policy"] is not None}
    if any(e.interface.clock_domain != workload.network_clock for e in endpoints.values()):
        raise UnsupportedSemantics("all fabric attachments must declare the experiment network clock")
    pf = bundle.packet_format
    channels = {r.ref.resource_id: r for r in root.resource_graph.resources}
    route_rules = {r.context: r.actions[0] for r in root.routing_policy.rules}
    class_vcs = dict(bundle.vc_assignment.traffic_class_to_vcs)
    vc_class = dict(bundle.vc_assignment.vc_to_routing_class)
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

    def path(src, dst, cls):
        if cls not in class_vcs:
            raise InvalidInput(f"undeclared traffic class {cls}")
        routing_classes = {vc_class[v] for v in class_vcs[cls]}
        if len(routing_classes) != 1:
            raise UnsupportedSemantics("a traffic class must resolve to one routing class")
        rc = next(iter(routing_classes))
        router, target = endpoints[src].router_id, endpoints[dst].router_id
        hops, seen = [], set()
        while router != target:
            if router in seen:
                raise EvidenceInvalid("compiled route contains a cycle")
            seen.add(router)
            context = RoutingContext(router, target, (RoutingStateBinding("class", rc),))
            action = route_rules[context]
            if action.eject:
                raise EvidenceInvalid("route ejects before reaching the target router")
            hops.append(action.resource.resource_id)
            router = action.next_router
        return tuple(hops)

    def wire_phases(src, dst, count, cls):
        sc, dc, nc = endpoint_clock(src), endpoint_clock(dst), workload.network_clock
        for pair in ((sc, nc), (nc, dc)):
            if pair[0] != pair[1] and pair not in crossings:
                raise UnsupportedSemantics(f"missing explicit crossing {pair[0]}->{pair[1]}")
        packets = packetize_message(count * 8, pf)
        flits = sum(flitize_packet(bits, pf)[0] for bits in packets)
        phases = [("interface", src, "out", sc, nc, flits)]
        phases.extend(("channel", cid, flits, cls) for cid in path(src, dst, cls))
        phases.append(("interface", dst, "in", nc, dc, flits))
        return phases, flits, len(packets)

    pending, operation_children, deps, trackers = [], {}, {}, {}
    authorizations = []
    previous = []
    if len(workload.operations) > 10_000:
        raise UnsupportedSemantics("abstract data movement supports <=10k operations")
    demand_bits = expected_children = 0
    total_flits = total_packets = total_payload = 0
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
            total_flits += rf + sf
            total_packets += rp + sp
            total_payload += child.byte_length
            pending.append((op, child, outgoing + [("service", op.target, dc, op.service_cycles)] + incoming))
    if len(pending) > 10_000 or total_flits > 1_000_000:
        raise UnsupportedSemantics("abstract data-movement envelope: <=10k children and <=1M flits")

    # Event order: completions/phase arrivals before issue on simultaneous edges.
    events, scheduled_issue, lane_free, records, completed_ops = [], {}, {}, [], set()
    peak_live = {eid: 0 for eid in trackers}
    next_issue = {eid: Fraction(0) for eid in trackers}
    serial = 0

    def push(time, priority, payload):
        nonlocal serial
        serial += 1
        heapq.heappush(events, (time, priority, serial, payload))

    def wake(eid, time):
        period = Fraction(1, clocks[endpoint_clock(eid)])
        time = edge_at_or_after(max(time, next_issue[eid]), period)
        if eid not in scheduled_issue or time < scheduled_issue[eid]:
            scheduled_issue[eid] = time
            push(time, 1, ("issue", eid))

    if _runtime is not None:
        _runtime.bind(deps=deps, push=push, wake=wake, trackers=trackers, lane_free=lane_free)
    for eid in trackers:
        wake(eid, Fraction(0))
    if _faults is not None and not isinstance(_faults, FaultProfile):
        raise InvalidInput("fault recovery requires an explicit FaultProfile")
    def _retry(op, record, now, phases, reason):
        """Automatic bounded retry: one more physical attempt, same identity."""
        attempt = record["attempt"]
        record["attempt_log"].append({"event": reason, "attempt": attempt, "time_s": ratio(now)})
        if attempt >= _faults.max_attempts:
            raise EvidenceInvalid(
                f'child {op.operation_id}:{record["child"]["sequence"]} sealed after '
                f'{attempt} physical attempts ({reason})')
        # A request retry re-runs the request flight; a response retry resumes
        # after the service phase so memory is never mutated or committed twice.
        start = 0 if not record.get("service_done") else record["service_phase"] + 1
        record["attempt"] = attempt + 1
        record["attempt_log"].append({"event": "attempt_retry", "attempt": record["attempt"],
                                      "time_s": ratio(now), "resume_phase": start})
        push(now, 0, ("phase", op, phases, start, record, record["attempt"]))

    phase_records, fifo_writes, fifo_reads = [], 0, 0
    routed_flit_um = Fraction(0)
    while events:
        if _runtime is not None and _runtime.finished:
            break
        queued_event = heapq.heappop(events)
        now, _, _, event = queued_event
        if _runtime is not None:
            if now > _runtime.horizon:
                heapq.heappush(events, queued_event)
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
                _runtime.issued(op, record, now, phases)
            push(now, 0, ("phase", op, phases, 0, record, record.get("attempt", 1)))
            next_issue[eid] = now + Fraction(1, clocks[endpoint_clock(eid)])
            wake(eid, next_issue[eid])
        else:
            _, op, phases, index, record, attempt_of_event = event
            if event[0] == "deadline":
                # A response deadline only fires while THIS attempt still lacks
                # a response; a superseded or already-retired attempt is ignored.
                if not record["responded"] and attempt_of_event == record["attempt"]:
                    _retry(op, record, now, phases, "response_timeout")
                continue
            if _runtime is not None and index and phases[index - 1][0] == "service":
                _runtime.commit(op, record, now)
            if _faults is not None:
                if attempt_of_event != record["attempt"]:
                    # A superseded attempt's already-queued phases are void: the
                    # retry owns the child. First response still wins.
                    continue
                key = f'{op.operation_id}:{record["child"]["sequence"]}'
                attempt = record["attempt"]
                if index == record["service_phase"]:
                    if attempt in _faults.dropped_requests.get(key, ()):
                        _retry(op, record, now, phases, "request_dropped")
                        continue
                elif index == record["service_phase"] + 1:
                    # The service phase has now run: memory committed exactly once.
                    if not record["service_done"]:
                        record["service_done"] = True
                        push(now + _faults.timeout_cycles * Fraction(1, clocks[workload.network_clock]),
                             0, ("deadline", op, phases, index, record, attempt))
                    if attempt in _faults.dropped_responses.get(key, ()):
                        _retry(op, record, now, phases, "response_dropped")
                        continue
            if index == len(phases):
                record["completed_s"] = ratio(now)
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
                for eid in trackers:
                    wake(eid, now)
                continue
            phase = phases[index]
            fifo = None
            if phase[0] == "interface":
                _, eid, direction, source_clock, dest_clock, words = phase
                crossing = crossings.get((source_clock, dest_clock))
                key = ("crossing", crossing.id) if crossing else ("interface", eid, direction)
                start = max(now, lane_free.get(key, Fraction(0)))
                if crossing:
                    fifo = clocked_fifo_transfer(config=crossing.async_fifo,
                        write_hz=clocks[source_clock], read_hz=clocks[dest_clock], words=words, start_s=start)
                    end, free = fifo.completed_s, fifo.reusable_s
                    fifo_writes += fifo.writes
                    fifo_reads += fifo.reads
                else:
                    period = Fraction(1, clocks[source_clock])
                    start = edge_at_or_after(start, period)
                    end = free = start + words * period
            elif phase[0] == "channel":
                _, cid, words, traffic_class = phase
                ch = channels[cid]
                key = ("channel", cid)
                period = Fraction(1, clocks[workload.network_clock])
                start = edge_at_or_after(max(now, lane_free.get(key, Fraction(0))), period)
                # Whole-message store-and-forward, not wormhole/VC flow control.
                cycles = (words * pf.flit_width_bits + ch.width_bits - 1) // ch.width_bits
                end = start + (cycles + ch.latency_cycles) * period
                free = end
            else:
                _, eid, clock, cycles = phase
                key = ("service", eid)
                period = Fraction(1, clocks[clock])
                start = edge_at_or_after(max(now, lane_free.get(key, Fraction(0))), period)
                if _runtime is not None:
                    cycles = _runtime.service_cycles(op, record, cycles)
                end = free = start + cycles * period
                if _runtime is not None:
                    _runtime.service_accepted(op, record, now, start, end)
                    if "owner_cache_plan" in record:
                        record["owner_service_cycles"] = cycles
            lane_free[key] = free
            entry = {"parent": op.operation_id, "sequence": record["child"]["sequence"],
                     "resource": list(key), "start_s": ratio(start), "completed_s": ratio(end),
                     "queued_s": ratio(start - now)}
            if _runtime is not None:
                entry["reusable_s"] = ratio(free)
            if phase[0] == "service" and _runtime is not None and "owner_service_cycles" in record:
                entry["service_cycles"] = record["owner_service_cycles"]
            if phase[0] == "channel":
                length = placement.length_um(ch.source, ch.destinations[0])
                routed_flit_um += words * length
                entry.update({"flits": words, "length_um": ratio(length),
                              "traffic_class": traffic_class})
            if fifo:
                entry.update({"writes": fifo.writes, "reads": fifo.reads,
                              "peak_occupancy": fifo.peak_occupancy, "blocked_write_cycles": fifo.blocked_write_cycles})
            phase_records.append(entry)
            push(end, 0, ("phase", op, phases, index + 1, record, record.get("attempt", 0)))
    if _runtime is not None:
        return _runtime.finish(pending=pending, events=events, children=records,
                               phases=phase_records, completed_ops=completed_ops,
                               peak_live=peak_live, authorizations=authorizations,
                               total_payload=total_payload, total_flits=total_flits,
                               fifo_writes=fifo_writes, fifo_reads=fifo_reads)
    if pending or len(completed_ops) != len(workload.operations):
        raise EvidenceInvalid("data-movement execution stalled before parent completion")
    if total_payload != sum(op.payload_bytes for op in workload.operations) or fifo_writes != fifo_reads:
        raise EvidenceInvalid("data-movement conservation failed")
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
                  **({"access_authorization": "ABSTRACT_POLICY_ENFORCED_NOT_FIREWALL"}
                     if root.access_system is not None else {})},
        "summary": {"parents_completed": len(completed_ops), "children_completed": len(records),
                    "payload_bytes": total_payload, "packets": total_packets, "flits": total_flits,
                    "fifo_words_written": fifo_writes, "fifo_words_read": fifo_reads,
                    "completion_s": ratio(finish), "routed_flit_um": ratio(routed_flit_um),
                    "peak_outstanding": {str(e): n for e, n in peak_live.items()}},
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
