"""Wave E identity/authenticity tests (§11/§65–§67/§73/§75/§80–§84).

Attacks every semantic layer: model fields, workload events, network
binding provenance, result summaries and identity transplants. Every
mutation must change identity or refuse — never survive silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))


import copy
from fractions import Fraction

import pytest

from veritx_dse.wavee.model import (
    ClockDef, ModelError, ResourceDef, WaveEPerformanceModel, rate_duration,
)
from veritx_dse.wavee.network import (
    NetworkWindowBinding, TimeError, bind_network_window,
)
from veritx_dse.wavee.result import (
    ResultError, WaveEEventGraph, build_performance_result, reverify_result,
)
from veritx_dse.wavee.scheduler import schedule_workload
from veritx_dse.wavee.time import QTime
from veritx_dse.wavee.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW, WaveERequest, WaveETemporalEvent,
    WaveETemporalWorkload, WorkloadError,
)

US = 10 ** 6


def comp_ev(eid, dur_us, deps=(), **kw):
    return WaveETemporalEvent(eid, "COMPUTE", QTime(dur_us, US),
                              "gpu.compute", deps=tuple(deps), **kw)


def make_model(**kw) -> WaveEPerformanceModel:
    return WaveEPerformanceModel(
        clocks=(ClockDef("net", kw.get("clock", 10 ** 9)),),
        resources=(ResourceDef("gpu.compute", "EXCLUSIVE",
                               capacity=kw.get("capacity", 1)),
                   ResourceDef("hbm", "BANDWIDTH",
                               bandwidth_bytes_per_s=kw.get("bw", 1200))),
        network_clock="net")


def basic_workload(model=None) -> WaveETemporalWorkload:
    model = model or make_model()
    return WaveETemporalWorkload(
        performance_model=model,
        events=(WaveETemporalEvent("K", "COMPUTE", QTime(4000, US),
                                   "gpu.compute"),
                WaveETemporalEvent("T", "COMPUTE", QTime(1000, US),
                                   "gpu.compute", deps=("K",))))


# ── §11 mutation resistance: artifacts are transitively immutable ────

class TestImmutability:
    def test_model_id_stable_across_reconstruction(self):
        m = make_model()
        m2 = WaveEPerformanceModel.from_dict(m.to_dict())
        assert m.performance_model_id() == m2.performance_model_id()

    def test_workload_survives_event_dict_mutation(self):
        model = make_model()
        ev = WaveETemporalEvent("A", "COMPUTE", QTime(5, US), "gpu.compute")
        d = ev.to_dict()
        d["duration"]["numerator"] = 999  # mutate AFTER to_dict
        # the live event is unaffected
        assert ev.duration == QTime(5, US)
        w1 = WaveETemporalWorkload(performance_model=model,
                                   events=(ev,))
        w2 = WaveETemporalWorkload(performance_model=model, events=(
            WaveETemporalEvent.from_dict(ev.to_dict()),))
        assert w1.temporal_workload_id() == w2.temporal_workload_id()

    def test_event_attributes_immutable(self):
        ev = WaveETemporalEvent("A", "COMPUTE", QTime(5, US), "gpu.compute")
        with pytest.raises(AttributeError):
            ev.duration = QTime(9, US)


# ── §82 timing attacks: model identity must move ─────────────────────

class TestModelIdentityMutations:
    def base_id(self, **kw) -> str:
        return make_model(**kw).performance_model_id()

    def test_capacity_mutation_changes_id(self):
        assert self.base_id(capacity=1) != self.base_id(capacity=2)

    def test_bandwidth_mutation_changes_id(self):
        assert self.base_id(bw=1200) != self.base_id(bw=2400)

    def test_clock_mutation_changes_id(self):
        assert self.base_id(clock=10 ** 9) != self.base_id(clock=2 * 10 ** 9)

    def test_arbitration_policy_is_identity_bearing(self):
        """§20: a contention policy is declared, never assumed."""
        base = make_model()
        assert base.arbitration_exclusive == "FIFO_SERIAL"
        assert base.arbitration_bandwidth == "EQUAL_SHARE_BANDWIDTH"
        # roundtrip keeps the declaration
        rebuilt = WaveEPerformanceModel.from_dict(base.to_dict())
        assert rebuilt.performance_model_id() == base.performance_model_id()
        # an unsupported policy refuses instead of being ignored
        with pytest.raises(ModelError):
            WaveEPerformanceModel(
                clocks=base.clocks, resources=base.resources,
                network_clock="net",
                arbitration_exclusive="PRETEND_GPU_SCHEDULER")
        with pytest.raises(ModelError):
            WaveEPerformanceModel(
                clocks=base.clocks, resources=base.resources,
                network_clock="net",
                arbitration_bandwidth="MAGIC_SHARING")
        # a scheduler must refuse a policy it does not implement
        from veritx_dse.wavee.scheduler import SchedulerError, schedule_workload
        from veritx_dse.wavee.workload import WaveETemporalWorkload
        forged = WaveEPerformanceModel(
            clocks=base.clocks, resources=base.resources,
            network_clock="net", arbitration_exclusive="FIFO_SERIAL")
        object.__setattr__(forged, "arbitration_exclusive", "OTHER")
        w = WaveETemporalWorkload(
            performance_model=forged,
            events=(WaveETemporalEvent(
                "A", "COMPUTE", QTime(1, 1000), "gpu.compute"),))
        with pytest.raises(SchedulerError, match="arbitration"):
            schedule_workload(w)

    def test_adding_resource_changes_id(self):
        m1 = make_model()
        m2 = WaveEPerformanceModel(
            clocks=(ClockDef("net", 10 ** 9),),
            resources=(ResourceDef("gpu.compute", "EXCLUSIVE", capacity=1),
                       ResourceDef("hbm", "BANDWIDTH",
                                   bandwidth_bytes_per_s=1200),
                       ResourceDef("dma", "EXCLUSIVE", capacity=1)),
            network_clock="net")
        assert m1.performance_model_id() != m2.performance_model_id()

    def test_invalid_values_refuse(self):
        with pytest.raises(ModelError):
            ClockDef("bad", 0)
        with pytest.raises(ModelError):
            ClockDef("bad", -5)
        with pytest.raises(ModelError):
            ResourceDef("g", "EXCLUSIVE", capacity=0)
        with pytest.raises(ModelError):
            ResourceDef("g", "EXCLUSIVE", capacity=-1)
        with pytest.raises(ModelError):
            ResourceDef("h", "BANDWIDTH", bandwidth_bytes_per_s=0)
        with pytest.raises(ModelError):
            ResourceDef("x", "QUANTUM")
        with pytest.raises(ModelError):
            WaveEPerformanceModel(clocks=(), resources=(
                ResourceDef("g", "EXCLUSIVE", capacity=1),),
                network_clock="net")
        # no default clock: network_clock must name a bound clock
        with pytest.raises(ModelError):
            WaveEPerformanceModel(clocks=(ClockDef("net", 10 ** 9),),
                                  resources=(ResourceDef(
                                      "g", "EXCLUSIVE", capacity=1),),
                                  network_clock="unbound")

    def test_rate_law_exact(self):
        # T = bytes / bandwidth, exactly; there is deliberately no
        # latency term (a hidden zero would be a hidden assumption)
        assert rate_duration(1000, 100) == Fraction(10)
        assert rate_duration(0, 100) == Fraction(0)
        with pytest.raises(ModelError):
            rate_duration(-1, 100)


# ── §81 dependency attacks ───────────────────────────────────────────

class TestWorkloadAttacks:
    def test_cycle_refused(self):
        with pytest.raises(WorkloadError, match="cycle"):
            WaveETemporalWorkload(performance_model=make_model(), events=(
                WaveETemporalEvent("X", "COMPUTE", QTime(1, US),
                                   "gpu.compute", deps=("Y",)),
                WaveETemporalEvent("Y", "COMPUTE", QTime(1, US),
                                   "gpu.compute", deps=("X",))))

    def test_self_dependency_refused(self):
        with pytest.raises(WorkloadError, match="itself"):
            WaveETemporalWorkload(performance_model=make_model(), events=(
                WaveETemporalEvent("X", "COMPUTE", QTime(1, US),
                                   "gpu.compute", deps=("X",)),))

    def test_missing_dependency_refused(self):
        with pytest.raises(WorkloadError, match="missing"):
            WaveETemporalWorkload(performance_model=make_model(), events=(
                WaveETemporalEvent("X", "COMPUTE", QTime(1, US),
                                   "gpu.compute", deps=("GHOST",)),))

    def test_unknown_resource_refused(self):
        with pytest.raises(WorkloadError, match="unknown resource"):
            WaveETemporalWorkload(performance_model=make_model(), events=(
                WaveETemporalEvent("X", "COMPUTE", QTime(1, US),
                                   "ghost.r"),))

    def test_negative_duration_refused(self):
        """Negative time cannot even be constructed (time.py law)."""
        from veritx_dse.wavee.time import TimeError
        with pytest.raises(TimeError):
            QTime(-1, US)
        # ... so a negative duration can never reach the workload
        with pytest.raises(TimeError):
            QTime(0) - QTime(1)

    def test_bool_is_not_time(self):
        from veritx_dse.wavee.time import TimeError
        with pytest.raises(TimeError):
            QTime(True)
        with pytest.raises(TimeError):
            QTime(1, True)

    def test_empty_overlay_refused(self):
        with pytest.raises(WorkloadError, match="at least one event"):
            WaveETemporalWorkload(performance_model=make_model(), events=())

    def test_bytes_on_compute_event_refused(self):
        with pytest.raises(WorkloadError, match="bytes_count"):
            WaveETemporalEvent("X", "COMPUTE", QTime(1, US), "gpu.compute",
                               bytes_count=8)

    def test_bytes_on_network_event_refused(self):
        with pytest.raises(WorkloadError, match="bytes_count"):
            WaveETemporalEvent("X", EVENT_NETWORK_TRAFFIC_WINDOW, QTime(0),
                               bytes_count=8)

    def test_unknown_request_refused(self):
        with pytest.raises(WorkloadError, match="unknown request"):
            WaveETemporalWorkload(
                performance_model=make_model(),
                events=(WaveETemporalEvent("X", "COMPUTE", QTime(1, US),
                                           "gpu.compute", request_id="nope"),))

    def test_undeclared_wave_d_operation_refused(self):
        with pytest.raises(WorkloadError, match="not in the declared set"):
            WaveETemporalWorkload(
                performance_model=make_model(),
                events=(WaveETemporalEvent(
                    "N", "COMPUTE", QTime(1, US), "gpu.compute",
                    wave_d_operation_id="opX"),),
                wave_d_operation_ids=("op1",))

    def test_identity_changes_with_duration_mutation(self):
        w1 = basic_workload()
        model = make_model()
        w2 = WaveETemporalWorkload(
            performance_model=model,
            events=(WaveETemporalEvent("K", "COMPUTE", QTime(4001, US),
                                       "gpu.compute"),
                    WaveETemporalEvent("T", "COMPUTE", QTime(1000, US),
                                       "gpu.compute", deps=("K",))))
        assert w1.temporal_workload_id() != w2.temporal_workload_id()

    def test_identity_changes_with_dependency_mutation(self):
        model = make_model()
        w1 = WaveETemporalWorkload(performance_model=model, events=(
            WaveETemporalEvent("A", "COMPUTE", QTime(1, US), "gpu.compute"),
            WaveETemporalEvent("B", "COMPUTE", QTime(1, US), "gpu.compute")))
        w2 = WaveETemporalWorkload(performance_model=model, events=(
            WaveETemporalEvent("A", "COMPUTE", QTime(1, US), "gpu.compute"),
            WaveETemporalEvent("B", "COMPUTE", QTime(1, US), "gpu.compute",
                               deps=("A",))))
        assert w1.temporal_workload_id() != w2.temporal_workload_id()

    def test_identity_changes_with_resource_reassignment(self):
        model = make_model()
        mk = lambda res: WaveETemporalWorkload(  # noqa: E731
            performance_model=model, events=(
                WaveETemporalEvent("M", "MEMORY_READ", QTime(0), res,
                                   bytes_count=100)))
        # same bytes on two differently-named bandwidth resources →
        # different workload ids (resource is identity-bearing)
        m_hbm = WaveETemporalWorkload(
            performance_model=make_model(), events=(
                WaveETemporalEvent("M", "MEMORY_READ", QTime(0), "hbm",
                                   bytes_count=100),))
        m_other = WaveETemporalWorkload(
            performance_model=WaveEPerformanceModel(
                clocks=(ClockDef("net", 10 ** 9),),
                resources=(ResourceDef("gpu.compute", "EXCLUSIVE",
                                       capacity=1),
                           ResourceDef("nvm", "BANDWIDTH",
                                       bandwidth_bytes_per_s=1200)),
                network_clock="net"),
            events=(WaveETemporalEvent("M", "MEMORY_READ", QTime(0), "nvm",
                                       bytes_count=100),))
        assert m_hbm.temporal_workload_id() != m_other.temporal_workload_id()


# ── §42/§52: network binding provenance ──────────────────────────────

class FakeEvidence:
    def __init__(self, stats, sha=None):
        self.stats = stats
        self.sha256 = sha


CHAIN = {
    "operation_graph_id": "og-123",
    "physical_traffic_id": "pt-456",
    "backend_config_hash": "cfg-789",
    "backend_input_hash": "in-000",
}


class TestClosureFindings:
    """Attacks for the independent-audit closure findings."""

    # ── F1: one aggregate network window, never per-operation ───────
    def test_per_operation_network_event_refused(self):
        with pytest.raises(WorkloadError, match="NETWORK_OPERATION_REF is "
                                                "UNSUPPORTED|global"):
            WaveETemporalEvent("N", "NETWORK_OPERATION_REF", QTime(0),
                               wave_d_operation_id="op1")

    def test_multiple_window_events_refused(self):
        """The global window cannot be split across events."""
        with pytest.raises(WorkloadError, match="at most ONE"):
            WaveETemporalWorkload(
                performance_model=make_model(),
                events=(WaveETemporalEvent("N1",
                                           EVENT_NETWORK_TRAFFIC_WINDOW,
                                           QTime(0)),
                        WaveETemporalEvent("N2",
                                           EVENT_NETWORK_TRAFFIC_WINDOW,
                                           QTime(0))))

    def test_window_event_with_declared_duration_refused(self):
        with pytest.raises(WorkloadError, match="duration 0"):
            WaveETemporalEvent("N", EVENT_NETWORK_TRAFFIC_WINDOW,
                               QTime(1, US))

    def test_window_event_citing_an_operation_refused(self):
        with pytest.raises(WorkloadError, match="WHOLE traffic"):
            WaveETemporalEvent("N", EVENT_NETWORK_TRAFFIC_WINDOW, QTime(0),
                               wave_d_operation_id="op1")

    # ── F2: WaveEEventGraph must be transitively immutable ──────────
    def test_event_graph_is_immutable(self):
        from veritx_dse.wavee.result import WaveEEventGraph
        w = WaveETemporalWorkload(performance_model=make_model(),
                                  events=(comp_ev("K", 1),))
        chain = {"waved_workload_id": "w", "operation_graph_id": "og",
                 "physical_traffic_id": "pt", "packet_format_hash": "pf",
                 "resolved_fabric_hash": "rf", "message_artifact_id": "m",
                 "parallelism_id": "pa", "wave_d_semantics_id": "s",
                 "workload_kind": "WAVE_D_SEMANTIC"}
        g = WaveEEventGraph(workload=w, wave_d_chain=chain)
        before = g.event_graph_id()
        chain["operation_graph_id"] = "FORGED"
        chain["physical_traffic_id"] = "FORGED"
        assert g.event_graph_id() == before
        with pytest.raises(AttributeError):
            g.wave_d_chain = None  # type: ignore[misc]
        with pytest.raises(TypeError):
            g.wave_d_chain["operation_graph_id"] = "FORGED"  # type: ignore

    # ── F3: no false analytical-compute provenance ──────────────────
    def test_analytical_compute_refused(self):
        with pytest.raises(ModelError, match="compute_source"):
            WaveEPerformanceModel(
                clocks=(ClockDef("net", 10 ** 9),),
                resources=(ResourceDef("g", "EXCLUSIVE", capacity=1),),
                compute_source="ANALYTICAL_MODEL", network_clock="net")

    def test_memory_source_controls_memory_durations(self):
        from veritx_dse.wavee.scheduler import schedule_workload
        ev = (WaveETemporalEvent("M", "MEMORY_READ", QTime(0), "hbm",
                                 bytes_count=1200),)
        explicit = WaveETemporalWorkload(
            performance_model=make_model(bw=1200), events=ev)
        analytical = WaveETemporalWorkload(
            performance_model=WaveEPerformanceModel(
                clocks=(ClockDef("net", 10 ** 9),),
                resources=(ResourceDef("hbm", "BANDWIDTH",
                                       bandwidth_bytes_per_s=1200),),
                memory_source="ANALYTICAL_BANDWIDTH", network_clock="net"),
            events=ev)
        # both derive from bytes/BW for a bandwidth resource, but the
        # DECLARED source is what the fidelity warning reports
        assert explicit.performance_model.memory_source == \
            "EXPLICIT_DURATION"
        assert analytical.performance_model.memory_source == \
            "ANALYTICAL_BANDWIDTH"
        assert schedule_workload(analytical).end("M") == QTime(1)

    # ── F4: no hidden memory latency ────────────────────────────────
    def test_rate_law_has_no_latency_term(self):
        import inspect
        from veritx_dse.wavee.model import rate_duration
        params = list(inspect.signature(rate_duration).parameters)
        assert params == ["bytes_count", "bandwidth_bps"]
        assert rate_duration(1200, 1200) == Fraction(1)

    # ── F5: nested schemas are closed ───────────────────────────────
    def test_event_schema_is_closed(self):
        good = comp_ev("K", 1).to_dict()
        with pytest.raises(WorkloadError, match="unknown fields"):
            WaveETemporalEvent.from_dict(
                {**good, "claimed_h100_latency_ns": 17})

    def test_request_schema_is_closed(self):
        good = WaveERequest("r1", QTime(0)).to_dict()
        with pytest.raises(WorkloadError, match="unknown fields"):
            WaveERequest.from_dict({**good, "claimed_tpot_ns": 3})

    def test_resource_schema_is_closed(self):
        good = ResourceDef("g", "EXCLUSIVE", capacity=1).to_dict()
        with pytest.raises(ModelError, match="unknown|malformed"):
            ResourceDef.from_dict({**good, "peak_tflops": 989})

    # ── F6: request identity and ownership ──────────────────────────
    def test_duplicate_request_ids_refused(self):
        with pytest.raises(WorkloadError, match="duplicate request_ids"):
            WaveETemporalWorkload(
                performance_model=make_model(),
                events=(comp_ev("K", 1),),
                requests=(WaveERequest("r1", QTime(0)),
                          WaveERequest("r1", QTime(10, US))))

    def test_first_token_must_be_owned_or_unowned(self):
        """Request A cannot claim request B's event as its first token."""
        with pytest.raises(WorkloadError, match="already owned"):
            WaveETemporalWorkload(
                performance_model=make_model(),
                events=(comp_ev("A", 1, request_id="r1"),
                        comp_ev("B", 1, request_id="r2")),
                requests=(WaveERequest("r1", QTime(0),
                                       first_token_event_id="B"),
                          WaveERequest("r2", QTime(0))))

    # ── F7: persisted schedule roundtrip keeps bytes_moved ──────────
    def test_reverify_preserves_bytes_moved(self):
        from veritx_dse.wavee.result import (
            WaveEEventGraph, build_performance_result, reverify_result,
        )
        from veritx_dse.wavee.scheduler import schedule_workload
        w = WaveETemporalWorkload(
            performance_model=make_model(),
            events=(WaveETemporalEvent("M1", "MEMORY_READ", QTime(0), "hbm",
                                       bytes_count=1200),
                    WaveETemporalEvent("D", "COMPUTE", QTime(500, US),
                                       "gpu.compute"),
                    WaveETemporalEvent("M2", "MEMORY_READ", QTime(0), "hbm",
                                       deps=("D",), bytes_count=600)))
        s = schedule_workload(w)
        doc = build_performance_result(graph=WaveEEventGraph(workload=w),
                                       schedule=s)
        assert doc["utilization"]["hbm"]["bytes_moved"] == 1800
        again = reverify_result(dict(doc), workload=w)
        assert again["utilization"]["hbm"]["bytes_moved"] == 1800

    def test_schedule_row_schema_is_closed(self):
        from veritx_dse.wavee.result import (
            WaveEEventGraph, ResultError, build_performance_result,
            reverify_result,
        )
        from veritx_dse.wavee.scheduler import schedule_workload
        w = WaveETemporalWorkload(performance_model=make_model(),
                                  events=(comp_ev("K", 1),))
        doc = build_performance_result(graph=WaveEEventGraph(workload=w),
                                       schedule=schedule_workload(w))
        doc["schedule"]["events"][0]["forged_field"] = 1
        with pytest.raises(ResultError, match="unknown fields"):
            reverify_result(doc, workload=w)

    # ── F8: the dependency critical path is named honestly ──────────
    def test_dependency_critical_path_excludes_resource_edges(self):
        """Two independent events on capacity 1: 20ms makespan, 10ms chain."""
        from veritx_dse.wavee.metrics import dependency_critical_path
        from veritx_dse.wavee.scheduler import schedule_workload
        w = WaveETemporalWorkload(
            performance_model=make_model(capacity=1),
            events=(comp_ev("A", 10000), comp_ev("B", 10000)))
        s = schedule_workload(w)
        assert s.makespan() == QTime(20, 1000)   # realized schedule
        path, length = dependency_critical_path(w, s)
        assert length == QTime(10, 1000)          # explicit deps only
        assert len(path) == 1


