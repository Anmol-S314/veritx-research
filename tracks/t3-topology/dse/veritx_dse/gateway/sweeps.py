"""Read-only supported-sweep evidence; never execute a simulator on a GET."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import InvalidInput
from veritx_dse.gateway.errors import NotFound


def latest_topology_sweep(repo: Path) -> dict[str, Any]:
    root = (repo / "tracks/t3-topology/runs/supported-sweep").resolve()
    # Only the runner's root and one level of named runs, never client paths.
    paths = [root / "topology_sweep.json", *root.glob("*/topology_sweep.json")]
    paths = [p for p in paths if p.is_file() and p.resolve().is_relative_to(root)]
    paths.sort(key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)
    if not paths:
        raise NotFound("No supported-topology sweep; run scripts/sweep_supported.py first")
    path = paths[0]
    with path.open('rb') as handle:
        raw = handle.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise InvalidInput("Supported-topology sweep exceeds 4 MiB")
    try:
        rows = json.loads(raw, parse_constant=lambda value: None)
    except (ValueError, UnicodeError) as exc:
        raise InvalidInput("Supported-topology sweep is not valid JSON") from exc
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get("topology"), str)
        and isinstance(row.get("injection_rate"), (int, float))
        and bool(row["topology"])
        and not isinstance(row.get("injection_rate"), bool)
        and math.isfinite(row["injection_rate"]) and row["injection_rate"] >= 0
        for row in rows
    ):
        raise InvalidInput("Supported-topology sweep must contain topology/rate rows")
    return {
        "source_path": str(path.relative_to(repo)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "repository sweep, not selected project or run",
        "rows": rows,
    }
