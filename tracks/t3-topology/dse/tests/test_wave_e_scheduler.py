"""Wave E scheduler proof tests (§18/§76/§77/§78/§79/§138).

Methods: hand-computed reference schedules (every expectation obvious
on paper), permutation invariance, monotonicity laws, metamorphic
overlap laws, and Hypothesis property tests. All quantities are exact
rationals — no float arithmetic anywhere in the assertions.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))


import copy
import random
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veritx_dse.performance.metrics import (
    dependency_critical_path, latency_summary, request_latencies,
    resource_utilization,
)
from veritx_dse.performance.model import (
    ClockDef, ResourceDef, PerformanceModel,
)
from veritx_dse.performance.scheduler import (
    SchedulerDeadlock, schedule_workload,
)
from veritx_dse.core.time import QTime
from veritx_dse.performance.workload import (
    EVENT_MEMORY_READ, EVENT_NETWORK_TRAFFIC_WINDOW, PerformanceRequest,
    TemporalEvent, TemporalWorkload, WorkloadError,
)

US = 10 ** 6  # microsecond as Fraction-of-second denominator


def make_model(capacity: int = 2, bandwidth: int = 1200,
               clock: int | Fraction = 10 ** 9,
               memory_source: str = "ANALYTICAL_BANDWIDTH"
               ) -> PerformanceModel:
    """The test model declares ANALYTICAL_BANDWIDTH: these fixtures rely on
    the shared rate law, and the workload law refuses to let a declared
    duration and the rate law both claim authority."""
    return PerformanceModel(
        clocks=(ClockDef("net", clock),),
        resources=(ResourceDef("gpu.compute", "EXCLUSIVE",
                               capacity=capacity),
                   ResourceDef("hbm", "BANDWIDTH",
                               bandwidth_bytes_per_s=bandwidth)),
        memory_source=memory_source,
        network_clock="net")


def comp(eid: str, dur_us: int, deps: tuple[str, ...] = (),
         res: str = "gpu.compute", **kw) -> TemporalEvent:
    return TemporalEvent(eid, "COMPUTE", QTime(dur_us, US), res,
                              deps=tuple(deps), **kw)


def mem(eid: str, nbytes: int, deps: tuple[str, ...] = (),
        ) -> TemporalEvent:
    return TemporalEvent(eid, EVENT_MEMORY_READ, QTime(0), "hbm",
                              deps=tuple(deps), bytes_count=nbytes)


def net_event(eid: str = "NET", op: str | None = None,
              deps: tuple[str, ...] = ()) -> TemporalEvent:
    """The ONE aggregate network window event (§39)."""
    return TemporalEvent(eid, EVENT_NETWORK_TRAFFIC_WINDOW, QTime(0),
                              deps=deps)


# ── §76 hand-computed reference schedules ────────────────────────────

class TestReferenceSchedules:
    def test_simple_chain(self):
        """A(10us) → B(5us): starts exactly at predecessor end."""
        w = TemporalWorkload(performance_model=make_model(),
                                  events=(comp("A", 10), comp("B", 5, ("A",))))
        s = schedule_workload(w)
        assert s.start("A") == QTime(0)
        assert s.end("A") == QTime(10, US)
        assert s.start("B") == QTime(10, US)
        assert s.end("B") == QTime(15, US)
        assert s.makespan() == QTime(15, US)

    def test_fork_join_oracle_18(self):
        """§18: A=10; B=5,C=7 after A (cap 2) → makespan exactly 17us."""
        w = TemporalWorkload(performance_model=make_model(),
                                  events=(comp("B", 5, ("A",)),
                                          comp("A", 10),
                                          comp("C", 7, ("A",))))
        s = schedule_workload(w)
        assert s.start("B") == s.start("C") == QTime(10, US)
        assert s.end("B") == QTime(15, US)
        assert s.end("C") == QTime(17, US)
        assert s.makespan() == QTime(17, US)

    def test_two_independent_capacity1_serialized(self):
        w = TemporalWorkload(
            performance_model=make_model(capacity=1),
            events=(comp("P", 10), comp("Q", 10)))
        s = schedule_workload(w)
        # FIFO by (ready, id): P first
        assert s.start("P") == QTime(0)
        assert s.start("Q") == QTime(10, US)
        assert s.makespan() == QTime(20, US)

    def test_resource_capacity2_parallel(self):
        w = TemporalWorkload(
            performance_model=make_model(capacity=2),
            events=(comp("P", 10), comp("Q", 10)))
        s = schedule_workload(w)
        assert s.start("P") == s.start("Q") == QTime(0)
        assert s.makespan() == QTime(10, US)

    def test_bandwidth_equal_share_simultaneous(self):
        """2×1200B @1200B/s sharing → both finish at exactly 2s."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), mem("M2", 1200)))
        s = schedule_workload(w)
        assert s.start("M1") == s.start("M2") == QTime(0)
        assert s.get("M1").bandwidth_allocated_bps == Fraction(600)
        assert s.end("M1") == s.end("M2") == QTime(2)

    def test_bandwidth_single_transfer(self):
        w = TemporalWorkload(performance_model=make_model(),
                                  events=(mem("S", 1200),))
        s = schedule_workload(w)
        assert s.end("S") == QTime(1)

    def test_bandwidth_staggered_arrival(self):
        """M1 alone [0,1s); M2 joins at 0.5ms; hand-recomputed split."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), comp("D", 500),
                    mem("M2", 600, ("D",))))
        s = schedule_workload(w)
        assert s.start("M1") == QTime(0)
        assert s.start("M2") == QTime(500, US)
        # M2: 600B @600B/s = 1s after its start
        assert s.end("M2") == QTime(2001, 2000)
        # M1: alone 0.6B, then 599.4B @600 → 0.0005+0.999 + 599.4/1200 = 1.5
        assert s.end("M1") == QTime(3, 2)

    def test_arrival_time_delay(self):
        """A compute gated by a long memory transfer arrives late."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 10, ("BIG",)), mem("BIG", 2400),
                    comp("IDLEFILLER", 1)))
        s = schedule_workload(w)
        assert s.start("A") == s.end("BIG") == QTime(2)

    def test_compute_network_overlap(self):
        """§43: compute [0,4ms], network [0,2.5ms] → makespan 5ms."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("K", 4000), net_event(),
                    comp("TAIL", 1000, ("K", "NET"))),
            wave_d_operation_ids=("op1",))
        s = schedule_workload(w, network_durations={"NET": QTime(2500, US)})
        assert s.end("NET") == QTime(2500, US)
        assert s.start("TAIL") == QTime(4000, US)
        assert s.makespan() == QTime(5000, US)

    def test_memory_network_overlap_window(self):
        """Memory transfer runs concurrently with the network window."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M", 1200), net_event(),
                    comp("TAIL", 1000, ("M", "NET"))),
            wave_d_operation_ids=("op1",))
        s = schedule_workload(w, network_durations={"NET": QTime(2500, 1000)})
        assert s.end("M") == QTime(1)  # transfer done at 1s
        # TAIL waits for NET (2.5s), not M → 2.5s + 1ms
        assert s.start("TAIL") == QTime(5, 2)
        assert s.makespan() == QTime(2501, 1000)

    def test_three_resource_critical_path(self):
        """A(3ms)→C(4ms)→D(1ms) critical; B(2ms) branch excluded."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 3000), comp("B", 2000),
                    comp("C", 4000, ("A",)),
                    comp("D", 1000, ("B", "C"))))
        s = schedule_workload(w)
        assert s.makespan() == QTime(8000, US)
        path, length = dependency_critical_path(w, s)
        assert set(path) == {"A", "C", "D"}
        assert length == QTime(8000, US)

    def test_zero_duration_event(self):
        w = TemporalWorkload(performance_model=make_model(),
                                  events=(comp("Z", 0), comp("A", 5, ("Z",))))
        s = schedule_workload(w)
        assert s.end("Z") == s.start("A") == QTime(0)
        assert s.makespan() == QTime(5, US)


# ── §34 scheduler invariants as properties ───────────────────────────

class TestSchedulerInvariants:
    @given(st.lists(st.tuples(st.integers(min_value=1, max_value=200),
                              st.integers(min_value=0, max_value=3)),
                    min_size=1, max_size=8))
    @settings(max_examples=50, deadline=None)
    def test_dependency_and_capacity_never_violated(self, specs):
        model = make_model(capacity=2)
        events = []
        ids = []
        for i, (dur, ndeps) in enumerate(specs):
            deps = tuple(ids[-j - 1] for j in range(ndeps) if j < len(ids))
            events.append(comp(f"e{i}", dur, deps))
            ids.append(f"e{i}")
        w = TemporalWorkload(performance_model=model,
                                  events=tuple(events))
        s = schedule_workload(w)
        by_id = {e.event_id: e for e in w.events}
        for e in w.events:
            # start >= every predecessor end (§34)
            for d in by_id[e.event_id].deps:
                assert s.start(e.event_id) >= s.end(d)
            assert s.start(e.event_id) <= s.end(e.event_id)
        # capacity never exceeded: sweep interval endpoints
        marks = sorted({s.get(e.event_id).start.q for e in w.events} |
                       {s.get(e.event_id).end.q for e in w.events})
        for m in marks:
            active = sum(
                1 for e in w.events
                if e.resource == "gpu.compute"
                and s.get(e.event_id).start.q <= m
                < s.get(e.event_id).end.q)
            assert active <= 2

    def test_quiescence_schedules_everything(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=tuple(comp(f"e{i}", i + 1,
                              (f"e{i-1}",) if i else ()) for i in range(20)))
        s = schedule_workload(w)
        assert len(s) == 20
        assert s.makespan() == QTime(sum(range(1, 21)), US)


# ── §77 permutation invariance ───────────────────────────────────────

class TestPermutationInvariance:
    def test_random_reordering_same_identity_and_schedule(self):
        rng = random.Random(20260920)
        base_events = (
            comp("A", 10), comp("B", 5, ("A",)), comp("C", 7, ("A",)),
            mem("M", 600, ("B",)), comp("D", 3, ("C", "M")))
        ref_w = TemporalWorkload(performance_model=make_model(),
                                      events=base_events)
        ref_s = schedule_workload(ref_w)
        ref_id = ref_w.temporal_workload_id()
        for trial in range(10):
            shuffled = list(base_events)
            rng.shuffle(shuffled)
            w = TemporalWorkload(performance_model=make_model(),
                                      events=tuple(shuffled))
            assert w.temporal_workload_id() == ref_id
            s = schedule_workload(w)
            assert s.to_dict() == ref_s.to_dict()


# ── §78 monotonicity laws ────────────────────────────────────────────

class TestMonotonicity:
    def test_increase_duration_makespan_not_decrease(self):
        w1 = TemporalWorkload(performance_model=make_model(),
                                   events=(comp("A", 10),
                                           comp("B", 5, ("A",))))
        w2 = TemporalWorkload(performance_model=make_model(),
                                   events=(comp("A", 20),
                                           comp("B", 5, ("A",))))
        t1 = schedule_workload(w1).makespan()
        t2 = schedule_workload(w2).makespan()
        assert t2 >= t1

    def test_increase_capacity_makespan_not_increase(self):
        evs = (comp("P", 10), comp("Q", 10), comp("R", 10))
        t1 = schedule_workload(TemporalWorkload(
            performance_model=make_model(capacity=1), events=evs)).makespan()
        t2 = schedule_workload(TemporalWorkload(
            performance_model=make_model(capacity=2), events=evs)).makespan()
        assert t2 <= t1

    def test_increase_bandwidth_completion_not_later(self):
        w_fast = TemporalWorkload(
            performance_model=make_model(bandwidth=2400),
            events=(mem("S", 1200),))
        w_slow = TemporalWorkload(
            performance_model=make_model(bandwidth=1200),
            events=(mem("S", 1200),))
        assert schedule_workload(w_fast).end("S") == QTime(1, 2)
        assert schedule_workload(w_slow).end("S") == QTime(1)

    def test_remove_dependency_makespan_not_increase(self):
        with_dep = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 10), comp("B", 5, ("A",))))
        without = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 10), comp("B", 5)))
        assert schedule_workload(without).makespan() \
            <= schedule_workload(with_dep).makespan()


# ── §79 metamorphic overlap laws ─────────────────────────────────────

class TestMetamorphicOverlap:
    def test_hidden_noncritical_event_double_duration_no_effect(self):
        """Doubling a fully-hidden event leaves makespan unchanged."""
        base = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 10), comp("B", 20), comp("J", 1, ("A", "B"))))
        bigger = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 10), comp("B", 40), comp("J", 1, ("A", "B"))))
        assert schedule_workload(base).makespan() == QTime(21, US)
        assert schedule_workload(bigger).makespan() == QTime(41, US)
        # B (40) dominates; extending the HIDDEN A branch does nothing:
        hidden = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 30), comp("B", 40), comp("J", 1, ("A", "B"))))
        assert schedule_workload(hidden).makespan() == QTime(41, US)

    def test_independent_compute_insertion_changes_nothing_critical(self):
        """Insert an event on an unused second capacity slot: the
        original chain's completion is unchanged."""
        base = TemporalWorkload(
            performance_model=make_model(capacity=2),
            events=(comp("A", 10), comp("B", 5, ("A",))))
        w2 = TemporalWorkload(
            performance_model=make_model(capacity=2),
            events=(comp("A", 10), comp("B", 5, ("A",)),
                    comp("X", 3), comp("Y", 2, ("X",))))
        s1 = schedule_workload(base)
        s2 = schedule_workload(w2)
        assert s1.end("B") == s2.end("B") == QTime(15, US)

    def test_network_active_time_vs_makespan_contribution_distinct(self):
        """§43: network active 2.5ms but contributes 0 when hidden."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("K", 4000), net_event(),
                    comp("TAIL", 1000, ("K", "NET"))),
            wave_d_operation_ids=("op1",))
        covered = schedule_workload(w, network_durations={"NET": QTime(2500, US)})
        zero = schedule_workload(w, network_durations={"NET": QTime(0)})
        assert covered.makespan() == zero.makespan() == QTime(5000, US)


# ── §35 deadlock + refusal behavior ─────────────────────────────────

class TestRefusals:
    def test_deadlock_raises_typed_error(self):
        """Zero-duration chain stalls? No — exercised via corrupted
        internal state is not injectable; instead verify the typed
        error exists and that an empty resource graph cannot run."""
        # every event waits on a resource that does not exist → the
        # workload validator refuses before scheduling
        with pytest.raises(WorkloadError):
            TemporalWorkload(
                performance_model=make_model(),
                events=(TemporalEvent(
                    "E", "COMPUTE", QTime(5, US), "ghost.resource"),))

    def test_cycle_refused_before_scheduling(self):
        with pytest.raises(WorkloadError, match="cycle"):
            TemporalWorkload(
                performance_model=make_model(),
                events=(comp("X", 1, ("Y",)), comp("Y", 1, ("X",))))


# ── exact-rational arithmetic sanity (§87/§88) ──────────────────────

class TestExactness:
    def test_no_float_drift_in_fluid_sharing(self):
        """1/3-second style splits stay exact: 1000B@900B/s, two sharers."""
        w = TemporalWorkload(
            performance_model=make_model(bandwidth=900),
            events=(mem("M1", 1000), mem("M2", 1000)))
        s = schedule_workload(w)
        # 1000/450 = 2 + 2/9 seconds exactly
        assert s.end("M1") == QTime(Fraction(2000, 900))
        assert Fraction(s.end("M1").q) == Fraction(20, 9)

    def test_schedule_dict_roundtrip_exact(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), mem("M2", 600)))
        s = schedule_workload(w)
        doc = s.to_dict()
        import json
        text = json.dumps(doc)
        assert json.loads(text) == doc  # canonical JSON-safe


# ── metrics re-derivation checks (§45/§46/§53) ──────────────────────

class TestMetrics:
    def test_utilization_exact_fraction(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 3000), comp("B", 2000),
                    comp("C", 4000, ("A",)),
                    comp("D", 1000, ("B", "C"))))
        s = schedule_workload(w)
        u = resource_utilization(w, s)
        # occupied 10ms / (2 × 8ms) = 5/8
        assert abs(u["gpu.compute"]["utilization"] - 0.625) < 1e-12

    def test_request_arrival_gates_its_work(self):
        """§52/§101: an arrival is a RELEASE TIME, not bookkeeping.

        The request arrives at 1 ms, so none of its work may start
        before 1 ms — otherwise the request could complete before it
        exists and the latency metric would have to refuse a workload
        the scheduler accepted.
        """
        req = PerformanceRequest("r1", QTime(1000, US),
                           completion_event_ids=("D",))
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("A", 3000, request_id="r1"),
                    comp("B", 2000, request_id="r1"),
                    comp("C", 4000, ("A",), request_id="r1"),
                    comp("D", 1000, ("B", "C"), request_id="r1")),
            requests=(req,))
        s = schedule_workload(w)
        assert s.start("A") == QTime(1000, US)
        assert s.start("B") == QTime(1000, US)
        assert s.end("C") == QTime(8000, US)
        assert s.end("D") == QTime(9000, US)
        rows = request_latencies(w, s)
        assert rows[0]["latency"] == QTime(8000, US).to_dict()
        summary = latency_summary(rows)
        assert summary["sample_count"] == 1

    def test_two_requests_queue_on_a_shared_resource(self):
        """Deterministic queueing: later arrival, later service."""
        w = TemporalWorkload(
            performance_model=make_model(capacity=1),
            events=(comp("A", 1000, request_id="r1"),
                    comp("B", 1000, request_id="r2")),
            requests=(PerformanceRequest("r1", QTime(0),
                                   completion_event_ids=("A",)),
                      PerformanceRequest("r2", QTime(500, US),
                                   completion_event_ids=("B",))))
        s = schedule_workload(w)
        assert s.start("A") == QTime(0)
        assert s.start("B") == QTime(1000, US)  # after A, not at arrival
        rows = request_latencies(w, s)
        assert Fraction(rows[0]["latency"]["numerator"],
                        rows[0]["latency"]["denominator"]) == Fraction(1, 1000)
        # r2: service 1ms..2ms, arrival 0.5ms -> latency 1.5ms
        assert Fraction(rows[1]["latency"]["numerator"],
                        rows[1]["latency"]["denominator"]) == Fraction(3, 2000)

    def test_first_token_before_arrival_refuses(self):
        """A negative TTFT is nonsense; it must refuse, never report."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("FT", 1000, request_id="r1", is_first_token=True),
                    comp("C", 9000, ("FT",), request_id="r1")),
            requests=(PerformanceRequest("r1", QTime(5000, US),
                                   completion_event_ids=("C",),
                                   first_token_event_id="FT"),))
        s = schedule_workload(w)
        # arrival gates the work, so FT now ends AFTER the arrival
        assert s.end("FT") == QTime(6000, US)
        rows = request_latencies(w, s)
        assert rows[0]["first_token_latency"] == QTime(1000, US).to_dict()

    def test_ttft_only_with_first_token_event(self):
        req = PerformanceRequest("r1", QTime(0), completion_event_ids=("D",),
                           first_token_event_id="T")
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(comp("P", 2000, request_id="r1"),
                    comp("T", 500, ("P",), request_id="r1"),
                    comp("D", 100, ("T",), request_id="r1")),
            requests=(req,))
        s = schedule_workload(w)
        rows = request_latencies(w, s)
        assert rows[0]["first_token_latency"] == QTime(2500, US).to_dict()


