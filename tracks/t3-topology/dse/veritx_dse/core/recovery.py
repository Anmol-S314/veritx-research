"""veritx_dse.recovery — Cleanup and rollback utilities.

Ensures partial state is cleaned up on failure.
"""
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def temporary_directory(prefix: str = "veritx_"):
    """Context manager that cleans up temp dir on any exit."""
    tmpdir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield tmpdir
    finally:
        if tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)


@contextmanager
def atomic_write(path: Path):
    """Write to temp file, then rename on success."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        yield tmp_path
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
