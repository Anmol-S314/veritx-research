"""ABSTRACT_MULTICAST_TREE_V1: explicit P2P tree, atomic reference flit forks.

Uses canonical format for payload partition/accounting, NOT its unicast
header as a multicast wire encoding. No canonical/native multicast support.
"""
from __future__ import annotations

from dataclasses import dataclass
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact
from veritx_dse.model.packet_format import PacketFormatArtifact
from veritx_dse.model.reference_network import (
    ReferenceNetworkError, exact, integer, keys, parents, rows, pairs, sealed, text,
)

PROFILE = "ABSTRACT_MULTICAST_TREE_V1"
SEMANTICS = {
    "fork": "ATOMIC_ALL_CHILDREN_AND_LOCAL_SINKS",
    "timing": "START_SNAPSHOT_SIMULTANEOUS_COMMIT_ONE_HOP_PER_TICK",
    "arbitration": "ASCENDING_ROUTER_ID_ALL_OUTPUTS_OR_NONE",
    "injection": "ONE_SOURCE_FLIT_PER_TICK_AT_END_OF_TICK_NO_SAME_TICK_FORWARD",
    "sink_credit": "RETURN_AT_TICK_START_ZERO_DELAY_AT_COMMIT_NO_SAME_TICK_REUSE",
    "link_capacity": "ONE_FLIT_PER_CHANNEL_PER_TICK",
    "encoding": "REFERENCE_TOKENS_NOT_MULTICAST_WIRE_HEADERS",
}


@dataclass(frozen=True)
class SinkCredit:
    endpoint: int
    capacity: int
    return_delay: int
    ready_ticks: tuple[int, ...]

    def __post_init__(self):
        integer(self.endpoint, "sink endpoint")
        integer(self.capacity, "sink capacity", 1)
        integer(self.return_delay, "sink return_delay")
        if type(self.ready_ticks) is not tuple:
            raise ReferenceNetworkError("ready_ticks must be immutable")
        for tick in self.ready_ticks:
            integer(tick, "ready tick")
        if self.ready_ticks != tuple(sorted(set(self.ready_ticks))):
            raise ReferenceNetworkError("ready ticks must be sorted unique")

    def to_dict(self):
        return {"endpoint": self.endpoint, "capacity": self.capacity,
                "return_delay": self.return_delay, "ready_ticks": list(self.ready_ticks)}

    @classmethod
    def from_dict(cls, data):
        keys(data, {"endpoint", "capacity", "return_delay", "ready_ticks"}, "sink")
        return cls(data["endpoint"], data["capacity"], data["return_delay"],
                   tuple(rows(data["ready_ticks"], "ready_ticks")))


