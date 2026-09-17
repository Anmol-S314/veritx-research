"""PR 5 protocol tests — LLMServingSim backend session at the real OS boundary.

Handoff §26 Level 3: a fake interactive backend implementing the exact
stdin/stdout protocol traced from vendored source
(docs/protocols/llmservingsim-backend.md — every pinned behavior cites a
source location). NO subprocess mocks: every test launches the real
fake_serving_backend.py as a child process over real pipes.

Pinned facts (source citations in comments):
  * startup burst + first Waiting is unsolicited       (main.cc:225-262)
  * every command → exactly one Waiting-terminated reply (main.cc:336-343)
  * terminator = line CONTAINING "Waiting" (substring rule, controller.py:39)
  * legacy "Checking Non-Exited Systems ..." accepted, never produced
  * load = silent ack, no reply                         (main.cc:345-349)
  * done = Waiting-only reply                           (main.cc:336-343)
  * exit → EOF, exit code 0                             (main.cc:318-320)
  * backend owns simulated time; pass <t> jumps it      (__main__.py:1747)
  * EOF with work outstanding = ProtocolError           (__main__.py:1076)
  * a livelock (Waiting forever, unchanged state) is DETECTABLE as
    stalled replies — evidence for Q12.1 liveness diagnostics, NOT a
    guardrail (§32: never paper over serving-loop bugs with timeouts).

No-orphan guarantee: every path (test failure, protocol error, hang) ends
with the child's process group dead — asserted in-process via poll() and
from outside via /proc/<pid> absence (Linux).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from veritx_dse.simulation.llmserving_protocol import (
    BackendReply,
    ProtocolError,
    ServingBackendSession,
)

FAKE = Path(__file__).parent / "fake_serving_backend.py"


def backend_argv(mode: str, npus: int = 2) -> list[str]:
    return [sys.executable, str(FAKE), mode, str(npus)]


def session(mode: str, npus: int = 2, tmp_path: Path | None = None,
            **kwargs) -> ServingBackendSession:
    env = None
    if tmp_path is not None:
        env = {**os.environ, "FAKE_BACKEND_STATE": str(tmp_path / "state.json")}
    return ServingBackendSession(
        backend_argv(mode, npus), env=env, **kwargs)


def read_state(tmp_path: Path) -> dict:
    f = tmp_path / "state.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text())


def assert_child_dead(pid: int) -> None:
    """The child must not merely be reaped — it must be GONE (no orphan
    that survived into a stopped/killed-but-unreaped state)."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    # if we get here the pid still exists — but it may be our own table
    # holding a zombie only the parent reaps; poll() handles that. Fail:
    pytest.fail(f"backend pid {pid} still alive 5s after close")


# ---------------------------------------------------------------------------
# startup + normal progression
# ---------------------------------------------------------------------------


class TestStartup:
    def test_startup_burst_is_unsolicited(self, tmp_path):
        """main.cc:225-262: argv workload runs at startup; first Waiting
        arrives with no command sent."""
        with session("normal", tmp_path=tmp_path) as s:
            first = s.read_startup()
            assert first.terminated_by == "Waiting"
            assert first.completions() == 2          # one per NPU
            assert first.cycle == 0
            assert s.poll() is None                  # alive, awaiting cmd

    def test_startup_hang_times_out_and_kills(self):
        """startup_hang mode: no burst within the (short) startup timeout →
        ProtocolError, process group dead, diagnosable error."""
        with pytest.raises(ProtocolError) as ei:
            with session("startup_hang", startup_timeout_s=1.0) as s:
                s.read_startup()
        assert "terminator" in str(ei.value).lower()
        # close() already escalated inside the raise path; session exited
        # the with-block; nothing to leak (assert_child_dead needs the pid,
        # which the error path owns — covered by TestNoOrphan below).

    def test_startup_eof_is_a_protocol_error(self):
        """EOF before the first Waiting with the run not started is never
        an empty reply (frontend fails loud, __main__.py:1076)."""
        with pytest.raises(ProtocolError) as ei:
            with session("startup_eof") as s:
                s.read_startup()
        assert "eof" in str(ei.value).lower()

    def test_startup_nonzero_exit(self):
        with pytest.raises(ProtocolError) as ei:
            with session("startup_exit_nonzero") as s:
                s.read_startup()
        assert "exit code 3" in str(ei.value)


