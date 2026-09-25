"""Durable run bundles and reproduction (C3).

Covers: atomic finalize, checksum verification without rerunning, and
refusal of missing/extra/tampered/unsupported bundles. The BookSim
reproduction test is gated on a real binary and refuses divergence.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.core.run_bundle import (  # noqa: E402
    CHECKSUMS_NAME, RunBundleError, bundle_id, finalize_run_bundle,
    verify_run_bundle,
)


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    (root / "prepared").mkdir(parents=True)
    (root / "prepared" / "config.cfg").write_text("k = 4;\n", encoding="utf-8")
    (root / "result.json").write_text('{"completion_cycles": 40}\n',
                                      encoding="utf-8")
    finalize_run_bundle(root)
    return root


def test_finalize_then_verify_roundtrip(tmp_path):
    root = _bundle(tmp_path)
    assert (root / CHECKSUMS_NAME).is_file()
    first = verify_run_bundle(root)
    second = verify_run_bundle(root)
    assert first["bundle_id"] == second["bundle_id"]
    assert first["file_count"] == 2


def test_verify_refuses_tampered_file(tmp_path):
    root = _bundle(tmp_path)
    (root / "result.json").write_text('{"completion_cycles": 41}\n',
                                      encoding="utf-8")
    with pytest.raises(RunBundleError, match="tampered"):
        verify_run_bundle(root)


def test_verify_refuses_missing_file(tmp_path):
    root = _bundle(tmp_path)
    (root / "result.json").unlink()
    with pytest.raises(RunBundleError, match="incomplete"):
        verify_run_bundle(root)


def test_verify_refuses_extra_file(tmp_path):
    root = _bundle(tmp_path)
    (root / "sneaky.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RunBundleError, match="undeclared"):
        verify_run_bundle(root)


def test_verify_refuses_edited_bundle_id(tmp_path):
    root = _bundle(tmp_path)
    doc = json.loads((root / CHECKSUMS_NAME).read_text())
    doc["bundle_id"] = "0" * 64
    (root / CHECKSUMS_NAME).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RunBundleError, match="bundle_id"):
        verify_run_bundle(root)


def test_verify_refuses_unsupported_schema(tmp_path):
    root = _bundle(tmp_path)
    doc = json.loads((root / CHECKSUMS_NAME).read_text())
    doc["schema_version"] = 999
    (root / CHECKSUMS_NAME).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RunBundleError, match="schema_version"):
        verify_run_bundle(root)


def test_unfinalized_directory_refuses(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    (root / "x").write_text("y", encoding="utf-8")
    with pytest.raises(RunBundleError, match="not a finalized"):
        verify_run_bundle(root)


def test_bundle_id_is_path_independent(tmp_path):
    a = _bundle(tmp_path / "a")
    b = _bundle(tmp_path / "b")
    assert verify_run_bundle(a)["bundle_id"] \
        == verify_run_bundle(b)["bundle_id"]


# ── real-backend reproduction ─────────────────────────────────────────────

def _real_binary():
    from test_backend_booksim_execution import _real_binary as rb
    return rb()


_requires_binary = pytest.mark.skipif(
    _real_binary() is None, reason="no BookSim binary available")


def _execute_real_bundle(tmp_path):
    from test_backend_booksim_execution import _parents
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    _, parents = _parents()
    prepared = prepare_booksim_input(parents)
    run_dir = tmp_path / "run"
    execute_prepared_booksim(
        prepared=prepared, binary=_real_binary(),
        run_dir=run_dir, timeout=600)
    return run_dir


@_requires_binary
def test_real_run_is_finalized_and_reproduces(tmp_path):
    from veritx_dse.backend.reproduce import reproduce_booksim_run_bundle
    run_dir = _execute_real_bundle(tmp_path)
    verify_run_bundle(run_dir)                       # finalized by execution
    result = reproduce_booksim_run_bundle(
        run_dir, binary=_real_binary(), timeout=600)
    assert result["matched"] is True


@_requires_binary
def test_reproduce_refuses_after_tampering(tmp_path):
    from veritx_dse.backend.reproduce import reproduce_booksim_run_bundle
    run_dir = _execute_real_bundle(tmp_path)
    (run_dir / "workload.trace").write_text("0 0 0 1 1\n", encoding="utf-8")
    with pytest.raises(RunBundleError):
        reproduce_booksim_run_bundle(run_dir, binary=_real_binary(),
                                     timeout=600)