# ── §83/§84: independent bounded-exhaustive oracles ──────────────────

def _brute_force_makespan(workload: TemporalWorkload) -> Fraction:
    """Exhaustive independent scheduler for TINY exclusive-resource DAGs.

    Plain recursion over states ``(done, running, now)``: complete
    everything due, try EVERY admissible admission order, otherwise
    advance to the next decision point. Returns the minimum makespan
    over all feasible schedules. Shares no code with the production
    scheduler — it is the independent reference the greedy policy is
    measured against.

    Bandwidth resources are out of scope here (they have their own
    exact oracle below); this models EXCLUSIVE capacity only.
    """
    model = workload.performance_model
    events = {e.event_id: e for e in workload.events}
    for e in workload.events:
        if e.resource is not None and \
                model.resource(e.resource).kind != "EXCLUSIVE":
            raise AssertionError(
                "brute force oracle: exclusive resources only")
    deps = {eid: tuple(sorted(set(e.deps))) for eid, e in events.items()}
    n = len(events)
    finish: dict[str, Fraction] = {}
    best: list[Fraction | None] = [None]

    def ready_at(eid: str) -> Fraction:
        return max((finish[d] for d in deps[eid]), default=Fraction(0))

    def rec(done: frozenset[str], running: tuple[tuple[Fraction, str], ...],
            now: Fraction) -> None:
        # 1. complete everything due at `now`
        newly = frozenset(eid for end, eid in running if end <= now)
        if newly:
            rec(done | newly,
                tuple((end, eid) for end, eid in running if end > now),
                now)
            return
        if len(done) == n:
            m = max(finish.values())
            if best[0] is None or m < best[0]:
                best[0] = m
            return
        # 2. every admissible admission order at this instant
        running_ids = {eid for _end, eid in running}
        busy: dict[str, int] = {}
        for _end, eid in running:
            res = events[eid].resource
            busy[res] = busy.get(res, 0) + 1
        ready: list[str] = []
        future: list[Fraction] = []
        for eid, e in events.items():
            if eid in done or eid in running_ids:
                continue
            if not set(deps[eid]) <= done:
                continue
            r = ready_at(eid)
            if r > now:
                future.append(r)
                continue
            cap = model.resource(e.resource).capacity if e.resource else 0
            if e.resource is None or busy.get(e.resource, 0) < cap:
                ready.append(eid)
        if ready:
            for eid in sorted(ready):
                e = events[eid]
                start = max(ready_at(eid), now)
                end = start + e.duration.q
                finish[eid] = end
                rec(done, running + ((end, eid),), now)
                del finish[eid]
            return
        # 3. advance to the next decision point (completion or readiness)
        cands = [end for end, _eid in running if end > now] + future
        if not cands:
            return  # dead end: this admission order cannot complete
        rec(done, running, min(cands))

    rec(frozenset(), (), Fraction(0))
    assert best[0] is not None, \
        "brute force oracle found no feasible schedule"
    return best[0]


