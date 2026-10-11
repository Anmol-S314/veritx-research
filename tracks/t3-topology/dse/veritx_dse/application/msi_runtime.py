"""Reference MSI directory/cache transitions used by the coupled executor."""
from collections import OrderedDict

from veritx_dse.application.data_movement import ratio
from veritx_dse.core.errors import EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.transaction_intent import TransactionKind


class MsiRuntimeMixin:
    """MSI state and planning behavior mixed into the coupled runtime."""

    def initialize_msi_state(self):
        self.msi_profile = self.workload.msi_profile
        # Committed protocol state is distinct from the home-arbitrated
        # projection used to prepare transactions ahead of their service slot.
        # The projection reserves deterministic outcomes; only commit() applies
        # each transaction's delta after its scheduler service event completes.
        self.msi_directory = {}
        self.msi_caches = {}
        # Atomic reservation ownership for MSI home/line keys and finite
        # requester caches. Every plan reserves its whole touched-line set,
        # every resident line that can be an LRU victim, and each cache whose
        # state can be recalled/invalidated before projection begins.
        self.msi_reservations = {}
        self.msi_reservations_by_owner = {}
        self.msi_backing_projection = {}
        self.msi_projected_directory = {}
        self.msi_projected_caches = {}
        self.msi_projected_backing_projection = {}
        self.msi_transactions = []
        self.msi_committed = []
        self.msi_stats = {name: 0 for name in (
            "reads", "writes", "fills", "invalidations", "acknowledgements",
            "dirty_recalls", "writebacks", "evictions", "deduplicated_retries")}
        self.cache_stats = {"line_lookups": 0, "hits": 0, "misses": 0,
                            "backing_read_bytes": 0, "lookup_cycles": 0,
                            "fill_service_cycles": 0, "invalidations": 0,
                            "evictions": 0, "dedup_lookups": 0,
                            "dedup_lookup_cycles": 0, "dedup_write_ack_cycles": 0,
                            "write_service_cycles": 0}
        if self.cache_profile:
            limit = self.cache_profile.capacity_bytes // self.cache_profile.line_bytes
            for target in sorted({s.target for t in self.workload.demand.tensors for s in t.shards}):
                self.cache_lines[target] = OrderedDict()
                self.cache_projection[target] = OrderedDict()
            self.cache_limit = limit
        if self.msi_profile:
            requesters = sorted({a.issuer for a in self.workload.demand.accesses})
            self.msi_caches = {requester: OrderedDict() for requester in requesters}
            self.msi_projected_caches = {
                requester: OrderedDict() for requester in requesters}

    def validate_msi_lines(self):
        line_bytes = self.msi_profile.line_bytes
        tensors = {t.tensor_id: t for t in self.workload.demand.tensors}
        covered_lines = set()
        for access in self.accesses.values():
            if access.kind not in (TransactionKind.READ, TransactionKind.WRITE):
                raise UnsupportedSemantics("MSI profile supports READ and WRITE only")
            if access.cache_policy != "BYPASS":
                raise UnsupportedSemantics("MSI profile cannot compose with OWNER_CACHE")
            for request in (r for r in self.demand.requests if r.access_id == access.access_id):
                tensor = tensors[request.tensor_id]
                shard = next(s for s in tensor.shards if s.shard_id == request.shard_id)
                first = request.payload_address & ~(line_bytes - 1)
                last = (request.payload_address + request.payload_bytes - 1) & ~(line_bytes - 1)
                if access.issuer not in self.msi_caches:
                    raise EvidenceInvalid("MSI request has no declared cache requester")
                for address in range(first, last + 1, line_bytes):
                    if (address < shard.base_address
                            or address + line_bytes > shard.base_address + shard.size_bytes):
                        raise UnsupportedSemantics(
                            "MSI line must fit wholly inside one initialized home shard")
                    key = (shard.target, shard.address_space.value, address)
                    covered_lines.add(key)
                    if len(covered_lines) > 65536:
                        raise UnsupportedSemantics("MSI directory supports at most 65536 accessed lines")
                    tensor_id, offset = self._line_location(key, line_bytes)
                    if len(self.images[tensor_id][offset:offset + line_bytes]) != line_bytes:
                        raise UnsupportedSemantics("MSI line fill requires initialized bytes")

    def _msi_line_bytes(self, key, *, projected=False):
        directory = (self.msi_projected_directory if projected
                     else self.msi_directory)
        backing = (self.msi_projected_backing_projection if projected
                   else self.msi_backing_projection)
        entry = directory.get(key)
        if entry and entry["state"] == "M":
            return bytes.fromhex(entry["dirty_data"])
        if key in backing:
            return backing[key]
        tensor_id, offset = self._line_location(key, self.msi_profile.line_bytes)
        data = bytes(self.images[tensor_id][offset:offset + self.msi_profile.line_bytes])
        if len(data) != self.msi_profile.line_bytes:
            raise EvidenceInvalid("MSI backing image lost a complete cache line")
        return data

    @staticmethod
    def _msi_entry_copy(entry):
        if entry is None:
            return {"state": "I", "sharers": set(),
                    "dirty_owner": None, "dirty_data": None}
        return {"state": entry["state"], "sharers": set(entry["sharers"]),
                "dirty_owner": entry["dirty_owner"],
                "dirty_data": entry["dirty_data"]}

    @staticmethod
    def _msi_entry_document(entry):
        return {"state": entry["state"],
                "sharers": sorted(entry["sharers"]),
                "dirty_owner": entry["dirty_owner"],
                "dirty_data": entry["dirty_data"]}

    def _msi_plan(self, op, record):
        access = self.accesses[self.requests[op.operation_id].access_id]
        original = self.retry_roots[access.access_id]
        if original != access.access_id:
            return {"retry": True, "actions": [], "writebacks": [],
                    "statistics": {"deduplicated_retries": 1},
                    "read_hex": None, "cycles": self.msi_profile.directory_lookup_cycles}

        line_bytes = self.msi_profile.line_bytes
        child_start = record["child"]["address_start"]
        child_end = record["child"]["address_end"]
        _request, _child_offset, child_value_offset, _child_size = self.slice(op, record)
        keys = [self._cache_key(op, record, address) for address in range(
            child_start & ~(line_bytes - 1),
            ((child_end - 1) & ~(line_bytes - 1)) + 1,
            line_bytes)]
        requester = access.issuer
        # The projection is home-arbitrated at the service reservation point.
        # It allows later queued requests to plan against earlier reservations
        # without exposing any of their state as committed directory/cache data.
        directory = self.msi_projected_directory
        caches = self.msi_projected_caches
        backing = self.msi_projected_backing_projection
        before_directory = {}
        before_caches = {}
        before_backing = {}
        stats_delta = {name: 0 for name in self.msi_stats}
        cache_touches = []
        cache = caches[requester]
        plan = {"retry": False, "requester": requester, "kind": op.kind.value,
                "keys": [list(key) for key in keys], "actions": [], "writebacks": [],
                "read_hex": None, "cycles": 0}
        costs = self.msi_profile

        def remember_directory(key):
            before_directory.setdefault(
                key, self._msi_entry_copy(directory.get(key)))

        def remember_cache(endpoint, key):
            values = before_caches.setdefault(endpoint, {})
            values.setdefault(key, caches[endpoint].get(key))

        def remember_backing(key):
            before_backing.setdefault(key, backing.get(key))

        def action(kind, key, **details):
            remember_directory(key)
            plan["actions"].append({"kind": kind, "line": list(key), **details})

        def writeback(key, data, reason):
            data = bytes(data)
            if len(data) != line_bytes:
                raise EvidenceInvalid("MSI writeback is not a complete line")
            tensor_id, offset = self._line_location(key, line_bytes)
            remember_backing(key)
            backing[key] = data
            plan["writebacks"].append({"tensor_id": tensor_id, "offset": offset,
                                       "hex": data.hex(), "reason": reason})
            plan["cycles"] += costs.writeback_cycles
            stats_delta["writebacks"] += 1
            action("dirty_writeback", key, reason=reason, bytes=line_bytes)

        for key in keys:
            entry = directory.setdefault(key, {
                "state": "I", "sharers": set(), "dirty_owner": None,
                "dirty_data": None})
            plan["cycles"] += costs.directory_lookup_cycles
            action("directory_lookup", key, state_before=entry["state"])
            if key not in cache:
                while len(cache) >= self.msi_profile.capacity_lines_per_requester:
                    victim = next(iter(cache))
                    remember_directory(victim)
                    remember_cache(requester, victim)
                    cache.popitem(last=False)
                    victim_entry = directory[victim]
                    if victim_entry["dirty_owner"] == requester:
                        writeback(victim, bytes.fromhex(victim_entry["dirty_data"]), "eviction")
                        victim_entry.update({"state": "I", "sharers": set(),
                                             "dirty_owner": None, "dirty_data": None})
                    else:
                        victim_entry["sharers"].discard(requester)
                        if not victim_entry["sharers"]:
                            victim_entry.update({"state": "I", "dirty_owner": None,
                                                 "dirty_data": None})
                    plan["cycles"] += costs.directory_lookup_cycles
                    stats_delta["evictions"] += 1
                    action("eviction", victim, requester=requester,
                           resulting_state=victim_entry["state"])

            line_data = self._msi_line_bytes(key, projected=True)
            if op.kind is TransactionKind.READ:
                stats_delta["reads"] += 1
                if entry["state"] == "I":
                    plan["cycles"] += costs.memory_read_cycles
                    stats_delta["fills"] += 1
                    action("memory_fill", key, bytes=line_bytes)
                    entry.update({"state": "S", "sharers": {requester},
                                  "dirty_owner": None, "dirty_data": None})
                elif entry["state"] == "M" and entry["dirty_owner"] != requester:
                    owner = entry["dirty_owner"]
                    plan["cycles"] += (costs.dirty_recall_cycles + costs.writeback_cycles
                                        + costs.acknowledgement_cycles)
                    stats_delta["dirty_recalls"] += 1
                    stats_delta["writebacks"] += 1
                    stats_delta["acknowledgements"] += 1
                    writeback_row = {"tensor_id": self._line_location(key, line_bytes)[0],
                                     "offset": self._line_location(key, line_bytes)[1],
                                     "hex": line_data.hex(), "reason": "dirty_recall"}
                    plan["writebacks"].append(writeback_row)
                    remember_backing(key)
                    backing[key] = line_data
                    entry.update({"state": "S", "sharers": {owner, requester},
                                  "dirty_owner": None, "dirty_data": None})
                    remember_cache(owner, key)
                    caches[owner][key] = "S"
                    action("dirty_recall", key, owner=owner, requester=requester)
                    action("dirty_writeback", key, reason="dirty_recall", bytes=line_bytes)
                    action("recall_ack", key, owner=owner)
                else:
                    entry["sharers"].add(requester)
                    if entry["state"] == "I":
                        entry["state"] = "S"
                    if entry["state"] != "M" or entry["dirty_owner"] != requester:
                        action("shared_read", key, requester=requester,
                               bytes=line_bytes)
                remember_cache(requester, key)
                cache[key] = "S" if entry["state"] == "S" else "M"
                cache.move_to_end(key)
                cache_touches.append((requester, key))
            else:
                stats_delta["writes"] += 1
                if entry["state"] == "M" and entry["dirty_owner"] == requester:
                    dirty = bytearray(line_data)
                else:
                    recalled_owner = None
                    if entry["state"] == "M" and entry["dirty_owner"] != requester:
                        owner = entry["dirty_owner"]
                        recalled_owner = owner
                        plan["cycles"] += (costs.dirty_recall_cycles + costs.writeback_cycles
                                            + costs.acknowledgement_cycles)
                        stats_delta["dirty_recalls"] += 1
                        stats_delta["writebacks"] += 1
                        stats_delta["acknowledgements"] += 1
                        tensor_id, offset = self._line_location(key, line_bytes)
                        plan["writebacks"].append({"tensor_id": tensor_id,
                            "offset": offset, "hex": line_data.hex(), "reason": "dirty_recall"})
                        remember_backing(key)
                        backing[key] = line_data
                        remember_cache(owner, key)
                        caches[owner].pop(key, None)
                        entry["sharers"].discard(owner)
                        entry.update({"state": "S" if entry["sharers"] else "I",
                                      "dirty_owner": None, "dirty_data": None})
                        action("dirty_recall", key, owner=owner, requester=requester)
                        action("dirty_writeback", key, reason="dirty_recall", bytes=line_bytes)
                        action("recall_ack", key, owner=owner)
                    elif entry["state"] == "I":
                        plan["cycles"] += costs.memory_read_cycles
                        stats_delta["fills"] += 1
                        action("memory_fill", key, bytes=line_bytes)
                    dirty = bytearray(line_data)
                    for sharer in sorted(entry["sharers"] - {requester, recalled_owner}):
                        plan["cycles"] += costs.invalidate_cycles + costs.acknowledgement_cycles
                        stats_delta["invalidations"] += 1
                        stats_delta["acknowledgements"] += 1
                        remember_cache(sharer, key)
                        caches[sharer].pop(key, None)
                        action("invalidate", key, requester=sharer)
                        action("invalidate_ack", key, requester=sharer)
                write_start = max(child_start, key[2])
                write_end = min(child_end, key[2] + line_bytes)
                if write_start < write_end:
                    byte_in_line = write_start - key[2]
                    value_offset = child_value_offset + write_start - child_start
                    size = write_end - write_start
                    dirty[byte_in_line:byte_in_line + size] = self.values[access.access_id][value_offset:value_offset + size]
                already_modified = (entry["state"] == "M"
                                    and entry["dirty_owner"] == requester)
                entry.update({"state": "M", "sharers": {requester},
                              "dirty_owner": requester, "dirty_data": bytes(dirty).hex()})
                remember_cache(requester, key)
                cache[key] = "M"
                cache.move_to_end(key)
                cache_touches.append((requester, key))
                if not already_modified:
                    action("ownership_grant", key, owner=requester)

        if op.kind is TransactionKind.READ:
            response = bytearray()
            cursor, end = child_start, child_end
            while cursor < end:
                key = self._cache_key(op, record, cursor & ~(line_bytes - 1))
                data = self._msi_line_bytes(key, projected=True)
                take = min(end - cursor, key[2] + line_bytes - cursor)
                response.extend(data[cursor - key[2]:cursor - key[2] + take])
                cursor += take
            plan["read_hex"] = bytes(response).hex()
        plan["cycles"] += costs.directory_lookup_cycles * 0
        touched = {tuple(row["line"]) for row in plan["actions"]}
        plan["_commit_delta"] = {
            "directory": [{"line": list(key),
                "before": self._msi_entry_document(before_directory[key]),
                "after": self._msi_entry_document(
                    self._msi_entry_copy(directory.get(key)))}
                for key in sorted(touched) if key in before_directory],
            "caches": [{"requester": endpoint, "line": list(key),
                "before": before_value,
                "after": caches[endpoint].get(key)}
                for endpoint, values in sorted(before_caches.items())
                for key, before_value in sorted(values.items())],
            "backing": [{"line": list(key),
                "before": before.hex() if before is not None else None,
                "after": backing[key].hex() if key in backing else None}
                for key, before in sorted(before_backing.items())],
            "cache_touches": [[endpoint, list(key)]
                              for endpoint, key in cache_touches],
            "statistics": stats_delta,
        }
        # These are reference scheduler states, not evidence that wire-level
        # coherence messages or acknowledgements have actually retired.
        transient = "REFERENCE_PROTOCOL_ACTIONS_PENDING"
        transaction_id = f'{op.operation_id}#{record["child"]["sequence"]}'
        logical_id = f'{original}#{record["child"]["sequence"]}'
        for action_index, row in enumerate(plan["actions"], 1):
            row.update({"logical_transaction_id": logical_id,
                        "execution_epoch": self.epoch,
                        "action_id": f'{logical_id}/protocol-{action_index}'})
        plan["transaction_id"] = transaction_id
        self.msi_transactions.append({"transaction": transaction_id,
                                      "logical_transaction_id": logical_id,
                                      "operation_id": op.operation_id,
                                      "access_id": access.access_id,
                                      "kind": op.kind.value,
                                      "requester": requester,
                                      "home": op.target,
                                      "reserved_resources": record.get("msi_reservations", []),
                                      "epoch": self.epoch, "actions": plan["actions"],
                                      "cycles": plan["cycles"], "state": transient})
        return plan

    def _msi_network_messages(self, op, plan):
        home = op.target
        requester = plan["requester"]
        control_bytes = op.control_bytes
        messages = []
        recall_owner = {}

        def add(action, source, destination, payload_bytes):
            ordinal = len(messages) + 1
            messages.append({
                "message_id": f"protocol-{ordinal}",
                "action_id": action["action_id"],
                "kind": action["kind"],
                "line": action["line"],
                "source": source,
                "destination": destination,
                "payload_bytes": payload_bytes,
                "traffic_class": (op.response_traffic_class or op.traffic_class)
                    if source == home else op.traffic_class,
                "acknowledgement": action["kind"] in
                    ("invalidate_ack", "recall_ack"),
                "before_service": action["kind"] not in
                    ("memory_fill", "shared_read", "ownership_grant"),
                "delivered_attempts": [],
            })

        for action in plan["actions"]:
            kind = action["kind"]
            if kind == "dirty_recall":
                recall_owner[tuple(action["line"])] = action["owner"]
                add(action, home, action["owner"], control_bytes)
            elif kind == "invalidate":
                add(action, home, action["requester"], control_bytes)
            elif kind == "invalidate_ack":
                add(action, action["requester"], home, control_bytes)
            elif kind == "recall_ack":
                add(action, action["owner"], home, control_bytes)
            elif kind == "dirty_writeback":
                line = tuple(action["line"])
                if action.get("reason") == "dirty_recall":
                    source = recall_owner.get(line)
                    if source is None:
                        raise EvidenceInvalid("MSI dirty writeback lacks its recalled owner")
                else:
                    source = requester
                add(action, source, home, self.msi_profile.line_bytes)
            elif kind in ("memory_fill", "shared_read"):
                add(action, home, requester, self.msi_profile.line_bytes)
            elif kind == "ownership_grant":
                add(action, home, action["owner"], control_bytes)
            elif kind == "eviction":
                add(action, action["requester"], home, control_bytes)
        return messages

    def protocol_messages(self, op, record):
        plan = record.get("msi_plan")
        if not self.msi_profile or plan is None or plan.get("retry"):
            return ()
        if "protocol_messages" not in plan:
            messages = self._msi_network_messages(op, plan)
            plan["protocol_messages"] = messages
            transaction = next(row for row in reversed(self.msi_transactions)
                              if row["transaction"] == plan["transaction_id"])
            transaction["messages"] = messages
            transaction["required_acknowledgements"] = [
                row["message_id"] for row in messages if row["acknowledgement"]]
            transaction["required_grants"] = [
                row["message_id"] for row in messages
                if row["kind"] == "ownership_grant"]
            lines = sorted({tuple(row["line"]) for row in plan["actions"]})
            transient = ("IM_WAITING_FOR_INVALIDATION_ACKS"
                         if any(row["kind"] == "invalidate" for row in plan["actions"])
                         else "SM_WAITING_FOR_DIRTY_RECALL_ACK"
                         if any(row["kind"] == "dirty_recall" for row in plan["actions"])
                         else "IS_WAITING_FOR_FILL"
                         if any(row["kind"] == "memory_fill" for row in plan["actions"])
                         else "IM_WAITING_FOR_OWNERSHIP"
                         if plan["kind"] == TransactionKind.WRITE.value
                         else "IS_WAITING_FOR_DATA")
            transaction["transient_states"] = [
                {"line": list(line), "state": transient} for line in lines]
            transaction["state_history"] = [{"state": transaction["state"],
                                             "time_s": ratio(self.now)}]
            transaction["state"] = ("TRANSIENT_WAITING_FOR_ACKS"
                                     if transaction["required_acknowledgements"]
                                     else "TRANSIENT_WAITING_FOR_GRANT"
                                     if transaction["required_grants"]
                                     else "TRANSIENT_WAITING_FOR_HOME")
            transaction["state_history"].append({"state": transaction["state"],
                                                 "time_s": ratio(self.now)})
        return tuple(plan["protocol_messages"])

    def protocol_message_completed(self, record, message_id, attempt, now):
        plan = record.get("msi_plan")
        if plan is None:
            raise EvidenceInvalid("MSI message retired without its transaction plan")
        message = next((row for row in plan.get("protocol_messages", ())
                        if row["message_id"] == message_id), None)
        if message is None:
            raise EvidenceInvalid(f"unknown MSI protocol message {message_id!r}")
        if attempt not in message["delivered_attempts"]:
            message["delivered_attempts"].append(attempt)
        record.setdefault("msi_protocol_log", []).append({
            "message_id": message_id, "attempt": attempt,
            "event": "ack_delivered" if message["acknowledgement"] else "message_delivered",
            "time_s": ratio(now)})
        transaction = next(row for row in reversed(self.msi_transactions)
                            if row["transaction"] == plan["transaction_id"])
        delivered = {message["message_id"]
                     for message in plan["protocol_messages"]
                     if message["delivered_attempts"]}
        acknowledgements_ready = set(
            transaction.get("required_acknowledgements", ())) <= delivered
        grants_ready = set(transaction.get("required_grants", ())) <= delivered
        next_state = ("TRANSIENT_WAITING_FOR_ACKS" if not acknowledgements_ready
                      else "TRANSIENT_WAITING_FOR_GRANT" if not grants_ready
                      else "TRANSIENT_WAITING_FOR_HOME")
        if transaction["state"] != next_state:
            transaction["state"] = next_state
            transaction["state_history"].append({
                "state": transaction["state"], "time_s": ratio(now)})

    def _commit_msi_delta(self, plan):
        """Apply one home-arbitrated MSI transition after required network ACKs."""
        delta = plan.get("_commit_delta")
        if delta is None:
            for name, amount in plan.get("statistics", {}).items():
                self.msi_stats[name] += amount
            return
        transaction = next((row for row in reversed(self.msi_transactions)
                            if row["transaction"] == plan.get("transaction_id")), None)
        if transaction is None:
            raise EvidenceInvalid("MSI commit has no home transaction")
        for message_id in (*transaction.get("required_acknowledgements", ()),
                           *transaction.get("required_grants", ())):
            message = next((row for row in plan.get("protocol_messages", ())
                            if row["message_id"] == message_id), None)
            if message is None or not message["delivered_attempts"]:
                raise EvidenceInvalid(
                    f"MSI ownership transition preceded required message {message_id}")

        def current_entry(key):
            return self._msi_entry_document(self._msi_entry_copy(
                self.msi_directory.get(key)))

        for row in delta["directory"]:
            key = tuple(row["line"])
            if current_entry(key) != row["before"]:
                raise EvidenceInvalid(
                    "MSI home arbitration changed directory state before its scheduled commit")
        for row in delta["caches"]:
            key = tuple(row["line"])
            if self.msi_caches[row["requester"]].get(key) != row["before"]:
                raise EvidenceInvalid(
                    "MSI home arbitration changed requester-cache state before its scheduled commit")
        for row in delta["backing"]:
            key = tuple(row["line"])
            current = self.msi_backing_projection.get(key)
            if (current.hex() if current is not None else None) != row["before"]:
                raise EvidenceInvalid(
                    "MSI backing projection changed before its scheduled commit")

        for row in delta["directory"]:
            key = tuple(row["line"])
            after = row["after"]
            self.msi_directory[key] = {
                "state": after["state"], "sharers": set(after["sharers"]),
                "dirty_owner": after["dirty_owner"],
                "dirty_data": after["dirty_data"]}
        for row in delta["caches"]:
            key = tuple(row["line"])
            cache = self.msi_caches[row["requester"]]
            if row["after"] is None:
                cache.pop(key, None)
            else:
                cache[key] = row["after"]
        for endpoint, line in delta["cache_touches"]:
            self.msi_caches[endpoint].move_to_end(tuple(line))
        for row in delta["backing"]:
            key = tuple(row["line"])
            if row["after"] is None:
                self.msi_backing_projection.pop(key, None)
            else:
                self.msi_backing_projection[key] = bytes.fromhex(row["after"])
        transaction["committed_directory"] = [
            {"line": row["line"], **self._msi_entry_document(
                self.msi_directory[tuple(row["line"])])}
            for row in delta["directory"]]
        for name, amount in delta["statistics"].items():
            self.msi_stats[name] += amount


