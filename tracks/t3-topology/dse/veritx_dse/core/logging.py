"""veritx_dse.logging — Structured logging with verbosity, JSON, and file output.

Every function receives a Ctx object. No global mutable state.
Also provides get_logger() for library-level logging via Python stdlib.

Logging boundary (Phase 3a unification):
  - Package code (veritx_dse.cli.*, veritx_dse.core.*, pipeline orchestration)
    MUST use these Ctx helpers only — never bare print(). Data/machine-clean
    output goes to stdout via output()/print_human()/emit(); human status goes
    to stderr via log()/ok()/fail()/verbose()/debug()/diag(). banner() stays
    on stdout but is suppressed in quiet/json modes.
  - Standalone scripts (scripts/*.py, scripts/lib/t3log.py SweepLogger) keep
    their own logger and MUST NOT import this module. SweepLogger owns
    session/event logging for sweep runs; Ctx owns CLI/pipeline logging.
    The two systems meet only in log files on disk, never in imports.
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
    failed: bool = False        # set by fail(); main() exits 1 when set
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
    """Error message (always shown). Marks the run failed so main() can
    exit nonzero — a fail()-and-return command must never exit 0."""
    print(f"  \033[31m✗\033[0m {msg}", file=sys.stderr)
    ctx._append("ERROR", msg)
    ctx.failed = True


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


def emit(ctx: Ctx, msg: str = "", *, end: str = "\n"):
    """Verbatim stdout line for data/machine-clean output (no prefix).

    Unlike print_human(), this is UNCONDITIONAL: no verbosity or json_mode
    gate — it preserves the exact routing of legacy bare print() data lines
    (tables, resolved paths, menus, summaries) which historically printed to
    stdout even in quiet mode. Structured results should still go through
    output(); emit() is the bridge for human-rendered data lines whose text
    is pinned and must not gain a log()/ok()/fail() prefix.
    """
    print(msg, end=end)
    ctx._append("OUT", msg)


def diag(ctx: Ctx, msg: str = "", *, end: str = "\n"):
    """Verbatim stderr line for status that must not gain a prefix.

    Companion to emit() for the stderr side: preserves the exact text of
    legacy print(..., file=sys.stderr) lines (e.g. exception tails,
    "Interrupted.") which cannot go through fail()/log() without changing
    their pinned wording. Always shown, always on stderr.
    """
    print(msg, end=end, file=sys.stderr)
    ctx._append("DIAG", msg)


def early_error(msg: str):
    """Stderr line for pre-Ctx failures (e.g. --log path unusable).

    No Ctx exists yet so log()/fail()/diag() are unavailable. Verbatim to
    stderr, no prefix — the caller exits nonzero immediately after.
    """
    print(msg, file=sys.stderr)


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
