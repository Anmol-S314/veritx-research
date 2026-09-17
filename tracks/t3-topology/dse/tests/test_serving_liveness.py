"""Liveness observability tests (review-directed, post-PR5).

Deterministic, no simulator binaries required. Two layers:

1. Pure probe tests — the 6-state classification vocabulary, fingerprint
   stability, report shape, and the review's eight answerable questions.
2. Fake-backend-driven tests — PR5's real-process fixture produces reply
   sequences through ServingBackendSession; observations are built from
   those replies EXACTLY the way the serving loop's observe block does
   (same field extraction), then classified. This keeps the tests
   honest about the wiring without launching the real serving loop.

Required scenarios (review list):
  * Waiting repeats with no clock/request progress
  * clock advances but no request retires
  * request retires
  * backend completion arrives
  * scheduler dispatch changes state
  * multiple instances: one progresses, one stuck
  * pending request with zero inflight work
  * inflight work with no backend completion

Instrumentation-independence: the probe is pure — observe() never
mutates the observation beyond assigning its round number, and the
serving-loop observe block is wrapped so any instrumentation error can
not change simulation behavior (pinned by a test).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_LLM_DIR = Path(__file__).resolve().parents[4] / "third_party" / "llmservingsim"
sys.path.insert(0, str(_LLM_DIR))

from serving.core.liveness import (  # noqa: E402
    LivenessProbe,
    ProgressObservation,
    attach_to_failure,
    BACKEND_NOT_RESPONDING,
    BACKEND_RESPONSIVE_NO_TIME_ADVANCE,
    SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS,
    SCHEDULER_NO_DISPATCH,
    INFLIGHT_NO_COMPLETION,
    USEFUL_PROGRESS,
)

from veritx_dse.simulation.llmserving_protocol import (  # noqa: E402
    ServingBackendSession,
)

FAKE = Path(__file__).parent / "fake_serving_backend.py"


def backend_argv(mode: str, npus: int = 2) -> list[str]:
    return [sys.executable, str(FAKE), mode, str(npus)]


def obs_from_reply(reply, *, sim_time, retired, pending, deferred,
                   inflight, dispatched, last_command,
                   per_instance=None, backend_alive=True):
    """Build an observation from a BackendReply exactly as the serving
    loop's observe block does (same extraction, same fields)."""
    return ProgressObservation(
        round=0,
        sim_time=sim_time,
        backend_cycle=reply.cycle,
        backend_completions=reply.completions(),
        retired_requests=retired,
        pending_requests=pending,
        deferred_requests=deferred,
        inflight_batches=inflight,
        dispatched_this_round=dispatched,
        last_command=last_command,
        per_instance=per_instance or {},
        backend_alive=backend_alive,
    )


# ---------------------------------------------------------------------------
# layer 1: pure probe semantics
# ---------------------------------------------------------------------------


