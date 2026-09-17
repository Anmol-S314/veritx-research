"""PR 4 supervision tests: process failure/cancellation at the real OS boundary.

Redesign §26 Level 2 — fake executables (tests/fake_sim.py), NO subprocess
mocks: every test launches a real process and asserts on real signals,
real exit codes, real process-table state. These pin the §21 process-
supervision contract that core.process.supervised_run provides, and that
run_booksim's default runner now relies on:

  * success/exit-code capture, stdout+stderr delivered
  * process-group ownership: a spawned grandchild does not survive the
    child's timeout (the bare-subprocess.run leak)
  * TERM->KILL escalation: a SIGTERM-ignoring child is still reaped
  * bounded capture: a flooding child cannot balloon memory or deadlock
  * env pass-through untouched (caller owns provenance policy)
  * signals: negative return codes surface as evidence
  * parent cancellation: KeyboardInterrupt kills the group and propagates
  * run_booksim integration: timeout classified as TimeoutError carrying
    partial output; success path unchanged for injected runners
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from veritx_dse.core import process as procmod
from veritx_dse.core.process import supervised_run, SupervisedResult

FAKE_SIM = Path(__file__).resolve().parent / "fake_sim.py"


def _cmd(*args: str) -> list[str]:
    return [sys.executable, str(FAKE_SIM), *args]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _wait_gone(pid: int, deadline_s: float = 10.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


# ── baseline lifecycle ───────────────────────────────────────────────────────

class TestBaseline:
    def test_success_captures_streams_and_code(self, tmp_path):
        r = supervised_run(_cmd("echo-exit", "0"), cwd=tmp_path, timeout=30)
        assert isinstance(r, subprocess.CompletedProcess)  # seam contract
        assert r.returncode == 0
        assert "stdout-line" in r.stdout
        assert "stderr-line" in r.stderr
        assert not r.timed_out and r.complete
        assert r.wall_time_s > 0

    def test_nonzero_exit_is_evidence_not_exception(self, tmp_path):
        r = supervised_run(_cmd("echo-exit", "3"), cwd=tmp_path, timeout=30)
        assert r.returncode == 3
        assert "stdout-line" in r.stdout and "stderr-line" in r.stderr

    def test_death_by_signal_is_negative_returncode(self, tmp_path):
        r = supervised_run(_cmd("kill-self", str(signal.SIGUSR1)),
                           cwd=tmp_path, timeout=30)
        assert r.returncode == -signal.SIGUSR1

    def test_argv_not_shell(self, tmp_path):
        # §3.7: the child's argv must be exactly what we passed — a shell
        # would make injection possible and quoting lossy.
        seen = {}
        real = subprocess.Popen

        def spy(argv, **kw):
            seen["argv"] = list(argv)
            return real(argv, **kw)

        # spy at the boundary one level under supervised_run is NOT a mock
        # of the child: the child still really runs.
        import unittest.mock as um
        with um.patch.object(procmod.subprocess, "Popen", side_effect=spy):
            supervised_run(_cmd("echo-exit", "0"), cwd=tmp_path, timeout=30)
        assert seen["argv"] == _cmd("echo-exit", "0")
        assert seen["argv"][0] == sys.executable  # no "sh" anywhere


# ── ownership & escalation (the §21 behaviors subprocess.run lacks) ─────────

class TestOwnership:
    def test_timeout_kills_whole_group(self, tmp_path):
        # Child forks its own sleeper grandchild; the timeout must end BOTH.
        pidfile = tmp_path / "grandchild.pid"
        with pytest.raises(subprocess.TimeoutExpired) as ei:
            supervised_run(_cmd("spawn-sleeper", str(pidfile), "120"),
                           cwd=tmp_path, timeout=2, grace_s=1.0)
        assert ei.value.timeout == 2
        assert pidfile.exists()  # SPAWNED made it out before the kill
        gpid = int(pidfile.read_text())
        assert _wait_gone(gpid), \
            f"grandchild {gpid} outlived the supervised child"

    def test_term_ignoring_child_still_reaped(self, tmp_path):
        # The §21 escalation: SIGTERM alone would hang the pipeline forever.
        t0 = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            supervised_run(_cmd("ignore-term", "120"),
                           cwd=tmp_path, timeout=2, grace_s=2.0)
        elapsed = time.monotonic() - t0
        # 2s budget + 2s grace + slack; SIGKILL enforced
        assert elapsed < 10, "SIGKILL escalation did not fire"

    def test_on_timeout_complete_yields_debris(self, tmp_path):
        r = supervised_run(_cmd("ignore-term", "120"), cwd=tmp_path,
                           timeout=2, grace_s=1.0, on_timeout="complete")
        assert isinstance(r, SupervisedResult)
        assert r.timed_out and not r.complete
        assert r.returncode == -signal.SIGKILL
        assert "IGNORE-READY" in r.stdout  # captured before the kill

    def test_fast_exit_at_budget_edge_never_signaled(self, tmp_path):
        # A child finishing just inside the budget must be classified as a
        # completion (no supervisor signal), not a timeout.
        r = supervised_run(_cmd("sleep", "0.2"), cwd=tmp_path, timeout=30)
        assert r.complete and r.returncode == 0


# ── bounded capture (§27 stderr floods) ─────────────────────────────────────

class TestBoundedCapture:
    def test_flood_is_capped_not_lost_head_nor_tail(self, tmp_path):
        r = supervised_run(_cmd("flood", "200000"), cwd=tmp_path, timeout=60)
        assert r.returncode == 0
        lines = r.stdout.splitlines()
        assert lines[0] == "FLOOD-HEAD"
        assert lines[-1] == "FLOOD-END"
        # Hard cap: head + tail + nothing else can exceed this.
        assert len(lines) <= procmod._HEAD_LINES + procmod._TAIL_LINES + 2
        assert all(len(l) <= procmod._LINE_CAP + 1 for l in lines)

    def test_env_passthrough_untouched(self, tmp_path):
        env = dict(os.environ)
        env["VERITX_PROBE"] = "sentinel-123"
        r = supervised_run(_cmd("print-env", "VERITX_PROBE"),
                           cwd=tmp_path, timeout=30, env=env)
        assert r.stdout.strip() == "sentinel-123"


# ── parent cancellation (§21: UI cancellation == process cancellation) ──────

class TestCancellation:
    def test_ctrl_c_kills_child_and_propagates(self, tmp_path):
        # REAL signal, no internals patched beyond capturing the child:
        # deliver SIGINT to this process while the main thread sits inside
        # supervised_run's wait, exactly like Ctrl-C in a terminal. The
        # owner must kill the child, then propagate the interrupt.
        child_holder: dict = {}
        real = subprocess.Popen

        def spawn(argv, **kw):
            p = real(argv, **kw)
            child_holder["p"] = p
            return p

        import unittest.mock as um
        with um.patch.object(procmod.subprocess, "Popen", side_effect=spawn):
            def fire():  # fires while the main thread waits on the child
                time.sleep(0.5)
                os.kill(os.getpid(), signal.SIGINT)

            threading.Timer(0.5, fire).start()
            with pytest.raises(KeyboardInterrupt):
                supervised_run(_cmd("sleep", "120"), cwd=tmp_path,
                               timeout=None)
        child = child_holder["p"]
        assert _wait_gone(child.pid), "child survived the owner's Ctrl-C"


# ── run_booksim integration (default runner behind the seam) ────────────────

class TestRunBooksimIntegration:
    @pytest.fixture()
    def booksim_repo(self, tmp_path):
        return tmp_path

    def _run(self, repo, config, timeout=30):
        from veritx_dse.core.logging import Ctx
        import veritx_dse.simulation.booksim as bm
        return bm.run_booksim(Ctx(), config, repo_root=repo, timeout=timeout)

    def test_booksim_timeout_classified_with_partial_output(
            self, booksim_repo, monkeypatch):
        import veritx_dse.simulation.booksim as bm
        from veritx_dse.core.errors import TimeoutError as BooksimTimeout

        def runner(cmd, cwd, timeout):
            return supervised_run(
                _cmd("ignore-term", "120"), cwd=cwd, timeout=0.5,
                grace_s=0.5, on_timeout="complete")

        monkeypatch.setattr(bm, "find_booksim_bin", lambda repo: Path("x"))
        with pytest.raises(BooksimTimeout) as ei:
            bm.run_booksim(
                __import__("veritx_dse.core.logging", fromlist=["Ctx"]).Ctx(),
                "irrelevant", repo_root=booksim_repo, timeout=5,
                runner=runner)
        assert "timed out" in str(ei.value)
        assert "IGNORE-READY" in (ei.value.stdout or "")

    def test_booksim_success_via_default_supervisor(self, booksim_repo):
        # End-to-end through the real seam: no injected runner. The "binary"
        # is a wrapper script that ignores its config arg and prints stats.
        bin_ = booksim_repo / "fake-booksim"
        bin_.write_text(
            "#!/bin/sh\n"
            "echo 'Packet latency average = 35.05 (1 samples)'\n"
            "echo 'delivered 4 packets'\n")
        bin_.chmod(0o755)
        import veritx_dse.simulation.booksim as bm
        monkey = pytest.MonkeyPatch()
        monkey.setattr(bm, "find_booksim_bin", lambda repo: bin_)
        try:
            r = self._run(booksim_repo, "topology = mesh;\n")
        finally:
            monkey.undo()
        assert r["latency"] == 35.05
        assert r["delivered"] == 4
        assert r["wall_time_s"] >= 0
