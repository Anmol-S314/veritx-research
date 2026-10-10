"""Closed-loop REFERENCE compute/network/byte-memory execution, not native timing.

The private V1 runtime hook shares its exact routing, authorization, credits and
FIFO machinery. Requests start only when this DAG releases their ACCESS node;
responses release compute, which can release later requests.
"""
from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path
import sys

from veritx_dse.application.data_movement import execute_data_movement, ratio
from veritx_dse.application.tensor_demand import RemoteDemandPolicy, project_remote_tensor_demand
from veritx_dse.core.artifact import FrozenMap, canonical_bytes, content_id, thaw
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.coupled_tensor import CoupledTensorWorkload, fields
from veritx_dse.model.transaction_intent import TransactionKind
from veritx_dse.simulation.clocked_fifo import edge_at_or_after
from veritx_dse.workload.tensor_demand import lower_tensor_demand

PROFILE = "COUPLED_TENSOR_REFERENCE_V1"


@dataclass(frozen=True)
class CoupledTensorEvidence:
    data: FrozenMap

    def artifact_id(self):
        return content_id("veritx/CoupledTensorEvidence/v1", self.data)

    def to_dict(self):
        return {**thaw(self.data), "artifact_id": self.artifact_id()}

    def revalidate(self, *, compilation, workload, policy, placement):
        if self != execute_coupled_tensor(compilation, workload, policy, placement):
            raise EvidenceInvalid("coupled evidence differs from parent-recomputed execution")

    @classmethod
    def from_dict(cls, doc, *, compilation, workload, policy, placement):
        expected = execute_coupled_tensor(compilation, workload, policy, placement)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("coupled evidence differs from parent-recomputed execution")
        return expected