@dataclass(frozen=True)
class MulticastTreeContract:
    topology: TopologyArtifact
    attachment: AgentAttachmentArtifact
    vc_resource: VCResourceArtifact
    packet_format: PacketFormatArtifact
    operation_id: str
    source: int
    destinations: tuple[int, ...]
    traffic_class: str
    payload_bytes: int
    # Directed channel ID, outgoing VC. One incoming CHANNEL/VC per nonroot.
    edges: tuple[tuple[int, int], ...]
    injection_vc: int
    input_vc_capacity: int
    injection_cycles: tuple[int, ...]
    sinks: tuple[SinkCredit, ...]
    tick_bound: int

    def __post_init__(self):
        endpoints = parents(self.topology, self.attachment)
        if not isinstance(self.vc_resource, VCResourceArtifact) or not isinstance(self.packet_format, PacketFormatArtifact):
            raise ReferenceNetworkError("actual VC and packet format artifacts required")
        self.packet_format.validate_against(self.topology, self.attachment, self.vc_resource)
        text(self.operation_id, "operation_id")
        text(self.traffic_class, "traffic_class")
        integer(self.source, "source")
        integer(self.payload_bytes, "payload_bytes", 1)
        integer(self.injection_vc, "injection_vc")
        integer(self.input_vc_capacity, "input_vc_capacity", 1)
        integer(self.tick_bound, "tick_bound", 1)
        if self.source not in endpoints:
            raise ReferenceNetworkError("unknown source endpoint")
        if type(self.destinations) is not tuple or not self.destinations:
            raise ReferenceNetworkError("explicit nonempty destinations required")
        for endpoint in self.destinations:
            integer(endpoint, "destination endpoint")
        if self.destinations != tuple(sorted(set(self.destinations))) or any(e not in endpoints for e in self.destinations):
            raise ReferenceNetworkError("destinations must be sorted unique actual endpoint IDs")
        eligible = dict(self.vc_resource.traffic_class_to_vcs).get(self.traffic_class, ())
        if self.injection_vc not in eligible:
            raise ReferenceNetworkError("injection VC/class ineligible")
        if type(self.edges) is not tuple or any(type(e) is not tuple or len(e) != 2 for e in self.edges):
            raise ReferenceNetworkError("edges must be immutable channel/VC pairs")
        if self.edges != tuple(sorted(self.edges)):
            raise ReferenceNetworkError("edges must be sorted")
        channel_map = {c.channel_id: c for c in self.topology.channels}
        root = endpoints[self.source]
        incoming = {}
        children = {}
        for cid, vc in self.edges:
            integer(cid, "channel ID")
            integer(vc, "edge VC")
            channel = channel_map.get(cid)
            if channel is None:
                raise ReferenceNetworkError("edge references absent CHANNEL")
            if vc not in eligible:
                raise ReferenceNetworkError("edge VC/class ineligible")
            if channel.dst_router == root or channel.dst_router in incoming:
                raise ReferenceNetworkError("tree cycle/reconvergence/duplicate parent")
            incoming[channel.dst_router] = (cid, vc)
            children.setdefault(channel.src_router, []).append(channel.dst_router)
        visited = set()

        def visit(router):
            if router in visited:
                raise ReferenceNetworkError("tree cycle")
            visited.add(router)
            for child in children.get(router, ()):
                visit(child)
        visit(root)
        if visited != {root} | set(incoming) or any(r not in visited for r in children):
            raise ReferenceNetworkError("tree has disconnected/cyclic edges")
        target_routers = {endpoints[e] for e in self.destinations}
        if not target_routers <= visited:
            raise ReferenceNetworkError("tree misses a declared destination")
        for router in visited:
            if not children.get(router) and router not in target_routers:
                raise ReferenceNetworkError("tree has dead/extra branch")
        transitions = set(self.vc_resource.allowed_transitions)
        for cid, vc in self.edges:
            source_router = channel_map[cid].src_router
            ingress_vc = self.injection_vc if source_router == root else incoming[source_router][1]
            if (ingress_vc, vc) not in transitions:
                raise ReferenceNetworkError("illegal concrete ingress-to-child VC transition")
        if type(self.sinks) is not tuple or any(not isinstance(s, SinkCredit) for s in self.sinks):
            raise ReferenceNetworkError("explicit immutable sink records required")
        if tuple(s.endpoint for s in self.sinks) != self.destinations:
            raise ReferenceNetworkError("exact destination sink-credit records required")
        if any(t >= self.tick_bound for s in self.sinks for t in s.ready_ticks):
            raise ReferenceNetworkError("sink schedule outside horizon")
        if type(self.injection_cycles) is not tuple:
            raise ReferenceNetworkError("explicit immutable injection schedule required")
        for cycle in self.injection_cycles:
            integer(cycle, "injection cycle")
        if self.injection_cycles != tuple(sorted(self.injection_cycles)) or any(c >= self.tick_bound for c in self.injection_cycles):
            raise ReferenceNetworkError("injection schedule must be ordered within horizon")
        if len(self.injection_cycles) != len(self.tokens()):
            raise ReferenceNetworkError("one explicit injection cycle per original flit required")

    def tokens(self):
        """Packetize ONCE; ranges are payload bits, never header/padding."""
        width = self.packet_format.payload_bits_per_flit
        limit = self.packet_format.max_packet_flits
        result = []
        for index, start in enumerate(range(0, self.payload_bytes * 8, width)):
            result.append({"operation_id": self.operation_id, "packet": index // limit,
                           "flit": index % limit, "sequence": index,
                           "payload_range_bits": [start, min(start + width, self.payload_bytes * 8)]})
        return result

    def to_dict(self):
        return sealed(PROFILE, {
            "profile": PROFILE, "semantics": dict(SEMANTICS),
            "topology_hash": self.topology.topology_hash(), "attachment_hash": self.attachment.attachment_hash(),
            "vc_resource_hash": self.vc_resource.artifact_hash, "packet_format_hash": self.packet_format.packet_format_hash,
            "operation_id": self.operation_id, "source": self.source,
            "destinations": list(self.destinations), "traffic_class": self.traffic_class,
            "payload_bytes": self.payload_bytes, "edges": [list(e) for e in self.edges],
            "injection_vc": self.injection_vc, "input_vc_capacity": self.input_vc_capacity,
            "injection_cycles": list(self.injection_cycles), "sinks": [s.to_dict() for s in self.sinks],
            "tick_bound": self.tick_bound,
        })

    @classmethod
    def from_dict(cls, data, *, topology, attachment, vc_resource, packet_format):
        keys(data, {"profile", "semantics", "topology_hash", "attachment_hash", "vc_resource_hash",
                    "packet_format_hash", "operation_id", "source", "destinations", "traffic_class",
                    "payload_bytes", "edges", "injection_vc", "input_vc_capacity", "injection_cycles",
                    "sinks", "tick_bound", "artifact_hash"}, "multicast tree")
        result = cls(topology, attachment, vc_resource, packet_format, data["operation_id"], data["source"],
                     tuple(rows(data["destinations"], "destinations")), data["traffic_class"], data["payload_bytes"],
                     tuple(tuple(e) for e in pairs(data["edges"], "edges")), data["injection_vc"], data["input_vc_capacity"],
                     tuple(rows(data["injection_cycles"], "injection_cycles")),
                     tuple(SinkCredit.from_dict(s) for s in rows(data["sinks"], "sinks")), data["tick_bound"])
        exact(data, result.to_dict(), "multicast tree")
        return result