class TestNetworkBinding:
    def test_barrier_window_binds_all_provenance(self):
        ev = FakeEvidence({"completion_time": 2500, "delivered": 4,
                           "pkt_count": 4}, sha="deadbeef")
        binding, dur = bind_network_window(
            evidence=ev, chain=CHAIN, network_clock_hz=10 ** 9,
            evidence_sha256="deadbeef")
        assert dur == QTime(1, 400000)  # 2500 cycles @ 1GHz = 2.5us
        d = binding.to_dict()
        assert d["evidence_sha256"] == "deadbeef"
        assert d["stats_sha256"]
        assert d["window_kind"] == "BARRIER_TRAFFIC_WINDOW"
        # roundtrip
        b2 = NetworkWindowBinding.from_dict(d)
        assert b2 == binding

    def test_cycles_only_mode_without_clock(self):
        ev = FakeEvidence({"completion_time": 2500, "delivered": 4})
        binding, cycles = bind_network_window(
            evidence=ev, chain=CHAIN, network_clock_hz=None,
            evidence_sha256="deadbeef")
        assert cycles == 2500  # raw cycles; no wall-time claim possible
        assert binding.network_clock_hz is None

    def test_missing_completion_time_refuses(self):
        ev = FakeEvidence({"delivered": 4})  # no completion_time
        with pytest.raises(TimeError, match="completion_time"):
            bind_network_window(evidence=ev, chain=CHAIN,
                                network_clock_hz=10 ** 9,
                                evidence_sha256="deadbeef")

    def test_no_stats_refuses(self):
        with pytest.raises(TimeError, match="no BookSim stats"):
            bind_network_window(evidence=FakeEvidence(None), chain=CHAIN,
                                network_clock_hz=10 ** 9,
                                evidence_sha256="deadbeef")

    def test_packet_count_mismatch_refuses(self):
        ev = FakeEvidence({"completion_time": 100, "delivered": 3})
        with pytest.raises(TimeError, match="does not belong"):
            bind_network_window(evidence=ev, chain=CHAIN,
                                network_clock_hz=10 ** 9,
                                evidence_sha256="deadbeef",
                                expected_packets=4)

    def test_zero_clock_refuses(self):
        ev = FakeEvidence({"completion_time": 100})
        with pytest.raises(TimeError):
            bind_network_window(evidence=ev, chain=CHAIN,
                                network_clock_hz=0,
                                evidence_sha256="deadbeef")

    def test_binding_field_mutation_detected(self):
        ev = FakeEvidence({"completion_time": 2500, "delivered": 4})
        binding, _ = bind_network_window(evidence=ev, chain=CHAIN,
                                         network_clock_hz=10 ** 9,
                                         evidence_sha256="deadbeef")
        d = binding.to_dict()
        d["backend_config_hash"] = "tampered"
        b2 = NetworkWindowBinding.from_dict(d)
        assert b2 != binding

    def test_missing_evidence_digest_refuses(self):
        """Timing that cannot name its evidence is not timing (§42)."""
        ev = FakeEvidence({"completion_time": 2500, "delivered": 4})
        for bad in ("", None):
            with pytest.raises(TimeError, match="evidence"):
                bind_network_window(evidence=ev, chain=CHAIN,
                                    network_clock_hz=10 ** 9,
                                    evidence_sha256=bad)

    def test_unknown_field_in_binding_refuses(self):
        ev = FakeEvidence({"completion_time": 2500, "delivered": 4})
        binding, _ = bind_network_window(evidence=ev, chain=CHAIN,
                                         network_clock_hz=10 ** 9,
                                         evidence_sha256="deadbeef")
        d = binding.to_dict()
        d["invented_field"] = 1
        with pytest.raises(TimeError, match="exactly"):
            NetworkWindowBinding.from_dict(d)