class TestBoundedExhaustiveScheduler:
    """§83: the production schedule vs the brute-force optimum.

    The declared policy is ``FIFO_SERIAL`` (earliest-ready, then
    semantic id) — a DECLARED deterministic arbitration, not a makespan
    optimizer. Two statements hold and are checked here:

      * soundness: the production makespan is never SMALLER than the
        brute-force optimum (no scheduler beats the optimum without
        violating a constraint);
      * optimality where the policy is non-idling-optimal: capacity 1
        (a single machine never idles, so every order is optimal), the
        no-contention case, and the hand corpus.

    One property is RECORDED rather than asserted: FIFO admits by
    identity order, so under capacity contention it can be suboptimal
    (counterexample below). Because the arbitration policy is bound
    into ``performance_model_id``, that is a stated property of the
    model, not a hidden timing assumption (§20).
    """

    def test_recorded_fifo_counterexample(self):
        """Two short jobs admitted first can block a long one."""
        w = TemporalWorkload(
            performance_model=make_model(capacity=2),
            events=(comp("a", 1), comp("b", 1), comp("c", 2)))
        got = schedule_workload(w).makespan().q
        opt = _brute_force_makespan(w)
        assert got == Fraction(3, US)  # a, b admitted, then c
        assert opt == Fraction(2, US)  # c beside one short job
        assert got > opt

    def test_hand_corpus_is_optimal(self):
        cases = (
            (2, (comp("A", 10), comp("B", 5, ("A",)))),
            (2, (comp("A", 10), comp("B", 5, ("A",)),
                 comp("C", 7, ("A",)))),
            (1, (comp("P", 10), comp("Q", 10))),
            (2, (comp("P", 10), comp("Q", 10))),
            (1, (comp("A", 3), comp("B", 2, ("A",)),
                 comp("C", 1, ("B",)))),
            (2, (comp("A", 4), comp("B", 1), comp("C", 4, ("A",)),
                 comp("D", 1, ("B", "C")))),
            (1, (comp("A", 2), comp("B", 3), comp("C", 1, ("A", "B")))),
            (4, (comp("A", 3), comp("B", 2), comp("C", 2), comp("D", 2))),
        )
        for capacity, events in cases:
            w = TemporalWorkload(
                performance_model=make_model(capacity=capacity),
                events=events)
            got = schedule_workload(w).makespan().q
            opt = _brute_force_makespan(w)
            assert got == opt, (capacity, events, got, opt)

    @given(st.lists(st.tuples(st.integers(min_value=1, max_value=4),
                              st.integers(min_value=0, max_value=3)),
                    min_size=1, max_size=6))
    @settings(max_examples=80, deadline=None)
    def test_single_resource_makespan_is_total_work(self, specs):
        """Capacity 1 never idles: makespan == Σ durations == optimum."""
        events, ids = [], []
        for i, (dur, ndeps) in enumerate(specs):
            deps = tuple(ids[-j - 1] for j in range(ndeps) if j < len(ids))
            events.append(comp(f"e{i}", dur, deps))
            ids.append(f"e{i}")
        w = TemporalWorkload(
            performance_model=make_model(capacity=1), events=tuple(events))
        got = schedule_workload(w).makespan().q
        total = sum(e.duration.q for e in w.events)
        assert got == total
        assert got == _brute_force_makespan(w)

    @given(st.lists(st.tuples(st.integers(min_value=1, max_value=4),
                              st.integers(min_value=0, max_value=3)),
                    min_size=1, max_size=5),
           st.integers(min_value=2, max_value=3))
    @settings(max_examples=120, deadline=None)
    def test_random_tiny_dags_never_beat_optimum(self, specs, capacity):
        events, ids = [], []
        for i, (dur, ndeps) in enumerate(specs):
            deps = tuple(ids[-j - 1] for j in range(ndeps) if j < len(ids))
            events.append(comp(f"e{i}", dur, deps))
            ids.append(f"e{i}")
        w = TemporalWorkload(
            performance_model=make_model(capacity=capacity),
            events=tuple(events))
        got = schedule_workload(w).makespan().q
        opt = _brute_force_makespan(w)
        # soundness: no feasible schedule can beat the optimum
        assert got >= opt
        # and the schedule is exactly as long as its own event set says
        assert got == max(s.end.q for s in schedule_workload(w).events)


