"""Production concurrency / idempotency (C4).

Two identical jobs must not corrupt each other; two different jobs must not
collide; retries must yield the same scientific identity where the science
is deterministic.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim_execution import _parents, _real_binary  # noqa: E402

from veritx_dse.backend.booksim_projection import (  # noqa: E402
    prepare_booksim_input,
)
from veritx_dse.core.run_bundle import (  # noqa: E402
    finalize_run_bundle, verify_run_bundle,
)

_requires_binary = pytest.mark.skipif(
    _real_binary() is None, reason="no BookSim binary available")


def _seed(root: Path, text: str) -> Path:
    root.mkdir(parents=True)
    (root / "science.json").write_text(text, encoding="utf-8")
    return root


def test_concurrent_finalize_same_directory_is_idempotent(tmp_path):
    root = _seed(tmp_path / "run", '{"x": 1}')
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: finalize_run_bundle(root), range(4)))
    summary = verify_run_bundle(root)
    assert summary["file_count"] == 1


def test_concurrent_distinct_bundles_do_not_collide(tmp_path):
    dirs = [_seed(tmp_path / f"run{i}", '{"x": %d}' % i) for i in range(4)]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(finalize_run_bundle, dirs))
    ids = {verify_run_bundle(d)["bundle_id"] for d in dirs}
    assert len(ids) == 4
    for d in dirs:
        verify_run_bundle(d)


@_requires_binary
def test_concurrent_identical_runs_share_identity(tmp_path):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    prepared = prepare_booksim_input(_parents()[1])
    binary = _real_binary()

    def run(i):
        return execute_prepared_booksim(
            prepared=prepared, binary=binary,
            run_dir=tmp_path / f"run{i}", timeout=600)

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(run, range(2)))
    ids = {r.evidence.evidence_id() for r in records}
    assert len(ids) == 1                       # identical science
    assert records[0].attempt.run_dir != records[1].attempt.run_dir
    for i in range(2):
        verify_run_bundle(tmp_path / f"run{i}")


@_requires_binary
def test_concurrent_different_runs_do_not_collide(tmp_path):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.model.compile_model import TopologyFamily
    from test_backend_booksim_execution import _parents as parents_fn
    binary = _real_binary()
    variants = [
        prepare_booksim_input(parents_fn()[1]),
        prepare_booksim_input(parents_fn(compute=8, tp=8)[1]),
    ]

    def run(i):
        return execute_prepared_booksim(
            prepared=variants[i], binary=binary,
            run_dir=tmp_path / f"run{i}", timeout=600)

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(run, range(2)))
    assert records[0].evidence.evidence_id() \
        != records[1].evidence.evidence_id()