# ── §73/§75/§80/§83/§84: result tamper matrix ────────────────────────

class TestResultTamperMatrix:
    def build(self):
        model = make_model()
        w = basic_workload(model)
        g = WaveEEventGraph(workload=w, wave_d_chain=dict(CHAIN))
        s = schedule_workload(w)
        return w, g, build_performance_result(graph=g, schedule=s)

    def test_roundtrip_reverify(self):
        _w, _g, doc = self.build()
        reverify_result(copy.deepcopy(doc), workload=_w)

    def test_makespan_tamper_refuses(self):
        w, _g, doc = self.build()
        t = copy.deepcopy(doc)
        t["makespan"] = {"numerator": 999, "denominator": 1}
        with pytest.raises(ResultError, match="makespan"):
            reverify_result(t, workload=w)

    def test_dependency_critical_path_tamper_refuses(self):
        w, _g, doc = self.build()
        t = copy.deepcopy(doc)
        t["dependency_critical_path"] = ["NONEXISTENT"]
        with pytest.raises(ResultError, match="dependency_critical_path"):
            reverify_result(t, workload=w)

    def test_dependency_critical_path_duration_tamper_refuses(self):
        w, _g, doc = self.build()
        t = copy.deepcopy(doc)
        t["dependency_critical_path_duration"] = {"numerator": 1,
                                                  "denominator": 7}
        with pytest.raises(ResultError, match="dependency_critical_path_duration"):
            reverify_result(t, workload=w)

    def test_utilization_tamper_refuses(self):
        w, _g, doc = self.build()
        t = copy.deepcopy(doc)
        t["utilization"] = {"gpu.compute": {"utilization": 0.99}}
        with pytest.raises(ResultError, match="utilization"):
            reverify_result(t, workload=w)

    def test_unknown_field_refuses_schema_close(self):
        w, _g, doc = self.build()
        t = copy.deepcopy(doc)
        t["estimated_speedup"] = "47%"
        with pytest.raises(ResultError, match="schema close"):
            reverify_result(t, workload=w)

    def test_schedule_row_tamper_refuses_identity(self):
        w, _g, doc = self.build()
        t = copy.deepcopy(doc)
        t["schedule"]["events"][0]["end"] = {"numerator": 1, "denominator": 9}
        # the re-derived makespan check fires first (schedule is the parent)
        with pytest.raises(ResultError, match="disagrees with the schedule"):
            reverify_result(t, workload=w)

    def test_resource_id_transplant_refuses(self):
        w, _g, doc = self.build()
        model2 = make_model(capacity=2)  # different model
        w2 = basic_workload(model2)
        g2 = WaveEEventGraph(workload=w2)
        doc2 = build_performance_result(graph=g2, schedule=schedule_workload(w2))
        t = copy.deepcopy(doc)
        t["resource_id"] = doc2["resource_id"]
        with pytest.raises(ResultError, match="canonical content"):
            reverify_result(t, workload=w)

    def test_same_output_different_model_transplant_refuses(self):
        """§131: identical makespan, different model → hybrid refuses."""
        w, _g, doc = self.build()
        model2 = WaveEPerformanceModel(
            clocks=(ClockDef("net", 10 ** 9),),
            resources=(ResourceDef("gpu.compute", "EXCLUSIVE", capacity=1),
                       ResourceDef("unused_hbm", "BANDWIDTH",
                                   bandwidth_bytes_per_s=10 ** 12)),
            network_clock="net")
        w2 = WaveETemporalWorkload(
            performance_model=model2,
            events=(WaveETemporalEvent("K", "COMPUTE", QTime(4000, US),
                                       "gpu.compute"),
                    WaveETemporalEvent("T", "COMPUTE", QTime(1000, US),
                                       "gpu.compute", deps=("K",))))
        g2 = WaveEEventGraph(workload=w2)
        doc2 = build_performance_result(graph=g2,
                                        schedule=schedule_workload(w2))
        assert doc2["makespan"] == doc["makespan"]  # same number
        t = copy.deepcopy(doc)
        t["performance_model_id"] = doc2["performance_model_id"]
        t["event_graph_id"] = doc2["event_graph_id"]
        t["temporal_workload_id"] = doc2["temporal_workload_id"]
        with pytest.raises(ResultError, match="canonical content"):
            reverify_result(t, workload=w)

    def test_incomplete_schedule_refuses(self):
        w, _g, _doc = self.build()
        g = WaveEEventGraph(workload=w)
        from veritx_dse.wavee.scheduler import ScheduledEvent, Schedule
        partial = Schedule((ScheduledEvent(
            "K", QTime(0), QTime(4000, US), "gpu.compute"),))
        with pytest.raises(ResultError, match="incomplete schedule"):
            build_performance_result(graph=g, schedule=partial)


