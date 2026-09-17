"""Experiment store: a rebuildable sqlite index over result JSONs.

Design contract (see tests/test_history_store.py):

- **Files are the source of truth.** The DB is a disposable index: delete it
  and re-ingest — same rows. No sync machinery, no WAL, no migrations beyond
  CREATE TABLE IF NOT EXISTS.
- **Ingest is idempotent.** Re-scanning the same tree never duplicates rows;
  (source_path, row_index) is the natural key.
- **Never fabricates.** A result JSON that isn't a recognizable result row
  (list of dicts or a dict with a status/topology shape) is skipped, not
  guessed into the schema.

This is the foundation layer for the future backend/API/frontend: `veritx
history` queries it today; a FastAPI read-only service can sit on the same
Store class tomorrow without the schema changing.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Columns every recognized result row may carry. Extra keys are preserved in
# the raw JSON but not indexed (add here first if a query needs them).
_COLUMNS = (
    "topology", "workload", "status", "traffic",
    "astrasim_cycles", "latency_cycles", "exposed_comm_cycles",
    "comm_overhead_pct", "hops_avg", "injection_rate", "total_nodes",
)


class Store:
    """sqlite-backed index over result JSON files. See module docstring."""

    def __init__(self, db_path: str | Path):
        self._db = str(db_path)
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as c:
            cols = ",".join(f"{col} TEXT" for col in _COLUMNS)
            c.execute(
                f"""CREATE TABLE IF NOT EXISTS runs (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       source_path TEXT NOT NULL,
                       row_index   INTEGER NOT NULL,
                       raw TEXT,
                       {cols},
                       UNIQUE(source_path, row_index)
                   )"""
            )

    @staticmethod
    def _rows_from_file(path: Path):
        """Yield indexable dict rows from one result file; skip silently on
        unrecognizable shapes (the ingest count reports what was indexed)."""
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return
        candidates = data if isinstance(data, list) else [data]
        idx = 0
        for item in candidates:
            if isinstance(item, dict) and ("topology" in item or "status" in item):
                yield idx, item
            idx += 1

    def ingest(self, root: str | Path) -> int:
        """Walk `root` for *.json, index every recognizable row. Idempotent:
        re-ingesting an unchanged file replaces its rows (natural key)."""
        root = Path(root)
        n = 0
        with self._conn() as c:
            for path in sorted(root.rglob("*.json")):
                rows = list(self._rows_from_file(path))
                if not rows:
                    continue
                key = str(path.resolve())
                c.execute("DELETE FROM runs WHERE source_path = ?", (key,))
                for idx, row in rows:
                    cols = {}
                    for k in _COLUMNS:
                        v = row.get(k)
                        # sqlite binds str/int/float/None only — nested
                        # dicts/lists (plat_stats, per-rank maps) serialize.
                        if isinstance(v, (dict, list)):
                            v = json.dumps(v)
                        cols[k] = v
                    cols["raw"] = json.dumps(row)
                    names = ["source_path", "row_index", *cols]
                    marks = ",".join("?" for _ in names)
                    vals = [key, idx, *cols.values()]
                    c.execute(
                        f"INSERT INTO runs ({','.join(names)}) VALUES ({marks})",
                        vals,
                    )
                    n += 1
        return n

    def query(
        self,
        topology: str | None = None,
        status: str | None = None,
        workload: str | None = None,
        min_cycles: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Filter indexed rows; numeric comparisons are numeric, rest exact."""
        where, params = [], []
        for col, val in (("topology", topology), ("status", status),
                         ("workload", workload)):
            if val is not None:
                where.append(f"{col} = ?")
                params.append(str(val))
        if min_cycles is not None:
            where.append("CAST(astrasim_cycles AS REAL) >= ?")
            params.append(float(min_cycles))
        sql = (
            "SELECT *, source_path AS source_path FROM runs "
            + ("WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY id DESC LIMIT ?"
        )
        params.append(int(limit))
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(sql, params)]
        out = []
        for r in rows:
            try:
                parsed = json.loads(r.pop("raw"))
            except (json.JSONDecodeError, KeyError):
                continue
            # Provenance rides on the parsed row (API consumers trace any
            # row back to its file); never clobbers an in-row key.
            parsed.setdefault("source_path", r.get("source_path"))
            out.append(parsed)
        return out

    def count(self, topology: str | None = None, status: str | None = None) -> int:
        """Number of indexed rows matching the filter (cheap, no row fetch)."""
        where, params = [], []
        if topology is not None:
            where.append("topology = ?")
            params.append(str(topology))
        if status is not None:
            where.append("status = ?")
            params.append(str(status))
        sql = "SELECT COUNT(*) AS n FROM runs" + (
            " WHERE " + " AND ".join(where) if where else "")
        with self._conn() as c:
            return int(c.execute(sql, params).fetchone()["n"])

    def topologies(self) -> list[dict]:
        """Distinct topologies with row counts, largest first."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT topology, COUNT(*) AS rows FROM runs
                   WHERE topology IS NOT NULL
                   GROUP BY topology ORDER BY rows DESC, topology"""
            ).fetchall()
        return [{"topology": r["topology"], "rows": int(r["rows"])} for r in rows]