class TestClassification:
    def test_waiting_repeat_no_clock_no_progress(self):
        """THE livelock shape: Waiting forever, nothing changes."""
        p = LivenessProbe()
        for _ in range(4):
            p.observe(ProgressObservation(
                round=0, sim_time=1000, backend_cycle=1000,
                backend_completions=0, retired_requests=0,
                pending_requests=3, deferred_requests=0,
                inflight_batches=0, dispatched_this_round=False,
                last_command="pass", backend_alive=True))
        assert p.rounds_unchanged == 3
        assert p.classify() == BACKEND_RESPONSIVE_NO_TIME_ADVANCE

    def test_clock_advances_no_request_retires(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=2, retired_requests=0,
            pending_requests=5, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=True, last_command="/w/b0.llm"))
        p.observe(ProgressObservation(
            round=0, sim_time=2500, backend_cycle=2500,
            backend_completions=2, retired_requests=0,
            pending_requests=5, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=False, last_command="pass"))
        assert p.classify() == SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS

    def test_request_retires_is_useful_progress(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=2, retired_requests=0,
            pending_requests=5, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=True, last_command="/w/b0.llm"))
        p.observe(ProgressObservation(
            round=0, sim_time=2500, backend_cycle=2500,
            backend_completions=2, retired_requests=1,
            pending_requests=4, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=False, last_command="pass"))
        assert p.classify() == USEFUL_PROGRESS

    def test_completion_arrival_is_useful_progress(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=0, retired_requests=0,
            pending_requests=2, deferred_requests=0, inflight_batches=2,
            dispatched_this_round=True, last_command="/w/b0.llm"))
        p.observe(ProgressObservation(
            round=0, sim_time=1800, backend_cycle=1800,
            backend_completions=2, retired_requests=1,
            pending_requests=1, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=False, last_command="pass"))
        assert p.classify() == USEFUL_PROGRESS

    def test_dispatch_changes_state_is_useful_progress(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=500, backend_cycle=500,
            backend_completions=0, retired_requests=0,
            pending_requests=1, deferred_requests=0, inflight_batches=0,
            dispatched_this_round=False, last_command="pass"))
        p.observe(ProgressObservation(
            round=0, sim_time=500, backend_cycle=500,
            backend_completions=0, retired_requests=0,
            pending_requests=0, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=True, last_command="/w/b0.llm"))
        assert p.classify() == USEFUL_PROGRESS

    def test_scheduler_no_dispatch_with_pending_work(self):
        """pending > 0, inflight = 0, dispatch = 0, backend responsive."""
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=0, retired_requests=0,
            pending_requests=4, deferred_requests=0, inflight_batches=0,
            dispatched_this_round=False, last_command="pass"))
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=2, retired_requests=0,
            pending_requests=4, deferred_requests=0, inflight_batches=0,
            dispatched_this_round=False, last_command="pass"))
        # completions arrived but clock did not advance beyond prev
        assert p.classify() == SCHEDULER_NO_DISPATCH

    def test_inflight_no_completion(self):
        """inflight > 0, backend completions = 0, Waiting continues."""
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=0, retired_requests=0,
            pending_requests=0, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=True, last_command="/w/b0.llm"))
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=0, retired_requests=0,
            pending_requests=0, deferred_requests=0, inflight_batches=1,
            dispatched_this_round=False, last_command="pass"))
        assert p.classify() == INFLIGHT_NO_COMPLETION

    def test_backend_not_responding(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=2, retired_requests=1,
            pending_requests=0, deferred_requests=0, inflight_batches=0,
            dispatched_this_round=False, last_command="pass",
            backend_alive=False))
        assert p.classify() == BACKEND_NOT_RESPONDING

    def test_one_instance_progresses_one_stuck(self):
        """Multi-instance: per-instance state identifies the stuck one."""
        p = LivenessProbe()
        inst_a = {"instance_0": {"waiting": 0, "running": 2, "inflight": 1, "dp_queued": 0},
                  "instance_1": {"waiting": 3, "running": 0, "inflight": 0, "dp_queued": 0}}
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000, backend_completions=2,
            retired_requests=2, pending_requests=3, deferred_requests=0,
            inflight_batches=1, dispatched_this_round=True,
            last_command="/w/i0_b5.llm", per_instance=dict(inst_a)))
        inst_b = {"instance_0": {"waiting": 0, "running": 2, "inflight": 1, "dp_queued": 0},
                  "instance_1": {"waiting": 3, "running": 0, "inflight": 0, "dp_queued": 0}}
        p.observe(ProgressObservation(
            round=0, sim_time=3000, backend_cycle=3000, backend_completions=2,
            retired_requests=3, pending_requests=3, deferred_requests=0,
            inflight_batches=1, dispatched_this_round=True,
            last_command="/w/i0_b6.llm", per_instance=inst_b))
        assert p.classify() == USEFUL_PROGRESS
        a = p.answers()
        assert a["stuck_instance"] == "instance_1"