def execute_multicast(contract):
    """Bounded synchronous, conservative atomic-fork reference consumer.

    Every receiver uses START occupancy, even if it will dequeue this tick.
    Injection also uses start occupancy. No hidden extra input queue exists:
    unadmitted source tokens remain explicit pending source obligations.
    """
    endpoints = {e.endpoint_id: e.router_id for e in contract.attachment.endpoints}
    root = endpoints[contract.source]
    channel_map = {c.channel_id: c for c in contract.topology.channels}
    children = {}
    incoming = {root: ["SOURCE", contract.injection_vc]}
    for cid, vc in contract.edges:
        channel = channel_map[cid]
        children.setdefault(channel.src_router, []).append((cid, vc, channel.dst_router))
        incoming[channel.dst_router] = [cid, vc]
    local = {r: [e for e in contract.destinations if endpoints[e] == r] for r in incoming}
    obligations = {}

    def subtree(router):
        targets = set(local[router])
        for _, _, child in children.get(router, ()):
            child_targets = subtree(child)
            if targets & child_targets:
                raise ReferenceNetworkError("destination obligations overlap")
            targets |= child_targets
        obligations[router] = targets
        return targets
    if subtree(root) != set(contract.destinations):
        raise ReferenceNetworkError("destination obligation partition differs")
    tokens = contract.tokens()
    count = len(tokens)
    queues = {r: [] for r in incoming}
    sinks = {s.endpoint: s for s in contract.sinks}
    ready = {s.endpoint: set(s.ready_ticks) for s in contract.sinks}
    credits = {s.endpoint: s.capacity for s in contract.sinks}
    returns = {s.endpoint: [] for s in contract.sinks}
    delivered = {e: [] for e in contract.destinations}
    edge_flits = {cid: [] for cid, _ in contract.edges}
    injected = 0
    trace = []
    forks = 0

    def check():
        # Per-destination AND per-original-flit obligation law, including
        # explicit source pending tokens. Replicated token count is NOT conserved.
        for endpoint in contract.destinations:
            for sequence in range(count):
                held = sum(q.count(sequence) for r, q in queues.items() if endpoint in obligations[r])
                pending = int(sequence >= injected)
                done = delivered[endpoint].count(sequence)
                if pending + held + done != 1:
                    raise ReferenceNetworkError("lost/duplicate destination obligation")
            if delivered[endpoint] != list(range(len(delivered[endpoint]))):
                raise ReferenceNetworkError("destination flit delivery reordered")
            if credits[endpoint] + len(returns[endpoint]) != sinks[endpoint].capacity:
                raise ReferenceNetworkError("sink credit conservation failure")
        if any(len(q) > contract.input_vc_capacity for q in queues.values()):
            raise ReferenceNetworkError("input VC overflow")

    check()
    for tick in range(contract.tick_bound):
        returned = []
        for endpoint in contract.destinations:
            due = returns[endpoint].count(tick)
            if due:
                returns[endpoint] = [t for t in returns[endpoint] if t != tick]
                credits[endpoint] += due
                returned.append([endpoint, due])
        start = {r: list(q) for r, q in queues.items()}
        moves = []
        blocked = []
        used_channels = set()
        for router in sorted(start):
            if not start[router]:
                continue
            sequence = start[router][0]
            edges = children.get(router, ())
            targets = local[router]
            reasons = []
            for cid, _, child in edges:
                if len(start[child]) >= contract.input_vc_capacity:
                    reasons.append(f"INPUT_VC_FULL:{child}")
                if cid in used_channels:
                    reasons.append(f"CHANNEL_BUSY:{cid}")
            for endpoint in targets:
                if tick not in ready[endpoint]:
                    reasons.append(f"SINK_NOT_READY:{endpoint}")
                if credits[endpoint] < 1:
                    reasons.append(f"SINK_CREDIT_EMPTY:{endpoint}")
            if reasons:
                blocked.append({"router": router, "sequence": sequence, "reasons": reasons})
                continue
            used_channels.update(cid for cid, _, _ in edges)
            moves.append({"router": router, "token": tokens[sequence],
                          "edges": [[cid, vc] for cid, vc, _ in edges], "deliveries": list(targets)})
        injected_token = None
        if injected < count and contract.injection_cycles[injected] <= tick and len(start[root]) < contract.input_vc_capacity:
            injected_token = tokens[injected]
        for movement in moves:
            router, sequence = movement["router"], movement["token"]["sequence"]
            if queues[router].pop(0) != sequence:
                raise ReferenceNetworkError("FIFO head mismatch")
            if len(movement["edges"]) + len(movement["deliveries"]) > 1:
                forks += 1
            for cid, _vc, child in children.get(router, ()):
                if sequence in edge_flits[cid]:
                    raise ReferenceNetworkError("duplicate channel flit")
                edge_flits[cid].append(sequence)
                queues[child].append(sequence)
            for endpoint in movement["deliveries"]:
                delivered[endpoint].append(sequence)
                credits[endpoint] -= 1
                delay = sinks[endpoint].return_delay
                if delay == 0:
                    # Returned at commit, not reused by another movement this tick.
                    credits[endpoint] += 1
                    returned.append([endpoint, 1])
                else:
                    returns[endpoint].append(tick + delay)
        if injected_token is not None:
            queues[root].append(injected)
            injected += 1
        check()
        trace.append({"tick": tick, "injected": injected_token, "moves": moves, "blocked": blocked,
                      "credit_returns": returned,
                      "input_vcs": [{"router": r, "ingress": incoming[r], "sequences": list(queues[r])} for r in sorted(queues)],
                      "sink_credits": [[e, credits[e], list(returns[e])] for e in contract.destinations]})
        if injected == count and all(not q for q in queues.values()) and all(len(v) == count for v in delivered.values()):
            break
    complete = injected == count and all(not q for q in queues.values()) and all(len(v) == count for v in delivered.values())
    edge_count = sum(len(v) for v in edge_flits.values())
    payload_bits = lambda sequence: tokens[sequence]["payload_range_bits"][1] - tokens[sequence]["payload_range_bits"][0]
    outstanding = []
    for endpoint in contract.destinations:
        outstanding.append({"endpoint": endpoint, "pending_source": list(range(injected, count)),
                            "inflight": sorted(s for r, q in queues.items() if endpoint in obligations[r] for s in q)})
    return sealed(PROFILE + "/execution", {
        "profile": PROFILE, "scope": "REFERENCE_ONLY_NOT_HARDWARE_OR_NATIVE",
        "contract_hash": contract.to_dict()["artifact_hash"],
        "outcome": "COMPLETE" if complete else "BOUNDED_INCOMPLETE",
        "ticks_executed": len(trace), "trace": trace, "original_tokens": tokens,
        "source_payload_bytes": contract.payload_bytes,
        "source_injected_payload_bits": sum(payload_bits(s) for s in range(injected)),
        "source_injected_flits": injected, "fork_events": forks,
        "edge_flits": [[cid, list(v)] for cid, v in sorted(edge_flits.items())],
        "completed_edge_flits": edge_count,
        "modeled_link_wire_bits": edge_count * contract.packet_format.flit_width_bits,
        "delivered": [{"endpoint": e, "sequences": delivered[e],
                       "payload_bits": sum(payload_bits(s) for s in delivered[e])} for e in contract.destinations],
        "outstanding_obligations": outstanding,
    })


def validate_multicast_execution(evidence, *, contract):
    exact(evidence, execute_multicast(contract), "multicast execution replay")
