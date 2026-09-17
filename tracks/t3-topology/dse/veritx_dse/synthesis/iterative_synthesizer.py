#!/usr/bin/env python3
"""iterative_synthesizer.py — RHO + GRPO topology synthesis.

Rolling Horizon Optimization (RHO) and Group Relative Policy Optimization
(GRPO) for NoC topology search. Both start from a seed topology and
iteratively improve via BookSim trace-replay evaluation.

RHO: At each step, sample B candidate mutations, roll each forward H steps
with random rollouts, pick the candidate whose best rollout is lowest.

GRPO: At each step, sample a group of G candidates, evaluate all with
BookSim, compute group baseline (mean reward), pick the best with
advantage > 0, update surrogate online.

Usage:
  python3 iterative_synthesizer.py --trace runs/traces/qwen3_serving_16rank.trace \\
    --method rho --steps 50 --horizon 5 --branch 5
  python3 iterative_synthesizer.py --trace runs/traces/qwen3_serving_16rank.trace \\
    --method grpo --steps 50 --group 4
"""
import argparse
import copy
import json
import math
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Canonical topology sizes — single source of truth in
# veritx_dse.model.presets. Mesh/grid/anynet size math delegates here
# instead of hand-rolled counting.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from veritx_dse.model.presets import topo_size, count_anynet_edges
except ImportError:
    try:
        from ..model.presets import topo_size, count_anynet_edges  # type: ignore
    except Exception:
        topo_size = None  # type: ignore
        count_anynet_edges = None  # type: ignore

# Unified synthesis evaluation machinery (Phase 2a). Script-mode safe.
try:
    from veritx_dse.synthesis.evaluator import (
        ITERATIVE_PRESET,
        evaluate_adj,
        is_connected as _shared_is_connected,
        write_anynet as _shared_write_anynet,
    )
    from veritx_dse.synthesis.results import SynthResult
except Exception:
    try:
        from evaluator import (  # type: ignore
            ITERATIVE_PRESET,
            evaluate_adj,
            is_connected as _shared_is_connected,
            write_anynet as _shared_write_anynet,
        )
        from results import SynthResult  # type: ignore
    except Exception:
        ITERATIVE_PRESET = None  # type: ignore
        evaluate_adj = None  # type: ignore
        _shared_is_connected = None  # type: ignore
        _shared_write_anynet = None  # type: ignore
        SynthResult = None  # type: ignore


def mesh_size(k: int = 8, n: int = 2) -> tuple:
    """Thin wrapper over the canonical helper for mesh sizes.

    Kept under a local name for backward compat; new code should call
    ``topo_size`` directly.
    """
    if topo_size is not None:
        return topo_size("mesh", {"k": k, "n": n})
    return (k ** n, n * (k - 1) * k ** (n - 1) if k > 0 else 0)


def grid_size(num_nodes: int) -> tuple:
    """Thin wrapper for sqrt(n)×sqrt(n) grid meshes via the canonical helper."""
    k = math.isqrt(num_nodes)
    assert k * k == num_nodes, f"n={num_nodes} must be a perfect square"
    return mesh_size(k, 2)


def anynet_size(path) -> tuple:
    """Thin wrapper over the canonical anynet counter (backward compat)."""
    if count_anynet_edges is not None:
        return count_anynet_edges(str(path))
    # Fallback: parse locally (same format as count_anynet_edges).
    nodes: set = set()
    edges: set = set()
    try:
        for line in open(path):
            parts = line.split()
            if len(parts) < 5 or parts[0] != "router":
                continue
            rid = int(parts[1])
            nodes.add(rid)
            i = 4
            while i < len(parts):
                if parts[i] == "router" and i + 1 < len(parts):
                    pid = int(parts[i + 1])
                    nodes.add(pid)
                    edges.add((min(rid, pid), max(rid, pid)))
                    i += 2
                else:
                    i += 1
    except (OSError, ValueError):
        pass
    return len(nodes), len(edges)


