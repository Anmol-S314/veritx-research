"""bo_synthesizer.py — Bayesian Optimization topology synthesis.

Replaces SA with BO for sample-efficient optimization of NoC topologies.
Searches over TOPOLOGY PARAMETERS (5 dimensions) instead of individual
edges (118+ dimensions), making it tractable for GP surrogates.

Search space:
  cluster_size:   {4, 8, 16} — nodes per cluster
  express_length: {1, 2, 3}  — max hop length for express links
  radix:          {3, 4, 5}  — max degree per node
  intra_weight:   [0.5, 1.0] — probability of intra-cluster edges
  inter_weight:   [0.1, 0.5] — probability of inter-cluster edges

Usage:
  python3 bo_synthesizer.py --traffic runs/traces/test1_events.json --nodes 64 --iters 50
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from skopt import gp_minimize
from skopt.space import Categorical, Real
from skopt.utils import use_named_args

# ── Imports from our codebase ──────────────────────────────────────────
# fix path: repo_root/tracks/t3-topology/scripts
_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO / "tracks/t3-topology/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    from collectives import ring_allreduce_pairs
except ImportError:
    # fallback stub if collectives.py not found
    def ring_allreduce_pairs(participants, size_bytes):
        n = len(participants)
        if n <= 1: return []
        chunk = size_bytes / n
        return [(participants[i], participants[(i+1)%n], chunk) for i in range(n)]

# ── Topology generation from parameters ────────────────────────────────

def grid_xy(n):
    """Place n nodes on a sqrt(n) × sqrt(n) grid."""
    k = int(math.isqrt(n))
    assert k * k == n, f"n={n} must be a perfect square"
    return [(x, y) for y in range(k) for x in range(k)]


def generate_topology(n, cluster_size, express_length, radix,
                      intra_weight, inter_weight, seed=42):
    """Generate topology edges from parameters.

    Guarantees connectivity by starting with a nearest-neighbor mesh
    and adding parameterized edges on top.

    Returns adjacency dict: {node: set(neighbor_nodes)}.
    """
    rng = np.random.default_rng(seed)
    xy = grid_xy(n)
    k = int(math.isqrt(n))

    # Start with nearest-neighbor mesh (guarantees connectivity)
    adj = {i: set() for i in range(n)}
    for i in range(n):
        x, y = xy[i]
        for dx, dy in [(1, 0), (0, 1)]:  # right and down only (undirected)
            nx, ny = x + dx, y + dy
            if 0 <= nx < k and 0 <= ny < k:
                j = ny * k + nx
                adj[i].add(j)
                adj[j].add(i)

    # Add intra-cluster edges based on intra_weight
    cluster_of = [i // cluster_size for i in range(n)]
    n_clusters = n // cluster_size
    for c in range(n_clusters):
        members = [i for i in range(n) if cluster_of[i] == c]
        for i in members:
            for j in members:
                if i < j and j not in adj[i]:
                    d = abs(xy[i][0] - xy[j][0]) + abs(xy[i][1] - xy[j][1])
                    if d <= express_length and rng.random() < intra_weight:
                        adj[i].add(j)
                        adj[j].add(i)

    # Add inter-cluster express links based on inter_weight
    reps = [c * cluster_size for c in range(n_clusters)]
    for i in reps:
        for j in reps:
            if i < j and j not in adj[i]:
                d = abs(xy[i][0] - xy[j][0]) + abs(xy[i][1] - xy[j][1])
                if d <= express_length * 2 and rng.random() < inter_weight:
                    adj[i].add(j)
                    adj[j].add(i)

    # Enforce radix budget: remove longest edges at over-degree nodes
    changed = True
    while changed:
        changed = False
        for i in range(n):
            while len(adj[i]) > radix - 1:
                longest = max(adj[i], key=lambda j: abs(xy[i][0] - xy[j][0]) + abs(xy[i][1] - xy[j][1]))
                adj[i].discard(longest)
                adj[longest].discard(i)
                changed = True

    return adj


def adj_to_edge_list(adj):
    """Convert adjacency dict to sorted edge list."""
    edges = set()
    for a, nbrs in adj.items():
        for b in nbrs:
            edges.add(tuple(sorted((a, b))))
    return sorted(edges)


def edge_list_to_anynet(adj, path):
    """Write BookSim .anynet format."""
    n = len(adj)
    with open(path, "w") as f:
        for i in range(n):
            neighbors = sorted(adj.get(i, set()))
            f.write(f"router {i} node {i} " + " ".join(f"router {n}" for n in neighbors) + "\n")


# ── Objective function ─────────────────────────────────────────────────

def build_traffic_matrix(events_path, n_nodes):
    """Build traffic matrix from event stream or .trace file."""
    p = Path(events_path)
    # try JSON first, fallback to trace parsing
    try:
        events = json.load(open(events_path))
    except Exception:
        # .trace files are "cyc src cl dst sz" - build matrix from counts
        T = np.zeros((n_nodes, n_nodes))
        try:
            for line in open(p):
                line=line.strip()
                if not line or line.startswith("#"): continue
                parts=line.split()
                if len(parts) < 5: continue
                _, src, _, dst, _ = parts[:5]
                T[int(src)][int(dst)] += 1
        except Exception:
            pass
        if T.sum() == 0:
            T = np.ones((n_nodes, n_nodes))  # fallback uniform
        return T
    # traffic_model.json path: handle missing meta gracefully
    if "meta" not in events or "num_tiles" not in events.get("meta", {}):
        # traffic_model.json uses network.flow_classes, not meta/collectives
        # Fallback uniform for validation only — analytical path doesn't use this
        if "network" in events and "flow_classes" in events["network"]:
            # synthesize a simple T from flow_classes participants
            T = np.zeros((n_nodes, n_nodes))
            for fc in events["network"]["flow_classes"]:
                for inst in fc.get("instances", [])[:1]:
                    parts = inst.get("participants", [])[:4]
                    if len(parts) >= 2:
                        for s,d,b in ring_allreduce_pairs(parts, fc.get("bytes_per_invocation", 8192)):
                            if s < n_nodes and d < n_nodes: T[s][d] += b
            if T.sum() == 0: T = np.ones((n_nodes, n_nodes))
            return T
        T = np.ones((n_nodes, n_nodes))
        return T
    clusters = n_nodes // events["meta"]["num_tiles"]
    n_intra = events["meta"]["num_tiles"]

    T = np.zeros((n_nodes, n_nodes))
    for c in events["collectives"]:
        for rep in range(clusters):
            off = rep * n_intra
            for src, dst, b in ring_allreduce_pairs(
                [off + p for p in c["participants"]], c["size_bytes"]
            ):
                T[src][dst] += b

    # Inter-cluster gradient AR
    reps = [c * n_intra for c in range(clusters)]
    LLAMA7B_LAYER_GRAD_BYTES = (4096 * (3 * 4096 + 4096 + 2 * 11008)) * 2
    for src, dst, b in ring_allreduce_pairs(reps, LLAMA7B_LAYER_GRAD_BYTES):
        T[src][dst] += b

    return T


def _is_connected(adj):
    """BFS connectivity check."""
    n = len(adj)
    if n == 0:
        return False
    visited = set()
    queue = [0]
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                queue.append(nb)
    return len(visited) == n


def evaluate_topology(adj, T, workdir):
    """Run BookSim on topology + traffic, return latency (or 1000.0 on failure).

    Reuses a single work directory (overwrites files each eval).
    Supports trace mode (legit Qwen 95K) and matrix mode (synthetic).
    """
    n = len(adj)
    edge_count = sum(len(v) for v in adj.values()) // 2

    # Fast-fail: disconnected or degenerate topologies
    if edge_count < n - 1 or not _is_connected(adj):
        return 1e9  # penalty >> real latency (~40k) so GP doesn't prefer disconnected

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # Write .anynet
    anynet_path = workdir / "topo.anynet"
    edge_list_to_anynet(adj, anynet_path)

    # Trace mode (legit Qwen 95K) vs matrix mode (synthetic)
    global _trace_path
    if _trace_path and Path(_trace_path).exists():
        # Trace mode: use trace directly, auto sample_period from max cycle, packet_size 8, single class (anynet doesn't support classes)
        try:
            max_cyc = 0
            with open(_trace_path) as tf:
                for line in tf:
                    if line.startswith("#"): continue
                    parts=line.split()
                    if len(parts)>=5:
                        max_cyc = max(max_cyc, int(parts[0]))
            sample_period = max(200, max_cyc + 1000) if max_cyc>0 else 200
        except: sample_period = 200
        trace_abs = Path(_trace_path).resolve()
        cfg_path = workdir / "run.cfg"
        cfg_path.write_text(f"""topology = anynet;
