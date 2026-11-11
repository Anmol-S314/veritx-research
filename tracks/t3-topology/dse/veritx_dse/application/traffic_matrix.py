"""veritx_dse.application.traffic_matrix — src x dst aggregation of a run trace.

A rendered BookSim trace is the physical traffic the fabric actually carried:
one line per packet, `<cycle> <src> <class> <dst> <flits>`. Aggregating it by
(src, dst) yields the traffic matrix the topology was asked to serve — the
quantity every per-link claim is ultimately about, and the one thing the
topology view has never been able to show.

This is DERIVED EVIDENCE, not a model: it counts what the run emitted. It does
not estimate, extrapolate or fill in pairs the trace never carried. The same
aggregation is repeated per traffic class when a class-specific matrix is
needed; absent classes stay absent.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from veritx_dse.core.errors import InvalidInput

class TrafficMatrixError(ValueError):
    """The trace cannot be aggregated (fail-closed)."""

_COLUMNS = 5

def _grids(nodes: int, counts: dict[tuple[int, int], list[int]]) -> tuple[list[list[int]], list[list[int]]]:
    matrix = [[0] * nodes for _ in range(nodes)]
    flit_matrix = [[0] * nodes for _ in range(nodes)]
    for (src, dst), (packets, flits) in counts.items():
        matrix[src][dst] = packets
        flit_matrix[src][dst] = flits
    return matrix, flit_matrix

def _pairs(counts: dict[tuple[int, int], list[int]]) -> list[dict[str, int]]:
    return [
        {"src": src, "dst": dst, "packets": packets, "flits": flits}
        for (src, dst), (packets, flits) in sorted(
            counts.items(), key=lambda kv: (-kv[1][0], kv[0]))
    ]

def aggregate_trace(
        path: Path, *, expected_packets: int | None = None,
) -> dict[str, Any]:
    """Count packets and flits per (src, dst) over a rendered trace.

    ``expected_packets`` is the conservation check the run already made: when
    the caller knows how many packets the trace should carry, a short read is
    refused rather than silently reported as a smaller matrix.
    """
    trace = Path(path)
    if not trace.is_file():
        raise TrafficMatrixError(f"trace not found: {trace}")
    counts: dict[tuple[int, int], list[int]] = {}
    class_counts: dict[int, dict[tuple[int, int], list[int]]] = {}
    classes: dict[int, int] = {}
    packets = 0
    flits = 0
    max_node = -1
    malformed = 0
    with trace.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != _COLUMNS:
                malformed += 1
                continue
            try:
                src = int(parts[1])
                cls = int(parts[2])
                dst = int(parts[3])
                size = int(parts[4])
            except ValueError:
                malformed += 1
                continue
            if src < 0 or dst < 0 or size < 0:
                malformed += 1
                continue
            row = counts.get((src, dst))
            if row is None:
                counts[(src, dst)] = [1, size]
            else:
                row[0] += 1
                row[1] += size
            by_class = class_counts.setdefault(cls, {})
            class_row = by_class.get((src, dst))
            if class_row is None:
                by_class[(src, dst)] = [1, size]
            else:
                class_row[0] += 1
                class_row[1] += size
            classes[cls] = classes.get(cls, 0) + 1
            packets += 1
            flits += size
            if src > max_node:
                max_node = src
            if dst > max_node:
                max_node = dst
    if malformed:
        raise TrafficMatrixError(
            f"{malformed} malformed trace line(s) in {trace.name}: the trace "
            f"is not the canonical 5-column dialect, so a matrix over it "
            f"would be a guess")
    if expected_packets is not None and packets != expected_packets:
        raise TrafficMatrixError(
            f"trace carries {packets} packets but the run declared "
            f"{expected_packets} — refusing to report a partial matrix")
    nodes = max_node + 1
    matrix, flit_matrix = _grids(nodes, counts)
    class_matrices = {}
    for cls, by_class in sorted(class_counts.items()):
        class_matrix, class_flit_matrix = _grids(nodes, by_class)
        class_matrices[str(cls)] = {
            "packets": sum(row[0] for row in by_class.values()),
            "flits": sum(row[1] for row in by_class.values()),
            "distinct_pairs": len(by_class),
            "matrix": class_matrix,
            "flit_matrix": class_flit_matrix,
            "pairs": _pairs(by_class),
        }
    return {
        "nodes": nodes,
        "packets": packets,
        "flits": flits,
        "distinct_pairs": len(counts),
        "classes": {str(k): v for k, v in sorted(classes.items())},
        "matrix": matrix,
        "flit_matrix": flit_matrix,
        "pairs": _pairs(counts),
        "class_matrices": class_matrices,
    }

def _selfcheck() -> None:
    import tempfile
    body = ("0 0 0 1 8\n1 0 0 1 8\n2 1 0 0 8\n3 2 1 2 4\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.trace"
        p.write_text(body)
        m = aggregate_trace(p)
        assert m["nodes"] == 3, m["nodes"]
        assert m["packets"] == 4, m["packets"]
        assert m["flits"] == 28, m["flits"]
        assert m["matrix"][0][1] == 2, m["matrix"]
        assert m["matrix"][2][2] == 1, m["matrix"]
        assert m["distinct_pairs"] == 3
        assert m["pairs"][0] == {"src": 0, "dst": 1, "packets": 2, "flits": 16}
        assert set(m["class_matrices"]) == {"0", "1"}
        assert m["class_matrices"]["0"]["matrix"][0][1] == 2
        assert m["class_matrices"]["0"]["flit_matrix"][0][1] == 16
        assert m["class_matrices"]["1"]["matrix"][2][2] == 1
        assert m["class_matrices"]["1"]["flits"] == 4
        try:
            aggregate_trace(p, expected_packets=99)
        except TrafficMatrixError:
            pass
        else:
            raise AssertionError("short read must be refused")
        bad = Path(d) / "bad.trace"
        bad.write_text("0 0 0 1\n")
        try:
            aggregate_trace(bad)
        except TrafficMatrixError:
            pass
        else:
            raise AssertionError("malformed trace must be refused")
    print("traffic_matrix selfcheck ok")

__all__ = ["TrafficMatrixError", "aggregate_trace"]