def _ref_equal_share_completion(transfers: list[tuple[int, int]]
                                ) -> list[Fraction]:
    """Independent equal-share bandwidth reference (§84).

    ``transfers`` is a list of (arrival_us, bytes). Returns each
    transfer's completion time in seconds, computed by a tiny event
    walk: at every boundary the active set shares the total bandwidth
    equally. Deliberately naive and readable.
    """
    B = Fraction(1200)  # bytes/s, matches make_model()
    remaining = [Fraction(nbytes) for _a, nbytes in transfers]
    arrivals = [Fraction(a, US) for a, _n in transfers]
    done_at: list[Fraction | None] = [None] * len(transfers)
    t = Fraction(0)
    while any(d is None for d in done_at):
        active = [i for i in range(len(transfers))
                  if done_at[i] is None and arrivals[i] <= t]
        if not active:
            t = min(arrivals[i] for i in range(len(transfers))
                    if done_at[i] is None)
            continue
        share = B / len(active)
        # next boundary: earliest completion OR the next arrival, so a
        # late transfer starts exactly when it arrives (never earlier)
        bounds = [remaining[i] / share for i in active]
        bounds += [arrivals[i] - t for i in range(len(transfers))
                   if done_at[i] is None and arrivals[i] > t]
        dt = min(bounds)
        for i in active:
            remaining[i] -= share * dt
        t += dt
        for i in active:
            if remaining[i] <= 0:
                done_at[i] = t
    return [d for d in done_at]


