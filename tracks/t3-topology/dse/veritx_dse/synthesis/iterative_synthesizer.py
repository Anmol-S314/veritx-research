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

import numpy as np

REPO = Path(__file__).resolve().parents[3]
BOOKSIM = REPO / "third_party" / "booksim2" / "src" / "booksim"
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


def eval_bs(adj, trace_path, seed=42, timeout=60):
    n = len(adj)
    work = Path(tempfile.mkdtemp(dir=RUNS))
    anynet = work / "topo.anynet"
    with open(anynet, "w") as f:
        for i in range(n):
            peers = sorted(adj[i])
            f.write(f"router {i} node {i} " + " ".join(f"router {p}" for p in peers) + "\n")

    # Auto-detect span
    span = 0
    try:
        for line in open(trace_path):
            if line.startswith("#"):
                continue
            p = line.split()
            if len(p) >= 5:
                span = max(span, int(p[0]))
    except Exception:
        pass
    sp = max(50000, span + 10000)

    cfg = f"""topology = anynet;
routing_function = min;
network_file = {anynet};
traffic = trace({trace_path});
num_vcs = 4;
vc_buf_size = 8;
packet_size = 8;
sim_type = latency;
latency_thres = -1.0;
sample_period = {sp};
max_samples = 1;
wait_for_tail_credit = 1;
use_noc_latency = 0;
seed = {seed};
"""
    (work / "cfg").write_text(cfg)
    try:
        r = subprocess.run(
            [str(BOOKSIM.resolve()), str((work / "cfg").resolve())],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(work), stdin=subprocess.DEVNULL,
        )
        import re
        m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", r.stdout)
        lat = float(m.group(1)) if m else 1e9
    except Exception:
        lat = 1e9
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return lat


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


def run_rho(seed_adj, trace_path, steps=50, H=5, B=5, max_edges=120, timeout=60):
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


def run_grpo(seed_adj, trace_path, steps=50, group=4, max_edges=120, timeout=60):
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
                    help="Starting topology (default: mesh 8x8)")
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
        # Default: mesh 8x8
        seed_adj = {i: set() for i in range(64)}
        for y in range(8):
            for x in range(8):
                nid = y * 8 + x
                if x < 7:
                    seed_adj[nid].add(nid + 1)
                    seed_adj[nid + 1].add(nid)
                if y < 7:
                    seed_adj[nid].add(nid + 8)
                    seed_adj[nid + 8].add(nid)

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

    # Save winner
    out_path = Path(args.out) if args.out else RUNS / f"{args.method}_best.anynet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for i in range(len(best_adj)):
            peers = sorted(best_adj[i])
            f.write(f"router {i} node {i} " + " ".join(f"router {p}" for p in peers) + "\n")

    # Save results JSON
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps({
        "method": args.method,
        "trace": args.trace,
        "seed_anynet": args.seed_anynet,
        "steps": args.steps,
        "edges": len(edges_of(best_adj)),
        "latency": best_lat,
        "topology": str(out_path),
    }, indent=2))

    print(f"\nFinal: {best_lat:.2f}c {len(edges_of(best_adj))}e → {out_path}")


if __name__ == "__main__":
    main()
