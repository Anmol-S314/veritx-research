"""veritx_dse.core.process — one-shot process supervision (redesign PR 4).

The lifecycle mechanics handoff §21 requires for one-shot simulators,
behind one deep function:

    supervised_run(cmd, *, cwd, timeout, ...) -> SupervisedResult

  * argv-array launch, never a shell (§3.7)
  * process-group + session ownership: the child gets its own session, so
    escalation signals the whole tree — never our ancestors
  * stdout/stderr captured with BOUNDED memory (§27 "stderr floods": a
    flooding child cannot OOM the control plane)
  * timeout: SIGTERM to the group first, SIGKILL after a short grace
    window — a SIGTERM-ignoring child cannot hang the pipeline forever
  * exit-code capture, including negative signal codes
  * parent cancellation: Ctrl-C (KeyboardInterrupt) kills the group and
    propagates — UI cancellation becomes process cancellation (§21)

Why the child sits in a NEW session: a bare KeyboardInterrupt in this
process would otherwise be delivered to the whole foreground group —
i.e. shared with the child. Owning the child exclusively means the child
dies because WE decided, via the same escalation path as a timeout, not
because it happened to share our terminal's signal fan-out.

NOT for LLMServingSim: a long-lived load/run/pass/exit session is a
different execution model (§4.2) and gets its own protocol module in
Slice B. Do not force interactive sessions through this primitive.

This is the default runner behind simulation.booksim.run_booksim's
documented `runner` seam; callers that inject a runner are unaffected,
and SupervisedResult IS-A CompletedProcess, so the seam contract is
byte-identical for both.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

# SIGTERM -> SIGKILL escalation window (seconds). Long enough for a
# well-behaved simulator to flush its stats; short enough that a stuck
# run fails in seconds, not minutes.
GRACE_S = 5.0

# Bounded capture (§27): lines are individually capped, then the stream
# keeps its HEAD and TAIL only. Worst case per stream is bounded by
# (_HEAD_LINES + _TAIL_LINES + 1) short lines regardless of child output
# volume — a flooding child cannot balloon memory. Diagnostics need the
# banner (head) and the error (tail); the middle of a giant log is what
# artifacts/ files are for.
_LINE_CAP = 300
_HEAD_LINES = 100
_TAIL_LINES = 400


def _cap(line: str, cap: int = _LINE_CAP) -> str:
    return line if len(line) <= cap else line[:cap] + "…\n"


def _drain(stream: Any, head: list[str], tail: "deque[str]",
           total: list[int]) -> None:
    """Reader-thread body: bounded capture from one pipe.

    Threads drain the pipes so a chatty child can never block on a full
    pipe while the owner waits on the child (the classic capture deadlock).
    The first _HEAD_LINES lines land in `head`, the LAST _TAIL_LINES in
    `tail` (a bounded deque); everything between is counted and dropped.
    """
    try:
        for line in stream:
            line = _cap(line)
            total[0] += 1
            if len(head) < _HEAD_LINES:
                head.append(line)
            else:
                tail.append(line)  # deque(maxlen=_TAIL_LINES) evicts itself
    except Exception:
        pass  # stream died with the child — keep what we have
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _join(head: list[str], tail: "deque[str]", total: int) -> str:
    """Assemble the bounded capture: head, drop marker, tail."""
    kept = len(head) + len(tail)
    if total <= kept:
        return "".join(head) + "".join(tail)
    dropped = total - kept
    return ("".join(head)
            + f"\n… [{dropped} lines truncated] …\n"
            + "".join(tail))


def _await_exit(proc: subprocess.Popen, deadline: float) -> bool:
    """Wait until `deadline` for the child to exit on its own."""
    try:
        proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        return True
    except subprocess.TimeoutExpired:
        return False


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    """Signal the child's whole process group, falling back to the child.

    ProcessLookupError means the group is already gone (all members
    reaped) — a clean no-op, never an error.
    """
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            pass


class SupervisedResult(subprocess.CompletedProcess):
    """CompletedProcess plus supervision facts — drop-in at the seam.

    `timed_out` distinguishes "the child finished" from "we ended it at
    the budget": a result assembled after SIGKILL must never be mistaken
    for a measurement (the same rule run_booksim applies to partial
    stats after a nonzero exit).
    """

    def __init__(self, cmd: list[str], returncode: int | None,
                 stdout: str, stderr: str, *,
                 wall_time_s: float, timed_out: bool) -> None:
        super().__init__(cmd, returncode, stdout, stderr)
        self.wall_time_s = wall_time_s
        self.timed_out = timed_out

    @property
    def complete(self) -> bool:
        """True only if the child exited on its own within the budget."""
        return not self.timed_out


def supervised_run(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    grace_s: float = GRACE_S,
    on_timeout: Literal["raise", "complete"] = "raise",
) -> SupervisedResult:
    """Run one process to completion under full lifecycle ownership.

    env is passed through untouched — environment selection is the
    CALLER's provenance policy (e.g. _timeloop_env), not this module's.

    on_timeout="complete" assembles a SupervisedResult anyway (returncode
    reflects the killing signal, e.g. -9 after SIGKILL; timed_out=True)
    for callers that want to inspect the debris; the default "raise"
    raises subprocess.TimeoutExpired with the captured output attached,
    which is what run_booksim's existing seam contract expects.
    """
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,  # own session/group: we signal the tree
    )
    out_head: list[str] = []
    err_head: list[str] = []
    out_tail: deque = deque(maxlen=_TAIL_LINES)
    err_tail: deque = deque(maxlen=_TAIL_LINES)
    out_total = [0]
    err_total = [0]
    readers = [
        threading.Thread(target=_drain,
                         args=(proc.stdout, out_head, out_tail, out_total)),
        threading.Thread(target=_drain,
                         args=(proc.stderr, err_head, err_tail, err_total)),
    ]
    for t in readers:
        t.daemon = True
        t.start()

    deadline = t0 + timeout if timeout is not None else None
    did_timeout = False
    try:
        if deadline is not None:
            if not _await_exit(proc, deadline):
                did_timeout = True
                if proc.poll() is None:  # may have exited in the last instant
                    _signal_group(proc, signal.SIGTERM)
                    if not _await_exit(
                            proc, time.monotonic() + grace_s) \
                            and proc.poll() is None:
                        _signal_group(proc, signal.SIGKILL)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass  # reaped by the kernel; proceed with evidence
        proc.wait()
    except KeyboardInterrupt:
        # Parent cancellation (§21): kill the group and propagate. No
        # grace period — the user asked to stop now, and a TERM-ignoring
        # child must not trap us inside its own shutdown.
        _signal_group(proc, signal.SIGKILL)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    for t in readers:
        t.join(timeout=5)

    stdout = _join(out_head, out_tail, out_total[0])
    stderr = _join(err_head, err_tail, err_total[0])
    if did_timeout and on_timeout == "raise":
        e = subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
        e.stdout, e.stderr = stdout, stderr
        raise e
    return SupervisedResult(
        cmd, proc.returncode, stdout, stderr,
        wall_time_s=time.monotonic() - t0, timed_out=did_timeout,
    )