class TestReportShape:
    def test_no_useful_progress_report_is_machine_readable(self):
        p = LivenessProbe()
        for _ in range(3):
            p.observe(ProgressObservation(
                round=0, sim_time=1000, backend_cycle=1000,
                backend_completions=0, retired_requests=0,
                pending_requests=3, deferred_requests=0,
                inflight_batches=0, dispatched_this_round=False,
                last_command="pass 1750",
                per_instance={"instance_0": {"waiting": 2, "running": 0,
                                             "inflight": 0, "dp_queued": 0}}))
        r = p.no_useful_progress_report()
        # every review-mandated field present
        for key in ("state", "rounds_unchanged", "sim_time", "retired_requests",
                    "pending_requests", "deferred_requests", "inflight_batches",
                    "backend_completions", "last_command", "per_instance"):
            assert key in r, key
        json.dumps(r)  # serializable

    def test_render_matches_mandated_block(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=0, retired_requests=0,
            pending_requests=3, deferred_requests=0, inflight_batches=0,
            dispatched_this_round=False, last_command="pass"))
        p.observe(ProgressObservation(
            round=0, sim_time=1000, backend_cycle=1000,
            backend_completions=0, retired_requests=0,
            pending_requests=3, deferred_requests=0, inflight_batches=0,
            dispatched_this_round=False, last_command="pass"))
        text = p.render()
        assert text.startswith("NO_USEFUL_PROGRESS")
        assert "rounds_unchanged: 1" in text
        assert "sim_time: 1000" in text
        assert "last_command: pass" in text
        assert "per_instance:" in text

    def test_attach_to_failure_includes_snapshot(self):
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=7, backend_cycle=7, backend_completions=0,
            retired_requests=0, pending_requests=1, deferred_requests=0,
            inflight_batches=0, dispatched_this_round=False,
            last_command="exit", backend_alive=False))
        msg = attach_to_failure(p, "backend EOF")
        assert msg.startswith("backend EOF")
        assert "liveness snapshot at failure:" in msg
        assert "BACKEND_NOT_RESPONDING" in msg

    def test_fingerprint_ignores_wall_clock(self):
        """Fingerprint = scientific state only; identical state across
        rounds counts as unchanged regardless of real time taken."""
        p = LivenessProbe()
        p.observe(ProgressObservation(
            round=0, sim_time=100, backend_cycle=100, backend_completions=1,
            retired_requests=0, pending_requests=1, deferred_requests=0,
            inflight_batches=1, dispatched_this_round=True,
            last_command="/w/b.llm"))
        p.observe(ProgressObservation(
            round=0, sim_time=100, backend_cycle=100, backend_completions=1,
            retired_requests=0, pending_requests=1, deferred_requests=0,
            inflight_batches=1, dispatched_this_round=True,
            last_command="/w/b.llm"))
        assert p.rounds_unchanged == 1


# ---------------------------------------------------------------------------
# layer 2: fake-backend-driven (real pipes, same extraction as the loop)
# ---------------------------------------------------------------------------


