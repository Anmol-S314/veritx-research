"""veritx_dse.backend.reproduce — re-execute and compare a BookSim bundle.

``reproduce`` does NOT trust the stored numbers: it verifies the bundle,
re-runs the recorded backend on the verified inputs in a fresh directory,
and compares the deterministic science (parsed statistics and the executed
route-dump digest). A divergence refuses.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from veritx_dse.backend.booksim_execution import parse_booksim_stats
from veritx_dse.backend.booksim_projection import (
    CONFIG_FILE, ROUTE_DUMP_FILE, TOPOLOGY_FILE, TRACE_FILE,
)
from veritx_dse.core.run_bundle import RunBundleError, verify_run_bundle

_EVIDENCE_NAME = "backend-evidence.json"
_INPUT_NAMES = (CONFIG_FILE, TRACE_FILE, TOPOLOGY_FILE)


def _evidence_doc(run_dir: Path) -> dict[str, Any]:
    path = run_dir / _EVIDENCE_NAME
    if not path.is_file():
        raise RunBundleError(
            f"{run_dir} holds no {_EVIDENCE_NAME}; not a BookSim run bundle")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunBundleError(f"{path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict) or "evidence" not in doc:
        raise RunBundleError(f"{path} is not a booksim evidence document")
    return doc


def reproduce_booksim_run_bundle(
        run_dir: str | Path, *, binary: str | Path | None = None,
        timeout: int = 600) -> dict[str, Any]:
    """Verify, re-execute and compare; refuse any scientific divergence."""
    root = Path(run_dir)
    verify_summary = verify_run_bundle(root)
    doc = _evidence_doc(root)
    stored = doc["evidence"]
    attempt = doc.get("attempt", {})
    if binary is None:
        binary = attempt.get("binary_path")
    if not binary or not Path(binary).is_file():
        raise RunBundleError(
            f"reproduce needs the backend binary; none at {binary!r} "
            "(pass --binary)")

    with tempfile.TemporaryDirectory(prefix="veritx-reproduce-") as tmp:
        work = Path(tmp)
        for name in _INPUT_NAMES:
            src = root / name
            if src.is_file():
                shutil.copy2(src, work / name)
        cmd = [str(binary), CONFIG_FILE]
        proc = subprocess.run(
            cmd, cwd=str(work), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, shell=False)
        if proc.returncode != 0:
            raise RunBundleError(
                f"reproduction backend exited {proc.returncode}: "
                f"{(proc.stderr or '')[-300:]}")

        new_stats = parse_booksim_stats(proc.stdout, proc.stderr)
        if new_stats != stored.get("stats"):
            raise RunBundleError(
                "reproduction diverges from the stored science: stats "
                f"{new_stats} != {stored.get('stats')}")

        stored_dump = stored.get("route_dump_sha256")
        if stored_dump is not None:
            dump_path = work / ROUTE_DUMP_FILE
            if not dump_path.is_file():
                raise RunBundleError(
                    "reproduction produced no route dump while the stored "
                    "evidence claims one")
            new_dump = hashlib.sha256(dump_path.read_bytes()).hexdigest()
            if new_dump != stored_dump:
                raise RunBundleError(
                    "reproduction route realization diverges from the "
                    f"stored dump ({new_dump} != {stored_dump})")
    return {"matched": True, "bundle_id": verify_summary["bundle_id"],
            "stats": new_stats, "route_dump_sha256": stored_dump}


__all__ = ["reproduce_booksim_run_bundle"]