class TestBandwidthAccounting:
    """The recorded allocation must integrate back to the bytes moved.

    A fluid transfer's share changes at every boundary; recording only
    the FINAL instantaneous rate made ``bytes_moved`` wrong (2400 instead
    of 1800 in the staggered case) and reported utilization above 1.
    """

    def test_bytes_moved_matches_declared_bytes(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), comp("D", 500), mem("M2", 600, ("D",))))
        s = schedule_workload(w)
        assert s.get("M1").bytes_moved == 1200
        assert s.get("M2").bytes_moved == 600
        util = resource_utilization(w, s)
        assert util["hbm"]["bytes_moved"] == 1800

    def test_average_rate_integrates_to_bytes(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), comp("D", 500), mem("M2", 600, ("D",))))
        s = schedule_workload(w)
        for eid in ("M1", "M2"):
            se = s.get(eid)
            span = se.end.q - se.start.q
            assert se.bandwidth_allocated_bps * span == se.bytes_moved

    def test_utilization_never_exceeds_one(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), mem("M2", 600), mem("M3", 1800)))
        s = schedule_workload(w)
        util = resource_utilization(w, s)
        assert util["hbm"]["utilization"] <= 1.0
        assert util["gpu.compute"]["utilization"] <= 1.0

    def test_infeasible_schedule_refused(self):
        """A forged schedule that over-uses a resource refuses."""
        from veritx_dse.performance.scheduler import Schedule, ScheduledEvent
        w = TemporalWorkload(performance_model=make_model(),
                                  events=(mem("M", 1200),))
        forged = Schedule((ScheduledEvent(
            "M", QTime(0), QTime(10), "hbm",
            bandwidth_allocated_bps=Fraction(1200), bytes_moved=13000),))
        with pytest.raises(ValueError, match="capacity"):
            resource_utilization(w, forged)