# ── QTime exactness + unit law (§12/§86/§88) ─────────────────────────

class TestTimeUnits:
    def test_cycles_to_seconds_requires_positive_clock(self):
        with pytest.raises(TimeError):
            QTime.from_cycles(100, 0)
        with pytest.raises(TimeError):
            QTime.from_cycles(100, -1)

    def test_noninteger_cycles_refuse(self):
        with pytest.raises(TimeError):
            QTime.from_cycles(1.5, 10 ** 9)

    def test_negative_cycles_refuse(self):
        with pytest.raises(TimeError):
            QTime.from_cycles(-1, 10 ** 9)

    def test_exact_rational_no_rounding(self):
        # 1 cycle @ 1.4 GHz = 1/1.4e9 s — NOT representable in integer ps
        t = QTime.from_cycles(1, Fraction(14, 10) * 10 ** 9)
        assert t == QTime(1, 1400000000)

    def test_qtime_rejects_zero_denominator(self):
        with pytest.raises(TimeError):
            QTime(1, 0)

    def test_qtime_dict_roundtrip(self):
        t = QTime(Fraction(355, 113))
        assert QTime.from_dict(t.to_dict()) == t

    def test_duration_between_refuses_reversed(self):
        with pytest.raises(TimeError):
            from veritx_dse.wavee.time import duration_between
            duration_between(QTime(2), QTime(1))
