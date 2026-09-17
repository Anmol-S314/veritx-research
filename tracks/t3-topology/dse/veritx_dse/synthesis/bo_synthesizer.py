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
# Ensure the DSE package (veritx_dse) is importable in script mode.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from collectives import ring_allreduce_pairs
except ImportError:
    # fallback stub if collectives.py not found
    def ring_allreduce_pairs(participants, size_bytes):
        n = len(participants)
        if n <= 1: return []
        chunk = size_bytes / n
        return [(participants[i], participants[(i+1)%n], chunk) for i in range(n)]

# Canonical topology sizes — single source of truth in
# veritx_dse.model.presets. All backend (mesh/grid/anynet) size math
# delegates here instead of hand-rolled k**n counting.
try:
    from veritx_dse.model.presets import topo_size, count_anynet_edges
except ImportError:
    try:
        from ..model.presets import topo_size, count_anynet_edges  # type: ignore
    except Exception:
        topo_size = None  # type: ignore
        count_anynet_edges = None  # type: ignore

# Canonical synth output dir — single source of truth in
# veritx_dse.core.paths. Module-global (not function-local) so tests can
# monkeypatch it for isolation; script-mode fallback is the same value.
try:
    from veritx_dse.core.paths import SYNTH_DIR as _SYNTH_DIR
except Exception:
    _SYNTH_DIR = None  # type: ignore
try:
    from veritx_dse.core.constants import BOOKSIM_SEED, DEFAULT_TIMEOUT, env_int
    from veritx_dse.core.constants import DEFAULT_NODES
except Exception:
    BOOKSIM_SEED = 42  # type: ignore  # same value; canonical home is core.constants
    DEFAULT_TIMEOUT = 60  # type: ignore
    DEFAULT_NODES = 64  # type: ignore
    def env_int(name, default):  # type: ignore
        import os
        raw = os.environ.get(name)
        if raw is None:
            return default
        return int(raw)  # fail fast like core.constants.env_int

# Unified synthesis evaluation machinery (Phase 2a). Script-mode safe:
# package import first, sibling fallback for `python3 bo_synthesizer.py`.
try:
    from veritx_dse.synthesis.evaluator import (
        BO_PRESET,
        evaluate_adj,
        is_connected as _shared_is_connected,
        write_anynet as _shared_write_anynet,
    )
    from veritx_dse.synthesis.results import SynthResult
except Exception:
    try:
        from evaluator import (  # type: ignore
            BO_PRESET,
            evaluate_adj,
            is_connected as _shared_is_connected,
            write_anynet as _shared_write_anynet,
        )
        from results import SynthResult  # type: ignore
    except Exception:
        BO_PRESET = None  # type: ignore
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
    k = int(math.isqrt(num_nodes))
    assert k * k == num_nodes, f"n={num_nodes} must be a perfect square"
    return mesh_size(k, 2)


def anynet_size(path) -> tuple:
    """Thin wrapper over the canonical anynet counter."""
    if count_anynet_edges is not None:
        return count_anynet_edges(str(path))
    return 0, 0


def _canonical_runs():
    """Absolute runs/booksim dir anchored at the track root.

    Outputs used to be runs/... relative to the CWD, so the winner +
    results + validation workdirs scattered across dse/runs, runs, and
    wherever else the synthesizer was invoked from. Anchor once: every
    invocation lands in the one dir the t3 pickers scan.
    NOTE: _REPO above is the track root (t3-topology/), not the repo root.
    """
    if _SYNTH_DIR is not None:
        d = _SYNTH_DIR
    else:
        d = _REPO / "runs" / "booksim"
    d.mkdir(parents=True, exist_ok=True)
    return d

# ── Topology generation from parameters ────────────────────────────────

def grid_xy(n):
    """Place n nodes on a sqrt(n) × sqrt(n) grid."""
    k = int(math.isqrt(n))
    assert k * k == n, f"n={n} must be a perfect square"
    return [(x, y) for y in range(k) for x in range(k)]


def generate_topology(n, cluster_size, express_length, radix,
                      intra_weight, inter_weight, seed=BOOKSIM_SEED):
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
    """Write BookSim .anynet format.

    Thin wrapper over the shared evaluator writer (Phase 2a); kept for
    backward compat (tests import it). Bit-identical output.
    """
    if _shared_write_anynet is not None:
        _shared_write_anynet(adj, path)
        return
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
    except Exception as e:
        print(f"warning: build_traffic_matrix: not JSON ({type(e).__name__}: {e}) — "
              f"parsing {events_path} as .trace", file=sys.stderr)
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
        except Exception as e2:
            print(f"warning: build_traffic_matrix: trace parse failed for {p}: "
                  f"{type(e2).__name__}: {e2} — falling back to uniform", file=sys.stderr)
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
    """BFS connectivity check.

    Thin wrapper over the shared evaluator check (Phase 2a); kept for
    backward compat (tests import it). Functionally identical.
    """
    if _shared_is_connected is not None:
        return _shared_is_connected(adj)
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


