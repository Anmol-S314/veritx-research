#!/usr/bin/env python3
"""Minimal DSE smoke test — 6 points, should run in <30s."""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from space import Axis, DesignSpace
from search import grid_search, print_ranking
from evaluator import BOOKSIM_BIN

SPACE = DesignSpace(
    axes=[
        Axis("topology", ("mesh",)),
        Axis("vcs", (2, 4)),
    ],
    defaults={
        "x_dim": 8, "y_dim": 8,
        "injection_rate": 0.08,
        "traffic": "uniform",
        "vc_buf": 8,
        "routing": "dor",
    },
)

def main():
    print(f"DSE smoke test: {SPACE.size()} points")
    print(f"booksim: {BOOKSIM_BIN}")
    t0 = time.time()
    results = grid_search(SPACE)
    print_ranking(results)
    print(f"\n  total: {time.time()-t0:.1f}s for {SPACE.size()} points")

if __name__ == "__main__":
    main()