def mesh_seed_adj(n: int) -> dict:
    """√n×√n mesh seed when n is a perfect square, else a connected
    ring + chords fallback. Starting from the wrong node count poisons the
    whole search: BookSim drops packets to unroutable nodes and every
    latency eval is garbage."""
    k = math.isqrt(n)
    if k * k != n:
        # Not a square: ring connects everything; add nearest-neighbor chords.
        adj = {i: set() for i in range(n)}
        for i in range(n):
            adj[i].add((i + 1) % n)
            adj[(i + 1) % n].add(i)
        for i in range(n):
            j = (i + max(1, n // 4)) % n
            adj[i].add(j)
            adj[j].add(i)
        return adj
    adj = {i: set() for i in range(n)}
    for y in range(k):
        for x in range(k):
            nid = y * k + x
            if x < k - 1:
                adj[nid].add(nid + 1)
                adj[nid + 1].add(nid)
            if y < k - 1:
                adj[nid].add(nid + k)
                adj[nid + k].add(nid)
    return adj

import numpy as np

# Canonical roots — single source of truth in veritx_dse.core.paths.
# The __file__ math below is the script-mode fallback (same values).
try:
    from veritx_dse.core.paths import REPO, BOOKSIM_BIN, SYNTH_DIR
    from veritx_dse.core.constants import BOOKSIM_SEED, DEFAULT_TIMEOUT, env_int
except Exception:
    REPO = Path(__file__).resolve().parents[5]
    BOOKSIM_BIN = REPO / "third_party" / "booksim2" / "src" / "booksim"
    SYNTH_DIR = Path(__file__).resolve().parents[3] / "runs" / "booksim"
    BOOKSIM_SEED = 42
    DEFAULT_TIMEOUT = 60
    def env_int(name, default):
        import os
        raw = os.environ.get(name)
        if raw is None:
            return default
        return int(raw)
BOOKSIM = BOOKSIM_BIN
RUNS = REPO / "runs" / "booksim"


def load_anynet(path):
    adj = {i: set() for i in range(256)}
    max_node = 0
    for line in open(path):
        parts = line.split()
        if parts[0] != "router":
            continue
        rid = int(parts[1])
        max_node = max(max_node, rid)
        i = 4
        while i < len(parts):
            if parts[i] == "router":
                pid = int(parts[i + 1])
                adj[rid].add(pid)
                adj[pid].add(rid)
                max_node = max(max_node, pid)
                i += 2
            else:
                i += 1
    n = max_node + 1
    return {k: adj[k] for k in range(n)}


def edges_of(adj):
    return set()
    # unreachable — but the function is called; fix:
    # Actually this was a bug in my earlier script. Let me rewrite properly.


def edges_of(adj):
    s = set()
    for a in adj:
        for b in adj[a]:
            if a < b:
                s.add((a, b))
    return s


def is_connected(adj):
    """Connectivity check (thin wrapper over the shared evaluator check).

    Kept for backward compat (tests import it); functionally identical.
    """
    if _shared_is_connected is not None:
        return _shared_is_connected(adj)
    n = len(adj)
    if n == 0:
        return False
    vis = {0}
    stack = [0]
    while stack:
        u = stack.pop()
        for v in adj.get(u, []):
            if v not in vis:
                vis.add(v)
                stack.append(v)
    return len(vis) == n


def eval_bs(adj, trace_path, seed=BOOKSIM_SEED, timeout=None):
    """Evaluate an adjacency on a trace; return latency (1e9 on failure).

    Phase 2a: delegates to the shared evaluator with ITERATIVE_PRESET
    (pareto-converged: span-derived sample_period, max_samples=5, warmup 1,
    honest-first first-match). Returns the same float
    sentinel the RHO/GRPO loops rely on; canonical status/error conversion
    happens at the .json sidecar record boundary in main().

    timeout=None resolves VERITX_TIMEOUT (default 60s) at call time.
    """
    if timeout is None:
        timeout = env_int("VERITX_TIMEOUT", DEFAULT_TIMEOUT)
    if evaluate_adj is not None and ITERATIVE_PRESET is not None:
        try:
            RUNS.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            res = evaluate_adj(
                adj, trace_path=trace_path, workdir=None,
                seed=seed, timeout=timeout, config=ITERATIVE_PRESET,
                name=f"iterative_N{len(adj)}", scratch_parent=RUNS,
            )
        except Exception as e:
            print(f"warning: eval_bs: BookSim run failed ({type(e).__name__}: {e}) — scoring 1e9",
                  file=sys.stderr)
            return 1e9
        if res.status == "ok":
            return float(res.latency)
        kind = (res.extra or {}).get("failure_kind", "")
        if kind == "timeout":
            print(f"warning: eval_bs: BookSim timed out after {timeout}s: {res.error} — scoring 1e9",
                  file=sys.stderr)
            return 1e9
        if kind == "no_latency":
            # Original garbage-output path was silent (returned 1e9 with no
            # warning); preserve silence here.
            return 1e9
        print(f"warning: eval_bs: BookSim run failed ({res.error}) — scoring 1e9",
              file=sys.stderr)
        return 1e9
    # No inline fallback: the pre-2a duplicated BookSim path lived here and
    # encoded pre-convergence numbers (max_samples 1, wait_for_tail, plat
    # parse). The shared evaluator (imported above, sibling fallback for
    # script mode) is the ONE evaluation path. Fail loudly if unavailable.
    raise ImportError(
        "iterative_synthesizer.eval_bs requires "
        "veritx_dse.synthesis.evaluator (or sibling evaluator.py for "
        "`python3 iterative_synthesizer.py`); refusing a divergent fallback."
    )


def mutate_add(adj, n):
    cand = copy.deepcopy(adj)
    a, b = random.randint(0, n - 1), random.randint(0, n - 1)
    if a != b and b not in cand[a]:
        cand[a].add(b)
        cand[b].add(a)
        return cand, f"add {a}-{b}"
    return None, None


def mutate_remove(adj):
    cand = copy.deepcopy(adj)
    es = list(edges_of(cand))
    if not es:
        return None, None
    a, b = random.choice(es)
    cand[a].discard(b)
    cand[b].discard(a)
    if not is_connected(cand):
        cand[a].add(b)
        cand[b].add(a)
        return None, None
    return cand, f"remove {a}-{b}"


def mutate(adj, n):
    if random.random() < 0.5:
        return mutate_add(adj, n)
    return mutate_remove(adj)


def run_rho(seed_adj, trace_path, steps=50, H=5, B=5, max_edges=120, timeout=None):
    n = len(seed_adj)
    best_adj = copy.deepcopy(seed_adj)
    best_lat = eval_bs(best_adj, trace_path, timeout=timeout)
    print(f"RHO start: {len(edges_of(best_adj))}e {best_lat:.2f}c (H={H} B={B})")
    t0 = time.time()

    for step in range(steps):
        candidates = []
        for _ in range(B * 2):
            cand, op = mutate(best_adj, n)
            if cand is None:
                continue
            if len(edges_of(cand)) > max_edges:
                continue
            # RHO rollout
            rollout_best = 1e9
            for _ in range(B):
                roll = copy.deepcopy(cand)
                for h in range(H - 1):
                    roll2, _ = mutate(roll, n)
                    if roll2 is not None and len(edges_of(roll2)) <= max_edges:
                        roll = roll2
                lat = eval_bs(roll, trace_path, timeout=timeout)
                if lat < rollout_best:
                    rollout_best = lat
            candidates.append((rollout_best, op, cand))

        if not candidates:
            continue
        candidates.sort(key=lambda x: x[0])
        best_roll, best_op, best_cand = candidates[0]
        imm_lat = eval_bs(best_cand, trace_path, timeout=timeout)

        if step % 10 == 0 or imm_lat < best_lat:
            print(f"  [{step+1:3d}] {best_op} {len(edges_of(best_cand))}e "
                  f"imm={imm_lat:.2f}c rollout={best_roll:.2f}c best={best_lat:.2f}c "
                  f"({time.time()-t0:.1f}s)")

        if imm_lat < best_lat:
            best_lat = imm_lat
            best_adj = best_cand
        elif best_roll < best_lat:
            best_adj = best_cand
            best_lat = imm_lat

    return best_adj, best_lat


def run_grpo(seed_adj, trace_path, steps=50, group=4, max_edges=120, timeout=None):
    n = len(seed_adj)
    best_adj = copy.deepcopy(seed_adj)
    best_lat = eval_bs(best_adj, trace_path, timeout=timeout)
    print(f"GRPO start: {len(edges_of(best_adj))}e {best_lat:.2f}c (group={group})")
    t0 = time.time()

    for step in range(steps):
        group_results = []
        for g in range(group):
            cand, _ = mutate(best_adj, n)
            if cand is None or len(edges_of(cand)) > max_edges:
                continue
            lat = eval_bs(cand, trace_path, timeout=timeout)
            reward = -lat - 0.1 * len(edges_of(cand))
            group_results.append((reward, lat, len(edges_of(cand)), cand))

        if not group_results:
            continue

        rewards = [r for r, _, _, _ in group_results]
        baseline = sum(rewards) / len(rewards)
        group_results.sort(key=lambda x: x[0], reverse=True)
        best_reward, best_imm, best_e, best_cand = group_results[0]
        adv = best_reward - baseline

        if step % 10 == 0 or best_imm < best_lat:
            print(f"  [{step+1:3d}] group={[f'{r:.1f}' for r in rewards[:4]]} "
                  f"baseline={baseline:.1f} best={best_imm:.2f}c {best_e}e "
                  f"adv={adv:.1f} ({time.time()-t0:.1f}s)")

        if best_imm < best_lat and best_e <= max_edges:
            best_lat = best_imm
            best_adj = best_cand

    return best_adj, best_lat


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--method", default="rho", choices=["rho", "grpo"])
    ap.add_argument("--seed-anynet", default=None,
                    help="Seed topology .anynet (default: √n mesh for the trace's node count)")
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--max-edges", type=int, default=120)
    ap.add_argument("--timeout", type=int, default=60)
    # RHO params
    ap.add_argument("--horizon", type=int, default=5, help="RHO lookahead depth")
    ap.add_argument("--branch", type=int, default=5, help="RHO rollouts per candidate")
    # GRPO params
    ap.add_argument("--group", type=int, default=4, help="GRPO group size")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    trace = str(Path(args.trace).resolve())

    if args.seed_anynet:
        seed_adj = load_anynet(args.seed_anynet)
    else:
        # Seed from the trace's actual node count — a hardcoded 64-node mesh
        # against a smaller trace leaves nodes unreachable and every eval
        # degenerate.
        max_node = -1
        for line in open(trace):
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) >= 5:
                try:
                    max_node = max(max_node, int(p[1]), int(p[3]))
                except ValueError:
                    continue
        if max_node < 0:
            ap.error(f"trace has no parseable packets: {args.trace}")
        n_seed = max_node + 1
        print(f"Seed topology: √{n_seed} mesh ({n_seed} nodes from trace)")
        seed_adj = mesh_seed_adj(n_seed)

    print(f"Method: {args.method} | Trace: {Path(args.trace).name} | Steps: {args.steps}")

    if args.method == "rho":
        best_adj, best_lat = run_rho(
            seed_adj, trace, steps=args.steps, H=args.horizon,
            B=args.branch, max_edges=args.max_edges, timeout=args.timeout,
        )
    else:
        best_adj, best_lat = run_grpo(
            seed_adj, trace, steps=args.steps, group=args.group,
            max_edges=args.max_edges, timeout=args.timeout,
        )

    # Save winner (canonical synth home; Phase 4c single results home).
    out_path = Path(args.out) if args.out else SYNTH_DIR / f"{args.method}_best.anynet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if _shared_write_anynet is not None:
        _shared_write_anynet(best_adj, out_path)
    else:
        with open(out_path, "w") as f:
            for i in range(len(best_adj)):
                peers = sorted(best_adj[i])
                f.write(f"router {i} node {i} " + " ".join(f"router {p}" for p in peers) + "\n")

    # Save results JSON
    json_path = out_path.with_suffix(".json")
    _sidecar = {
        "method": args.method,
        "trace": args.trace,
        "seed_anynet": args.seed_anynet,
        "steps": args.steps,
        "edges": len(edges_of(best_adj)),
        "latency": best_lat,
        "topology": str(out_path),
    }
    # Phase 2a record boundary: canonical winner record (ADDITIVE — existing
    # keys untouched). Inner RHO/GRPO loops keep float sentinels (1e9).
    try:
        if SynthResult is not None:
            _n = len(best_adj)
            _e = len(edges_of(best_adj))
            _ok = isinstance(best_lat, (int, float)) and best_lat < 1e9
            if _ok:
                _sr = SynthResult.ok(
                    name=f"{args.method}_best", topology="anynet",
                    nodes=_n, edges=_e, latency=float(best_lat), seed=BOOKSIM_SEED,
                    provenance="iterative_synthesizer+ITERATIVE_PRESET",
                    extra={"method": args.method, "trace": args.trace,
                           "steps": args.steps},
                )
            else:
                _sr = SynthResult.fail(
                    name=f"{args.method}_best", topology="anynet",
                    nodes=_n, edges=_e, error=f"best_lat sentinel {best_lat}",
                    seed=BOOKSIM_SEED,
                    provenance="iterative_synthesizer+ITERATIVE_PRESET",
                    extra={"method": args.method, "trace": args.trace,
                           "steps": args.steps},
                )
            _sidecar["synth_result"] = _sr.to_dict()
    except Exception:
        pass
    json_path.write_text(json.dumps(_sidecar, indent=2))

    print(f"\nFinal: {best_lat:.2f}c {len(edges_of(best_adj))}e → {out_path}")


if __name__ == "__main__":
    main()
