"""veritx_dse.gateway.staleness — detect a gateway serving stale code.

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

import os
import time
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

LOADED_AT = time.time()

def newest_source_mtime(root: Path | None = None) -> float | None:
    """Newest mtime among the package's .py files, or None if unreadable."""
    base = root or _PACKAGE_ROOT
    newest: float | None = None
    try:
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                m = path.stat().st_mtime
            except OSError:
                continue
            if newest is None or m > newest:
                newest = m
    except OSError:
        return None
    return newest

def staleness() -> dict[str, object]:
    """Whether the running process predates the code on disk.

    ``stale`` is the actionable bit: True means this process is NOT running
    the source you are reading, and a restart is required before trusting
    any response.
    """
    newest = newest_source_mtime()
    pid = os.getpid()
    if newest is None:
        return {"stale": None, "reason": "source tree not readable",
                "pid": pid, "loaded_at": LOADED_AT}
    stale = newest > LOADED_AT
    out: dict[str, object] = {
        "stale": stale,
        "pid": pid,
        "loaded_at": LOADED_AT,
        "newest_source_mtime": newest,
        "source_age_s": round(max(0.0, newest - LOADED_AT), 3),
    }
    if stale:
        out["reason"] = (
            "a source file is NEWER than this process: the running gateway "
            "was started before the current code was written and is serving "
            "the OLD code. Restart uvicorn before trusting any response.")
        out["hint"] = ("python3 -m uvicorn veritx_dse.gateway.app:app "
                       "--host 127.0.0.1 --port 8123")
    return out

def warn_if_stale(log: object | None = None) -> dict[str, object]:
    """Startup check: log loudly when the process is already behind."""
    info = staleness()
    if info.get("stale"):
        msg = f"GATEWAY CODE IS STALE — {info['reason']}"
        if log is not None and hasattr(log, "warning"):
            log.warning(msg)          # type: ignore[attr-defined]
        else:                          # pragma: no cover - startup path
            import sys
            print(f"WARNING: {msg}", file=sys.stderr)
    return info

__all__ = ["LOADED_AT", "newest_source_mtime", "staleness", "warn_if_stale"]
