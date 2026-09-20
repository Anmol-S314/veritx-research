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
    """One event's scheduled interval + allocation (§117).

    ``bytes_moved`` is the EXACT number of bytes the transfer moved, and
    ``bandwidth_allocated_bps`` is the time-weighted AVERAGE rate over
    the interval (bytes / duration), not the instantaneous rate at
    completion. A fluid transfer's share changes at every boundary, so
    recording only the final instantaneous rate loses the history: the
    average is what integrates back to the bytes actually moved.
    """

    __slots__ = ("event_id", "start", "end", "resource",
                 "bandwidth_allocated_bps", "bytes_moved")

    __setattr__ = _freeze

    def __init__(self, event_id: str, start: QTime, end: QTime,
                 resource: str | None,
                 bandwidth_allocated_bps: Fraction | None = None,
                 bytes_moved: int = 0) -> None:
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "resource", resource)
        object.__setattr__(self, "bandwidth_allocated_bps",
                           bandwidth_allocated_bps)
        object.__setattr__(self, "bytes_moved", bytes_moved)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event_id": self.event_id,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }
        if self.resource is not None:
            d["resource"] = self.resource
        if self.bytes_moved:
            d["bytes_moved"] = self.bytes_moved
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

    # §52/§101: an explicit request arrival is a RELEASE TIME for the
    # work that request owns, and for any event it declares as a root.
    # Without this, arrivals are inert bookkeeping: work could start (and
    # finish) before the request exists, and the latency metric would
    # then have to refuse a workload the scheduler happily accepted.
    # This is what makes multiple explicit arrivals real queueing on
    # shared resources rather than a silently time-zero assumption.
    release: dict[str, Fraction] = {}
    for req in workload.requests:
        gated = {e.event_id for e in workload.events
                 if e.request_id == req.request_id}
        gated |= set(req.root_event_ids)
        for eid in gated:
            if eid in by_id:
                release[eid] = max(release.get(eid, Fraction(0)),
                                   req.arrival.q)

    finish: dict[str, Fraction] = {}
    scheduled: dict[str, ScheduledEvent] = {}
    # exclusive resources: name -> list of (end_q, event_id) active
    exclusive_busy: dict[str, list[tuple[Fraction, str]]] = {}
    # bandwidth: name -> {"items": [...], "total": bytes/s}
    #   item = [eid, remaining_bytes, t_ref, start_q, work_bytes];
    #   remaining_bytes is measured at t_ref; start_q is the ORIGINAL
    #   start (reported in the schedule) — never advanced. The per-item
    #   rate is total/len(items), computed on demand: writing the same
    #   rate into every item at every admission is O(n) per admission,
    #   which is quadratic for a wide sharing set.
    bw_active: dict[str, dict[str, Any]] = {}

    def bw_rate(state: dict[str, Any]) -> Fraction:
        items = state["items"]
        if not items:
            return Fraction(0)
        return state["total"] / len(items)

    ready_heap: list[tuple[Fraction, str]] = []  # (ready_q, event_id)
    # Events ready but blocked by a FULL exclusive resource wait here,
    # per resource, instead of being re-scanned at every instant: they
    # can only become admissible when that resource releases, and the
    # release path re-queues exactly that resource's waiters. Each list
    # is a heap keyed by (ready, event_id) so an event that bounces
    # (moved to the ready heap, then blocked again by a rival that took
    # the slot first) returns to its correct FIFO position in
    # O(log n) rather than at the tail.
    blocked_by_res: dict[str, list[tuple[Fraction, str]]] = {}
    indegree = {eid: len(ds) for eid, ds in deps_of.items()}

    def ready_time(eid: str) -> Fraction:
        base = release.get(eid, Fraction(0))
        ds = deps_of[eid]
        if not ds:
            return base
        return max(base, max(finish[d] for d in ds))

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

    def admit_ready_batch() -> bool:
        """Admit every admissible ready event at ``t_now``, in order.

        Exactly the previous one-event-at-a-time policy, without the
        O(n) rescan per admission: the ready heap is already keyed by
        (ready, event_id), so popping it admits in the same order, and
        events that become ready mid-batch (a zero-duration predecessor
        completing) enter the same heap and are therefore considered
        before any later candidate — which is what the rescan used to
        guarantee. An event blocked by exclusive capacity is set aside
        and pushed back for the next instant; it cannot become
        admissible without a release, and releases only happen when
        ``t_now`` advances.
        """
        admitted_any = False
        while ready_heap and ready_heap[0][0] <= t_now:
            rq, eid = heapq.heappop(ready_heap)
            if eid in scheduled:
                continue
            e = by_id[eid]
            if e.resource is not None:
                rdef = model.resource(e.resource)
                if rdef.kind == RESOURCE_KIND_EXCLUSIVE and \
                        len(exclusive_busy.get(e.resource, [])) >= \
                        (rdef.capacity or 1):
                    heapq.heappush(
                        blocked_by_res.setdefault(e.resource, []),
                        (rq, eid))
                    continue
            _admit(eid, rq)
            admitted_any = True
        return admitted_any

    def requeue_unblocked() -> bool:
        """Move waiters of resources that now have room back to ready."""
        moved = False
        for res, waiters in list(blocked_by_res.items()):
            rdef = model.resource(res)
            room = (rdef.capacity or 1) - len(exclusive_busy.get(res, []))
            if room <= 0 or not waiters:
                continue
            # Waiters are appended in (ready, id) order, so moving the
            # first `room` of them preserves FIFO. Moving ALL of them
            # (and re-blocking the surplus) would rescan the whole queue
            # at every instant — the O(n^2) this queue exists to avoid.
            for _ in range(min(room, len(waiters))):
                heapq.heappush(ready_heap, heapq.heappop(waiters))
            moved = True
        return moved

    def _admit(eid: str, rq: Fraction) -> None:
        """Admit ONE event at ``rq`` (its ready time, <= t_now)."""
        e = by_id[eid]
        dur = net[eid] if eid in net else _duration_of(e, model)

        if e.resource is None:
            start_q = rq
            end_q = start_q + dur.q
            scheduled[eid] = ScheduledEvent(eid, QTime(start_q),
                                            QTime(end_q), None)
            finish[eid] = end_q
            complete(eid)
            return

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
            return

        # BANDWIDTH transfer: joins the active set at its own ready
        # time (== now by the gate) — never before it begins (§31).
        state = bw_active.setdefault(
            e.resource, {"items": [], "total": rdef.bandwidth_bps})
        start_q = max(rq, t_now)
        work_bytes = Fraction(e.bytes_count or 0)
        if work_bytes == 0:
            # zero-byte transfer: declared duration only (latency-like)
            end_q = start_q + dur.q
            scheduled[eid] = ScheduledEvent(
                eid, QTime(start_q), QTime(end_q), e.resource,
                bandwidth_allocated_bps=Fraction(0), bytes_moved=0)
            finish[eid] = end_q
            complete(eid)
            return
        state["items"].append(
            [eid, work_bytes, start_q, start_q, work_bytes])

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
            if requeue_unblocked():
                progressed = True
            if admit_ready_batch():
                progressed = True
        if len(scheduled) == n_events:
            break

        # 2) advance to the next STRICTLY FUTURE boundary: a future
        #    arrival, an exclusive release, or a fluid completion
        # The ready heap is ordered, so its minimum IS the next arrival:
        # scanning it (and the blocked waiters, which are all ready at or
        # before t_now by construction) was the remaining O(n) per
        # instant — quadratic on wide graphs.
        next_arrivals = []
        while ready_heap and ready_heap[0][1] in scheduled:
            heapq.heappop(ready_heap)  # defensive: stale entry
        if ready_heap:
            next_arrivals.append(ready_heap[0][0])
        next_releases = [q for busy in exclusive_busy.values()
                         for (q, _eid) in busy if q > t_now]
        fluid_bounds = []
        for state in bw_active.values():
            rate = bw_rate(state)
            for item in state["items"]:
                _eid, remaining, t_ref = item[0], item[1], item[2]
                if rate > 0:
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
        requeue_unblocked()

        # 4) complete / advance bandwidth transfers at t_now
        for rname, state in list(bw_active.items()):
            rate = bw_rate(state)
            still: list[list[Any]] = []
            for item in state["items"]:
                eid, remaining, t_ref = item[0], item[1], item[2]
                start_q = item[3]  # ORIGINAL start — never advanced
                work_bytes = item[4]
                end_q = t_ref + remaining / rate if rate > 0 else t_ref
                if rate > 0 and end_q <= t_now:
                    span = end_q - start_q
                    avg = Fraction(work_bytes) / span if span > 0 \
                        else Fraction(0)
                    scheduled[eid] = ScheduledEvent(
                        eid, QTime(start_q), QTime(end_q), rname,
                        bandwidth_allocated_bps=avg,
                        bytes_moved=int(work_bytes))
                    finish[eid] = end_q
                    complete(eid)
                else:
                    if rate > 0 and t_now > t_ref:
                        item[1] = remaining - rate * (t_now - t_ref)
                        item[2] = t_now
                    still.append(item)
            bw_active[rname] = {"items": still,
                                "total": state["total"]}

    return Schedule(tuple(scheduled.values()))
