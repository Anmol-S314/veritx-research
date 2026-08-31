#!/usr/bin/env python3
"""Zero-pads a Timeloop-derived NxN traffic matrix file up to an MxM
matrix (M >= N) so it can be fed to BookSim topologies whose node count
(k*k*c) doesn't exactly match the matrix's real node count. Padding
nodes are appended after the real ones (real node indices, including
the DRAM node, are unchanged) and have all-zero rows/cols, so they sit
idle (MatrixTrafficPattern sends a node with zero row-total to itself).
"""
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent / "_padded_matrices"


def _read_matrix(path: Path):
    vals = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0]
            vals.extend(float(x) for x in line.split())
    n = round(len(vals) ** 0.5)
    if n * n != len(vals):
        raise ValueError(f"{path}: {len(vals)} entries is not a perfect square")
    return [[vals[r * n + c] for c in range(n)] for r in range(n)], n


def padded_matrix_path(src_path, target_nodes: int) -> Path:
    """Returns a path to a target_nodes x target_nodes matrix file whose
    top-left NxN block is src_path's matrix and the rest is zero.
    Regenerated only if missing/stale; cached under _padded_matrices/."""
    src_path = Path(src_path)
    matrix, n = _read_matrix(src_path)
    if target_nodes < n:
        raise ValueError(f"{src_path}: has {n} real nodes, cannot pad down to {target_nodes}")

    _CACHE_DIR.mkdir(exist_ok=True)
    out_path = _CACHE_DIR / f"{src_path.stem}_{target_nodes}.txt"
    if target_nodes == n:
        out_path.write_text(src_path.read_text())
        return out_path

    if out_path.exists() and out_path.stat().st_mtime >= src_path.stat().st_mtime:
        return out_path

    lines = [f"# {src_path.name} ({n} real nodes) zero-padded to {target_nodes} nodes"]
    for r in range(target_nodes):
        row = matrix[r] + [0.0] * (target_nodes - n) if r < n else [0.0] * target_nodes
        lines.append(" ".join(repr(v) for v in row))
    out_path.write_text("\n".join(lines) + "\n")
    return out_path