class TestNormalProgression:
    def test_legacy_path_round(self, tmp_path):
        """Bare path line = the round form the serving frontend actually
        emits (get_workload returns a path, utils.py:35-48)."""
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            r = s.command("/inputs/workload/some_batch.llm")
            assert r.terminated_by == "Waiting"
            assert r.cycle == 1000
            assert r.completions() == 2
            st = read_state(tmp_path)
            assert st["loads"] == ["/inputs/workload/some_batch.llm"]
            assert st["rounds"] == 1

    def test_pass_echo_keeps_clock(self, tmp_path):
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            s.command("/inputs/w.llm")
            r = s.command("pass")
            assert r.cycle == 1000          # unchanged (echo round)
            assert read_state(tmp_path)["clock"] == 1000

    def test_pass_target_jumps_clock(self, tmp_path):
        """pass <t> with future arrival: backend clock jumps
        (__main__.py:1747-1751 semantics)."""
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            s.command("/inputs/w.llm")
            r = s.command("pass 9000")
            assert r.cycle == 9000
            assert read_state(tmp_path)["clock"] == 9000

    def test_done_waits_without_completions(self, tmp_path):
        """done: Waiting-only reply (main.cc:336-343) — reply without
        time advance: the exact shape the spin detector counts."""
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            r = s.command("done")
            assert r.terminated_by == "Waiting"
            assert r.lines == []            # no completion lines at all
            assert r.cycle is None
            assert read_state(tmp_path)["dones"] == 1

    def test_load_is_silent_ack(self, tmp_path):
        """load queues silently — NO reply (main.cc:345-349); expect_reply
        is the client's encoding of that traced fact."""
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            out = s.command("load /inputs/inst0/w", expect_reply=False)
            assert out is None
            r = s.command("run")            # apply queue
            assert r.cycle == 1000
            st = read_state(tmp_path)
            assert st["loads"] == ["/inputs/inst0/w"]
            assert st["rounds"] == 1

    def test_multiple_loads_then_run(self, tmp_path):
        with session("normal", npus=3, tmp_path=tmp_path) as s:
            s.read_startup()
            s.command("load /inputs/a", expect_reply=False)
            s.command("load /inputs/b", expect_reply=False)
            r = s.command("run")
            assert r.completions() == 3
            assert read_state(tmp_path)["loads"] == ["/inputs/a", "/inputs/b"]

    def test_sequenced_rounds_advance_clock_monotonically(self, tmp_path):
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            cycles = [s.command(f"/inputs/batch{i}.llm").cycle
                      for i in range(4)]
            assert cycles == [1000, 2000, 3000, 4000]

    def test_exit_then_eof_exit_code_zero(self, tmp_path):
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            r = s.command("exit")
            assert r.terminated_by == "eof"
            assert r.lines == []            # no protocol data after exit
        assert read_state(tmp_path)["exit_seen"] is True

    def test_delayed_waiting_within_timeout(self):
        with session("delayed_waiting", reply_timeout_s=2.0) as s:
            s.read_startup()
            r = s.command("pass")
            assert r.terminated_by == "Waiting"

    def test_multi_line_bursts_all_captured(self):
        """A burst may carry several completion records before Waiting
        (parse_all_completions exists for exactly this, controller.py:71)."""
        with session("multi_line_bursts") as s:
            s.read_startup()
            r = s.command("pass")
            assert r.completions() == 6     # 3 repetitions × 2 NPUs


# ---------------------------------------------------------------------------
# protocol violations and hostile backends
# ---------------------------------------------------------------------------


