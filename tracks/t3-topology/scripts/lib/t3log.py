#!/usr/bin/env python3
"""t3log.py — structured logging infrastructure for t3.

What it gives the pipeline:
  1. An append-only **NDJSON event log** per sweep (logs/<sweep_id>/events.ndjson)
     recording every meaningful pipeline event — sweep start/finish, per-point
     ok/skip/fail, interrupts — with full provenance (git commit, config, model,
     topo). This is the machine-readable history: a single `python3 -m lib.t3log
     tail` answers "what ran, when, with what knobs, and did it land?" without
     anyone remembering to print it.
  2. A per-run **text log** (logs/<sweep_id>/sweep.log) capturing stdout of the
     run so `✗ failed` sweeps can be diagnosed after the fact (logs/sim.log
     links to them).
  3. A tiny **viewer/CLI**: summary, tail, prune.

The Python logging API is deliberately small: `log_event(kind, **fields)` and
`session_log(line)`. Sweeps call those; nothing else changes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# scripts/lib/t3log.py -> tracks/t3-topology
ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = ROOT / "logs"
REPO_ROOT = ROOT.parent.parent                          # veritx-research

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _git_commit() -> str | None:
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(ROOT), capture_output=True, text=True,
                             timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _local_ts() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def now_ms() -> int:
    return int(time.time() * 1000)


_ACTIVE: "SweepLogger | None" = None


def active() -> "SweepLogger | None":
    """The most recent SweepLogger in this process (None outside sweeps)."""
    return _ACTIVE


def log_crash(exc: BaseException) -> None:
    """Record an unexpected crash on the active session (if any) so the log
    never shows a dead sweep as 'running/incomplete'. Callers re-raise."""
    if _ACTIVE is not None:
        _ACTIVE.log_event("crash", error=type(exc).__name__,
                          message=str(exc)[:500])
        _ACTIVE.finish("crashed")


class SweepLogger:
    """One instance per sweep run; writes events.ndjson + sweep.log."""

    def __init__(self, kind: str, cfg: str, extra: dict | None = None):
        global _ACTIVE
        _ACTIVE = self
        self.kind = kind                      # "sim" | "astrasim" | ...
        self.cfg = cfg
        self.sweep_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = LOGS_DIR / self.sweep_id
        # Rare same-second collisions: nudge instead of fail the sweep.
        n = 0
        while self.dir.exists() and n < 20:
            n += 1
            self.sweep_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{n}"
            self.dir = LOGS_DIR / self.sweep_id
        if self.dir.exists():
            # Still colliding after nudges: micros suffix, never reuse a dir
            # (reusing would append one session's events into another's).
            self.sweep_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            self.dir = LOGS_DIR / self.sweep_id
        self._dropped = 0
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.ndjson"
        self.text_path = self.dir / "sweep.log"
        self._t0 = now_ms()
        self.env = {
            "CONFIG": cfg,
            "MODEL": os.environ.get("MODEL", ""),
            "TOPO": os.environ.get("TOPO", ""),
            "RATES": os.environ.get("RATES", ""),
        }
        if extra:
            self.env.update(extra)
        self.log_event("sweep_start", sweep_kind=kind, **self.env)

    # ── public API ────────────────────────────────────────────────────────
    def log_event(self, kind: str, **fields) -> None:
        rec = {
            "ts": _local_ts(),
            "ts_ms": now_ms(),
            "sweep_id": self.sweep_id,
            "kind": kind,
            "sweep_kind": self.kind,
        }
        rec.update(fields)
        with self.events_path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def session_log(self, text: str) -> None:
        """Mirror stdout to sweep.log (one call per printed line)."""
        try:
            clean = ANSI_RE.sub("", text)
            with self.text_path.open("a") as f:
                f.write(clean.rstrip("\n") + "\n")
        except OSError:
            # Never break a sweep over logging; count drops for the summary.
            self._dropped = getattr(self, "_dropped", 0) + 1

    def finish(self, status: str, summary: dict | None = None) -> None:
        summary = dict(summary or {})
        if getattr(self, "_dropped", 0):
            summary["log_drops"] = self._dropped
        self.log_event("sweep_finish", status=status, elapsed_ms=now_ms() - self._t0,
                       **summary)


# ── viewer / CLI ─────────────────────────────────────────────────────────────

def read_events(sweep_id: str | None = None) -> list[dict]:
    """All events, newest sweep first. Corrupt lines are skipped."""
    out: list[dict] = []
    if not LOGS_DIR.exists():
        return out
    for d in sorted(LOGS_DIR.iterdir(), reverse=True):
        if not d.is_dir() or (sweep_id and d.name != sweep_id):
            continue
        ev = d / "events.ndjson"
        if not ev.exists():
            continue
        try:
            for line in ev.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                rec["_sweep_dir"] = d.name
                out.append(rec)
        except OSError:
            continue
    return out


def summarize(limit: int = 15) -> str:
    """Human table: one line per sweep session."""
    events = read_events()
    if not events:
        return "  no sweep logs yet — logs/ fills as you run sim/astrasim sweeps"
    sessions: dict[str, dict] = {}
    order: list[str] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        sid = e.get("sweep_id")
        if not sid:
            continue
        if sid not in sessions:
            sessions[sid] = {"kind": e.get("sweep_kind", "?"), "start": e,
                             "finish": None, "ok": 0, "fail": 0, "skip": 0,
                             "interrupted": False}
            order.append(sid)
        s = sessions[sid]
        kind = e.get("kind")
        if kind == "point":
            if e.get("status") == "ok":
                s["ok"] += 1
            elif e.get("status") == "skip":
                s["skip"] += 1
            else:
                s["fail"] += 1
        elif kind == "sweep_finish":
            s["finish"] = e
            if e.get("status") == "interrupted":
                s["interrupted"] = True
    lines = ["  latest sessions (logs/):"]
    for sid in order[:limit]:
        s = sessions[sid]
        start = s["start"].get("ts", "?")[:19]
        bits = [f"  {sid}  {s['kind']:<8} {start}"]
        env = s["start"]
        knob = env.get("MODEL") or env.get("RATES") or ""
        if knob:
            bits.append(f" [{knob}]")
        counts = f"ok={s['ok']} skip={s['skip']} fail={s['fail']}"
        status = "─ running/incomplete" if s["finish"] is None else (
            "interrupted" if s["interrupted"] else s["finish"].get("status", "done"))
        bits.append(f"  {counts}  {status}")
        lines.append("".join(bits))
    if len(order) > limit:
        lines.append(f"  … {len(order) - limit} older sessions (t3 log --all)")
    return "\n".join(lines)


def tail(sweep_id: str | None, n: int = 40) -> str:
    events = read_events(sweep_id)
    if not events:
        return f"  no events found for {sweep_id or 'any sweep'}"
    if sweep_id is None:
        # Newest-sweep-first overall, chronological within each sweep file:
        # show the newest sweep's tail (what just ran), oldest first.
        newest = events[0].get("_sweep_dir")
        events = [e for e in events if e.get("_sweep_dir") == newest][-n:]
    else:
        # Single-sweep file order is already chronological: tail = latest.
        events = events[-n:]
    lines = [f"  {len(events)} events" + (f" for {sweep_id}" if sweep_id else "") + ":"]
    for e in events:
        if not isinstance(e, dict):
            continue
        extra = {k: v for k, v in e.items()
                 if k not in ("ts", "ts_ms", "sweep_id", "kind", "sweep_kind",
                              "_sweep_dir")}
        t = e.get("ts", "?")[11:19]
        kind = e.get("kind", "?")
        if extra:
            kv = " ".join(f"{k}={v}" for k, v in extra.items())
            lines.append(f"  {t} {kind:<13} {kv}")
        else:
            lines.append(f"  {t} {kind}")
    return "\n".join(lines)


def prune(days: int = 30, dry_run: bool = False) -> str:
    """Delete session dirs older than N days (events include provenance)."""
    if not LOGS_DIR.exists():
        return "  no logs yet"
    cutoff = time.time() - days * 86400
    old, kept = [], 0
    for d in sorted(LOGS_DIR.iterdir()):
        if not d.is_dir():
            continue
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            old.append(d)
        else:
            kept += 1
    if not old:
        return f"  nothing older than {days}d ({kept} sessions kept)"
    if dry_run:
        return "  would remove:\n" + "\n".join(f"    {d.name}" for d in old)
    removed = 0
    for d in old:
        try:
            shutil.rmtree(d)
            removed += 1
        except OSError as e:
            print(f"  ⚠ could not remove {d.name}: {e}", file=sys.stderr)
    return f"  removed {removed} session(s), kept {kept + (len(old) - removed)}"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="t3 structured log viewer")
    ap.add_argument("cmd", nargs="?", default="summary",
                    choices=["summary", "tail", "prune"])
    ap.add_argument("--sweep", default=None, help="sweep id for tail")
    ap.add_argument("--all", action="store_true", help="summary: show all sessions")
    ap.add_argument("-n", type=int, default=40, help="tail line count")
    ap.add_argument("--days", type=int, default=30, help="prune: older than N days")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "summary":
        print(summarize(limit=1000 if a.all else 15))
    elif a.cmd == "tail":
        print(tail(a.sweep, a.n))
    elif a.cmd == "prune":
        print(prune(a.days, a.dry_run))


if __name__ == "__main__":
    main()
