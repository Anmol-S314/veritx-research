"""veritx_dse.wavee.scheduler — deterministic discrete-event scheduler (§33/§34).

One authoritative scheduler. Event boundaries are dependency
completions, resource releases, bandwidth completions, and future
ready times — never fixed timesteps (§32). Two resource classes from
the model:

- EXCLUSIVE capacity ``c``: at most ``c`` simultaneous claims. FIFO
  under contention ordered by earliest-ready time, then semantic event
  id (§20/§33; no set iteration, no host time).
- BANDWIDTH ``B`` bytes/s: fluid EQUAL_SHARE among active transfers.
  An arriving transfer joins the active set at its own ready time;
  every active transfer's rate is recomputed at each boundary
  (event-driven fluid equal sharing, §31).

Ready-time gate: an event is admitted only when every predecessor has
finished — a dependent entering the heap at admission time carries a
*future* ready time and acts as a future arrival, never as an
immediate start. This is what keeps fluid sharing causal: a transfer
cannot consume bandwidth before it begins.

Invariants enforced and tested (§34): start >= every predecessor end;
capacity never exceeded; start <= end; each event executes exactly
once; quiescence schedules everything. Unfinished events with no
runnable progress raise typed ``SchedulerDeadlock`` (§35: never spin).

All quantities are exact rational seconds (``QTime``/``Fraction``).
"""
from __future__ import annotations


def _freeze(self, name: str, value: object) -> None:
    raise AttributeError(
        f"{type(self).__name__} is immutable (Wave-E §11); construct a new instance instead")

import heapq
from fractions import Fraction
from typing import Any

from veritx_dse.wavee.model import (
    ARBITRATION_EQUAL_SHARE, ARBITRATION_FIFO,
    RESOURCE_KIND_BANDWIDTH, RESOURCE_KIND_EXCLUSIVE,
    WaveEPerformanceModel,
)
from veritx_dse.wavee.time import QTime, TimeError
from veritx_dse.wavee.workload import (
    EVENT_NETWORK_OPERATION_REF, MEMORY_KINDS, WaveETemporalEvent,
    WaveETemporalWorkload,
)


class SchedulerError(Exception):
    code = "SCHEDULER_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SchedulerDeadlock(SchedulerError):
    """Unfinished events with no runnable progress (§35)."""

    code = "SCHEDULER_DEADLOCK"


class ScheduledEvent:
    """One event's scheduled interval + allocation (§117)."""

    __slots__ = ("event_id", "start", "end", "resource",
                 "bandwidth_allocated_bps")

    __setattr__ = _freeze

    def __init__(self, event_id: str, start: QTime, end: QTime,
                 resource: str | None,
                 bandwidth_allocated_bps: Fraction | None = None) -> None:
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "resource", resource)
        object.__setattr__(self, "bandwidth_allocated_bps",
                           bandwidth_allocated_bps)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event_id": self.event_id,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }
        if self.resource is not None:
            d["resource"] = self.resource
        if self.bandwidth_allocated_bps is not None:
            d["bandwidth_allocated_bps"] = {
                "num": self.bandwidth_allocated_bps.numerator,
                "den": self.bandwidth_allocated_bps.denominator}
        return d


class Schedule:
    """Canonical, byte-identical schedule for identical inputs (§116)."""

    __slots__ = ("events", "_by_id")

    __setattr__ = _freeze

    def __init__(self, events: tuple[ScheduledEvent, ...]) -> None:
        object.__setattr__(self, "events", tuple(sorted(
            events, key=lambda s: s.event_id)))
        object.__setattr__(self, "_by_id",
                           {s.event_id: s for s in self.events})

    def __len__(self) -> int:
        return len(self.events)

    def get(self, event_id: str) -> ScheduledEvent:
        return self._by_id[event_id]

    def start(self, event_id: str) -> QTime:
        return self._by_id[event_id].start

    def end(self, event_id: str) -> QTime:
        return self._by_id[event_id].end

    def makespan(self) -> QTime:
        """max(end) - min(start) over the scheduled domain (§16)."""
        if not self.events:
            return QTime.zero()
        lo = min(s.start.q for s in self.events)
        hi = max(s.end.q for s in self.events)
        return QTime(hi - lo)

    def to_dict(self) -> dict[str, Any]:
        return {"events": [s.to_dict() for s in self.events]}


def _duration_of(e: WaveETemporalEvent, model: WaveEPerformanceModel
                 ) -> QTime:
    """Duration under the model's compute source (§22).

    EXPLICIT mode uses the declared duration verbatim (trustworthy
    relative-to-model baseline, §92). ANALYTICAL mode derives memory
    event durations from the resource rate law ``T = bytes / BW``; other
    events keep their declared duration (no fabricated FLOPs model).
    """
    if model.compute_source == "ANALYTICAL_MODEL" and \
            e.kind in MEMORY_KINDS and e.resource is not None:
        from veritx_dse.wavee.model import rate_duration
        rdef = model.resource(e.resource)
        if rdef.kind == RESOURCE_KIND_BANDWIDTH:
            return QTime(rate_duration(e.bytes_count or 0,
                                       rdef.bandwidth_bps))
    return e.duration


