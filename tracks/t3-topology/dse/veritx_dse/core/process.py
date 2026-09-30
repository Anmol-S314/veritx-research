"""veritx_dse.core.process — one-shot process supervision (redesign PR 4).

Rationale: docs/decisions/modules/core.md
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

GRACE_S = 5.0

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
                tail.append(line)
    except Exception:
        pass
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

Rationale: docs/decisions/modules/core.md
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

Rationale: docs/decisions/modules/core.md
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
        start_new_session=True,
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
                if proc.poll() is None:
                    _signal_group(proc, signal.SIGTERM)
                    if not _await_exit(
                            proc, time.monotonic() + grace_s) \
                            and proc.poll() is None:
                        _signal_group(proc, signal.SIGKILL)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
        proc.wait()
    except KeyboardInterrupt:
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
