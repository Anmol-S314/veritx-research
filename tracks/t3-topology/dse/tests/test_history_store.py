"""Contract tests for the experiment store (sqlite index over result JSONs)
and its CLI surface `veritx history`.

Seams (agreed):
1. `Store` — ingest a directory tree of result JSONs; query across runs.
   Unit tests use a real sqlite file in tmp_path (no mocks: sqlite is cheap
   and the persistence contract IS the behavior).
2. `veritx history` — subprocess against the real CLI: exit codes + output.

The store is the foundation for the future backend/API/frontend: files stay
the source of truth, the DB is a rebuildable index (delete + rescan = same
content), so no sync machinery — just ingest.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.store import Store  # noqa: E402


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "veritx_dse.cli", *args],
        cwd=str(DSE), capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )


def _write_run(root: Path, rel: str, row: dict) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(row))
    return p


# Two independent truth rows (spec by worked example, not by re-computation):
MESH_ROW = {
    "topology": "mesh4x4", "workload": "ALL_REDUCE",
    "astrasim_cycles": 3980310, "latency_cycles": 3980310,
    "exposed_comm_cycles": 3960310, "comm_overhead_pct": 99.5,
    "status": "ok", "traffic": "astrasim(all_reduce_chakra_et)",
}
TORUS_ROW = {
    "topology": "torus4x4", "workload": "ALL_REDUCE",
    "astrasim_cycles": 3600000, "latency_cycles": 3600000,
    "exposed_comm_cycles": 3570000, "comm_overhead_pct": 99.2,
    "status": "ok", "traffic": "astrasim(all_reduce_chakra_et)",
}


class TestStore:
    def test_ingest_indexable_rows_and_query(self, tmp_path):
        root = tmp_path / "results"
        _write_run(root, "smoketest/astrasim_sweep.json", [MESH_ROW, TORUS_ROW])
        s = Store(tmp_path / "index.db")
        n = s.ingest(root)
        assert n == 2
        rows = s.query(topology="mesh4x4")
        assert len(rows) == 1
        assert rows[0]["astrasim_cycles"] == 3980310

    def test_ingest_skips_non_result_json(self, tmp_path):
        root = tmp_path / "results"
        _write_run(root, "smoketest/astrasim_sweep.json", [MESH_ROW])
        (root / "smoketest" / "not_a_result.json").write_text('{"hello": 1}')
        (root / "smoketest" / "broken.json").write_text("{not json")
        s = Store(tmp_path / "index.db")
        assert s.ingest(root) == 1

    def test_ingest_is_idempotent_same_db(self, tmp_path):
        root = tmp_path / "results"
        _write_run(root, "a/astrasim_sweep.json", [MESH_ROW])
        s = Store(tmp_path / "index.db")
        s.ingest(root)
        s.ingest(root)  # re-scan must not duplicate
        assert len(s.query()) == 1

    def test_rebuild_from_scratch_is_lossless(self, tmp_path):
        """Files are the source of truth: delete the DB, re-ingest, same rows."""
        root = tmp_path / "results"
        _write_run(root, "a/astrasim_sweep.json", [MESH_ROW])
        _write_run(root, "b/topology_sweep.json", [TORUS_ROW])
        db = tmp_path / "index.db"
        s1 = Store(db)
        s1.ingest(root)
        first = sorted(r["astrasim_cycles"] for r in s1.query())
        db.unlink()
        s2 = Store(db)
        s2.ingest(root)
        assert sorted(r["astrasim_cycles"] for r in s2.query()) == first

    def test_query_filters(self, tmp_path):
        root = tmp_path / "results"
        _write_run(root, "a/astrasim_sweep.json", [MESH_ROW, TORUS_ROW])
        s = Store(tmp_path / "index.db")
        s.ingest(root)
        assert len(s.query(status="ok")) == 2
        assert len(s.query(topology="torus4x4")) == 1
        assert s.query(topology="nope") == []
        assert len(s.query(min_cycles=3700000)) == 1   # only mesh above 3.7M

    def test_single_object_row_also_indexed(self, tmp_path):
        """evaluate-astra writes a dict, sweeps write lists — both ingest."""
        root = tmp_path / "results"
        _write_run(root, "astra/eval_one.json", MESH_ROW)
        s = Store(tmp_path / "index.db")
        assert s.ingest(root) == 1


class TestStoreApiSupport:
    """Store additions the read-only API needs (same tmp-sqlite seam)."""

    def _seed(self, tmp_path) -> tuple[Store, Path]:
        root = tmp_path / "results"
        _write_run(root, "smoke/astrasim_sweep.json", [MESH_ROW, TORUS_ROW])
        # Second mesh4x4 row (different workload) so filtered < total is real.
        _write_run(root, "smoke2/astrasim_sweep.json",
                   [dict(MESH_ROW, workload="ALLGATHER")])
        _write_run(root, "other/eval_one.json", dict(MESH_ROW, topology="fly4"))
        s = Store(tmp_path / "index.db")
        s.ingest(root)
        return s, root

    def test_count_all_and_filtered(self, tmp_path):
        s, _ = self._seed(tmp_path)
        assert s.count() == 4
        assert s.count(topology="mesh4x4") == 2
        assert s.count(status="nope") == 0

    def test_topologies_with_counts(self, tmp_path):
        s, _ = self._seed(tmp_path)
        tops = {t["topology"]: t["rows"] for t in s.topologies()}
        assert tops == {"mesh4x4": 2, "torus4x4": 1, "fly4": 1}

    def test_query_rows_carry_provenance(self, tmp_path):
        """API consumers must be able to trace a row to its source file."""
        s, root = self._seed(tmp_path)
        rows = s.query(topology="mesh4x4")
        assert all("source_path" in r for r in rows)
        assert all(r["source_path"].endswith("astrasim_sweep.json") for r in rows)

    def test_count_topologies_empty_db(self, tmp_path):
        s = Store(tmp_path / "fresh.db")
        assert s.count() == 0
        assert s.topologies() == []


class TestHistoryCLI:
    def test_history_empty_state_guides_reindex(self, tmp_path, monkeypatch):
        """Fresh environment (no index.db yet): no crash, and the miss
        teaches the fix (--reindex) instead of printing an empty table.
        VERITX_INDEX_DB relocates the index so the test is hermetic — the
        subprocess must not depend on whatever the dev's repo happens to
        have indexed."""
        monkeypatch.setenv("VERITX_INDEX_DB", str(tmp_path / "index.db"))
        r = _cli("history")
        assert r.returncode == 0, r.stderr
        combined = r.stdout + r.stderr
        assert "No indexed rows" in combined
        assert "--reindex" in combined

    def test_history_json_mode(self):
        r = _cli("--json", "history")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert isinstance(data, list)
