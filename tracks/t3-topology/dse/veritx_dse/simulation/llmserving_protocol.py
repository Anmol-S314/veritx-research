"""LLMServingSim backend-session protocol (redesign PR 5).

A first-class, LLMServingSim-specific session over the exact stdin/stdout
protocol traced from vendored source — see
docs/protocols/llmservingsim-backend.md for every fact and citation.
NOT a generic interactive-runner: the handoff (§4.2) forbids forcing a
request/response session through a one-shot API, and no second interactive
system exists yet to justify a seam. When the analytical path (Slice C)
reuses this, only then compress.

Protocol contract (one command outstanding, always — the traced frontend
runs read_wait before every write, __main__.py:1074):

    spawn (argv array; backend runs the initial event-handler round)
        ↓ unsolicited burst + first Waiting-terminated reply
    write line: <workload path> | pass | pass <t> | pass -1 | done | exit
                (load <p> is backend-side only: silent ack, NO reply)
        ↓ zero+ event lines, then a terminator line:
        ↓   - contains "Waiting" (substring — traced rule), or
        ↓   - equals the legacy "Checking Non-Exited Systems ..." (accepted,
        ↓     never produced by any vendored binary)
    repeat; "exit" → EOF within a bounded time (backend breaks its loop).

Where this client is deliberately stricter than the traced frontend:
  * EOF while a reply is expected is a ProtocolError, never a silent empty
    reply (the frontend also fails loud here — __main__.py:1076-1093).
  * A missing terminator within the timeout is ProtocolError and the child
    process group is killed — a stall cannot leak (§21: cancellation must
    reach the real OS process).
  * stderr is drained by a bounded daemon thread (the undrained-pipe stall
    at ~round 1500 in the forward-port history is what this prevents), with
    evidence lines (ledger / Comm time / injection counter) kept in a
    separate non-evictable buffer from the diagnostic tail.
  * The substring terminator rule is reproduced EXACTLY (a line merely
    containing "Waiting" terminates) — see protocol doc §7; tests pin it.

Timeout enforcement note: stdout is read in binary via select() with a
deadline and lines are assembled by hand — a blocking readline() on a
stalled backend would hang past any timeout, and text-mode buffering
breaks fd-level readiness.
"""
from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

_TERMINATOR_SUBSTR = "Waiting"
_LEGACY_TERMINATOR = "Checking Non-Exited Systems ..."
_LINE_CAP = 300
_STDERR_KEEP = 200  # bounded diagnostic tail; protocol tests need the death message
#: Evidence lines are kept in their own buffer and are NOT evictable by
#: binary chatter: a real canonical round emits ~300 stderr lines of which
#: the collective ledger is a small, early, load-bearing subset.  A single
#: shared tail silently drops it (measured: a 16-rank AllReduce round emits
#: 16 [LEDGER][COLL_SUBMIT] lines and 310 lines total).
_EVIDENCE_KEEP = 8192
#: exactly the lines the evidence path parses -- see serving_runtime
#: ``parse_round_output`` and ``collective_ledger_lines``
_EVIDENCE_MARKERS = ("[LEDGER][COLL_SUBMIT]", "Comm time:", "injected=")
_STARTUP_TIMEOUT_S = 30.0
_REPLY_TIMEOUT_S = 60.0
_EXIT_TIMEOUT_S = 10.0
_KILL_GRACE_S = 5.0

# Completion grammars (controller.py:13-27): analytic iteration form and
# the [workload] form, with optional [info] prefix. Clock = trailing cycles.
_CYCLE_RE = re.compile(
    r"sys\[\d+\] (?:iteration \d+ |)finished, (\d+) cycles")


class ProtocolError(RuntimeError):
    """The backend violated the traced protocol, died, or stalled.

    Carries the bounded tail of the reply burst and of stderr so the
    failure is diagnosable without re-running (handoff §28: preserve
    root-cause information; never reduce it to "timeout").
    """

    def __init__(self, message: str, *, burst_tail: Optional[list[str]] = None,
                 stderr_tail: Optional[str] = None):
        super().__init__(message)
        self.burst_tail = list(burst_tail or [])
        self.stderr_tail = stderr_tail or ""


