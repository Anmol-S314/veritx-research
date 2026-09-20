"""veritx_dse.wavee.metrics — re-derived metrics from a schedule (§45/§46).

Every metric here is computed FROM a verified ``Schedule`` — never
trusted from a persisted summary (§74). Definitions:

- makespan: max(end) - min(start) (scheduler-owned).
- critical path: the longest causal chain of the scheduled DAG by
  duration; ties broken by semantic event id. NOT "largest busy time".
- utilization (exclusive): occupied capacity-time / (capacity x window),
  window = makespan (§46); bandwidth resources report bytes and the
  capacity integral (byte-seconds).
- request latency: completion - arrival for events bound to an explicit
  request (§53); distributions carry sample_count; unsupported metrics
  are absent, never zero (§97).
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from veritx_dse.wavee.model import (
    RESOURCE_KIND_BANDWIDTH, RESOURCE_KIND_EXCLUSIVE,
    WaveEPerformanceModel,
)
from veritx_dse.wavee.scheduler import Schedule
from veritx_dse.wavee.time import QTime
from veritx_dse.wavee.workload import (
    EVENT_NETWORK_OPERATION_REF, WaveETemporalWorkload,
)


def critical_path(workload: WaveETemporalWorkload, schedule: Schedule,
                  ) -> tuple[tuple[str, ...], QTime]:
    """Longest causal chain under scheduled durations (§45).

    Chain length = sum of scheduled durations along a dependency chain,
    maximized over the event DAG; ties broken by semantic event id
    ordering (deterministic). This is NOT "largest total busy time".
    Iterative memoized evaluation: safe for deep chains (§140).
    """
    by_id = {e.event_id: e for e in workload.events}
    if not schedule.events:
        return (), QTime.zero()
    # topological order over dependencies (acyclic by §17 law)
    indeg = {eid: len(by_id[eid].deps) for eid in by_id}
    dependents: dict[str, list[str]] = {eid: [] for eid in by_id}
    for e in workload.events:
        for d in e.deps:
            dependents[d].append(e.event_id)
    order: list[str] = [eid for eid, n in indeg.items() if n == 0]
    i = 0
    while i < len(order):
        for dep in dependents[order[i]]:
            indeg[dep] -= 1
            if indeg[dep] == 0:
                order.append(dep)
        i += 1
    if len(order) != len(by_id):  # pragma: no cover - §17 refuses cycles
        raise ValueError("cycle in event graph; workload validation bug")
    # longest_from(eid): (duration-sum, path) of the longest chain that
    # ENDS at eid (walking backward through deps). Process in topo order
    # so every event's deps are resolved before it.
    best_at: dict[str, tuple[Fraction, tuple[str, ...]]] = {}
    for eid in order:
        s = schedule.get(eid)
        dur = s.end.q - s.start.q
        best_len = dur
        best_pred: tuple[str, ...] = (eid,)
        for dep_id in sorted(by_id[eid].deps):
            sub_len, sub_path = best_at[dep_id]
            if dur + sub_len > best_len:
                best_len = dur + sub_len
                best_pred = (eid,) + sub_path
        best_at[eid] = (best_len, best_pred)
    best_len = Fraction(0)
    best_path: tuple[str, ...] = ()
    for eid in sorted(best_at):  # deterministic tie-break by id
        ln, path = best_at[eid]
        if ln > best_len:
            best_len, best_path = ln, path
    return best_path, QTime(best_len)


def resource_utilization(workload: WaveETemporalWorkload,
                         schedule: Schedule) -> dict[str, dict[str, Any]]:
    """§46: exact utilization per resource over the makespan window."""
    model = workload.performance_model
    if not schedule.events:
        return {}
    window = schedule.makespan().q
    if window == 0:
        window = Fraction(1)  # degenerate: avoid /0, report zeros
    out: dict[str, dict[str, Any]] = {}
    for rdef in model.resources:
        if rdef.kind == RESOURCE_KIND_EXCLUSIVE:
            cap = rdef.capacity or 1
            occupied = Fraction(0)
            for s in schedule.events:
                if s.resource == rdef.name:
                    occupied += s.end.q - s.start.q
            util = float(occupied / (cap * window))
            if occupied > cap * window:
                raise ValueError(
                    f"exclusive resource {rdef.name!r} is occupied "
                    f"{occupied}s in a window of {window}s with capacity "
                    f"{cap}: the schedule exceeds the resource capacity "
                    f"(infeasible schedule)")
            out[rdef.name] = {
                "kind": "EXCLUSIVE",
                "capacity": cap,
                "occupied_time": QTime(occupied).to_dict(),
                "window": QTime(window).to_dict(),
                "utilization": util,
            }
        else:
            # For a fluid transfer the capacity integral is EXACTLY the
            # bytes it moved (rate x dt integrated == bytes). Using the
            # recorded average rate here would be equivalent; using the
            # final instantaneous rate would not — that was a real bug
            # (a shared transfer's share changes at every boundary).
            moved_bytes = Fraction(0)
            for s in schedule.events:
                if s.resource != rdef.name:
                    continue
                moved_bytes += Fraction(s.bytes_moved)
            capacity_integral = moved_bytes
            util = float(capacity_integral / (rdef.bandwidth_bps * window))
            if capacity_integral > rdef.bandwidth_bps * window:
                raise ValueError(
                    f"bandwidth resource {rdef.name!r} moved "
                    f"{moved_bytes} bytes in a window of {window}s at "
                    f"{rdef.bandwidth_bps} B/s: the schedule exceeds the "
                    f"resource capacity (infeasible schedule)")
            out[rdef.name] = {
                "kind": "BANDWIDTH",
                "bandwidth_bps": {
                    "num": rdef.bandwidth_bps.numerator,
                    "den": rdef.bandwidth_bps.denominator},
                "bytes_moved": moved_bytes,
                "byte_seconds": capacity_integral,
                "window": QTime(window).to_dict(),
                "utilization": util,
            }
    return out


def request_latencies(workload: WaveETemporalWorkload,
                      schedule: Schedule) -> list[dict[str, Any]]:
    """§53: latency = completion - arrival per explicit request.

    Completion = max end over the request's completion events (or all
    events the request owns when none declared). Requests without any
    bound completion event produce NO entry (unsupported, not zero).
    """
    by_id = {e.event_id: e for e in workload.events}
    rows: list[dict[str, Any]] = []
    for req in workload.requests:
        owned = [e for e in workload.events if e.request_id == req.request_id]
        comp_ids = list(req.completion_event_ids) or \
            [e.event_id for e in owned]
        if not comp_ids:
            continue
        end = max(schedule.get(cid).end.q for cid in comp_ids)
        lat = end - req.arrival.q
        if lat < 0:
            raise ValueError(
                f"request {req.request_id!r} completes before arrival; "
                f"workload timing is inconsistent")
        ft = None
        if req.first_token_event_id:
            ft_end = schedule.get(req.first_token_event_id).end.q
            ft_lat = ft_end - req.arrival.q
            if ft_lat < 0:
                raise ValueError(
                    f"request {req.request_id!r} first-token event "
                    f"{req.first_token_event_id!r} completes before the "
                    f"request arrives; refusing a negative time-to-first-"
                    f"token")
            ft = QTime(ft_lat).to_dict()
        rows.append({
            "request_id": req.request_id,
            "arrival": req.arrival.to_dict(),
            "completion": QTime(end).to_dict(),
            "latency": QTime(lat).to_dict(),
            "first_token_latency": ft,
        })
    return rows


def latency_summary(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Distribution summary with mandatory sample_count (§53)."""
    if not rows:
        return None
    lats = sorted(Fraction(r["latency"]["numerator"],
                           r["latency"]["denominator"]) for r in rows)

    def pct(p: float) -> Fraction:
        if len(lats) == 1:
            return lats[0]
        idx = min(len(lats) - 1, int(p * (len(lats) - 1) + 0.5))
        return lats[idx]

    return {
        "sample_count": len(lats),
        "mean": QTime(sum(lats) / len(lats)).to_dict(),
        "median": QTime(lats[len(lats) // 2]).to_dict(),
        "p95": QTime(pct(0.95)).to_dict(),
        "max": QTime(lats[-1]).to_dict(),
    }