class _ReferenceRuntime:
    def __init__(self, compilation, workload, policy, placement, demand, remote):
        self.workload, self.policy, self.placement = workload, policy, placement
        self.compilation = compilation
        self.demand, self.remote = demand, remote
        self.clocks = {c.id: c.frequency_hz for c in compilation.compiled_system.clock_domains.domains}
        if (workload.horizon_clock not in self.clocks or any(e.clock not in self.clocks for e in workload.engines)
                or any(n.reset_clock not in self.clocks for n in workload.nodes if n.kind == "DRAIN_RESET")):
            raise InvalidInput("compute/horizon clock must be compiled")
        self.horizon = Fraction(workload.horizon_cycles, self.clocks[workload.horizon_clock])
        self.now = Fraction(0)
        self.nodes = {n.node_id: n for n in workload.nodes}
        self.engines = {e.engine_id: e for e in workload.engines}
        self.access_nodes = {n.access_id: n.node_id for n in workload.nodes if n.kind == "ACCESS"}
        self.requests = {r.request_id: r for r in demand.requests}
        self.gates, self.completed, self.started = set(), set(), set()
        self.remaining = {a: set(g) for a, g in remote.completion_groups.items()}
        self.live = {e: 0 for e in self.engines}
        self.peak = dict(self.live)
        self.ledger, self.intervals = [], []
        self.images = {k: bytearray.fromhex(v) for k, v in workload.initial_images}
        self.values = {k: bytes.fromhex(v) for k, v in workload.access_values}
        self.reads = {a.access_id: bytearray(a.count*a.block_bytes) for a in workload.demand.accesses if a.kind is TransactionKind.READ}
        self.accesses = {a.access_id: a for a in workload.demand.accesses}
        self.returned_bytes = {a: 0 for a in self.reads}
        self.read_fragments = {a: [] for a in self.reads}
        self.committed_keys, self.responded_keys = set(), set()
        self.mutated_bytes = 0
        self.epoch, self.dedup, self.replayed_bytes = 0, {}, 0
        self.retry_roots = {n.access_id: n.retry_of or n.access_id for n in workload.nodes if n.kind == "ACCESS"}
        self.reset_intervals = []
        self.cache_profile = workload.cache_profile
        self.cache_lines = {}
        self.cache_projection = {}
        self.cache_stats = {"line_lookups": 0, "hits": 0, "misses": 0,
                            "backing_read_bytes": 0, "lookup_cycles": 0,
                            "fill_service_cycles": 0, "invalidations": 0,
                            "evictions": 0, "dedup_lookups": 0,
                            "dedup_lookup_cycles": 0, "dedup_write_ack_cycles": 0,
                            "write_service_cycles": 0}
        if self.cache_profile:
            limit = self.cache_profile.capacity_bytes // self.cache_profile.line_bytes
            for target in sorted({s.target for t in workload.demand.tensors for s in t.shards}):
                self.cache_lines[target] = OrderedDict()
                self.cache_projection[target] = OrderedDict()
            self.cache_limit = limit

    def log(self, event, identity, now, **extra):
        self.ledger.append({"event": event, "id": identity, "time_s": ratio(now), **extra})

    def bind(self, *, deps, push, wake, trackers, lane_free):
        if self.cache_profile:
            self.validate_cache_lines()
        self.push, self.wake, self.trackers, self.lane_free = push, wake, trackers, lane_free
        self.operation_deps = deps
        # Preserve compiled ordering and detect cycles introduced by its edges.
        extra = {n: set() for n in self.nodes}
        for request_id, required in deps.items():
            node = self.access_nodes[self.requests[request_id].access_id]
            extra[node].update(self.access_nodes[self.requests[d].access_id] for d in required
                               if self.requests[d].access_id != self.requests[request_id].access_id)
        self.deps, ancestry = self.workload.dependency_ancestors(extra)
        resets = [n.node_id for n in self.nodes.values() if n.kind == "DRAIN_RESET"]
        for reset in resets:
            for other in list(self.access_nodes.values()) + resets:
                if reset != other and reset not in ancestry[other] and other not in ancestry[reset]:
                    raise InvalidInput("DRAIN_RESET must be comparable to every ACCESS and reset")
        for node in self.nodes.values():
            if node.retry_of is None:
                continue
            if node.retry_of not in self.access_nodes or self.retry_roots[node.retry_of] != node.retry_of:
                raise InvalidInput("retry_of must name a unique original, not a retry chain")
            original_node = self.access_nodes[node.retry_of]
            if original_node not in ancestry[node.node_id]:
                raise InvalidInput("retry requires original access retirement dependency")
            if {r for r in resets if r in ancestry[node.node_id]} != {r for r in resets if r in ancestry[original_node]}:
                raise UnsupportedSemantics("cross-epoch retry after reset is refused before issue")
            a, b = self.accesses[node.access_id], self.accesses[node.retry_of]
            same = ("tensor_id", "issuer", "kind", "offset_bytes", "block_bytes", "count", "stride_bytes", "cache_policy")
            if any(getattr(a, k) != getattr(b, k) for k in same):
                raise InvalidInput("retry identity/byte coverage must exactly match original")
            if a.kind is TransactionKind.WRITE and self.values[a.access_id] != self.values[b.access_id]:
                raise InvalidInput("retry WRITE payload differs from original")
        accesses = list(self.accesses.values())
        for i, a in enumerate(accesses):
            for b in accesses[i+1:]:
                if a.tensor_id != b.tensor_id or a.kind is b.kind is TransactionKind.READ:
                    continue
                an, bn = self.access_nodes[a.access_id], self.access_nodes[b.access_id]
                if an in ancestry[bn] or bn in ancestry[an]:
                    continue
                if any(a.offset_bytes + j*a.stride_bytes < b.offset_bytes + k*b.stride_bytes + b.block_bytes
                       and b.offset_bytes + k*b.stride_bytes < a.offset_bytes + j*a.stride_bytes + a.block_bytes
                       for j in range(a.count) for k in range(b.count)):
                    raise UnsupportedSemantics("unsequenced overlapping write requires completion ordering")
        push(Fraction(0), 1, ("runtime", ("dispatch",)))

    @property
    def finished(self):
        return len(self.completed) == len(self.nodes)

    def ready(self, request_id):
        return self.access_nodes[self.requests[request_id].access_id] in self.gates

    def dispatch(self, now):
        # Finite DAG gives bounded same-time barrier closure. IDs break ties.
        while True:
            changed = False
            for nid in sorted(self.nodes):
                node = self.nodes[nid]
                if nid in self.started or not self.deps[nid] <= self.completed:
                    continue
                if node.kind == "COMPUTE":
                    engine = self.engines[node.engine_id]
                    if self.live[engine.engine_id] + node.occupancy > engine.capacity:
                        continue
                    self.live[engine.engine_id] += node.occupancy
                    self.peak[engine.engine_id] = max(self.peak[engine.engine_id], self.live[engine.engine_id])
                    start = edge_at_or_after(now, Fraction(1, self.clocks[engine.clock]))
                    end = start + Fraction(node.cycles, self.clocks[engine.clock])
                    self.intervals.append({"node_id": nid, "engine_id": engine.engine_id,
                                           "reserved_s": ratio(now), "start_s": ratio(start),
                                           "completion_s": ratio(end), "occupancy": node.occupancy})
                    self.log("compute_reserved", nid, now)
                    self.push(end, 0, ("runtime", ("compute_complete", nid)))
                elif node.kind == "DRAIN_RESET":
                    if any(t.live_total for t in self.trackers.values()):
                        raise EvidenceInvalid("reset before response/credit drain")
                    start = edge_at_or_after(max([now, *self.lane_free.values()]), Fraction(1, self.clocks[node.reset_clock]))
                    end = start + Fraction(node.cycles, self.clocks[node.reset_clock])
                    self.reset_intervals.append({"node_id": nid, "drain_ready_s": ratio(now),
                                                 "start_s": ratio(start), "completion_s": ratio(end)})
                    self.log("reset_reserved", nid, now)
                    self.push(end, 0, ("runtime", ("reset_complete", nid)))
                elif node.kind == "ACCESS":
                    self.gates.add(nid)
                    self.log("access_released", nid, now)
                    for eid in sorted(self.trackers):
                        self.wake(eid, now)
                else:
                    self.completed.add(nid)
                    self.log("barrier_complete", nid, now)
                self.started.add(nid)
                changed = True
            if not changed:
                break

    def handle(self, action, now):
        if action[0] == "dispatch":
            self.dispatch(now)
            return
        if action[0] == "compute_complete":
            node = self.nodes[action[1]]
            self.live[node.engine_id] -= node.occupancy
            self.completed.add(node.node_id)
            self.log("compute_complete", node.node_id, now)
        elif action[0] == "reset_complete":
            self.epoch += 1
            self.dedup.clear()
            for rows in self.cache_lines.values():
                rows.clear()
            for rows in self.cache_projection.values():
                rows.clear()
            self.completed.add(action[1])
            self.log("reset_complete", action[1], now, epoch=self.epoch)
        self.push(now, 1, ("runtime", ("dispatch",)))

    def validate_cache_lines(self):
        line_bytes = self.cache_profile.line_bytes
        tensors = {t.tensor_id: t for t in self.workload.demand.tensors}
        accesses = self.accesses
        endpoints = {e.endpoint_id: e for e in self.compilation.compiled_system.fabric.attachment.endpoints}
        system = self.compilation.compiled_system
        for access in accesses.values():
            if access.cache_policy != "OWNER_CACHE":
                continue
            tensor = tensors[access.tensor_id]
            targets = {s.target for s in tensor.shards}
            spaces = {s.address_space for s in tensor.shards}
            if len(targets) != 1 or len(spaces) != 1:
                raise UnsupportedSemantics("owner cache requires one endpoint and address space per tensor")
            for request in (r for r in self.demand.requests if r.access_id == access.access_id):
                first = request.payload_address & ~(line_bytes - 1)
                last = (request.payload_address + request.payload_bytes - 1) & ~(line_bytes - 1)
                shard = next(s for s in tensor.shards if s.shard_id == request.shard_id)
                for address in range(first, last + 1, line_bytes):
                    if address < shard.base_address or address + line_bytes > shard.base_address + shard.size_bytes:
                        raise UnsupportedSemantics("cache line fill must fit the same initialized shard")
                    if access.kind is TransactionKind.READ and system.access_system is not None:
                        owner = endpoints[shard.target]
                        requester = endpoints[access.issuer]
                        spans = system.access_system.range_decisions(
                            operation="read", initiator=f"group:{requester.agent.group_index}",
                            target=f"group:{owner.agent.group_index}", address=address,
                            byte_length=line_bytes, address_space=shard.address_space,
                            endpoint_exists=True, route_exists=True, observed=False)
                        if any(row.permitted is not True for _start, _end, row in spans):
                            raise AccessDenied("owner cache line fill is not fully authorized", {
                                "operation_id": request.request_id, "address_start": address,
                                "address_end": address + line_bytes, "issued_children": 0})

    def _cache_key(self, op, record, address):
        return (op.target, op.address_space.value, address)

    def _line_location(self, key):
        _target, _space, address = key
        for tensor in self.workload.demand.tensors:
            for shard in tensor.shards:
                if shard.target == key[0] and shard.address_space.value == key[1] and shard.base_address <= address and address + self.cache_profile.line_bytes <= shard.base_address + shard.size_bytes:
                    offset = shard.offset_bytes + address - shard.base_address
                    return tensor.tensor_id, offset
        raise EvidenceInvalid("cache line lost its initialized owner shard")

    def service_cycles(self, op, record, authored_cycles):
        access = self.accesses[self.requests[op.operation_id].access_id]
        if not self.cache_profile:
            return authored_cycles
        if access.cache_policy != "OWNER_CACHE":
            if op.kind is TransactionKind.WRITE:
                line = self.cache_profile.line_bytes
                keys = tuple(self._cache_key(op, record, address) for address in range(
                    op.address & ~(line - 1), ((op.address + op.payload_bytes - 1) & ~(line - 1)) + 1, line))
                rows = self.cache_projection[op.target]
                invalidated = [key for key in keys if key in rows]
                for key in invalidated:
                    rows.pop(key)
                record["owner_cache_invalidation_plan"] = [list(k) for k in invalidated]
            return authored_cycles
        keys = tuple(self._cache_key(op, record, address) for address in range(
            op.address & ~(self.cache_profile.line_bytes - 1),
            ((op.address + op.payload_bytes - 1) & ~(self.cache_profile.line_bytes - 1)) + 1,
            self.cache_profile.line_bytes))
        retry = self.retry_roots[access.access_id] != access.access_id
        rows = self.cache_projection[op.target]
        hits, misses = [], []
        if retry:
            cycles = len(keys) * self.cache_profile.lookup_cycles
            if op.kind is TransactionKind.WRITE:
                cycles += authored_cycles
        else:
            for key in keys:
                hit = key in rows
                if hit:
                    hits.append(key)
                    if op.kind is TransactionKind.READ:
                        rows.move_to_end(key)
                else:
                    misses.append(key)
                if op.kind is TransactionKind.READ and not hit:
                    rows[key] = None
                    if len(rows) > self.cache_limit:
                        rows.popitem(last=False)
                elif op.kind is TransactionKind.WRITE and hit:
                    rows.pop(key)
            cycles = len(keys) * self.cache_profile.lookup_cycles
            if op.kind is TransactionKind.READ:
                cycles += len(misses) * self.cache_profile.line_fill_service_cycles
            else:
                cycles += authored_cycles
        record["owner_cache_plan"] = {"keys": [list(k) for k in keys],
            "hits": [list(k) for k in hits], "misses": [list(k) for k in misses],
            "retry": retry, "kind": op.kind.value, "cycles": cycles}
        return cycles

    def issued(self, op, record, now, phases):
        record["state"] = "REQUEST_INFLIGHT"
        record["flits_planned"] = sum(p[-1] for p in phases if p[0] == "interface" and p[2] == "out")
        record["epoch"] = self.epoch
        record["retry_of"] = self.retry_roots[self.requests[op.operation_id].access_id]
        self.log("request_issued", op.operation_id, now, sequence=record["child"]["sequence"], epoch=self.epoch)

    def service_accepted(self, op, record, now, start, end):
        record["state"] = "MEMORY_QUEUED_OR_SERVICING"
        record["memory_accepted_s"] = ratio(now)
        self.log("memory_accepted", op.operation_id, now,
                 sequence=record["child"]["sequence"], service_start_s=ratio(start), service_end_s=ratio(end))

    def slice(self, op, record):
        r = self.requests[op.operation_id]
        a = self.accesses[r.access_id]
        child = record["child"]
        offset = r.tensor_offset_bytes + child["address_start"] - op.address
        value_offset = r.block_index*a.block_bytes + offset - (a.offset_bytes + r.block_index*a.stride_bytes)
        return r, offset, value_offset, child["byte_length"]

    def _commit_owner_cache(self, op, record, access):
        plan = record.get("owner_cache_plan")
        if plan is None:
            invalidation_plan = record.get("owner_cache_invalidation_plan")
            if invalidation_plan is not None:
                rows = self.cache_lines[op.target]
                for key in invalidation_plan:
                    cache_key = tuple(key)
                    if cache_key not in rows:
                        raise EvidenceInvalid("owner-cache write invalidation projection diverged")
                    del rows[cache_key]
                    self.cache_stats["invalidations"] += 1
            return None
        keys = [tuple(k) for k in plan["keys"]]
        expected_hits = {tuple(k) for k in plan["hits"]}
        rows = self.cache_lines[op.target]
        if plan["retry"]:
            self.cache_stats["dedup_lookups"] += len(keys)
            self.cache_stats["dedup_lookup_cycles"] += len(keys) * self.cache_profile.lookup_cycles
            if op.kind is TransactionKind.WRITE:
                self.cache_stats["dedup_write_ack_cycles"] += op.service_cycles
            return None
        actual_hits = {key for key in keys if key in rows}
        if actual_hits != expected_hits:
            raise EvidenceInvalid("owner-cache reservation projection diverged from committed LRU")
        self.cache_stats["line_lookups"] += len(keys)
        self.cache_stats["lookup_cycles"] += len(keys) * self.cache_profile.lookup_cycles
        self.cache_stats["hits"] += len(expected_hits)
        self.cache_stats["misses"] += len(keys) - len(expected_hits)
        self.cache_stats["fill_service_cycles"] += len(plan["misses"]) * self.cache_profile.line_fill_service_cycles if op.kind is TransactionKind.READ else 0
        self.cache_stats["backing_read_bytes"] += len(plan["misses"]) * self.cache_profile.line_bytes if op.kind is TransactionKind.READ else 0
        self.cache_stats["write_service_cycles"] += op.service_cycles if op.kind is TransactionKind.WRITE else 0
        if op.kind is TransactionKind.READ:
            for cache_key in keys:
                if cache_key in rows:
                    rows.move_to_end(cache_key)
                else:
                    tensor_id, offset = self._line_location(cache_key)
                    line = bytes(self.images[tensor_id][offset:offset+self.cache_profile.line_bytes])
                    if len(line) != self.cache_profile.line_bytes:
                        raise EvidenceInvalid("cache line fill is not fully initialized")
                    rows[cache_key] = line
                    if len(rows) > self.cache_limit:
                        rows.popitem(last=False)
                        self.cache_stats["evictions"] += 1
            result = bytearray()
            cursor, end = op.address, op.address + op.payload_bytes
            while cursor < end:
                line_address = cursor & ~(self.cache_profile.line_bytes - 1)
                cache_key = self._cache_key(op, record, line_address)
                data = rows[cache_key]
                take = min(end - cursor, line_address + self.cache_profile.line_bytes - cursor)
                result.extend(data[cursor-line_address:cursor-line_address+take])
                cursor += take
            return bytes(result).hex()
        invalidated = 0
        for cache_key in keys:
            if cache_key in rows:
                del rows[cache_key]
                invalidated += 1
        self.cache_stats["invalidations"] += invalidated
        return None

    def commit(self, op, record, now):
        key = (op.operation_id, record["child"]["sequence"])
        if key in self.committed_keys:
            raise EvidenceInvalid("duplicate child memory commit")
        r, offset, value_offset, size = self.slice(op, record)
        original = self.retry_roots[r.access_id]
        dedup_key = (op.target, record["epoch"], original, op.initiator, op.kind.value,
                     op.address_space.value, record["child"]["address_start"],
                     record["child"]["address_end"], r.block_index)
        if original != r.access_id:
            if dedup_key not in self.dedup:
                raise EvidenceInvalid("retry lacks exact endpoint/epoch/child dedup identity")
            self._commit_owner_cache(op, record, self.accesses[r.access_id])
            response = self.dedup[dedup_key]
            self.replayed_bytes += size
            record["deduplicated"] = True
        else:
            if dedup_key in self.dedup:
                raise EvidenceInvalid("original child committed twice")
            access = self.accesses[r.access_id]
            if op.kind is TransactionKind.WRITE:
                self.images[r.tensor_id][offset:offset+size] = self.values[r.access_id][value_offset:value_offset+size]
                self.mutated_bytes += size
                self._commit_owner_cache(op, record, access)
                response = ""
            else:
                cached = self._commit_owner_cache(op, record, access)
                response = cached if cached is not None else bytes(self.images[r.tensor_id][offset:offset+size]).hex()
            self.dedup[dedup_key] = response
            record["deduplicated"] = False
        if op.kind is TransactionKind.READ:
            record["response_hex"] = response
        self.committed_keys.add(key)
        record["state"] = "RESPONSE_INFLIGHT"
        record["committed_s"] = ratio(now)
        self.log("memory_commit", op.operation_id, now, sequence=key[1], payload_bytes=size,
                 deduplicated=record["deduplicated"])

    def responded(self, op, record, now, parent_complete):
        key = (op.operation_id, record["child"]["sequence"])
        if key not in self.committed_keys or key in self.responded_keys:
            raise EvidenceInvalid("response must retire once after commit")
        self.responded_keys.add(key)
        record["state"] = "RETIRED"
        r, _, value_offset, size = self.slice(op, record)
        if op.kind is TransactionKind.READ:
            data = bytes.fromhex(record["response_hex"])
            if data != self.values[r.access_id][value_offset:value_offset+size]:
                raise EvidenceInvalid(f"READ response differs from expected bytes for {r.access_id}")
            self.reads[r.access_id][value_offset:value_offset+size] = data
            self.returned_bytes[r.access_id] += size
            self.read_fragments[r.access_id].append({"offset_bytes": value_offset, "hex": data.hex()})
        self.log("response_retired", op.operation_id, now, sequence=key[1])
        if parent_complete:
            self.remaining[r.access_id].remove(op.operation_id)
            if not self.remaining[r.access_id]:
                nid = self.access_nodes[r.access_id]
                self.completed.add(nid)
                self.log("access_complete", nid, now)
                self.push(now, 1, ("runtime", ("dispatch",)))

    def finish(self, *, pending, events, children, phases, completed_ops, peak_live,
               authorizations, total_payload, total_flits, fifo_writes, fifo_reads):
        complete = len(self.completed) == len(self.nodes)
        status = "COMPLETE" if complete else "INCOMPLETE" if events else "DEADLOCK"
        issued, responded = len(children), len(self.responded_keys)
        live = sum(t.live_total for t in self.trackers.values())
        states = {state: sum(c["state"] == state for c in children) for state in (
            "REQUEST_INFLIGHT", "MEMORY_QUEUED_OR_SERVICING", "RESPONSE_INFLIGHT", "RETIRED")}
        accepted = sum("memory_accepted_s" in c for c in children)
        if (sum(states.values()) != issued or accepted != len(self.committed_keys) + states["MEMORY_QUEUED_OR_SERVICING"]):
            raise EvidenceInvalid("coupled request/memory/response ownership conservation failed")
        if issued != responded + live or responded > len(self.committed_keys) or fifo_writes != fifo_reads:
            raise EvidenceInvalid("coupled child/credit/commit conservation failed")
        for tracker in self.trackers.values():
            tracker.assert_invariants()
        if any(not 0 <= count <= self.engines[eid].capacity for eid, count in self.live.items()):
            raise EvidenceInvalid("compute engine occupancy violates capacity")
        if complete and (pending or live or any(self.live.values()) or total_payload != self.demand.audit["request_payload_bytes"]):
            raise EvidenceInvalid("completed coupled execution has unresolved demand")
        for auth in authorizations:
            done = auth["operation_id"] in completed_ops
            for span in auth["spans"]:
                span["decision"]["observed"] = done
        final_images = {k: bytes(v).hex() for k, v in sorted(self.images.items())}
        cache_scope = "ABSTRACT_OWNER_CACHE_REFERENCE" if self.cache_profile else "BYPASS"
        return CoupledTensorEvidence(FrozenMap({
            "type": "veritx/CoupledTensorEvidence", "schema_version": 1, "profile": PROFILE,
            "status": status, "stop_reason": "ALL_NODES_RETIRED" if complete else "INCLUSIVE_HORIZON" if events else "NO_SCHEDULED_PROGRESS",
            "next_event_s": ratio(min(e[0] for e in events)) if events and not complete else None,
            "design_hash": self.workload.demand.design_hash,
            "system_hash": self.workload.demand.system_hash, "workload_id": self.workload.workload_id(),
            "demand_id": self.demand.artifact_id(), "transport": self.policy.to_dict(),
            "placement_id": self.placement.artifact_id(),
            "scope": {"timing": "REFERENCE_STORE_AND_FORWARD_AUTHORED_MEMORY_SERVICE",
                      "native_network": False, "native_memory": False, "signoff_verified": False,
                      "cache_policy": cache_scope,
                      "coherence": "UNIQUE_OWNER_NO_PROTOCOL" if self.cache_profile else "UNIQUE_OWNER_UNCACHED_NO_PROTOCOL",
                      "visibility": "CHILD_SERVICE_COMPLETION_SPLIT_WRITE_NONATOMIC",
                      "fifo_counters": "RESERVED_FULL_BURSTS_NOT_PARTIAL_EDGE_COUNTS",
                      "retry": "AUTHORED_POST_RETIREMENT_DEDUP_NO_TIMEOUT_LOSS_RECOVERY",
                      "reset": "GLOBAL_DRAIN_RETAIN_IMAGE_CLEAR_DEDUP_CLOCKS_CONTINUE",
                      "power_sideband": "NOT_EXECUTED"},
            **({"cache_profile": self.cache_profile.to_dict(),
                "cache_statistics": dict(self.cache_stats)} if self.cache_profile else {}),
            "summary": {"elapsed_s": ratio(self.now if complete or not events else self.horizon),
                        "horizon_s": ratio(self.horizon), "nodes_completed": len(self.completed),
                        "children_source_held": len(pending), "children_issued": issued,
                        "children_committed": len(self.committed_keys), "children_responded": responded,
                        "children_memory_accepted": accepted, "child_states": states,
                        "children_declared": len(pending) + issued,
                        "children_live": live, "payload_bytes": total_payload,
                        "flits_declared": total_flits, "write_bytes_committed": self.mutated_bytes,
                        "read_bytes_returned": sum(self.returned_bytes.values()),
                        "retry_payload_bytes": sum(r.payload_bytes for r in self.demand.requests if self.retry_roots[r.access_id] != r.access_id),
                        "useful_payload_bytes": sum(r.payload_bytes for r in self.demand.requests if self.retry_roots[r.access_id] == r.access_id),
                        "deduplicated_payload_bytes": self.replayed_bytes,
                        "retry_flits_planned": sum(c["flits_planned"] for c in children if self.retry_roots[self.requests[c["child"]["parent_id"]].access_id] != self.requests[c["child"]["parent_id"]].access_id),
                        "useful_flits_planned": sum(c["flits_planned"] for c in children if self.retry_roots[self.requests[c["child"]["parent_id"]].access_id] == self.requests[c["child"]["parent_id"]].access_id),
                        "fifo_words_reserved_written": fifo_writes, "fifo_words_reserved_read": fifo_reads,
                        "peak_outstanding": {str(k): v for k, v in peak_live.items()},
                        "peak_engine_occupancy": self.peak, "engine_occupancy": self.live},
            "source_held_children": [{"child": child.to_dict(),
                                      "operation_dependencies": sorted(self.operation_deps[op.operation_id]-completed_ops),
                                      "access_released": self.ready(op.operation_id)}
                                     for op, child, _ in pending],
            "pending_nodes": sorted(set(self.nodes)-self.completed),
            "blocked_dependencies": {n: sorted(self.deps[n]-self.completed) for n in sorted(set(self.nodes)-self.started)},
            "ledger": self.ledger, "compute_intervals": self.intervals,
            "reset_intervals": self.reset_intervals, "endpoint_epoch": self.epoch,
            "children": children, "phases": phases, "authorizations": authorizations,
            "initial_image_id": content_id("veritx/ByteImage/v1", dict(self.workload.initial_images)),
            "final_image_id": content_id("veritx/ByteImage/v1", final_images),
            "final_images": final_images,
            "read_results": {k: {"hex": bytes(v).hex() if not self.remaining[k] else None,
                                  "returned_bytes": self.returned_bytes[k],
                                  "fragments": self.read_fragments[k],
                                  "complete": not self.remaining[k]} for k, v in self.reads.items()}}))