class BackendReply:
    """One Waiting-terminated reply burst.

    lines   — every line before the terminator (protocol data: per-NPU
              completion lines, [plat] summaries)
    cycle   — the backend's cumulative clock parsed from the LAST
              completion line in the burst (both traced grammar
              variants), else None
    terminated_by — "Waiting" | "legacy-checking" | "eof"
    """

    def __init__(self, lines: list[str], terminated_by: str):
        self.lines = lines
        self.terminated_by = terminated_by
        self.cycle: Optional[int] = None
        for line in lines:
            m = _CYCLE_RE.search(line)
            if m:
                self.cycle = int(m.group(1))

    def completions(self) -> int:
        """Number of per-NPU completion lines (progress evidence)."""
        return sum(1 for ln in self.lines if _CYCLE_RE.search(ln))

    def text(self) -> str:
        return "\n".join(self.lines)


def _start_stderr_drain(stderr_file) -> tuple[threading.Thread, deque, deque]:
    tail: deque = deque(maxlen=_STDERR_KEEP)
    evidence: deque = deque(maxlen=_EVIDENCE_KEEP)

    if stderr_file is None:
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        return t, tail, evidence

    def _drain() -> None:
        try:
            for raw in iter(stderr_file.readline, b""):
                line = raw.decode("utf-8", errors="replace")[:_LINE_CAP]
                tail.append(line)
                if any(marker in line for marker in _EVIDENCE_MARKERS):
                    evidence.append(line)
        except (ValueError, OSError):
            pass  # closed under us during teardown

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    return t, tail, evidence