def evaluate_topology(adj, T, workdir, timeout=None):
    """Run BookSim on topology + traffic, return latency (or 1000.0 on failure).

    Reuses a single work directory (overwrites files each eval).
    Supports trace mode (legit Qwen 95K) and matrix mode (synthetic).

    Phase 2a: delegates to the shared evaluator with BO_PRESET
    (pareto-converged measurement: span-derived sample_period, max_samples=5,
    warmup 1, honest-first first-match; throughput sim_type kept).
    Returns the same float sentinels the GP loop relies on (1e9 disconnect,
    1000.0 runtime); canonical status/error conversion happens at the
    bo_results_N.json record boundary in main().

    timeout=None resolves VERITX_TIMEOUT (default 60s) at call time.
    """
    # Shared path (preserves numbers + workdir reuse + log prefixes).
    if evaluate_adj is not None and BO_PRESET is not None:
        if timeout is None:
            timeout = env_int("VERITX_TIMEOUT", DEFAULT_TIMEOUT)
        global _trace_path
        use_trace = bool(_trace_path) and Path(_trace_path).exists()
        try:
            if use_trace:
                res = evaluate_adj(
                    adj, trace_path=_trace_path, workdir=workdir,
                    seed=BOOKSIM_SEED, timeout=timeout, config=BO_PRESET,
                    name=f"bo_N{len(adj)}",
                )
            else:
                res = evaluate_adj(
                    adj, traffic_matrix=T, workdir=workdir,
                    seed=BOOKSIM_SEED, timeout=timeout, config=BO_PRESET,
                    name=f"bo_N{len(adj)}",
                )
        except Exception as e:
            # Matrix-normalization TypeError path (T=None) propagated like
            # the original outside-try code: re-raise unchanged.
            raise
        if res.status == "ok":
            return float(res.latency)
        kind = (res.extra or {}).get("failure_kind", "")
        if kind == "disconnected":
            return 1e9  # silent fast-fail, like the original
        if kind == "timeout":
            print(f"warning: evaluate_topology: BookSim timed out in {workdir}: {res.error} — scoring 1000.0",
                  file=sys.stderr)
            return 1000.0
        if kind == "no_latency":
            rc = (res.extra or {}).get("returncode", "?")
            print(f"warning: evaluate_topology: no latency in BookSim output for {workdir} "
                  f"(exit {rc}) — scoring 1000.0", file=sys.stderr)
            return 1000.0
        print(f"warning: evaluate_topology: BookSim run failed in {workdir} "
              f"({res.error}) — scoring 1000.0", file=sys.stderr)
        return 1000.0
    # No inline fallback: the pre-2a duplicated BookSim path lived here and
    # encoded pre-convergence numbers (sample 200/max 3/plat-last). The
    # shared evaluator (imported above, sibling fallback for script mode)
    # is the ONE evaluation path — a second one would silently diverge
    # again. Fail loudly if it is somehow unavailable.
    raise ImportError(
        "bo_synthesizer.evaluate_topology requires "
        "veritx_dse.synthesis.evaluator (or sibling evaluator.py for "
        "`python3 bo_synthesizer.py`); refusing to run a divergent fallback."
    )


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
        from veritx_dse.synthesis.event_objective import score_topology
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
_trace_path = None   # set by main(); evaluate_topology must not NameError when called directly