def execute_coupled_tensor(compilation, workload, policy, placement):
    if not isinstance(workload, CoupledTensorWorkload) or not isinstance(policy, RemoteDemandPolicy):
        raise InvalidInput("explicit coupled workload and remote policy required")
    demand = lower_tensor_demand(compilation, workload.demand, allow_owner_cache=True)
    remote = project_remote_tensor_demand(compilation, workload.demand, policy, allow_owner_cache=True)
    if compilation.compiled_system.access_system is None:
        raise UnsupportedSemantics("coupled byte memory requires full compiled authorization")
    runtime = _ReferenceRuntime(compilation, workload, policy, placement, demand, remote)
    return execute_data_movement(compilation, remote.workload, placement, _runtime=runtime)


def run_document(doc):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.physical_placement import PhysicalPlacement
    fields(doc, {"design", "workload", "transport", "placement"}, "coupled experiment")
    compilation = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    return execute_coupled_tensor(compilation, CoupledTensorWorkload.from_dict(doc["workload"]),
                                  RemoteDemandPolicy.from_dict(doc["transport"]),
                                  PhysicalPlacement.from_dict(doc["placement"]))


def main(argv=None):
    from veritx_dse.core.errors import Refusal
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 1:
            raise InvalidInput("expected one coupled experiment JSON path")
        evidence = run_document(json.loads(Path(argv[0]).read_text()))
    except (Refusal, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REFUSED", "profile": PROFILE, "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(evidence.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
