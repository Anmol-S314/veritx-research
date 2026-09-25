"""Production fault injection (C4).

Every failure mode must end in a typed failure with no certified result and
no partially trusted evidence. Uses the injected process seam for the
failure shapes that do not need a real backend, and the real binary for the
post-qualification tamper checks.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim_execution import (  # noqa: E402
    _binary, _parents, _runner_for, GOOD_STDERR, GOOD_STDOUT,
)

from veritx_dse.backend import booksim_execution as bx  # noqa: E402
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    prepare_booksim_input,
)
from veritx_dse.core.run_bundle import (  # noqa: E402
    RunBundleError, finalize_run_bundle, verify_run_bundle,
)


def _prepared():
    return prepare_booksim_input(_parents()[1])


def _execute(tmp_path, *, runner, prepared=None, **kw):
    prepared = prepared or _prepared()
    return bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "run", timeout=30, runner=runner, **kw)


def test_nonzero_exit_is_a_typed_failure_no_evidence(tmp_path):
    prepared = _prepared()
    with pytest.raises(bx.BookSimExecutionError, match="exited 3"):
        _execute(tmp_path, runner=_runner_for(prepared, returncode=3),
                 prepared=prepared)
    assert not (tmp_path / "run" / "backend-evidence.json").exists()


def test_backend_hang_times_out_and_fails(tmp_path):
    prepared = _prepared()
    with pytest.raises(bx.BookSimExecutionError, match="timed out"):
        _execute(tmp_path, runner=_runner_for(prepared, timed_out=True),
                 prepared=prepared)
    assert not (tmp_path / "run" / "backend-evidence.json").exists()


def test_malformed_output_missing_completion_fails(tmp_path):
    prepared = _prepared()
    bad = GOOD_STDOUT.replace("Completion time is 777 cycles\n", "")
    with pytest.raises(bx.BookSimExecutionError):
        _execute(tmp_path, runner=_runner_for(prepared, stdout=bad),
                 prepared=prepared)


def test_partial_output_missing_delivered_fails_conservation():
    # A supervised (certified) run requires the delivered counter; an
    # injected run does not, so this is asserted at the gate itself.
    stats = bx.parse_booksim_stats(GOOD_STDOUT, GOOD_STDERR)
    with pytest.raises(bx.BookSimExecutionError,
                       match="conservation|delivered|prove"):
        bx.assert_execution_gate(
            stats, expected_packets=5, expected_flits=4,
            require_conservation=True)


def test_config_modified_after_preparation_refuses(tmp_path):
    prepared = _prepared()
    run_dir = tmp_path / "run"
    bx.materialize_prepared(prepared, run_dir)
    (run_dir / "config.cfg").write_text("k = 99;\n", encoding="utf-8")
    with pytest.raises(bx.BookSimExecutionError, match="different bytes"):
        bx.materialize_prepared(prepared, run_dir)


def test_trace_modified_after_preparation_refuses(tmp_path):
    prepared = _prepared()
    run_dir = tmp_path / "run"
    bx.materialize_prepared(prepared, run_dir)
    (run_dir / "workload.trace").write_text("0 0 0 1 1\n", encoding="utf-8")
    with pytest.raises(bx.BookSimExecutionError, match="different bytes"):
        bx.materialize_prepared(prepared, run_dir)


def test_stale_directory_with_foreign_file_refuses(tmp_path):
    prepared = _prepared()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "leftover.bin").write_bytes(b"old")
    with pytest.raises(bx.BookSimExecutionError, match="unexpected file"):
        bx.materialize_prepared(prepared, run_dir)


def test_evidence_modified_after_finalize_refuses(tmp_path):
    prepared = _prepared()
    run_dir = tmp_path / "run"
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path), run_dir=run_dir,
        timeout=30, runner=_runner_for(prepared))
    assert record.ref is not None
    verify_run_bundle(run_dir)
    ev = run_dir / "backend-evidence.json"
    ev.write_text(ev.read_text().replace('"stats"', '"stats_tampered"'),
                  encoding="utf-8")
    with pytest.raises(RunBundleError, match="tampered"):
        verify_run_bundle(run_dir)


def test_partial_bundle_refuses(tmp_path):
    prepared = _prepared()
    run_dir = tmp_path / "run"
    bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path), run_dir=run_dir,
        timeout=30, runner=_runner_for(prepared))
    # remove an artifact but keep checksums.json -> incomplete
    (run_dir / "workload.trace").unlink()
    with pytest.raises(RunBundleError, match="incomplete"):
        verify_run_bundle(run_dir)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores mode bits")
def test_read_only_directory_cannot_finalize(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "x").write_text("y", encoding="utf-8")
    run_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(OSError):
            finalize_run_bundle(run_dir)
    finally:
        run_dir.chmod(stat.S_IRWXU)
