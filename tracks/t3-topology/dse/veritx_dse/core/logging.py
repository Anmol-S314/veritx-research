"""veritx_dse.logging — Structured logging with verbosity, JSON, and file output.

Every function receives a Ctx object. No global mutable state.
Also provides get_logger() for library-level logging via Python stdlib.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Ctx:
    """Immutable context passed through all CLI operations."""
    verbosity: int = 1          # 0=quiet, 1=normal, 2=verbose, 3=debug
    json_mode: bool = False
    output_file: str | None = None
    log_file: str | None = None
    seed: int = 0              # reproducibility seed (auto-generated if 0)
    _log_fh: object = field(default=None, repr=False)

    def __post_init__(self):
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self.log_file, "a")
            self._append("START", f"veritx (pid={__import__('os').getpid()})")

    def close(self):
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    def _append(self, level: str, msg: str):
        if self._log_fh:
            try:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._log_fh.write(f"{ts} [{level:5s}] {msg}\n")
                self._log_fh.flush()
            except Exception:
                pass


# ── Public helpers ──────────────────────────────────────────────────────────

def log(ctx: Ctx, msg: str):
    """Normal progress message (level 1+)."""
    if ctx.verbosity >= 1:
        print(f"  \033[36m▸\033[0m {msg}", file=sys.stderr)
    ctx._append("INFO", msg)


def ok(ctx: Ctx, msg: str):
    """Success message (level 1+)."""
    if ctx.verbosity >= 1:
        print(f"  \033[32m✓\033[0m {msg}", file=sys.stderr)
    ctx._append("OK", msg)


def fail(ctx: Ctx, msg: str):
    """Error message (always shown)."""
    print(f"  \033[31m✗\033[0m {msg}", file=sys.stderr)
    ctx._append("ERROR", msg)


def verbose(ctx: Ctx, msg: str):
    """Verbose detail (level 2+)."""
    if ctx.verbosity >= 2:
        print(f"  \033[90m·\033[0m {msg}", file=sys.stderr)
    ctx._append("DEBUG", msg)


def debug(ctx: Ctx, msg: str):
    """Debug-level detail (level 3+)."""
    if ctx.verbosity >= 3:
        print(f"  \033[90m…\033[0m {msg}", file=sys.stderr)
    ctx._append("TRACE", msg)


def banner(ctx: Ctx, title: str, width: int = 60):
    """Section header (suppressed in quiet/json mode)."""
    if ctx.verbosity < 1 or ctx.json_mode:
        return
    print(f"\n\033[1m{'=' * width}\033[0m")
    print(f"  \033[1m{title}\033[0m")
    print(f"\033[1m{'=' * width}\033[0m\n")


def output(ctx: Ctx, data, human_fn=None):
    """Output results in JSON or human-readable format, optionally saving to file."""
    if ctx.json_mode:
        print(json.dumps(data, indent=2))
    elif human_fn:
        human_fn(data)
    if ctx.output_file:
        out = Path(ctx.output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2))
        ok(ctx, f"Saved: {out}")


def print_human(ctx: Ctx, msg: str):
    """Print human-readable output (respects verbosity)."""
    if ctx.verbosity >= 1 and not ctx.json_mode:
        print(msg)


# ── Stdlib logging integration (replaces logger.py) ───────────────────────

_STDLOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_STDLOG_DATE = "%Y-%m-%d %H:%M:%S"
_stdlog_initialized = False


def get_logger(name: str) -> logging.Logger:
    """Get a named stdlib logger. Auto-configures on first call."""
    global _stdlog_initialized
    if not _stdlog_initialized:
        logging.basicConfig(
            level=logging.INFO,
            format=_STDLOG_FORMAT,
            datefmt=_STDLOG_DATE,
            handlers=[logging.StreamHandler(sys.stderr)],
        )
        _stdlog_initialized = True
    return logging.getLogger(name)


def setup_file_logging(log_path: Path) -> logging.FileHandler:
    """Add a file handler for persistent logs."""
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter(_STDLOG_FORMAT, _STDLOG_DATE))
    logging.getLogger().addHandler(handler)
    return handler
