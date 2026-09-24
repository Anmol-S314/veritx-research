"""core.runs hardening: floor consistency, atomic init, concurrent writes.

`core.runs` is the intended single run/lifecycle authority but was
untested and used non-atomic initial publication plus an unlocked
read-modify-write for results.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core import runs  # noqa: E402
from veritx_dse.core.runs import Run, RunError  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    d = tmp_path / "veritx-runs"
    monkeypatch.setattr(runs, "VERITX_RUNS_DIR", d)
    return d


def _create(repo: Path) -> Run:
    return Run.create(repo, {"a": 1}, argv=["veritx", "run"])


def test_runtime_floor_matches_pyproject():
    assert runs._RUNTIME_FLOOR == runs._declared_floor()
    assert runs._declared_floor() == (3, 10)


def test_dependency_lock_exists_and_is_fingerprinted():
    assert runs._LOCK_PATH.is_file(), "requirements.lock must ship"
    identity = runs._dependency_lock_identity()
    assert identity["requirements.lock.sha256"] is not None


def test_create_publishes_all_files_atomically(runs_dir, tmp_path):
    r = _create(_repo(tmp_path))
    for name in ("manifest.json", "provenance.json", "spec.resolved.json",
                 "state.json"):
        assert (r.root / name).is_file(), name
    assert not list(r.root.glob("*.tmp")), "no leftover temp files"
    assert r.state == "CREATED"


def test_create_refuses_an_existing_run_directory(runs_dir, tmp_path,
                                                 monkeypatch):
    repo = _repo(tmp_path)
    _create(repo)
    # pin the same run id -> the directory already exists
    existing = sorted(p.name for p in runs_dir.iterdir())[0]
    monkeypatch.setattr(runs, "new_run_id", lambda: existing)
    with pytest.raises(FileExistsError):
        _create(repo)


def test_concurrent_add_result_preserves_every_write(runs_dir, tmp_path):
    r = _create(_repo(tmp_path))
    n = 32

    def writer(i: int) -> None:
        r.add_result(f"task{i}", {"value": i})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    manifest = json.loads((r.root / "manifest.json").read_text())
    recorded = sorted(entry["task_id"] for entry in manifest["results"])
    assert recorded == sorted(f"task{i}" for i in range(n))


def test_add_result_after_terminal_refuses(runs_dir, tmp_path):
    r = _create(_repo(tmp_path))
    r.cancel("done")                       # CREATED -> CANCELLED (terminal)
    with pytest.raises(RunError, match="immutable"):
        r.add_result("t2", {"value": 2})


def test_illegal_transition_refuses(runs_dir, tmp_path):
    r = _create(_repo(tmp_path))
    with pytest.raises(RunError, match="illegal transition"):
        r.transition("SUCCEEDED")
