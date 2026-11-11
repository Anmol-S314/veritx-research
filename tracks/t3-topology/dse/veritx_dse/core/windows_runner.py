"""Contain one supervised command before it can spawn any descendants.

The parent kills this wrapper on timeout; its private job handle then closes
and Windows kills the whole owned tree. This avoids the attach-after-spawn race
of assigning an already-running third-party executable to a job from outside.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    from veritx_dse.core.windows_job import contain_current_process
    contain_current_process()
    if not sys.argv[1:]:
        raise ValueError("missing supervised Windows command")
    return subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
