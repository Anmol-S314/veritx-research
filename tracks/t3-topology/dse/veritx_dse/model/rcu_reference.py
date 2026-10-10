"""ABSTRACT_RCU_REFERENCE_V1: a topology-bound serial UINT32 sum sidecar.

Network arrival/delivery times are external inputs, not NoC predictions.
No canonical agent, native backend, area or hardware capability is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.reference_network import (
    ReferenceNetworkError, exact, integer, keys, pairs, parents, path, rows,
    sealed, text,
)

PROFILE = "ABSTRACT_RCU_REFERENCE_V1"
SEMANTICS = "SERIAL_VECTOR_NO_QUEUE_EXOGENOUS_NETWORK_TIMES"


@dataclass(frozen=True)
class RCUReferenceContract:
    topology: TopologyArtifact
    attachment: AgentAttachmentArtifact
    group_id: str
    contributors: tuple[int, ...]
    root: int
    reducer_router: int
    lane_count: int
    service_cycles: int
    inbound_paths: tuple[tuple[int, tuple[int, ...]], ...]
    outbound_path: tuple[int, ...]
    operation: str
    dtype: str
    overflow: str

    def __post_init__(self):
        endpoints = parents(self.topology, self.attachment)
        text(self.group_id, "group_id")
        integer(self.root, "root")
        integer(self.reducer_router, "reducer_router")
        integer(self.lane_count, "lane_count", 1)
        integer(self.service_cycles, "service_cycles", 1)
        if (self.operation, self.dtype, self.overflow) != ("SUM", "UINT32", "WRAP_MOD_2_32"):
            raise ReferenceNetworkError("explicit SUM/UINT32/WRAP_MOD_2_32 required")
        if type(self.contributors) is not tuple or not self.contributors:
            raise ReferenceNetworkError("explicit nonempty contributor tuple required")
        for endpoint in self.contributors:
            integer(endpoint, "contributor")
        if self.contributors != tuple(sorted(set(self.contributors))):
            raise ReferenceNetworkError("contributors must be sorted unique endpoint IDs")
        if self.root not in endpoints or any(e not in endpoints for e in self.contributors):
            raise ReferenceNetworkError("unknown root/contributor endpoint")
        if self.reducer_router not in {r.router_id for r in self.topology.routers}:
            raise ReferenceNetworkError("unknown reducer placement router")
        if type(self.inbound_paths) is not tuple or any(
            type(row) is not tuple or len(row) != 2 for row in self.inbound_paths
        ):
            raise ReferenceNetworkError("inbound_paths must be immutable endpoint/path pairs")
        if tuple(e for e, _ in self.inbound_paths) != self.contributors:
            raise ReferenceNetworkError("exact contributor paths required")
        for endpoint, route in self.inbound_paths:
            integer(endpoint, "inbound endpoint")
            path(self.topology, route, endpoints[endpoint], self.reducer_router)
        path(self.topology, self.outbound_path, self.reducer_router, endpoints[self.root])

    def to_dict(self):
        return sealed(PROFILE, {
            "profile": PROFILE, "semantics": SEMANTICS,
            "topology_hash": self.topology.topology_hash(),
            "attachment_hash": self.attachment.attachment_hash(),
            "group_id": self.group_id, "contributors": list(self.contributors),
            "root": self.root, "reducer_router": self.reducer_router,
            "lane_count": self.lane_count, "service_cycles": self.service_cycles,
            "inbound_paths": [[e, list(p)] for e, p in self.inbound_paths],
            "outbound_path": list(self.outbound_path),
            "operation": self.operation, "dtype": self.dtype, "overflow": self.overflow,
        })

    @classmethod
    def from_dict(cls, data, *, topology, attachment):
        keys(data, {"profile", "semantics", "topology_hash", "attachment_hash",
                    "group_id", "contributors", "root", "reducer_router", "lane_count",
                    "service_cycles", "inbound_paths", "outbound_path", "operation",
                    "dtype", "overflow", "artifact_hash"}, "RCU contract")
        result = cls(topology, attachment, data["group_id"],
                     tuple(rows(data["contributors"], "contributors")), data["root"],
                     data["reducer_router"], data["lane_count"], data["service_cycles"],
                     tuple((e, tuple(rows(p, "path"))) for e, p in pairs(data["inbound_paths"], "inbound_paths")),
                     tuple(rows(data["outbound_path"], "outbound_path")),
                     data["operation"], data["dtype"], data["overflow"])
        exact(data, result.to_dict(), "RCU contract")
        return result


@dataclass(frozen=True)
class ReducerState:
    epoch: int | None = None
    status: str = "IDLE"
    accepted: tuple[int, ...] = ()
    accumulator: tuple[int, ...] = ()
    busy_until: int = 0
    last_cycle: int = 0
    emitted_at: int | None = None
    delivered_at: int | None = None


def validate_event(event):
    keys_by_kind = {
        "open": set(), "abort": set(), "contribute": {"endpoint", "values"},
        "emit": set(), "deliver": {"endpoint"},
    }
    if type(event) is not dict or event.get("kind") not in keys_by_kind:
        raise ReferenceNetworkError("unknown RCU event kind")
    keys(event, {"kind", "cycle", "event_id", "group_id", "epoch"} | keys_by_kind[event["kind"]], "RCU event")
    integer(event["cycle"], "cycle")
    integer(event["epoch"], "epoch")
    text(event["event_id"], "event_id")
    text(event["group_id"], "group_id")


def transition(contract, state, event):
    """Rejects leave the entire reducer state unchanged; no retry/dedup queue.

    Accepted vectors occupy [cycle,cycle+service). Arithmetic is reserved at
    admission; visibility is gated by the finish cycle. Abort cancels occupancy.
    """
    validate_event(event)
    cycle, epoch, kind = event["cycle"], event["epoch"], event["kind"]

    def reject(reason):
        return state, {"accepted": False, "reason": reason}

    if event["group_id"] != contract.group_id:
        return reject("WRONG_GROUP")
    if cycle < state.last_cycle:
        return reject("OUT_OF_ORDER_CYCLE")
    if kind == "open":
        if state.status not in {"IDLE", "DELIVERED", "ABORTED"}:
            return reject("ACTIVE_EPOCH")
        if state.epoch is not None and epoch <= state.epoch:
            return reject("NONINCREASING_EPOCH")
        return ReducerState(epoch=epoch, status="ACTIVE", accumulator=(0,) * contract.lane_count,
                            last_cycle=cycle, busy_until=cycle), {"accepted": True}
    if state.epoch != epoch:
        return reject("WRONG_EPOCH")
    if kind == "contribute":
        if state.status != "ACTIVE":
            return reject("NOT_ACTIVE")
        endpoint, values = event["endpoint"], event["values"]
        if type(endpoint) is not int or endpoint not in contract.contributors:
            return reject("UNKNOWN_CONTRIBUTOR")
        if endpoint in state.accepted:
            return reject("DUPLICATE_CONTRIBUTOR")
        if type(values) is not list or len(values) != contract.lane_count or any(
            type(v) is not int or not 0 <= v < 2**32 for v in values
        ):
            return reject("INVALID_UINT32_VECTOR")
        if cycle < state.busy_until:
            return reject("BUSY")
        accumulator = tuple((a + b) % 2**32 for a, b in zip(state.accumulator, values))
        finish = cycle + contract.service_cycles
        return replace(state, accepted=tuple(sorted((*state.accepted, endpoint))),
                       accumulator=accumulator, busy_until=finish, last_cycle=cycle), {
            "accepted": True, "finish_cycle": finish,
            "payload_bytes": contract.lane_count * 4,
            "path": list(dict(contract.inbound_paths)[endpoint]),
            "busy_interval": [cycle, finish],
        }
    if kind == "abort":
        if state.status != "ACTIVE":
            return reject("NOT_ACTIVE")
        return replace(state, status="ABORTED", last_cycle=cycle, busy_until=cycle), {
            "accepted": True, "missing": sorted(set(contract.contributors) - set(state.accepted)),
        }
    if kind == "emit":
        if state.status != "ACTIVE":
            return reject("NOT_ACTIVE")
        if state.accepted != contract.contributors or cycle < state.busy_until:
            return reject("RESULT_NOT_READY")
        return replace(state, status="EMITTED", emitted_at=cycle, last_cycle=cycle), {
            "accepted": True, "result": list(state.accumulator),
            "payload_bytes": 4 * contract.lane_count, "path": list(contract.outbound_path),
        }
    if type(event["endpoint"]) is not int or event["endpoint"] != contract.root:
        return reject("WRONG_ROOT")
    if state.status != "EMITTED":
        return reject("NOT_EMITTED")
    return replace(state, status="DELIVERED", delivered_at=cycle, last_cycle=cycle), {"accepted": True}


def execute_rcu(contract, events, until_cycle):
    integer(until_cycle, "until_cycle")
    rows(events, "events")
    for event in events:
        validate_event(event)
        if event["cycle"] > until_cycle:
            raise ReferenceNetworkError("event beyond explicit horizon")
    if len({e["event_id"] for e in events}) != len(events):
        raise ReferenceNetworkError("event IDs must be unique (replay is not retry)")
    state = ReducerState()
    trace = []
    inbound_bytes = outbound_bytes = inbound_hop_bytes = outbound_hop_bytes = 0
    rejections = {}
    for event in sorted(events, key=lambda e: (e["cycle"], e["event_id"])):
        state, response = transition(contract, state, event)
        trace.append({"event": event, "response": response})
        if not response["accepted"]:
            reason = response["reason"]
            rejections[reason] = rejections.get(reason, 0) + 1
        elif event["kind"] == "contribute":
            inbound_bytes += response["payload_bytes"]
            inbound_hop_bytes += response["payload_bytes"] * len(response["path"])
        elif event["kind"] == "emit":
            outbound_bytes += response["payload_bytes"]
            outbound_hop_bytes += response["payload_bytes"] * len(response["path"])
    ready = state.status in {"ACTIVE", "EMITTED", "DELIVERED"} and state.accepted == contract.contributors and until_cycle >= state.busy_until
    return sealed(PROFILE + "/execution", {
        "profile": PROFILE, "scope": "REFERENCE_ONLY_EXOGENOUS_NETWORK_TIMES",
        "contract_hash": contract.to_dict()["artifact_hash"], "until_cycle": until_cycle,
        "trace": trace, "status": state.status, "epoch": state.epoch,
        "accepted_contributions": sum(r["event"]["kind"] == "contribute" and r["response"]["accepted"] for r in trace),
        "missing": sorted(set(contract.contributors) - set(state.accepted)),
        "result": list(state.accumulator) if ready else None,
        "result_ready_cycle": state.busy_until if ready else None,
        "emitted_at": state.emitted_at, "delivered_at": state.delivered_at,
        "inbound_payload_bytes": inbound_bytes, "outbound_payload_bytes": outbound_bytes,
        "inbound_hop_bytes": inbound_hop_bytes, "outbound_hop_bytes": outbound_hop_bytes,
        "rejections": rejections,
        "accumulator_words": contract.lane_count, "contributor_bitmap_bits": len(contract.contributors),
    })


def validate_rcu_execution(evidence, *, contract, events, until_cycle):
    exact(evidence, execute_rcu(contract, events, until_cycle), "RCU execution replay")