class TestAgainstFakeBackend:
    def test_waiting_without_progress_end_to_end(self):
        """PR5's livelock fixture → probe → mandated diagnosis."""
        with ServingBackendSession(backend_argv("waiting_without_progress"),
                                   reply_timeout_s=5.0) as s:
            first = s.read_startup()
            p = LivenessProbe()
            p.observe(obs_from_reply(
                first, sim_time=first.cycle, retired=0, pending=2,
                deferred=0, inflight=0, dispatched=False,
                last_command="<startup>"))
            last_cmd = "pass"
            for _ in range(4):
                reply = s.command(last_cmd, timeout=5.0)
                p.observe(obs_from_reply(
                    reply, sim_time=reply.cycle, retired=0, pending=2,
                    deferred=0, inflight=0, dispatched=False,
                    last_command=last_cmd))
            # 4 identical pass replies; the streak is 3 because the startup
            # burst (2 completions, cycle 0) differs from Waiting-only
            # replies — exactly the transition the classifier must see.
            assert p.rounds_unchanged == 3
            assert p.classify() == BACKEND_RESPONSIVE_NO_TIME_ADVANCE
            a = p.answers()
            assert a["backend_alive"] is True
            assert a["sim_time_changing"] is False
            assert a["requests_retiring"] is False
            assert a["repeating_same_action"] is True
            # deterministic mandated output
            text = p.render()
            assert text.startswith("NO_USEFUL_PROGRESS")
            assert "state: BACKEND_RESPONSIVE_NO_TIME_ADVANCE" in text

    def test_normal_backend_shows_useful_progress(self):
        with ServingBackendSession(backend_argv("normal"),
                                   reply_timeout_s=5.0) as s:
            s.read_startup()
            p = LivenessProbe()
            reply = s.command("/inputs/w/b0.llm", timeout=5.0)
            p.observe(obs_from_reply(
                reply, sim_time=reply.cycle, retired=0, pending=1,
                deferred=0, inflight=1, dispatched=True,
                last_command="/inputs/w/b0.llm"))
            reply = s.command("pass", timeout=5.0)
            p.observe(obs_from_reply(
                reply, sim_time=reply.cycle, retired=1, pending=0,
                deferred=0, inflight=0, dispatched=False, last_command="pass"))
            assert p.classify() == USEFUL_PROGRESS
            assert p.answers()["requests_retiring"] is True

    def test_pass_target_jumps_clock_without_retirement(self):
        """pass <t> advances the backend clock; with no work retiring this
        is SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS, not USEFUL_PROGRESS."""
        with ServingBackendSession(backend_argv("normal"),
                                   reply_timeout_s=5.0) as s:
            s.read_startup()
            p = LivenessProbe()
            r0 = s.command("/inputs/w/b0.llm", timeout=5.0)
            p.observe(obs_from_reply(
                r0, sim_time=r0.cycle, retired=0, pending=1, deferred=0,
                inflight=1, dispatched=True, last_command="/inputs/w/b0.llm"))
            r1 = s.command("pass 90000", timeout=5.0)
            p.observe(obs_from_reply(
                r1, sim_time=r1.cycle, retired=0, pending=1, deferred=0,
                inflight=1, dispatched=False, last_command="pass 90000"))
            assert r1.cycle == 90000
            assert p.classify() == SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS


# ---------------------------------------------------------------------------
# instrumentation independence
# ---------------------------------------------------------------------------


class TestInstrumentationIsPure:
    def test_observe_never_mutates_beyond_round(self):
        o = ProgressObservation(
            round=0, sim_time=10, backend_cycle=10, backend_completions=1,
            retired_requests=0, pending_requests=1, deferred_requests=0,
            inflight_batches=1, dispatched_this_round=True,
            last_command="/w/b.llm")
        before = (o.sim_time, o.backend_cycle, o.backend_completions,
                  o.retired_requests, o.inflight_batches, o.last_command)
        p = LivenessProbe()
        p.observe(o)
        after = (o.sim_time, o.backend_cycle, o.backend_completions,
                 o.retired_requests, o.inflight_batches, o.last_command)
        assert before == after
        assert o.round == 1  # the only mutation

    def test_history_tail_is_bounded(self):
        p = LivenessProbe()
        for _ in range(100):
            p.observe(ProgressObservation(
                round=0, sim_time=1, backend_cycle=1, backend_completions=0,
                retired_requests=0, pending_requests=0, deferred_requests=0,
                inflight_batches=0, dispatched_this_round=False,
                last_command="pass"))
        assert len(p.history_tail) <= 20

    def test_empty_probe_renders_without_crash(self):
        p = LivenessProbe()
        assert "unavailable" in p.render()
        assert p.no_useful_progress_report() == {
            "error": "no observations recorded"}
        assert attach_to_failure(p, "x") == "x"
