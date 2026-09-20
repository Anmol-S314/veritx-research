"""Wave E demonstration corpus + real backend E2E (§94/§95/§135/§136).

Three sensitivity demonstrations (compute-dominant, network-exposed,
overlap) whose conclusions are DERIVED from schedules — never
hard-coded labels (§90) — plus one real certified BookSim execution
whose evidence flows through bind_network_window into a verified
Wave-E result (§94), request-level metrics, and a scheduler scaling
check (§140).

Every timeline below is small enough to check by hand (§136).
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))


import os
from fractions import Fraction

import pytest

from veritx_dse.wavee.metrics import (
    dependency_critical_path, resource_utilization,
)
from veritx_dse.wavee.model import (
    ClockDef, ResourceDef, WaveEPerformanceModel,
)
from veritx_dse.wavee.network import bind_network_window
from veritx_dse.wavee.sensitivity import sensitivity_analysis
from veritx_dse.wavee.result import (
    WaveEEventGraph, build_performance_result, reverify_result,
)
from veritx_dse.wavee.scheduler import schedule_workload
from veritx_dse.wavee.time import QTime
from veritx_dse.wavee.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW, WaveERequest, WaveETemporalEvent,
    WaveETemporalWorkload,
)

US = 10 ** 6


def model(capacity=1, bandwidth=1200):
    return WaveEPerformanceModel(
        clocks=(ClockDef("net", 10 ** 9),),
        resources=(ResourceDef("gpu.compute", "EXCLUSIVE", capacity=capacity),
                   ResourceDef("hbm", "BANDWIDTH",
                               bandwidth_bytes_per_s=bandwidth)),
        memory_source="ANALYTICAL_BANDWIDTH",
        network_clock="net")


def comp(eid, dur_us, deps=(), **kw):
    return WaveETemporalEvent(eid, "COMPUTE", QTime(dur_us, US),
                              "gpu.compute", deps=tuple(deps), **kw)


def net(eid="NET", deps=()):
    return WaveETemporalEvent(eid, "NETWORK_TRAFFIC_WINDOW", QTime(0),
                              deps=tuple(deps))


def _mem(eid, nbytes, deps=()):
    return WaveETemporalEvent(eid, "MEMORY_READ", QTime(0), "hbm",
                              deps=tuple(deps), bytes_count=nbytes)


def _frac(d):
    return Fraction(d["numerator"], d["denominator"])


class TestDemoAComputeDominant:
    """§135.A: 2x compute matters; 2x network barely changes anything."""

    def test_derived_from_schedule(self):
        w = WaveETemporalWorkload(
            performance_model=model(),
            events=(comp("K", 4000), net(),
                    comp("TAIL", 1000, ("K", "NET"))),
            wave_d_operation_ids=("op1",))
        net_dur = {"NET": QTime(2500, US)}
        s = schedule_workload(w, network_durations=net_dur)
        out = sensitivity_analysis(w, s, network_durations=net_dur)
        # Timeline (§136): K [0,4ms] gpu; NET [0,2.5ms] (hidden);
        #                  TAIL [4ms,5ms] → makespan 5ms
        assert s.start("K") == QTime(0)
        assert s.end("K") == QTime(4000, US)
        assert s.start("TAIL") == QTime(4000, US)
        assert _frac(out["baseline_makespan"]) == Fraction(5, 1000)
        # network → 0: makespan UNCHANGED (fully hidden)
        assert _frac(out["exposed_network"]) == 0
        # local durations 2x: K→8ms AND TAIL→2ms → makespan 10ms
        t2x = _frac(out["parameters"]["local_durations_2x"]["makespan"])
        assert t2x == Fraction(1, 100)
        # speedup table shows compute sensitivity >> network sensitivity
        assert out["parameters"]["local_durations_2x"]["speedup"] \
            == pytest.approx(0.5)
        util = resource_utilization(w, s)
        assert util["gpu.compute"]["utilization"] == pytest.approx(1.0)


class TestDemoBNetworkExposed:
    """§135.B: network acceleration materially changes makespan."""

    def test_derived_from_schedule(self):
        w = WaveETemporalWorkload(
            performance_model=model(),
            events=(net(), comp("TAIL", 1000, ("NET",))),
            wave_d_operation_ids=("op1",))
        net_dur = {"NET": QTime(2500, US)}
        s = schedule_workload(w, network_durations=net_dur)
        out = sensitivity_analysis(w, s, network_durations=net_dur)
        # Timeline: NET [0,2.5ms] exposed; TAIL [2.5ms,3.5ms]
        assert _frac(out["baseline_makespan"]) == Fraction(35, 10000)
        # network → 0: makespan drops to exactly the TAIL duration
        assert _frac(out["exposed_network"]) == Fraction(1, 400)
        # 2x local durations only moves the tail: 2ms tail → 4.5ms
        t2x = _frac(out["parameters"]["local_durations_2x"]["makespan"])
        assert t2x == Fraction(45, 10000)


class TestDemoCOverlap:
    """§135.C: large network active time, mostly hidden by compute."""

    def test_derived_from_schedule(self):
        w = WaveETemporalWorkload(
            performance_model=model(),
            events=(comp("K1", 3000), net(deps=()),
                    comp("K2", 3000, ("K1",)),
                    comp("JOIN", 500, ("K2", "NET"))),
            wave_d_operation_ids=("op1",))
        net_dur = {"NET": QTime(7000, US)}  # window ends after K2
        s = schedule_workload(w, network_durations=net_dur)
        out = sensitivity_analysis(w, s, network_durations=net_dur)
        # Timeline: K1 [0,3ms]; NET [0,7ms]; K2 [3ms,6ms];
        #           JOIN [7ms,7.5ms] → makespan 7.5ms
        assert _frac(out["baseline_makespan"]) == Fraction(75, 10000)
        # network active 7ms, but removing it entirely saves only 1ms:
        # the window is ~86% hidden under compute
        assert _frac(out["exposed_network"]) == Fraction(1, 1000)
        assert _frac(out["baseline_makespan"]) - _frac(out["exposed_network"]) \
            == Fraction(65, 10000)
        # §100: duration-sum critical path IS NET→JOIN (7.5ms) — the
        # window determines quiescence — while the compute chain sums to
        # 6.5ms. Counterfactual removal (1ms) and critical-path membership
        # are DIFFERENT quantities and both are reported, never conflated.
        path, length = dependency_critical_path(w, s)
        assert set(path) == {"NET", "JOIN"}
        assert length == QTime(7500, US)


class TestRequestMetrics:
    def test_two_requests_arrival_and_summary(self):
        reqs = (WaveERequest("r1", QTime(0), completion_event_ids=("D1",)),
                WaveERequest("r2", QTime(600, US),
                             completion_event_ids=("D2",)))
        w = WaveETemporalWorkload(
            performance_model=model(capacity=1),
            events=(comp("P1", 2000, request_id="r1"),
                    comp("D1", 500, ("P1",), request_id="r1"),
                    comp("P2", 2000, request_id="r2"),
                    comp("D2", 500, ("P2",), request_id="r2")),
            requests=reqs)
        s = schedule_workload(w)
        from veritx_dse.wavee.metrics import latency_summary, request_latencies
        rows = request_latencies(w, s)
        assert len(rows) == 2
        # §20 FIFO by earliest-ready across ALL events (not per-request):
        # t=0: P1 (id tie-break) ; t=2ms: P2 (ready 0 beats D1's 2ms);
        # t=4ms: D1 ; t=4.5ms: D2
        # r1 completes at D1 end 4.5ms → latency 4.5ms
        assert _frac(rows[0]["latency"]) == Fraction(9, 2000)
        # r2 completes at D2 end 5ms; arrival 0.6ms → latency 4.4ms
        assert _frac(rows[1]["latency"]) == Fraction(11, 2500)
        summary = latency_summary(rows)
        assert summary["sample_count"] == 2
        # r1 (4.5ms) > r2 (4.4ms): FIFO starves r1's dependent D1
        assert _frac(summary["max"]) == Fraction(9, 2000)
        assert _frac(rows[1]["arrival"]) == Fraction(6, 10000)

    def test_ttft_requires_explicit_first_token(self):
        req = (WaveERequest("r1", QTime(0), completion_event_ids=("D",),
                            first_token_event_id="T1"),)
        w = WaveETemporalWorkload(
            performance_model=model(),
            events=(comp("P", 2000, request_id="r1"),
                    comp("T1", 300, ("P",), request_id="r1"),
                    comp("T2", 300, ("T1",), request_id="r1"),
                    comp("D", 200, ("T2",), request_id="r1")),
            requests=req)
        s = schedule_workload(w)
        from veritx_dse.wavee.metrics import request_latencies
        rows = request_latencies(w, s)
        # TTFT = end of T1 (2.3ms) - arrival (0)
        assert _frac(rows[0]["first_token_latency"]) == Fraction(23, 10000)
        # total latency 2.8ms; TPOT-style cadence derivable from steps
        assert _frac(rows[0]["latency"]) == Fraction(28, 10000)


class TestSensitivityCorrectness:
    """The counterfactuals must zero EXACTLY the class they name.

    ``exposed_compute`` and ``exposed_memory`` were computed with the
    same perturbation (zero all non-memory durations), so they were
    always identical and the memory label was a lie.
    """

    def _workload(self):
        return WaveETemporalWorkload(
            performance_model=model(),
            events=(comp("K", 3000), _mem("M", 1200),
                    comp("TAIL", 1000, ("K", "M"))))

    def test_compute_and_memory_counterfactuals_differ(self):
        w = self._workload()
        s = schedule_workload(w)
        out = sensitivity_analysis(w, s)
        assert _frac(out["exposed_compute"]) != _frac(out["exposed_memory"])
        # zeroing compute leaves the 1s memory transfer exposed
        assert _frac(out["exposed_compute"]) == Fraction(1, 1000)
        # zeroing memory leaves the 3ms compute chain + 1ms tail exposed
        assert _frac(out["exposed_memory"]) == Fraction(997, 1000)

    def test_network_window_perturbations_exist_and_scale(self):
        w = WaveETemporalWorkload(
            performance_model=model(),
            events=(net(), comp("TAIL", 1000, ("NET",))),
            wave_d_operation_ids=("op1",))
        net_dur = {"NET": QTime(2500, US)}
        s = schedule_workload(w, network_durations=net_dur)
        out = sensitivity_analysis(w, s, network_durations=net_dur)
        assert "network_window_0.5x" in out["parameters"]
        assert "network_window_2x" in out["parameters"]
        assert _frac(out["parameters"]["network_window_2x"]["makespan"]) \
            > _frac(out["parameters"]["network_window_0.5x"]["makespan"])
        # the evidence-bound window is what got scaled, not a dead field
        assert _frac(out["parameters"]["network_window_2x"]["makespan"]) \
            == Fraction(6000, US)

    def test_perturbation_identity_is_reported(self):
        w = self._workload()
        s = schedule_workload(w)
        out = sensitivity_analysis(w, s)
        row = out["parameters"]["bandwidth_2x"]
        assert row["perturbed_model_id"] != w.performance_model.performance_model_id()
        assert row["perturbed_workload_id"] != w.temporal_workload_id()

    def test_perturb_model_changes_exactly_one_variable(self):
        """A counterfactual that also changes the memory authority is not
        a counterfactual."""
        from veritx_dse.wavee.sensitivity import perturb_model
        base = model()
        assert base.memory_source == "ANALYTICAL_BANDWIDTH"
        for factor in (Fraction(1, 2), Fraction(2)):
            p = perturb_model(base, bandwidth_factor=factor)
            assert p.memory_source == base.memory_source
            assert p.compute_source == base.compute_source
            assert p.arbitration_exclusive == base.arbitration_exclusive
            assert p.arbitration_bandwidth == base.arbitration_bandwidth
            assert p.performance_model_id() != base.performance_model_id()

    def test_perturb_model_preserves_arbitration(self):
        from veritx_dse.wavee.sensitivity import perturb_model
        base = model()
        p = perturb_model(base, bandwidth_factor=Fraction(2))
        assert p.arbitration_exclusive == base.arbitration_exclusive
        assert p.arbitration_bandwidth == base.arbitration_bandwidth


class TestScaling:
    def test_large_synthetic_workload_completes(self):
        """§140: 5000-event layered DAG schedules in event-driven time."""
        import time as _time
        n_layers, width = 50, 100
        events = []
        for layer in range(n_layers):
            for i in range(width):
                eid = f"e{layer}_{i}"
                deps = (f"e{layer-1}_{i}",) if layer else ()
                events.append(comp(eid, 10 + (i % 7), deps))
        w = WaveETemporalWorkload(performance_model=model(capacity=4),
                                  events=tuple(events))
        t0 = _time.perf_counter()
        s = schedule_workload(w)
        dt = _time.perf_counter() - t0
        assert len(s) == n_layers * width
        # each layer is sequential: makespan = 50 × 10us (min duration)
        assert s.makespan() >= QTime(n_layers * 10, US)
        assert dt < 30.0  # generous CI bound; event-driven, not per-cycle

    def test_wide_flat_graph_scales(self):
        """§140: 5000 independent events on capacity 4.

        This is the shape that exposed an O(n^2) admission scan: every
        event is ready at once, so a per-admission rescan of the whole
        ready set is quadratic. The bound is generous but would catch a
        return to that behaviour (which took ~10s here, vs ~0.1s).
        """
        import time as _time
        n = 5000
        events = tuple(comp(f"e{i}", 1 + (i % 5)) for i in range(n))
        w = WaveETemporalWorkload(performance_model=model(capacity=4),
                                  events=events)
        t0 = _time.perf_counter()
        s = schedule_workload(w)
        dt = _time.perf_counter() - t0
        assert len(s) == n
        assert dt < 5.0

    def test_wide_bandwidth_sharing_scales(self):
        """§140: 20000 transfers sharing one bandwidth resource."""
        import time as _time
        n = 20000
        events = tuple(_mem(f"m{i}", 120) for i in range(n))
        w = WaveETemporalWorkload(performance_model=model(),
                                  events=events)
        t0 = _time.perf_counter()
        s = schedule_workload(w)
        dt = _time.perf_counter() - t0
        assert len(s) == n
        assert dt < 5.0


@pytest.mark.skipif(
    not os.environ.get("WAVE_E_E2E"),
    reason="real BookSim execution gated by WAVE_E_E2E=1 (§94)")
class TestRealBookSimE2E:
    """Real certified execution: Wave-D traffic → BookSim → Wave-E result.

    Run with: WAVE_E_E2E=1 python3 -m pytest tests/test_wave_e_demos.py -k E2E

    This is the §1 trust chain over REAL evidence:

        sealed Wave-D semantics → prepare (conservation gates) →
        qualified BookSim execution → CertifiedBookSimEvidence →
        bind_network_window (§42 provenance) → WaveEEventGraph →
        deterministic schedule → verified performance result

    Every hash in the result's wave_d_chain / network_binding is the
    REAL one from the executed run — nothing is transcribed by hand.
    """

    def test_booksim_evidence_binds_into_wave_e_result(self, tmp_path):
        from pathlib import Path

        from veritx_dse.backend.booksim import run_qualified_booksim
        from veritx_dse.core.paths import REPO as REPO_ROOT
        from veritx_dse.simulation.booksim import find_booksim_bin
        from veritx_dse.waved.backend import prepare_waved_booksim
        from veritx_dse.waved.messages import LogicalMessageArtifact
        from veritx_dse.waved.operations import (
            KIND_P2P, OperationGraph, OperationNode, P2PTransfer,
        )
        from veritx_dse.waved.parallelism import ParallelismArtifact
        from veritx_dse.waved.semantics import WaveDWorkloadSemantics
        from veritx_dse.waved.traffic import PhysicalTrafficArtifact
        from veritx_dse.wavee.network import (
            WINDOW_KIND_BARRIER, bind_network_window,
        )
        from veritx_dse.wavee.result import reverify_result

        binary = find_booksim_bin(REPO_ROOT)

        # ── 1) minimal real Wave-D 2-rank P2P traffic artifact ──────
        par = ParallelismArtifact(tp=2, pp=1, ep=1, dp=1)
        sem = WaveDWorkloadSemantics(phase="DECODE")
        graph = OperationGraph(
            parallelism=par, semantics=sem, workload_id="wvd-e2e",
            nodes=(OperationNode(
                "p2p0", KIND_P2P, "DECODE", 0, 0, (),
                {"transfer_id": "t0"}),),
            collectives=(), p2p_transfers=(P2PTransfer(0, 1, 300, "t0"),),
            multicasts=())
        logical = LogicalMessageArtifact(graph=graph)
        logical.validate_against_oracle()

        # reuse the Wave-D certified bundle chain (2-rank mesh)
        from test_fabric_artifact import build_chain, compose
        from test_backend_bundle import make_bundle
        from veritx_dse.backend.bundle import make_resolved_fabric_bundle
        from veritx_dse.model.compile_model import TopologyFamily
        chain = build_chain(tp=2, pp=1, ep=1, dp=1, n_agents=2,
                            family=TopologyFamily.MESH)
        bundle = make_bundle(chain)
        pt = PhysicalTrafficArtifact(logical=logical, bundle=bundle)
        pt.validate_conservation()

        # ── 2) prepare through the sealed Wave-B/D path ─────────────
        prepared, summary = prepare_waved_booksim(pt)
        assert summary["num_packets"] == pt.totals()["packet_count"]

        # ── 3) REAL qualified execution ─────────────────────────────
        evidence = run_qualified_booksim(
            prepared, run_dir=Path(tmp_path), repo_root=REPO_ROOT,
            timeout=120, binary=Path(binary))
        assert evidence.exit_status == 0
        assert evidence.route_equivalence == "EXACT"
        stats = evidence.stats
        assert stats["delivered"] == summary["num_packets"]
        assert stats["flits_injected"] == summary["flits_total"]
        assert stats["completion_time"] > 0

        # ── 4) bind the evidence into a Wave-E network window ───────
        wd_chain = {
            "waved_workload_id": graph.workload_id,
            "operation_graph_id": graph.operation_graph_id(),
            "message_artifact_id": logical.message_artifact_id(),
            "physical_traffic_id": pt.physical_traffic_id(),
            "resolved_fabric_hash": bundle.resolved_fabric.
                resolved_fabric_hash(),
            "packet_format_hash":
                bundle.packet_format.packet_format_hash(),
            "backend_config_hash": evidence.backend_config_hash,
            "backend_input_hash": evidence.backend_input_hash,
        }
        binding, window = bind_network_window(
            evidence=evidence, chain=wd_chain, network_clock_hz=10 ** 9,
            expected_packets=summary["num_packets"])
        assert binding.window_kind == WINDOW_KIND_BARRIER
        assert binding.evidence_sha256
        assert window == QTime(stats["completion_time"], 10 ** 9)

        # ── 5) Wave-E event graph: NET ref + local compute tail ─────
        model = WaveEPerformanceModel(
            clocks=(ClockDef("net", 10 ** 9),),
            resources=(ResourceDef("gpu.compute", "EXCLUSIVE",
                                   capacity=1),),
            network_clock="net")
        events = (
            WaveETemporalEvent(
                "NET", EVENT_NETWORK_TRAFFIC_WINDOW, QTime(0),
                phase="DECODE", rank=0),
            WaveETemporalEvent(
                "TAIL", "COMPUTE", QTime(500, 10 ** 6), "gpu.compute",
                deps=("NET",), phase="DECODE", rank=0),
        )
        w = WaveETemporalWorkload(
            performance_model=model, events=events,
            wave_d_operation_ids=("p2p0",))
        # (provenance check runs in __init__: NET cites a declared op)
        egraph = WaveEEventGraph(workload=w, network_binding=binding,
                                 wave_d_chain=wd_chain)

        # ── 6) deterministic schedule over the REAL window ──────────
        schedule = schedule_workload(w, network_durations=
                                     egraph.network_durations())
        assert schedule.start("NET") == QTime(0)
        assert schedule.end("NET") == window
        assert schedule.start("TAIL") == window
        assert schedule.makespan() == window + QTime(500, 10 ** 6)

        # ── 7) verified result: identity + re-derivable summaries ───
        result = build_performance_result(graph=egraph, schedule=schedule)
        assert result["wave_d_chain"] == wd_chain
        assert result["network_binding"]["evidence_sha256"] \
            == binding.evidence_sha256
        assert result["makespan"] == schedule.makespan().to_dict()
        # loaded result must re-derive everything or refuse (§74)
        reverify_result(result, workload=w)
        # makespan = real network window + local tail, in exact rationals
        assert result["makespan"] \
            == (window + QTime(500, 10 ** 6)).to_dict()
