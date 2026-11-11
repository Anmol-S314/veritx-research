"""Cross-platform atomic replace.

POSIX renames over an open file; Windows refuses, surfacing as
``PermissionError`` with ``WinError`` 5 (access denied) or 32 (sharing
violation). Job and run documents are polled while they are rewritten, so on
Windows the rename needs a bounded retry: this is required for correctness
there, not blanket robustness.
"""
from __future__ import annotations

import os
import time

# ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION.
_TRANSIENT_WINERRORS = frozenset({5, 32, 33})
_IS_WINDOWS = os.name == "nt"
_replace = os.replace
_RETRY_BUDGET_S = 2.0
_MAX_SLEEP_S = 0.02


def atomic_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """``os.replace`` that tolerates Windows readers holding the target."""
    deadline = time.monotonic() + _RETRY_BUDGET_S
    delay = 0.001
    while True:
        try:
            _replace(src, dst)
            return
        except PermissionError as exc:
            if (not _IS_WINDOWS
                    or getattr(exc, "winerror", None) not in _TRANSIENT_WINERRORS
                    or time.monotonic() >= deadline):
                raise
            time.sleep(delay)
            delay = min(delay * 2, _MAX_SLEEP_S)