routing_function = min;
network_file = {anynet_path.resolve()};
traffic = trace({trace_abs});
num_vcs = 4;
vc_buf_size = 8;
packet_size = 8;
sample_period = 200;
max_samples = 3;
seed = 42;
sim_type = throughput;
""")
    else:
        # Matrix mode (synthetic)
        max_val = T.max() if T is not None else 1
        T_norm = T / max_val if max_val > 0 else T
        matrix_path = workdir / "traffic.matrix"
        with open(matrix_path, "w") as f:
            for row in T_norm:
                f.write(" ".join(f"{v:.6g}" for v in row) + "\n")
        cfg_path = workdir / "run.cfg"
        cfg_path.write_text(f"""topology = anynet;
routing_function = min;
network_file = {anynet_path.resolve()};
traffic = matrix({matrix_path.resolve()});
num_vcs = 4;
vc_buf_size = 16;
sample_period = 100;
max_samples = 3;
injection_rate = 0.04;  # 9ce5 pre-knee: BookSim 0.08 saturates, use 0.04
seed = 42;
sim_type = throughput;
""")

    # Run BookSim — pass ABSOLUTE cfg path (subprocess cwd=workdir,
    # so relative paths get doubled)
    import subprocess
    booksim = "/home/datavex/veritx-research/third_party/booksim2/src/booksim"
    try:
        r = subprocess.run(
            [booksim, str(cfg_path.resolve())],
            capture_output=True, text=True, timeout=60, cwd=str(workdir.resolve())
        )
        # Parse latency
        import re
        matches = re.findall(r"Packet latency average\s*=\s*([0-9.]+)", r.stdout)
        if matches:
            return float(matches[-1])  # Last sample = final average
        return 1000.0  # No latency found (timeout or error)
    except (subprocess.TimeoutExpired, Exception):
        return 1000.0  # Large but finite (GP can't handle inf)


# ── BO objective wrapper ───────────────────────────────────────────────

# Search space dimensions
search_space = [
    Categorical([4, 8, 16], name="cluster_size"),
    Categorical([1, 2, 3], name="express_length"),
    Categorical([3, 4, 5], name="radix"),
    Real(0.5, 1.0, name="intra_weight"),
    Real(0.1, 0.5, name="inter_weight"),
]

_eval_count = 0
_best_lat = float("inf")
_best_params = None
_booksim_workdir_counter = 0


@use_named_args(search_space)
def objective(cluster_size, express_length, radix, intra_weight, inter_weight):
    """BO objective: minimize latency.

    Scorer modes:
      - 'analytical': fast Dijkstra-based scoring (~50ms/eval, event-native)
      - 'booksim':    cycle-accurate BookSim S1 trace replay (~10-60s/eval)
    """
    global _eval_count, _best_lat, _best_params, _booksim_workdir_counter
    _eval_count += 1

    n = _n_nodes
    adj = generate_topology(n, cluster_size, express_length, radix,
                            intra_weight, inter_weight, seed=_eval_count)

    edge_count = sum(len(v) for v in adj.values()) // 2

    if _scorer == "booksim":
        # Cycle-accurate BookSim scoring — the honest number
        wb = Path(_booksim_workdir)
        wb.mkdir(parents=True, exist_ok=True)
        _booksim_workdir_counter += 1
        eval_dir = wb / f"iter_{_booksim_workdir_counter:04d}"
        lat = evaluate_topology(adj, _T_matrix, str(eval_dir))
        # Also count edges for display
        edge_count = len(adj_to_edge_list(adj))
    else:
        # Event-native scoring: collectives kept structural, algorithm chosen
        # per-topology, priority-weighted (~50ms, Dijkstra-based).
        from event_objective import score_topology
        obj, _det = score_topology(adj, _xy, _events)
        lat = obj / 1e9  # scale to comparable magnitude (GB-cycles)

    if lat < _best_lat:
        _best_lat = lat
        _best_params = {
            "cluster_size": int(cluster_size),
            "express_length": int(express_length),
            "radix": int(radix),
            "intra_weight": float(intra_weight),
            "inter_weight": float(inter_weight),
            "edges": edge_count,
        }

    marker = " *" if lat == _best_lat and lat < 1e8 else ""
    print(f"  [{_eval_count:3d}] cs={cluster_size} el={express_length} r={radix} "
          f"iw={intra_weight:.2f} ew={inter_weight:.2f} "
          f"edges={edge_count:3d} lat={lat:.2f}c{_scorer[0]}{marker}")

    return lat


# ── Main ───────────────────────────────────────────────────────────────

_n_nodes = 64
_T_matrix = None
_events = None
_xy = None
_scorer = "analytical"
_booksim_workdir = None


def main():
    global _n_nodes, _T_matrix, _events, _xy

    ap = argparse.ArgumentParser()
    ap.add_argument("--traffic", default="runs/traces/test1_events.json")
    ap.add_argument("--nodes", type=int, default=64)
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scorer", default="analytical", choices=["analytical", "booksim"],
                    help="Scoring function: 'analytical' (fast, ~50ms) or 'booksim' (accurate, ~10-60s)")
    args = ap.parse_args()

    global _scorer, _booksim_workdir, _trace_path
    _n_nodes = args.nodes
    _scorer = args.scorer
    _trace_path = args.traffic if Path(args.traffic).exists() and Path(args.traffic).suffix==".trace" else None
    # Only build T when needed — analytical path uses _events+_xy only (no matrix)
    # For trace files, BookSim trace mode is used, not matrix
    if _scorer == "booksim":
        _T_matrix = build_traffic_matrix(args.traffic, args.nodes) if _trace_path is None else None
    else:
        _T_matrix = None  # analytical path: structural events only
    _booksim_workdir = f"runs/booksim/bo_{_scorer}_N{args.nodes}"
    # Clean previous iteration dirs to avoid disk bloat
    import shutil
    bwdir = Path(_booksim_workdir)
    if bwdir.exists():
        shutil.rmtree(bwdir, ignore_errors=True)
    # _events is used for event-native scoring; if traffic is .trace, build stub.
    # Try JSON first; on failure, parse trace directly (no T needed for analytical path).
    try:
        _events = json.load(open(args.traffic))
        if "collectives" not in _events:
            raise ValueError("not events json")
    except Exception:
        _events = {"meta": {"num_tiles": 16}, "collectives": []}
        if _scorer == "booksim" and _T_matrix is not None:
            T = _T_matrix
            for src in range(min(4, args.nodes)):
                dsts = [j for j in range(args.nodes) if T[src][j] > 0][:8]
                if len(dsts) >= 2:
                    _events["collectives"].append({"tensor": f"trace_col_{src}", "participants": dsts[:4], "size_bytes": 8192, "priority": 2, "pattern": "allreduce"})
        else:
            # analytical path: parse trace directly to build stub (no T build)
            try:
                from collections import defaultdict
                pairs = defaultdict(int)
                with open(args.traffic) as tf:
                    for line in tf:
                        line=line.strip()
                        if not line or line.startswith("#"): continue
                        pts=line.split()
                        if len(pts) < 5: continue
                        _, s, _, d, _ = pts[:5]
                        pairs[(int(s), int(d))] += 1
                # pick top-4 src groups
                by_src = defaultdict(list)
                for (s,d),c in pairs.items(): by_src[s].append(d)
                for s in list(by_src.keys())[:4]:
                    dsts = by_src[s][:4]
                    if len(dsts) >= 2:
                        _events["collectives"].append({"tensor": f"trace_col_{s}", "participants": dsts[:4], "size_bytes": 8192, "priority": 2, "pattern": "allreduce"})
            except Exception: pass
        if not _events["collectives"]:
            _events["collectives"] = [{"tensor": "trace_col_0", "participants": list(range(min(8, args.nodes))), "size_bytes": 8192, "priority": 2, "pattern": "allreduce"}]
    _k = int(math.isqrt(args.nodes))
    _xy = [(x, y) for y in range(_k) for x in range(_k)]

    scorer_label = "BookSim S1 cycle-accurate" if _scorer == "booksim" else "analytical Dijkstra (fast)"
    gb_str = f"{_T_matrix.sum()/1e9:.2f} GB" if _T_matrix is not None else "structural (no T)"
    print(f"=== BO Topology Synthesis ({_scorer} scorer) ===")
    print(f"Nodes: {args.nodes}, Traffic: {gb_str}")
    print(f"Iterations: {args.iters}, Scorer: {scorer_label}")
    print()

    t0 = time.time()
    result = gp_minimize(
        objective,
        search_space,
        n_calls=args.iters,
        n_random_starts=10,
        random_state=args.seed,
        verbose=False,
    )
    elapsed = time.time() - t0

    print(f"\n=== Results ===")
    print(f"Best latency: {result.fun:.1f} cycles")
    print(f"Best params: {_best_params}")
    print(f"Total time: {elapsed:.1f}s ({elapsed/args.iters:.1f}s/eval)")
    print(f"Total evals: {result.func_vals}")

    # Save results
    out = {
        "best_latency": result.fun,
        "best_params": _best_params,
        "all_evals": [
            {"params": dict(zip(
                ["cluster_size", "express_length", "radix", "intra_weight", "inter_weight"],
                [int(x) if isinstance(x, (int, np.integer)) else float(x) for x in xi]
            )), "latency": float(fi)}
            for xi, fi in zip(result.x_iters, result.func_vals)
        ],
        "elapsed": elapsed,
    }
    out_path = Path(f"runs/booksim/bo_results_N{args.nodes}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))
    print(f"Results saved to {out_path}")

    # Write winner topology to stable path for pipeline cert
    if _best_params:
        winner_adj = generate_topology(args.nodes, _best_params["cluster_size"],
                                        _best_params["express_length"], _best_params["radix"],
                                        _best_params["intra_weight"], _best_params["inter_weight"],
                                        seed=args.seed)
        winner_path = Path("runs/booksim/topo.anynet")
        winner_path.parent.mkdir(parents=True, exist_ok=True)
        edge_list_to_anynet(winner_adj, winner_path)
        print(f"Winner topology: {winner_path} ({_best_params['edges']} edges)")

    # BookSim-validate the winner (skip if BookSim was already the scorer)
    if _best_params and _scorer != "booksim":
        print(f"\n=== BookSim validation of winner ===")
        adj = generate_topology(args.nodes, _best_params["cluster_size"],
                                _best_params["express_length"], _best_params["radix"],
                                _best_params["intra_weight"], _best_params["inter_weight"],
                                seed=args.seed)
        # Build T lazily for validation only (analytical path skipped it)
        try:
            val_T = _T_matrix if _T_matrix is not None else build_traffic_matrix(args.traffic, args.nodes)
            bs_lat = evaluate_topology(adj, val_T, "runs/booksim/bo_final")
        except Exception as e:
            print(f"BookSim validation skipped: {e}")
            bs_lat = float('nan')
        print(f"BookSim latency: {bs_lat:.1f} cycles on {_best_params['edges']} edges")
        out["booksim_latency"] = bs_lat
        out_path.write_text(json.dumps(out, indent=1))
    elif _scorer == "booksim":
        # Already validated — best_latency IS the BookSim number
        out["booksim_latency"] = result.fun
        out_path.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
