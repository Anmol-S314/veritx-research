from typing import List
from .space import DesignSpace, DesignPoint, SimResult
from .evaluator import run_booksim
import time


def grid_search(space: DesignSpace, timeout: int = 120) -> List[SimResult]:
    points = space.enumerate()
    results: List[SimResult] = []
    total = len(points)

    print(f"  grid search: {total} points")

    for i, point in enumerate(points, 1):
        t0 = time.time()
        result = run_booksim(point, space.defaults, timeout=timeout)
        dt = time.time() - t0

        status = f"lat={result.avg_latency:.1f}" if result.ok else f"ERR: {result.error}"
        print(f"  [{i:>{len(str(total))}}/{total}] {point.slug():<50} {status:<25} {dt:.1f}s")
        results.append(result)

    return results


def rank_by_latency(results: List[SimResult]) -> List[SimResult]:
    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]
    ok.sort(key=lambda r: r.avg_latency)
    return ok + fail


def print_ranking(results: List[SimResult], top: int = 10):
    ranked = rank_by_latency(results)
    ok = [r for r in ranked if r.ok]

    print(f"\n{'Rank':<6}{'Config':<55}{'Latency':<12}{'Hops':<10}{'Throughput':<12}")
    print("-" * 95)

    for i, r in enumerate(ok[:top], 1):
        lat = f"{r.avg_latency:.1f}"
        hops = f"{r.avg_hops:.1f}" if r.avg_hops is not None else "-"
        thr = f"{r.throughput:.4f}" if r.throughput is not None else "-"
        print(f"{i:<6}{r.point.slug():<55}{lat:<12}{hops:<10}{thr:<12}")

    if any(not r.ok for r in ranked):
        print(f"\n  {sum(1 for r in ranked if not r.ok)} failed points:")
        for r in ranked:
            if not r.ok:
                print(f"    {r.point.slug()}: {r.error}")