def main():
    global _n_nodes, _T_matrix, _events, _xy

    ap = argparse.ArgumentParser()
    # Absolute default (Phase 4 follow-up): the old relative default landed
    # wherever the caller ran from; _REPO is the track root either way.
    ap.add_argument("--traffic", default=str(_REPO / "runs" / "traces" / "test1_events.json"))
    ap.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--seed", type=int, default=BOOKSIM_SEED)
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
    _booksim_workdir = str(_canonical_runs() / f"bo_{_scorer}_N{args.nodes}")
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
    except Exception as e:
        print(f"warning: bo_synthesizer: traffic is not events JSON ({type(e).__name__}: {e}) — "
              f"building stub collectives from trace", file=sys.stderr)
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
            except Exception as e2:
                print(f"warning: bo_synthesizer: trace stub parse failed for {args.traffic}: "
                      f"{type(e2).__name__}: {e2} — using default collective", file=sys.stderr)
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
    if args.iters < 1:
        parser.error("--iters must be >= 1")
    result = gp_minimize(
        objective,
        search_space,
        n_calls=args.iters,
        # skopt requires n_calls >= n_random_starts; scale the random phase down
        # instead of silently inflating the user's budget.
        n_random_starts=min(10, args.iters),
        random_state=args.seed,
        verbose=False,
    )
    elapsed = time.time() - t0

    print(f"\n=== Results ===")
    print(f"Best latency: {result.fun:.1f} cycles")
    print(f"Best params: {_best_params}")
    _n_evals = len(result.func_vals)
    print(f"Total time: {elapsed:.1f}s ({elapsed/_n_evals:.1f}s/eval)")
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
    # Phase 2a record boundary: convert the winner float sentinel to a
    # canonical SynthResult (ADDITIVE — existing keys untouched). The inner
    # GP loop keeps floats; only this JSON carries status/error.
    try:
        if SynthResult is not None and _best_params is not None:
            _w_lat = float(result.fun)
            import math as _math
            # BO sentinels are exactly 1e9 (disconnect) / 1000.0 (runtime);
            # a real BookSim latency coinciding bit-exactly is negligible.
            _w_sentinel = (_w_lat == 1e9 or _w_lat == 1000.0)
            _w_ok = _math.isfinite(_w_lat) and _w_lat < 1e8 and not _w_sentinel
            _w_prov = ("bo_synthesizer+BO_PRESET" if _scorer == "booksim"
                       else "bo_synthesizer+analytical")
            if _w_ok:
                _w_res = SynthResult.ok(
                    name=f"bo_N{args.nodes}_winner", topology="anynet",
                    nodes=int(args.nodes), edges=int(_best_params.get("edges", 0)),
                    latency=_w_lat, seed=int(args.seed), provenance=_w_prov,
                    extra={"scorer": _scorer, "best_params": dict(_best_params)},
                )
            else:
                _w_res = SynthResult.fail(
                    name=f"bo_N{args.nodes}_winner", topology="anynet",
                    nodes=int(args.nodes), edges=int(_best_params.get("edges", 0)),
                    error=f"best_latency sentinel {_w_lat}", seed=int(args.seed),
                    provenance=_w_prov,
                    extra={"scorer": _scorer, "best_params": dict(_best_params)},
                )
            out["synth_result"] = _w_res.to_dict()
    except Exception:
        pass
    out_path = _canonical_runs() / f"bo_results_N{args.nodes}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))
    print(f"Results saved to {out_path}")

    # Write winner topology to stable path for pipeline cert
    if _best_params:
        winner_adj = generate_topology(args.nodes, _best_params["cluster_size"],
                                        _best_params["express_length"], _best_params["radix"],
                                        _best_params["intra_weight"], _best_params["inter_weight"],
                                        seed=args.seed)
        winner_path = _canonical_runs() / "topo.anynet"
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
            bs_lat = evaluate_topology(adj, val_T, str(_canonical_runs() / "bo_final"))
        except Exception as e:
            print(f"BookSim validation skipped: {e}")
            bs_lat = float('nan')
        print(f"BookSim latency: {bs_lat:.1f} cycles on {_best_params['edges']} edges")
        out["booksim_latency"] = bs_lat
        # Phase 2a: canonical record for the validation run (additive).
        try:
            if SynthResult is not None:
                import math as _math2
                _v_sentinel = (bs_lat == 1e9 or bs_lat == 1000.0)
                _v_ok = isinstance(bs_lat, float) and _math2.isfinite(bs_lat) and bs_lat < 1e8 and not _v_sentinel
                if _v_ok:
                    _v_res = SynthResult.ok(
                        name=f"bo_N{args.nodes}_validation", topology="anynet",
                        nodes=int(args.nodes), edges=int(_best_params.get("edges", 0)),
                        latency=float(bs_lat), seed=int(args.seed),
                        provenance="bo_synthesizer+BO_PRESET",
                        extra={"scorer": "booksim-validation"},
                    )
                else:
                    _v_res = SynthResult.fail(
                        name=f"bo_N{args.nodes}_validation", topology="anynet",
                        nodes=int(args.nodes), edges=int(_best_params.get("edges", 0)),
                        error=f"validation sentinel {bs_lat}", seed=int(args.seed),
                        provenance="bo_synthesizer+BO_PRESET",
                        extra={"scorer": "booksim-validation"},
                    )
                out["booksim_synth_result"] = _v_res.to_dict()
        except Exception:
            pass
        out_path.write_text(json.dumps(out, indent=1))
    elif _scorer == "booksim":
        # Already validated — best_latency IS the BookSim number
        out["booksim_latency"] = result.fun
        out_path.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