def _kill_group(proc: subprocess.Popen) -> None:
    """TERM the process group, escalate to KILL (PR 4 escalation path)."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + _KILL_GRACE_S
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=_KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


class ServingBackendSession:
    """One owned backend process speaking the traced protocol.

    Usage shape (mirrors the serving loop, not an abstraction):

        with ServingBackendSession(argv) as session:
            first = session.read_startup()          # unsolicited burst
            reply = session.command("<workload>")   # legacy round
            reply = session.command("pass")
            reply = session.command("done")
        # exit+escalation happens on close; nothing survives the block.

    Cancellation safety: if the body raises, __exit__ still closes —
    'exit' is written, and a backend that ignores stdin is TERM→KILLed
    with its process group. No orphan survives the with-block.
    """

    def __init__(self, argv: list[str], *, cwd: Optional[Path | str] = None,
                 env: Optional[dict[str, str]] = None,
                 reply_timeout_s: float = _REPLY_TIMEOUT_S,
                 startup_timeout_s: float = _STARTUP_TIMEOUT_S):
        if len(argv) < 1 or not argv[0]:
            raise ValueError("argv must name a backend binary (no shell)")
        self._argv = list(argv)
        self._cwd = str(cwd) if cwd else None
        self._env = dict(env) if env is not None else None
        self._reply_timeout = reply_timeout_s
        self._startup_timeout = startup_timeout_s
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_tail: deque = deque(maxlen=_STDERR_KEEP)
        self._stderr_evidence: deque = deque(maxlen=_EVIDENCE_KEEP)
        self._readbuf = b""       # partially-read line (binary assembly)
        self._closed = False

    # -- lifecycle -------------------------------------------------------

    def __enter__(self) -> "ServingBackendSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._proc is not None:
            raise ProtocolError("session already started")
        # stdout binary: timeout-aware line assembly needs raw fd + select.
        # stdin text: commands are written with explicit flush per message.
        self._proc = subprocess.Popen(
            self._argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
            start_new_session=True,  # own group: our signals are ours alone
        )
        self._stderr_thread, self._stderr_tail, self._stderr_evidence = (
            _start_stderr_drain(self._proc.stderr))

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    def poll(self) -> Optional[int]:
        return self._proc.poll() if self._proc else None

    def stderr_text(self) -> str:
        """The evidence-bearing stderr lines the backend emitted.

        This is the filtered evidence buffer (ledger submissions, per-endpoint
        ``Comm time`` and the injection counter), not the diagnostic tail:
        evidence must not be evictable by how chatty the binary happens to be.
        ``ProtocolError`` still carries the bounded raw tail separately.
        """
        return "".join(self._stderr_evidence)

    # -- protocol operations ----------------------------------------------

    def read_startup(self) -> BackendReply:
        """Consume the unsolicited startup burst + first Waiting.

        All three traced frontends run the argv workload during startup and
        emit one completion burst + Waiting with no command sent.
        """
        return self._read_reply(timeout=self._startup_timeout)

    def command(self, line: str, *, expect_reply: bool = True,
                timeout: Optional[float] = None) -> Optional[BackendReply]:
        """Send one command line; consume its reply.

        expect_reply=False for the silent-ack 'load' command (traced:
        backend-side queueing, no reply — main.cc:345-349). 'exit' is the
        one command whose reply is EOF (backend breaks its loop).
        """
        if self._proc is None or self._closed:
            raise ProtocolError("session not started or already closed")
        if "\n" in line:
            raise ProtocolError("command must be a single line")
        self._write_line(line)
        if not expect_reply:
            return None
        if line == "exit":
            return self._read_eof_reply(timeout=timeout or _EXIT_TIMEOUT_S)
        return self._read_reply(timeout=timeout or self._reply_timeout)

    # -- internals ---------------------------------------------------------

    def _fail(self, msg: str, burst: list[str]) -> ProtocolError:
        return ProtocolError(
            msg, burst_tail=burst[-10:],
            stderr_tail="".join(self._stderr_tail) or None)

    def _write_line(self, line: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write((line + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise self._fail(
                f"backend pipe closed while writing {line!r}", [])

    def _readline_until(self, deadline: float) -> Optional[str]:
        """One line with a hard deadline; None on timeout; '' sentinel-free.

        Returns the line (with trailing newline stripped of '\\n' only),
        or raises nothing: timeout → None; EOF → None is ambiguous, so EOF
        is signalled by returning the string '' ONLY when the stream truly
        ended (distinct from timeout via the deadline check order).
        """
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        fd = proc.stdout.fileno()
        while True:
            nl = self._readbuf.find(b"\n")
            if nl >= 0:
                raw = self._readbuf[:nl]
                self._readbuf = self._readbuf[nl + 1:]
                return raw.decode("utf-8", errors="replace")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None  # timeout (caller distinguishes from EOF)
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.1))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if chunk == b"":
                # EOF: flush any partial line as a final unterminated line
                if self._readbuf:
                    raw, self._readbuf = self._readbuf, b""
                    return raw.decode("utf-8", errors="replace")
                return "\x00EOF"  # EOF marker (cannot appear in text lines)
            self._readbuf += chunk

    _EOF = "\x00EOF"

    def _read_reply(self, *, timeout: float) -> BackendReply:
        proc = self._proc
        assert proc is not None
        burst: list[str] = []
        deadline = time.monotonic() + timeout
        while True:
            line = self._readline_until(deadline)
            if line is None:
                _kill_group(proc)
                raise self._fail(
                    f"backend made no terminator within {timeout:.1f}s "
                    f"(stall/livelock; process group killed)", burst)
            if line == self._EOF:
                code = proc.poll()
                raise self._fail(
                    f"backend EOF before Waiting (exit code {code})", burst)
            burst.append(line[:_LINE_CAP])
            if (_TERMINATOR_SUBSTR in line
                    or line.rstrip("\r") == _LEGACY_TERMINATOR):
                return BackendReply(burst[:-1],
                                    terminated_by="Waiting"
                                    if _TERMINATOR_SUBSTR in line
                                    else "legacy-checking")

    def _read_eof_reply(self, *, timeout: float) -> BackendReply:
        """Post-'exit' consumption: burst lines then EOF (never Waiting)."""
        proc = self._proc
        assert proc is not None
        burst: list[str] = []
        deadline = time.monotonic() + timeout
        while True:
            line = self._readline_until(deadline)
            if line is None:
                _kill_group(proc)
                raise self._fail(
                    f"backend did not exit within {timeout:.1f}s after "
                    f"'exit' (process group killed)", burst)
            if line == self._EOF:
                return BackendReply(burst, terminated_by="eof")
            burst.append(line[:_LINE_CAP])

    # -- teardown ------------------------------------------------------------

    def close(self, *, force: bool = False) -> Optional[int]:
        """Graceful close: 'exit' if healthy, then EOF-wait, then escalation.

        Safe to call twice; safe after child death. Returns the exit code
        if obtainable. The no-orphan guarantee: whatever state the session
        is in, close() terminates the process group.
        """
        if self._closed or self._proc is None:
            return None
        self._closed = True
        proc = self._proc
        code = proc.poll()
        if code is None and not force:
            try:
                self._write_line("exit")
            except ProtocolError:
                pass
            deadline = time.monotonic() + _EXIT_TIMEOUT_S
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
        if proc.poll() is None:
            _kill_group(proc)
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except (OSError, ValueError):
                pass
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        return proc.poll()