def schedule_workload(workload: WaveETemporalWorkload, *,
                      network_durations: dict[str, QTime] | None = None
                      ) -> Schedule:
    """Deterministic earliest-start schedule under model policies.

    ``network_durations`` maps NETWORK_OPERATION_REF event ids to exact
    durations bound to qualified backend evidence (§36/§42); events not
    present there keep their declared duration. The caller — never the
    scheduler — owns the evidence seam (§113).
    """
    model = workload.performance_model
    # §20: the contention policy is declared in the model, not assumed
    # here. An unknown policy refuses rather than silently scheduling
    # under FIFO.
    if model.arbitration_exclusive != ARBITRATION_FIFO:
        raise SchedulerError(
            f"unsupported exclusive arbitration "
            f"{model.arbitration_exclusive!r}")
    if model.arbitration_bandwidth != ARBITRATION_EQUAL_SHARE:
        raise SchedulerError(
            f"unsupported bandwidth arbitration "
            f"{model.arbitration_bandwidth!r}")
    net = dict(network_durations or {})
    by_id = {e.event_id: e for e in workload.events}

    # §36/§42: a NETWORK_OPERATION_REF with no evidence-bound duration
    # would silently schedule at its declared placeholder (0) — i.e.
    # claim the network is free without any timing authority. Refuse:
    # network time enters ONLY through the evidence seam.
    unbound = sorted(e.event_id for e in workload.events
                     if e.kind == EVENT_NETWORK_OPERATION_REF
                     and e.event_id not in net)
    if unbound:
        raise TimeError(
            f"NETWORK_OPERATION_REF events {unbound} have no "
            f"evidence-bound duration; network timing requires qualified "
            f"backend evidence (§36/§42) — refusing to treat the "
            f"network as free")

    deps_of: dict[str, tuple[str, ...]] = {}
    dependents: dict[str, list[str]] = {eid: [] for eid in by_id}
    for e in workload.events:
        ds = tuple(sorted(set(e.deps)))
        deps_of[e.event_id] = ds
        for d in ds:
            dependents[d].append(e.event_id)

    finish: dict[str, Fraction] = {}
    scheduled: dict[str, ScheduledEvent] = {}
    # exclusive resources: name -> list of (end_q, event_id) active
    exclusive_busy: dict[str, list[tuple[Fraction, str]]] = {}
    # bandwidth: name -> [eid, remaining_bytes, rate, t_ref, start_q]
    #   remaining_bytes is measured at t_ref; start_q is the ORIGINAL
    #   start (reported in the schedule) — never advanced.
    bw_active: dict[str, list[list[Any]]] = {}

    ready_heap: list[tuple[Fraction, str]] = []  # (ready_q, event_id)
    indegree = {eid: len(ds) for eid, ds in deps_of.items()}

    def ready_time(eid: str) -> Fraction:
        ds = deps_of[eid]
        if not ds:
            return Fraction(0)
        return max(finish[d] for d in ds)

    def push_ready(eid: str) -> None:
        heapq.heappush(ready_heap, (ready_time(eid), eid))

    for eid, deg in indegree.items():
        if deg == 0:
            push_ready(eid)

    def complete(eid: str) -> None:
        for dep in dependents.get(eid, []):
            indegree[dep] -= 1
            if indegree[dep] == 0:
                push_ready(dep)

    t_now = Fraction(0)
    n_events = len(by_id)

    def admit_one() -> bool:
        """Schedule the single best ADMISSIBLE ready event, or False.

        Admissible = ready_time <= t_now AND its resource has room
        (exclusive) / is shareable (bandwidth). Candidate order is
        earliest-ready then semantic id — fully deterministic (§33).
        """
        nonlocal ready_heap
        candidates: list[tuple[Fraction, str]] = []
        for rq, eid in ready_heap:
            if eid in scheduled:
                continue
            if rq > t_now:  # ready-time gate: future arrival
                continue
            e = by_id[eid]
            if e.resource is None:
                candidates.append((rq, eid))
                continue
            rdef = model.resource(e.resource)
            if rdef.kind == RESOURCE_KIND_EXCLUSIVE:
                if len(exclusive_busy.get(e.resource, [])) < \
                        (rdef.capacity or 1):
                    candidates.append((rq, eid))
            else:  # BANDWIDTH: always admissible, sharing adapts
                candidates.append((rq, eid))
        if not candidates:
            return False
        candidates.sort()
        rq, eid = candidates[0]
        ready_heap = [(a, b) for (a, b) in ready_heap if b != eid]
        heapq.heapify(ready_heap)
        e = by_id[eid]
        dur = net[eid] if eid in net else _duration_of(e, model)

        if e.resource is None:
            start_q = rq
            end_q = start_q + dur.q
            scheduled[eid] = ScheduledEvent(eid, QTime(start_q),
                                            QTime(end_q), None)
            finish[eid] = end_q
            complete(eid)
            return True

        rdef = model.resource(e.resource)
        if rdef.kind == RESOURCE_KIND_EXCLUSIVE:
            start_q = max(rq, t_now)  # never start in the past
            end_q = start_q + dur.q
            exclusive_busy.setdefault(e.resource, []).append((end_q, eid))
            scheduled[eid] = ScheduledEvent(eid, QTime(start_q),
                                            QTime(end_q), e.resource)
            # finish is deterministic at admission; dependents become
            # future heap arrivals gated by their ready time.
            finish[eid] = end_q
            complete(eid)
            return True

        # BANDWIDTH transfer: joins the active set at its own ready
        # time (== now by the gate) — never before it begins (§31).
        state = bw_active.setdefault(e.resource, [])
        start_q = max(rq, t_now)
        work_bytes = Fraction(e.bytes_count or 0)
        if work_bytes == 0:
            # zero-byte transfer: declared duration only (latency-like)
            end_q = start_q + dur.q
            scheduled[eid] = ScheduledEvent(
                eid, QTime(start_q), QTime(end_q), e.resource,
                bandwidth_allocated_bps=Fraction(0))
            finish[eid] = end_q
            complete(eid)
            return True
        state.append([eid, work_bytes, None, start_q, start_q])
        _recompute_bandwidth(state, rdef.bandwidth_bps)
        return True

    while len(scheduled) < n_events:
        # 0+1) fixed point: release capacity that is DUE (q <= t_now,
        #      zero-duration events complete immediately) and admit what
        #      fits, until neither can make progress
        progressed = True
        while progressed:
            progressed = False
            for busy in list(exclusive_busy.values()):
                due = any(q <= t_now for (q, _eid) in busy)
                if due:
                    busy[:] = [(q, eid) for (q, eid) in busy if q > t_now]
                    progressed = True
            while admit_one():
                progressed = True
        if len(scheduled) == n_events:
            break

        # 2) advance to the next STRICTLY FUTURE boundary: a future
        #    arrival, an exclusive release, or a fluid completion
        next_arrivals = [rq for rq, eid in ready_heap
                         if eid not in scheduled and rq > t_now]
        next_releases = [q for busy in exclusive_busy.values()
                         for (q, _eid) in busy if q > t_now]
        fluid_bounds = []
        for state in bw_active.values():
            for item in state:
                _eid, remaining, rate, t_ref, _start = item
                if rate and rate > 0:
                    b = t_ref + remaining / rate
                    if b > t_now:
                        fluid_bounds.append(b)
        if not next_arrivals and not next_releases and not fluid_bounds:
            waiting = sorted(set(by_id) - set(scheduled))
            raise SchedulerDeadlock(
                f"scheduler stalled at t={t_now}: {len(waiting)} unscheduled "
                f"events with no runnable progress (first: {waiting[0]!r}) "
                f"(§35)")
        t_next = min(next_arrivals + next_releases + fluid_bounds)
        if t_next <= t_now:
            raise SchedulerDeadlock(
                f"scheduler boundary did not advance at t={t_now} (§35)")
        t_now = t_next

        # 3) release exclusive capacity (finish/propagation already
        #    happened deterministically at admission)
        for busy in list(exclusive_busy.values()):
            busy[:] = [(q, eid) for (q, eid) in busy if q > t_now]

        # 4) complete / advance bandwidth transfers at t_now
        for rname, state in list(bw_active.items()):
            rdef = model.resource(rname)
            still: list[list[Any]] = []
            for item in state:
                eid, remaining, rate, t_ref = item[0], item[1], item[2], item[3]
                start_q = item[4]  # ORIGINAL start — never advanced
                end_q = t_ref + remaining / rate
                if rate and rate > 0 and end_q <= t_now:
                    scheduled[eid] = ScheduledEvent(
                        eid, QTime(start_q), QTime(end_q), rname,
                        bandwidth_allocated_bps=rate)
                    finish[eid] = end_q
                    complete(eid)
                else:
                    if rate and rate > 0 and t_now > t_ref:
                        item[1] = remaining - rate * (t_now - t_ref)
                        item[3] = t_now
                    still.append(item)
            bw_active[rname] = still
            if still:
                _recompute_bandwidth(still, rdef.bandwidth_bps)

    return Schedule(tuple(scheduled.values()))


def _recompute_bandwidth(state: list[list[Any]], total: Fraction) -> None:
    """EQUAL_SHARE: every active transfer gets total/n (§31)."""
    if not state:
        return
    share = total / len(state)
    for item in state:
        item[2] = share
