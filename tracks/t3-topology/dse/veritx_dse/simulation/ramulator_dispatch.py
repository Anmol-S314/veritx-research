"""Multi-pool native callback dispatcher for the Ramulator backend."""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from veritx_dse.simulation.ramulator import (
    FIDELITY, SUPPORTED_PAIRS, MemoryEvidence, RamulatorBackend,
    RamulatorError, _metric, _sha256_hex,
)


def execute_dispatch(artifact, manifest: dict[str, Any], *,
                     backend: RamulatorBackend, run_dir: str | Path,
                     max_ticks: int = 1_000_000,
                     max_outstanding: int | None = None) -> MemoryEvidence:
    """Run an ordered dependency dispatcher on one native memory system.

    Native channels share one tick authority. Callback completion, not input
    serialization or acceptance, releases dependent semantic accesses.
    """
    from veritx_dse.workload.memory_lowering import (
        CHANNEL_INTERLEAVED, RAMULATOR_BACKPRESSURE_POLICY,
        RAMULATOR_DISPATCHER_V1, RAMULATOR_DISPATCHER_VERSION,
        RamulatorGeometry,
        ramulator_dispatch_config_payload,
    )
    if not backend.ready:
        raise RamulatorError("Ramulator native extension is unavailable")
    rundir = Path(run_dir)
    rundir.mkdir(parents=True, exist_ok=True)
    md = json.loads(json.dumps(manifest))
    expected_hash = md.pop("dispatch_input_hash", None)
    recomputed_hash = _sha256_hex(json.dumps(
        md, sort_keys=True, separators=(",", ":")).encode())
    if expected_hash != recomputed_hash:
        raise RamulatorError("dispatch manifest hash mismatch")
    if artifact.artifact_hash != md.get("source_memory_artifact_hash") or \
            artifact.access_stream_hash != md.get("access_stream_hash"):
        raise RamulatorError("dispatch manifest does not bind supplied artifact")
    dispatcher_version = md.get("dispatcher")
    retry_policy = md.get("backpressure_retry_policy")
    legacy_backpressure = (dispatcher_version == RAMULATOR_DISPATCHER_V1 and
                           retry_policy is None)
    if not legacy_backpressure and not (
            dispatcher_version == RAMULATOR_DISPATCHER_VERSION and
            retry_policy == RAMULATOR_BACKPRESSURE_POLICY):
        raise RamulatorError("dispatch engine/policy version is unsupported")
    geo = RamulatorGeometry.from_dict(md["geometry_per_pool"])
    devices = tuple(int(d) for d in md["device_channel_groups"])
    channels_per_pool = geo.channels
    config_hash = _sha256_hex(ramulator_dispatch_config_payload(
        geo, devices, geo.transaction_bytes, md.get("mapping_algorithm"),
        dispatcher_version=dispatcher_version,
        backpressure_retry_policy=retry_policy))
    if config_hash != md.get("backend_config_hash"):
        raise RamulatorError("dispatch config identity does not recompute")
    if geo.channels > 1 and md.get("mapping_algorithm") != CHANNEL_INTERLEAVED:
        raise RamulatorError("native channel groups require channel interleaved mapping")
    if (geo.dram_class, geo.controller) not in SUPPORTED_PAIRS:
        raise RamulatorError(
            f"dispatch geometry {geo.dram_class}/{geo.controller} is outside "
            f"the audited native envelope {sorted(SUPPORTED_PAIRS)}")
    base = {"producer": backend.producer(), "fidelity": FIDELITY,
            "memory_artifact_hash": artifact.artifact_hash,
            "lowering_manifest_hash": _sha256_hex(json.dumps(
                manifest, sort_keys=True, separators=(",", ":")).encode()),
            "backend_input_hash": expected_hash,
            "backend_config_hash": config_hash}
    if max_outstanding is None:
        max_outstanding = int(md["dispatcher_max_outstanding"])
    if max_outstanding != md["dispatcher_max_outstanding"]:
        raise RamulatorError(
            "dispatcher outstanding limit does not match the prepared "
            "configuration identity")
    transactions = md.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise RamulatorError("dispatch ledger has no native requests")
    if max_ticks < 1 or max_outstanding < 1:
        raise RamulatorError("dispatcher bounds must be positive")
    active_channels = len(devices) * channels_per_pool
    padding = md.get("controller_padding")
    expected_channels = (padding.get("native_controller_count")
                         if isinstance(padding, dict) else active_channels)
    if not isinstance(expected_channels, int) or isinstance(expected_channels, bool) or \
            expected_channels < active_channels or \
            expected_channels & (expected_channels - 1):
        raise RamulatorError("dispatch native controller count is invalid")
    if padding is not None and padding != {
            "policy": "inactive_power_of_two_tail_v1",
            "active_channels": active_channels,
            "native_controller_count": expected_channels,
            "inactive_channels": list(range(active_channels,
                                             expected_channels))}:
        raise RamulatorError("dispatch controller padding contract is invalid")
    if padding is None and expected_channels != active_channels:
        raise RamulatorError("dispatch omits required controller padding")
    dispatch_started = time.monotonic()
    for row in transactions:
        if row.get("native_channel", -1) < 0 or \
                row["native_channel"] >= active_channels or \
                row.get("native_transaction_bytes") != geo.transaction_bytes:
            raise RamulatorError("dispatch request has invalid native route/size")

    import sys
    package_dir = str(backend.package_dir)
    added_path = package_dir not in sys.path
    if added_path:
        sys.path.insert(0, package_dir)
    try:
        import ramulator
        from ramulator import _ramulator
        # The constructor requires a frontend, but this dispatcher owns
        # admission through send(). The empty trace is inert by construction
        # (is_finished() is true at length 0) and its identity is recorded
        # in the evidence so "inert frontend" is auditable, not asserted.
        frontend_path = rundir / "empty.trace"
        frontend_path.write_text("", encoding="utf-8")
        frontend_identity = _sha256_hex(frontend_path.read_bytes())
        ctrls = []
        for _ in range(expected_channels):
            ctrls.append(ramulator.controller.HBM34(
                dram=ramulator.dram.HBM3(
                    org_preset=geo.org_preset,
                    timing_preset=geo.timing_preset),
                scheduler=ramulator.scheduler.FRFCFS(),
                read_buffer_size=md["native_queue_sizes"]["read"],
                write_buffer_size=md["native_queue_sizes"]["write"],
                row_policy=ramulator.row_policy.Open(),
                addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
                refresh_manager=ramulator.refresh_manager.NoRefresh()))
        memory = ramulator.memory_system.GenericDRAM(
            clock_ratio=1, controllers=ctrls,
            channel_mapper=ramulator.channel_mapper.Gem5PortInterleave(
                interleave_size=geo.transaction_bytes))
        frontend = ramulator.frontend.ReadWriteTrace(
            clock_ratio=1, path=str(frontend_path))
        sim = _ramulator.Simulation({
            "frontend": frontend.to_config(),
            "memory_system": memory.to_config()})
        if sim.tx_bytes != geo.transaction_bytes:
            sim.finalize()
            return MemoryEvidence(
                status="UNSUPPORTED",
                failure_reason=(f"native Ramulator transaction size "
                               f"{sim.tx_bytes}B differs from dispatch "
                               f"geometry {geo.transaction_bytes}B"),
                metrics={}, assumptions=(), semantic_losses=(), raw={}, **base)

        access_rows: dict[str, list[dict[str, Any]]] = {}
        access_deps = md["access_dependencies"]
        access_order: list[str] = []
        for row in transactions:
            if row["access_id"] not in access_rows:
                access_order.append(row["access_id"])
                access_rows[row["access_id"]] = []
            access_rows[row["access_id"]].append(row)
        if set(access_deps) != set(access_order) or any(
                dep not in access_rows
                for deps in access_deps.values() for dep in deps):
            raise RamulatorError(
                "dispatch dependency edges do not name exactly the accesses "
                "present in the ledger")
        # Dependency state is per ACCESS, not per transaction: an access is
        # ready when every predecessor access has callback-completed all of
        # its transactions. The ready deque holds only accesses that can
        # still issue, so a tick costs the ready work, not the whole ledger.
        access_total = {aid: len(rows) for aid, rows in access_rows.items()}
        access_issued = {aid: 0 for aid in access_rows}
        access_remaining = {aid: total for aid, total in access_total.items()}
        dependents: dict[str, list[str]] = {aid: [] for aid in access_order}
        deps_pending: dict[str, int] = {}
        for aid in access_order:
            for dep in access_deps[aid]:
                if dep == aid:
                    raise RamulatorError(
                        f"access {aid!r} depends on itself")
                dependents[dep].append(aid)
            deps_pending[aid] = len(access_deps[aid])
        ready: deque[str] = deque(
            aid for aid in access_order if deps_pending[aid] == 0)
        states = {row["transaction_id"]: "unissued" for row in transactions}
        by_id = {row["transaction_id"]: row for row in transactions}
        callbacks: list[tuple[str, int, int, int, int]] = []
        accepted_by_channel = [dict(read=0, write=0)
                               for _ in range(expected_channels)]
        completed_by_channel = [dict(read=0, write=0)
                                for _ in range(expected_channels)]
        event_ledger: list[dict[str, Any]] = []
        events_dropped = 0
        backpressure_retries: dict[str, int] = {}
        blocked_queues: set[tuple[int, str]] = set()
        outstanding = 0
        completed_transaction_count = 0
        current_tick = 0
        failure = ""

        def record_event(kind: str, tid: str, ch: int, tick: int) -> None:
            nonlocal events_dropped
            if len(event_ledger) >= DISPATCH_EVENT_LIMIT:
                events_dropped += 1
                return
            event_ledger.append({"event": kind, "transaction_id": tid,
                                 "tick": tick, "native_channel": ch})

        def accept_callback(tid: str, addr: int, typ: int, size: int) -> None:
            # current_tick, not sim: a closure holding sim would keep the
            # native Simulation alive in a reference cycle.
            callbacks.append((tid, addr, typ, size, current_tick))

        def drain_callbacks() -> None:
            """Commit buffered native callbacks after acceptance is recorded.

            The controller may call back synchronously inside send() (a
            coalesced write) or during the next tick() (a served read or
            write). Either way the correlation record already exists and the
            transaction is already marked accepted, so a callback here is
            exactly-once and exactly post-acceptance.
            """
            nonlocal outstanding, completed_transaction_count
            while callbacks:
                tid, addr, typ, size, tick = callbacks.pop(0)
                row = by_id.get(tid)
                if row is None or states.get(tid) != "accepted":
                    raise RamulatorError(
                        f"duplicate or unknown native callback for {tid!r} "
                        f"(state {states.get(tid)!r})")
                expected_type = 1 if row["operation"] == "WRITE" else 0
                if (addr, typ, size) != (
                        row["native_address"], expected_type,
                        geo.transaction_bytes):
                    raise RamulatorError(
                        f"native callback mismatch for {tid}: "
                        f"{(addr, typ, size)}")
                states[tid] = "completed"
                completed_transaction_count += 1
                outstanding -= 1
                ch = row["native_channel"]
                side = "write" if expected_type else "read"
                completed_by_channel[ch][side] += 1
                blocked_queues.discard((ch, side))
                aid = row["access_id"]
                access_remaining[aid] -= 1
                if access_remaining[aid] == 0:
                    # The only completion path: a successor is released here
                    # and nowhere else, and only for the whole access.
                    for successor in dependents[aid]:
                        deps_pending[successor] -= 1
                        if deps_pending[successor] == 0:
                            ready.append(successor)
                record_event("callback", tid, ch, tick)

        def verify_lifecycle() -> None:
            accepted_n = sum(v["read"] + v["write"]
                             for v in accepted_by_channel)
            completed_n = sum(v["read"] + v["write"]
                              for v in completed_by_channel)
            if outstanding < 0 or accepted_n != completed_n + outstanding:
                raise RamulatorError(
                    "dispatcher lifecycle conservation failed: accepted "
                    f"{accepted_n} != completed {completed_n} + "
                    f"outstanding {outstanding}")

        try:
            for tick in range(max_ticks):
                sim.tick()
                current_tick = sim.memory_ticks
                drain_callbacks()
                verify_lifecycle()
                if completed_transaction_count == len(transactions):
                    break
                made_attempt = False
                # Round-robin ready accesses. A full native read/write queue
                # is retried only after a matching completion frees capacity.
                while ready and outstanding < max_outstanding:
                    sendable = False
                    stop_issue_loop = False
                    for _ in range(len(ready)):
                        aid = ready[0]
                        issued = access_issued[aid]
                        if issued >= access_total[aid]:
                            ready.popleft()
                            continue
                        row = access_rows[aid][issued]
                        ch = row["native_channel"]
                        side = ("write" if row["operation"] == "WRITE"
                                else "read")
                        if (ch, side) in blocked_queues:
                            ready.rotate(-1)
                            continue
                        sendable = True
                        break
                    if not sendable:
                        break
                    tid = row["transaction_id"]
                    made_attempt = True
                    states[tid] = "sending"
                    callback = lambda addr, typ, size, tid=tid: \
                        accept_callback(tid, addr, typ, size)
                    accepted = sim.send(
                        row["native_address"],
                        1 if side == "write" else 0,
                        geo.transaction_bytes, 0, ch, callback)
                    if accepted:
                        states[tid] = "accepted"
                        accepted_by_channel[ch][side] += 1
                        access_issued[aid] = issued + 1
                        outstanding += 1
                        record_event("accepted", tid, ch, current_tick)
                        if access_issued[aid] >= access_total[aid]:
                            ready.popleft()
                        else:
                            ready.rotate(-1)
                    else:
                        # Ramulator exposes no queue-ready signal. V2 parks
                        # this route/type until a matching callback proves
                        # capacity; V1 retries the head on the next tick.
                        states[tid] = "unissued"
                        if not legacy_backpressure:
                            blocked_queues.add((ch, side))
                        backpressure_retries[tid] = \
                            backpressure_retries.get(tid, 0) + 1
                        if backpressure_retries[tid] == 1:
                            record_event("backpressure", tid, ch, current_tick)
                        if legacy_backpressure:
                            stop_issue_loop = True
                        else:
                            ready.rotate(-1)
                    drain_callbacks()
                    verify_lifecycle()
                    if stop_issue_loop:
                        break
                if not made_attempt and outstanding == 0 and \
                        completed_transaction_count < len(transactions):
                    failure = ("dispatcher deadlock: no ready access and no "
                               "native request in flight")
                    break
            else:
                failure = f"dispatcher exceeded {max_ticks} native ticks"
            if not failure and completed_transaction_count < len(transactions):
                failure = "native dispatch did not fully drain"
            stats_doc = sim.get_stats()
            controller_stats = stats_doc.get("memory_system", {}).get("controller")
            if isinstance(controller_stats, dict):
                controller_stats = [controller_stats]
            if not isinstance(controller_stats, list) or \
                    len(controller_stats) != expected_channels:
                failure = failure or "native controller stats missing/malformed"
                controller_stats = []
            per_controller = []
            for ch in range(expected_channels):
                expected = {"read": sum(
                    r["native_channel"] == ch and r["operation"] == "READ"
                    for r in transactions), "write": sum(
                    r["native_channel"] == ch and r["operation"] == "WRITE"
                    for r in transactions)}
                stats = controller_stats[ch] if ch < len(controller_stats) else {}
                if (stats.get("num_read_reqs") != expected["read"] or
                        stats.get("num_write_reqs") != expected["write"]):
                    failure = failure or (
                        f"native controller {ch} accepted counters differ "
                        f"from ledger: expected {expected}, got "
                        f"R={stats.get('num_read_reqs')} "
                        f"W={stats.get('num_write_reqs')}")
                if (accepted_by_channel[ch] != expected or
                        completed_by_channel[ch] != expected):
                    failure = failure or (
                        f"controller {ch} event reconciliation failed: "
                        f"expected {expected}, accepted "
                        f"{accepted_by_channel[ch]}, completed "
                        f"{completed_by_channel[ch]}")
                if stats:
                    # OBSERVED native semantics (ControllerBase::send /
                    # serve_completed_reads / retire_request, confirmed by a
                    # bounded native probe): a forwarded read is completed by
                    # serve_completed_reads() WITHOUT incrementing
                    # num_read_reqs_served, and a coalesced write is never
                    # served. So accepted = served + forwarded (reads) and
                    # accepted = served + coalesced (writes). Any other
                    # combination is unexplained -> INCONCLUSIVE.
                    reads_served = stats.get("num_read_reqs_served", 0)
                    reads_forwarded = stats.get("num_read_reqs_forwarded", 0)
                    writes_served = stats.get("num_write_reqs_served", 0)
                    writes_coalesced = stats.get("num_write_reqs_coalesced", 0)
                    if (reads_served + reads_forwarded != expected["read"] or
                            writes_served + writes_coalesced !=
                            expected["write"]):
                        failure = failure or (
                            f"controller {ch} native drain counters do not "
                            "reconcile with callbacks and accepted ledger: "
                            f"served R={reads_served} (+forwarded "
                            f"{reads_forwarded}) W={writes_served} "
                            f"(+coalesced {writes_coalesced}) vs expected "
                            f"{expected}")
                per_controller.append({
                    "native_channel": ch, "pool_device_ids": [
                        d for d in devices
                        if md["device_channel_groups"][str(d)]["first_channel"]
                           <= ch < md["device_channel_groups"][str(d)][
                               "first_channel"] + md["device_channel_groups"][
                                   str(d)]["channel_count"]],
                    "expected": expected,
                    "accepted": accepted_by_channel[ch],
                    "completed": completed_by_channel[ch],
                    "native_stats": stats,
                })
            sim.finalize()
        except Exception as exc:
            failure = failure or f"native dispatcher error: {type(exc).__name__}: {exc}"
            try:
                sim.finalize()
            except Exception:
                pass
            stats_doc = {}
            per_controller = []
        finally:
            if added_path:
                try:
                    sys.path.remove(package_dir)
                except ValueError:
                    pass
    except Exception as exc:
        if added_path and package_dir in sys.path:
            sys.path.remove(package_dir)
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason=(f"native dispatcher setup failed: "
                           f"{type(exc).__name__}: {exc}"),
            metrics={}, assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)

    pool_evidence = []
    for device in devices:
        group = md["device_channel_groups"][str(device)]
        channel_ids = list(range(group["first_channel"],
                                 group["first_channel"] +
                                 group["channel_count"]))
        ledger = md["device_ledger"][str(device)]
        pool_evidence.append({
            "declared_device_id": device,
            "native_channels": channel_ids,
            "expected": {
                "read": ledger["read_transactions"],
                "write": ledger["write_transactions"],
                "generated_bytes": ledger["generated_bytes"],
                "padding_bytes": ledger["padding_bytes"]},
            "accepted": {
                "read": sum(accepted_by_channel[ch]["read"]
                            for ch in channel_ids),
                "write": sum(accepted_by_channel[ch]["write"]
                             for ch in channel_ids)},
            "completed": {
                "read": sum(completed_by_channel[ch]["read"]
                            for ch in channel_ids),
                "write": sum(completed_by_channel[ch]["write"]
                             for ch in channel_ids)},
            "native_controllers": [per_controller[ch]
                                   for ch in channel_ids
                                   if ch < len(per_controller)],
        })

    total_rd = md["counts"]["read_transactions"]
    total_wr = md["counts"]["write_transactions"]
    elapsed_ticks = getattr(sim, "memory_ticks", 0)
    generated_requests = total_rd + total_wr
    accepted_requests = sum(x["read"] + x["write"]
                            for x in accepted_by_channel)
    completed_requests = sum(x["read"] + x["write"]
                             for x in completed_by_channel)
    outstanding_requests = accepted_requests - completed_requests
    if outstanding_requests < 0:
        # Never clamp: a negative would hide a conservation defect that
        # verify_lifecycle must already have refused.
        raise RamulatorError(
            f"dispatcher over-completed: accepted {accepted_requests} but "
            f"completed {completed_requests}")
    metrics = {
        "issued_read_transactions": _metric(total_rd, "requests"),
        "issued_write_transactions": _metric(total_wr, "requests"),
        "generated_requests": _metric(generated_requests, "requests"),
        "accepted_requests": _metric(accepted_requests, "requests"),
        "completed_requests": _metric(completed_requests, "requests"),
        "outstanding_requests": _metric(outstanding_requests, "requests"),
        "completion_cycles": _metric(elapsed_ticks, "cycles"),
        "native_clock_period": _metric(sim.tCK_ps, "picoseconds"),
        "completed_read_bytes": _metric(total_rd * geo.transaction_bytes,
                                         "bytes"),
        "completed_write_bytes": _metric(total_wr * geo.transaction_bytes,
                                          "bytes"),
        "wall_time_s": _metric(round(time.monotonic() - dispatch_started, 3),
                                "seconds"),
    }
    aggregate_stats: dict[str, Any] = {}
    for key in ("row_hits", "row_misses", "row_conflicts",
                "num_read_reqs", "num_write_reqs",
                "num_read_reqs_served", "num_read_reqs_forwarded",
                "num_write_reqs_served", "num_write_reqs_coalesced"):
        vals = [item["native_stats"].get(key) for item in per_controller]
        if vals and all(isinstance(v, int) and not isinstance(v, bool)
                        for v in vals):
            aggregate_stats[key] = sum(vals)
    for native_key, metric_key, denominator_key in (
            ("avg_read_latency", "average_read_latency_cycles",
             "num_read_reqs_served"),
            ("avg_write_latency", "average_write_latency_cycles",
             "num_write_reqs_served")):
        numerator = denominator = 0.0
        for item in per_controller:
            stat = item["native_stats"]
            value = stat.get(native_key)
            weight = stat.get(denominator_key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and isinstance(weight, int) and not isinstance(weight, bool):
                numerator += float(value) * weight
                denominator += weight
        if denominator:
            metrics[metric_key] = _metric(numerator / denominator, "cycles")
            aggregate_stats[metric_key] = {
                "value": numerator / denominator,
                "weight": int(denominator),
                "weight_source": denominator_key}
    for key in ("row_hits", "row_misses", "row_conflicts"):
        if key in aggregate_stats:
            metrics[key] = _metric(aggregate_stats[key], "requests")
    controller_cycles = [item["native_stats"].get("cycles")
                         for item in per_controller]
    if not all(isinstance(c, int) and not isinstance(c, bool)
               for c in controller_cycles):
        # Never fall back to elapsed time here: that would present a shared
        # clock as a per-controller cycle count.
        failure = failure or (
            "native controller cycle counters are missing or malformed")
        max_controller_cycles: int | None = None
    else:
        max_controller_cycles = max(controller_cycles)
    raw = {"run_dir": str(rundir), "memory_ticks": elapsed_ticks,
           "native_tCK_ps": sim.tCK_ps,
           "max_controller_cycles": max_controller_cycles,
           "dispatcher_bounds": {"max_ticks": max_ticks,
                                  "max_outstanding": max_outstanding},
           "aggregate_stat_derivation": {
               "integer_counters": "sum across distinct native controllers",
               "latency_means": "weighted by the matching served-request counter "
                                  "(Ramulator's own denominator; a forwarded "
                                  "read adds read_latency without incrementing "
                                  "num_read_reqs_served)",
               "elapsed_cycles": "one shared native memory_ticks authority",
               "controller_cycles": "per-controller cycles are reported raw "
                                    "and never summed into elapsed time"},
           "aggregate_native_stats": aggregate_stats,
           "native_tx_bytes": sim.tx_bytes,
           "device_channel_groups": md["device_channel_groups"],
           "pool_profile_contract": md["pool_profile_contract"],
           "native_frontend": {
               "impl": "ReadWriteTrace",
               "role": "inert constructor placeholder; every request is "
                       "admitted by the host dispatcher via send()",
               "trace_sha256": frontend_identity,
               "trace_bytes": 0},
           "controller_stats": per_controller,
           "pool_stats": pool_evidence,
           "events": event_ledger,
           "event_ledger_limit": DISPATCH_EVENT_LIMIT,
           # The ledger is capped: events_dropped is reported honestly, but
           # the identity commits to the first DISPATCH_EVENT_LIMIT events
           # only. Lowering the limit changes every multi-pool evidence id.
           "events_dropped": events_dropped,
           "backpressure_retry_attempts": sum(backpressure_retries.values()),
           "backpressure_retries_by_transaction": backpressure_retries,
           "generated_transactions": transactions,
           "dispatcher": md["dispatcher"],
           "dependency_policy": md["dependency_policy"]}
    if padding is not None:
        raw["controller_padding"] = padding
    (rundir / "dispatch-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    (rundir / "dispatcher-result.json").write_text(
        json.dumps(raw, sort_keys=True, indent=2) + "\n")
    (rundir / "stdout.log").write_text(
        "direct native dispatch on one GenericDRAM system\n"
        f"native_controllers={expected_channels} "
        f"active_channels={active_channels} devices={list(devices)} "
        f"transactions={generated_requests} "
        f"accepted={accepted_requests} completed={completed_requests} "
        f"ticks={elapsed_ticks} status="
        f"{'PASS' if not failure else 'INCONCLUSIVE'}\n")
    (rundir / "stderr.log").write_text(failure + "\n" if failure else "")
    return MemoryEvidence(
        status="PASS" if not failure else "INCONCLUSIVE",
        failure_reason=failure, metrics=metrics,
        assumptions=("multi-pool model: each HBM_CONTROLLER is one logical "
                     "pool; selected profile channels apply per pool",
                     "pool/profile mapping is diagnostic model intent, not "
                     "physical HBM package equivalence or release qualification",
                     "DRAM timing uses one native shared tick authority; "
                     "declared access dependencies release on native callback"),
        semantic_losses=(), raw=raw, **base)


