from typing import List
import time
import os
import json
import hashlib
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from space import DesignSpace, DesignPoint, SimResult
from evaluator import run_booksim
from objective import rank_f2, is_saturated

# ── Cache helpers ──────────────────────────────────────────────────────
SCRATCH = Path(__file__).resolve().parent / ".scratch"


def _defaults_repr(defaults: dict) -> str:
    """Deterministic string form of defaults (stable across processes)."""
    return json.dumps(defaults, sort_keys=True, default=str)


def _cache_key(point: DesignPoint, defaults: dict) -> str:
    """Stable cross-process key: slug + sorted defaults repr hashed.

    NOTE: do NOT use hash() on frozenset/str here — Python hashes are
    randomized per process (PYTHONHASHSEED), so a hash-based key would
    never collide across runs and the cache would grow unboundedly
    with zero hits. sha1 of a deterministic repr is stable.
    """
    return hashlib.sha1(
        f"{point.slug()}|{_defaults_repr(defaults)}".encode()
    ).hexdigest()[:16]


def _load_cache(path: Path) -> dict[str, dict]:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_cache(path: Path, cache: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, indent=2)


def _result_to_cache(r: SimResult) -> dict:
    return {
        "values": dict(r.point.values),   # full assignments, no slug parsing needed
        "avg_latency": r.avg_latency,
        "avg_hops": r.avg_hops,
        "throughput": r.throughput,
        "energy_pj": r.energy_pj,
        "error": r.error,
    }


def _cache_to_result(key: str, d: dict, space_defaults: dict) -> SimResult:
    # Reconstruct the point from stored values dict or legacy slug.
    vals = d.get("values") or {}
    if not vals:
        # Legacy format: slug like "topology-mesh_vcs-4|hash" — parse it
        slug = d.get("slug", key.split("|")[0])
        for part in slug.split("_"):
            if "-" in part:
                k, v = part.split("-", 1)
                # Try to coerce to int
                try:
                    v = int(v)
                except ValueError:
                    pass
                vals[k] = v
    point = DesignPoint(tuple(vals.items()))
    return SimResult(
        point=point,
        avg_latency=d.get("avg_latency"),
        avg_hops=d.get("avg_hops"),
        throughput=d.get("throughput"),
        energy_pj=d.get("energy_pj"),
        error=d.get("error"),
    )


# ── Grid search ────────────────────────────────────────────────────────
def _run_one(args):
    """Top-level function for ProcessPoolExecutor (must be picklable)."""
    point, defaults, timeout = args
    return run_booksim(point, defaults, timeout=timeout)


def grid_search(space: DesignSpace, timeout: int = 120,
                workers: int | None = None,
                cache_path: str | Path | None = None) -> List[SimResult]:
    """Grid search over the design space.

    workers=None → auto-detect (min(cpu_count, 4) to avoid OOM).
    cache_path → JSON cache file; points already present are skipped.
    """
    points = space.enumerate()
    total = len(points)

    if workers is None:
        workers = min(os.cpu_count() or 1, 4)
    workers = min(workers, total)

    # ── load cache ──
    cache_file = Path(cache_path) if cache_path else SCRATCH / "grid_cache.json"
    cache = _load_cache(cache_file)

    # ── separate cached vs uncached ──
    uncached = []   # (index_in_points, point)
    for i, point in enumerate(points):
        key = _cache_key(point, space.defaults)
        if key in cache:
            continue
        uncached.append((i, point))

    cached_n = total - len(uncached)
    print(f"  grid search: {total} points, {len(uncached)} uncached "
          f"({cached_n} cached), {workers} workers")

    results: List[SimResult] = [None] * total

    # ── fill cached results ──
    for i, point in enumerate(points):
        key = _cache_key(point, space.defaults)
        if key in cache:
            results[i] = _cache_to_result(key, cache[key], space.defaults)

    # ── run uncached in parallel ──
    if uncached:
        if workers <= 1:
            for j, (i, point) in enumerate(uncached):
                t0 = time.time()
                result = run_booksim(point, space.defaults, timeout=timeout)
                dt = time.time() - t0
                key = _cache_key(point, space.defaults)
                cache[key] = _result_to_cache(result)
                _save_cache(cache_file, cache)
                status = f"lat={result.avg_latency:.1f}" if result.ok else f"ERR: {result.error}"
                print(f"  [{j+1:>{len(str(len(uncached)))}}/{len(uncached)}] {point.slug():<50} {status:<25} {dt:.1f}s")
                results[i] = result
        else:
            done = 0
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_run_one, (point, space.defaults, timeout)): idx
                    for idx, point in uncached
                }
                for future in as_completed(futures):
                    i = futures[future]
                    result = future.result()
                    done += 1
                    key = _cache_key(points[i], space.defaults)
                    cache[key] = _result_to_cache(result)
                    _save_cache(cache_file, cache)
                    status = f"lat={result.avg_latency:.1f}" if result.ok else f"ERR: {result.error}"
                    print(f"  [{done:>{len(str(len(uncached)))}}/{len(uncached)}] {result.point.slug():<50} {status}")
                    results[i] = result

    return results


def rank_by_latency(results: List[SimResult]) -> List[SimResult]:
    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]
    ok.sort(key=lambda r: r.avg_latency)
    return ok + fail


def rank(space: DesignSpace, results: List[SimResult]) -> List[SimResult]:
    """F2 ranking: feasible (non-saturated) configs first by latency, then
    saturated rejects, then errors. injection_rate comes from space defaults."""
    ir = space.defaults.get("injection_rate", 0.08)
    return rank_f2(results, ir)


def print_ranking(results: List[SimResult], top: int = 10, injection_rate: float = 0.08):
    ranked = rank_f2(results, injection_rate)
    feasible = [r for r in ranked if r.ok and not is_saturated(r, r.point.values.get("injection_rate", injection_rate))]
    rejected = [r for r in ranked if r.ok and is_saturated(r, r.point.values.get("injection_rate", injection_rate))]
    failed = [r for r in ranked if not r.ok]

    print(f"\n{'Rank':<6}{'Config':<55}{'Latency':<12}{'Hops':<10}{'Thru':<9}{'Flag'}")
    print("-" * 95)

    for i, r in enumerate(feasible[:top], 1):
        lat = f"{r.avg_latency:.1f}"
        hops = f"{r.avg_hops:.1f}" if r.avg_hops is not None else "-"
        thr = f"{r.throughput:.4f}" if r.throughput is not None else "-"
        print(f"{i:<6}{r.point.slug():<55}{lat:<12}{hops:<10}{thr:<9}{'OK'}")

    for r in rejected:
        lat = f"{r.avg_latency:.1f}"
        hops = f"{r.avg_hops:.1f}" if r.avg_hops is not None else "-"
        thr = f"{r.throughput:.4f}" if r.throughput is not None else "-"
        print(f"{'-':<6}{r.point.slug():<55}{lat:<12}{hops:<10}{thr:<9}{'SAT'}")

    print(f"\n  feasible={len(feasible)} saturated={len(rejected)} failed={len(failed)}")

    if failed:
        print(f"\n  failed points:")
        for r in failed:
            print(f"    {r.point.slug()}: {r.error}")