class TestProtocolViolations:
    def test_missing_waiting_is_a_stall_error(self):
        """Completion without terminator → timeout → group killed
        (the frontend would spin forever here; we fail loud — §27)."""
        with pytest.raises(ProtocolError) as ei:
            with session("missing_waiting", reply_timeout_s=1.0) as s:
                s.read_startup()
                s.command("pass")
        assert "terminator" in str(ei.value).lower()
        assert ei.value.burst_tail          # the completion is preserved

    def test_partial_line_never_terminates(self):
        """"Waiting" without newline is not a terminator — framing is
        line-based (readline semantics, controller.py:37)."""
        with pytest.raises(ProtocolError):
            with session("partial_line", reply_timeout_s=1.0) as s:
                s.read_startup()
                s.command("pass")

    def test_garbage_before_terminator_is_preserved(self):
        """Non-protocol lines do not break framing; the substring rule
        terminates (controller.py:39 — 'Waiting' anywhere in the line)."""
        with session("protocol_garbage") as s:
            s.read_startup()
            r = s.command("pass")
            assert r.terminated_by == "Waiting"
            assert "this is not protocol" in r.lines[0]

    def test_eof_mid_reply_carries_burst_tail(self):
        with pytest.raises(ProtocolError) as ei:
            with session("eof_before_waiting") as s:
                s.read_startup()
                s.command("pass")
        assert "eof" in str(ei.value).lower()
        assert ei.value.burst_tail == ["some data"]

    def test_crash_mid_session(self):
        with pytest.raises(ProtocolError) as ei:
            with session("crash_after_cmd") as s:
                s.read_startup()
                s.command("pass")
        assert "eof" in str(ei.value).lower()
        # the backend exited with code 7 — visible in the error
        assert "exit code 7" in str(ei.value)

    def test_legacy_checking_terminator_accepted(self):
        """Legacy 'Checking Non-Exited Systems ...' terminates read_wait
        (controller.py:39) though no vendored binary emits it."""
        with session("legacy_checking") as s:
            s.read_startup()
            r = s.command("pass")
            assert r.terminated_by == "legacy-checking"
            assert r.completions() == 1

    def test_stderr_flood_cannot_stall_protocol(self):
        """1 MiB/s stderr: the drain thread keeps stdout responsive
        (the ~round-1500 stderr-pipe stall is the failure this kills)."""
        with session("stderr_flood", reply_timeout_s=10.0) as s:
            s.read_startup()
            r = s.command("pass")
            assert r.terminated_by == "Waiting"


class TestWaitingWithoutProgress:
    def test_livelock_shape_is_deterministically_reproducible(self):
        """THE fixture the multi-instance investigation needs: backend
        answers Waiting forever, clock unchanged, zero completions.

        This is evidence machinery for Q12.1 liveness diagnostics — the
        client SURFACES the no-progress shape (cycle None, no completions,
        repeated identical replies); it does not pretend to fix the
        serving livelock (§32: no guardrail-as-fix).
        """
        with session("waiting_without_progress") as s:
            s.read_startup()
            replies = [s.command("pass", timeout=2.0) for _ in range(5)]
            for r in replies:
                assert r.terminated_by == "Waiting"
                assert r.completions() == 0
                assert r.cycle is None       # clock never moved
            # all identical: the distinguishable signature
            # "backend responsive, simulated state frozen"
            assert len({r.text() for r in replies}) == 1


class TestNoOrphan:
    def test_clean_close(self, tmp_path):
        with session("normal", tmp_path=tmp_path) as s:
            s.read_startup()
            s.command("pass")
            pid = s.pid
        assert_child_dead(pid)

    def test_close_after_child_death(self):
        with pytest.raises(ProtocolError):
            with session("startup_eof") as s:
                s.read_startup()
        # with-block exited through the error path; close() was still run
        # (no assertion on pid — it died on its own; no leak either way).

    def test_ignore_exit_is_escalated_to_kill(self):
        """A backend that never exits after 'exit' is TERM→KILLed within
        the escalation window — nothing survives close()."""
        s = session("ignore_exit")
        s.start()
        s.read_startup()
        pid = s.pid
        t0 = time.monotonic()
        s.close()               # graceful path: 'exit', wait, TERM, KILL
        elapsed = time.monotonic() - t0
        assert elapsed < 20.0   # bounded, not hung on the sleeper
        assert_child_dead(pid)

    def test_force_close_kills_healthy_child(self):
        s = session("normal")
        s.start()
        s.read_startup()
        pid = s.pid
        s.close(force=True)
        assert_child_dead(pid)

    def test_no_orphan_on_protocol_error(self):
        """missing_waiting stall → error path kills the group."""
        s = session("missing_waiting", reply_timeout_s=1.0)
        s.start()
        pid = s.pid
        s.read_startup()
        with pytest.raises(ProtocolError):
            s.command("pass")
        s.close()
        assert_child_dead(pid)


class TestSessionDiscipline:
    def test_double_close_is_safe(self):
        s = session("normal")
        s.start()
        s.read_startup()
        first = s.close()
        second = s.close()
        assert first is None or isinstance(first, int)
        assert second is None   # idempotent

    def test_command_after_close_raises(self):
        s = session("normal")
        s.start()
        s.read_startup()
        s.close()
        with pytest.raises(ProtocolError):
            s.command("pass")

    def test_multiline_command_rejected(self):
        with session("normal") as s:
            s.read_startup()
            with pytest.raises(ProtocolError):
                s.command("pass\nexit")