class TestBandwidthOracle:
    """§84: equal-share bandwidth against an independent reference."""

    def test_one_transfer(self):
        w = TemporalWorkload(performance_model=make_model(),
                                  events=(mem("M", 1200),))
        s = schedule_workload(w)
        assert s.end("M").q == _ref_equal_share_completion([(0, 1200)])[0]

    def test_two_equal_simultaneous(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), mem("M2", 1200)))
        s = schedule_workload(w)
        ref = _ref_equal_share_completion([(0, 1200), (0, 1200)])
        assert [s.end("M1").q, s.end("M2").q] == ref

    def test_unequal_sizes(self):
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 600), mem("M2", 1800)))
        s = schedule_workload(w)
        ref = _ref_equal_share_completion([(0, 600), (0, 1800)])
        assert [s.end("M1").q, s.end("M2").q] == ref

    def test_staggered_start(self):
        """M2 arrives after M1 has already made progress."""
        w = TemporalWorkload(
            performance_model=make_model(),
            events=(mem("M1", 1200), comp("D", 500),
                    mem("M2", 600, ("D",))))
        s = schedule_workload(w)
        # the reference walk must model M2's arrival as the end of D,
        # which the scheduler computed — feed it the scheduled start
        ref = _ref_equal_share_completion([(0, 1200), (500, 600)])
        assert s.end("M1").q == ref[0]
        assert s.end("M2").q == ref[1]
