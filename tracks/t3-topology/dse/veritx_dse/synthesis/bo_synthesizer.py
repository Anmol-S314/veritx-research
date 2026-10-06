"""bo_synthesizer.py — Bayesian Optimization topology synthesis.

Rationale: docs/decisions/modules/synthesis.md
"""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from skopt import Optimizer
from skopt.space import Categorical, Real
from skopt.utils import use_named_args

from veritx_dse.synthesis.traffic import (
    SynthesisTrafficError, SynthesisTrafficMatrix,
)

_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO / "tracks/t3-topology/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    from collectives import ring_allreduce_pairs
except ImportError:
    def ring_allreduce_pairs(participants, size_bytes):
        n = len(participants)
        if n <= 1: return []
        chunk = size_bytes / n
        return [(participants[i], participants[(i+1)%n], chunk) for i in range(n)]

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

    adj = {i: set() for i in range(n)}
    for i in range(n):
        x, y = xy[i]
        for dx, dy in [(1, 0), (0, 1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < k and 0 <= ny < k:
                j = ny * k + nx
                adj[i].add(j)
                adj[j].add(i)

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

    reps = [c * cluster_size for c in range(n_clusters)]
    for i in reps:
        for j in reps:
            if i < j and j not in adj[i]:
                d = abs(xy[i][0] - xy[j][0]) + abs(xy[i][1] - xy[j][1])
                if d <= express_length * 2 and rng.random() < inter_weight:
                    adj[i].add(j)
                    adj[j].add(i)

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

def _rows_from_trace_text(text, n_nodes):
    """Parse a .trace ("cyc src cl dst sz") into byte-demand rows."""
    rows = [[0.0] * n_nodes for _ in range(n_nodes)]
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        src, dst, size = int(parts[1]), int(parts[3]), int(parts[4])
        if not (0 <= src < n_nodes and 0 <= dst < n_nodes):
            raise SynthesisTrafficError(
                f"trace record {src}->{dst} is outside the matrix "
                f"namespace 0..{n_nodes - 1}")
        if src != dst:
            rows[src][dst] += float(size)
        n += 1
    if n == 0:
        raise SynthesisTrafficError(
            "no trace records parsed (expected 'cyc src cl dst sz' lines)")
    return rows

def _as_array(matrix):
    return np.array([list(r) for r in matrix.values], dtype=float)

def build_traffic_matrix(events_path, n_nodes):
    """Build a CANONICAL traffic matrix from a trace or traffic model.

    Fail-closed: a missing, malformed, or demand-less source refuses
    (SynthesisTrafficError). There is deliberately NO uniform fallback — a
    synthesizer run on invented demand would fabricate a result. Accepts a
    ``SynthesisTrafficMatrix`` directly (the canonical projection from a
    logical-message artifact via ``from_message_artifact``), a ``.trace``
    file, or a traffic-model JSON document.
    """
    if isinstance(events_path, SynthesisTrafficMatrix):
        return _as_array(events_path)
    p = Path(events_path)
    if not p.is_file():
        raise SynthesisTrafficError(f"traffic source not found: {p}")
    source_id = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None

    rows = None
    if isinstance(doc, dict) and "meta" in doc \
            and "num_tiles" in doc.get("meta", {}):
        clusters = n_nodes // doc["meta"]["num_tiles"]
        n_intra = doc["meta"]["num_tiles"]
        rows = [[0.0] * n_nodes for _ in range(n_nodes)]
        for c in doc["collectives"]:
            for rep in range(clusters):
                off = rep * n_intra
                for src, dst, b in ring_allreduce_pairs(
                        [off + x for x in c["participants"]],
                        c["size_bytes"]):
                    rows[src][dst] += b
    elif isinstance(doc, dict) and "network" in doc \
            and "flow_classes" in doc["network"]:
        rows = [[0.0] * n_nodes for _ in range(n_nodes)]
        for fc in doc["network"]["flow_classes"]:
            for inst in fc.get("instances", [])[:1]:
                parts = inst.get("participants", [])[:4]
                if len(parts) >= 2:
                    for s, d, b in ring_allreduce_pairs(
                            parts, fc.get("bytes_per_invocation", 8192)):
                        if s < n_nodes and d < n_nodes:
                            rows[s][d] += b
    if rows is None:
        rows = _rows_from_trace_text(text, n_nodes)

    matrix = SynthesisTrafficMatrix.from_rows(
        rows, source_artifact_id=source_id, namespace="rank", unit="bytes",
        aggregation="sum_over_workload")
    return _as_array(matrix)

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

class EvaluationFailed(Exception):
    """A BookSim evaluation that produced no latency figure.

    Carries the reason: disconnected candidate, binary failure, timeout,
    or output with no parseable latency. Callers must record the reason
    and exclude the candidate — never substitute a numeric fallback.
    A failed candidate must never participate as a numerical objective.
    """


def evaluate_topology(adj, T, workdir):
    """Run BookSim on topology + traffic; return the measured latency.

    Raises EvaluationFailed when no latency figure exists. There is
    deliberately no numeric fallback: 1000.0 and 1e9 look like plausible
    latencies to an optimizer, so returning them would silently promote
    the worst candidates.

    Reuses a single work directory (overwrites files each eval).
    """
    n = len(adj)
    edge_count = sum(len(v) for v in adj.values()) // 2

    if edge_count < n - 1 or not _is_connected(adj):
        raise EvaluationFailed(
            f"disconnected candidate: {edge_count} edges over {n} nodes")

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    anynet_path = workdir / "topo.anynet"
    edge_list_to_anynet(adj, anynet_path)

    global _trace_path
    if _trace_path and Path(_trace_path).exists():
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

    import subprocess
    from veritx_dse.core.paths import BOOKSIM_BIN
    booksim = str(BOOKSIM_BIN)
    try:
        r = subprocess.run(
            [booksim, str(cfg_path.resolve())],
            capture_output=True, text=True, timeout=60, cwd=str(workdir.resolve())
        )
    except subprocess.TimeoutExpired as exc:
        raise EvaluationFailed(
            f"booksim timed out after 60s in {workdir}: {exc}") from exc
    except OSError as exc:
        raise EvaluationFailed(
            f"booksim failed to launch ({booksim}): {exc}") from exc
    if r.returncode != 0:
        raise EvaluationFailed(
            f"booksim exit {r.returncode} in {workdir}: "
            f"{(r.stderr or '')[-2000:] or '(no stderr)'}")
    import re
    matches = re.findall(r"Packet latency average\s*=\s*([0-9.]+)", r.stdout)
    if not matches:
        raise EvaluationFailed(
            f"no 'Packet latency average' in booksim output in {workdir} "
            f"({len(r.stdout)} bytes stdout)")
    return float(matches[-1])

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
        wb = Path(_booksim_workdir)
        wb.mkdir(parents=True, exist_ok=True)
        _booksim_workdir_counter += 1
        eval_dir = wb / f"iter_{_booksim_workdir_counter:04d}"
        lat = evaluate_topology(adj, _T_matrix, str(eval_dir))
        edge_count = len(adj_to_edge_list(adj))
    else:
        from veritx_dse.synthesis.event_objective import score_topology
        obj, _det = score_topology(adj, _xy, _events)
        lat = obj / 1e9

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

_n_nodes = 64
_T_matrix = None
_events = None
_xy = None
_scorer = "analytical"
_booksim_workdir = None

def load_study_events(traffic_path):
    """Load the analytical scorer's event model, refusing invented demand.

    Raises SynthesisTrafficError when the source is missing, unreadable,
    not an events model, or carries no collectives. A study on invented
    demand would fabricate a result: missing traffic is a refusal (exit 2
    from main), never an invented allreduce with a fixed byte count.
    """
    try:
        with open(traffic_path) as handle:
            events = json.load(handle)
    except OSError as exc:
        raise SynthesisTrafficError(
            f"traffic source not found or unreadable: {traffic_path}: "
            f"{exc}") from exc
    except ValueError as exc:
        raise SynthesisTrafficError(
            f"traffic source is not an events model: {traffic_path}: "
            f"{exc}") from exc
    if not isinstance(events, dict) or not events.get("collectives"):
        raise SynthesisTrafficError(
            f"traffic source carries no collectives: {traffic_path} — "
            "supply an events model with demand, not a bare trace")
    return events

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
    if _scorer == "booksim":
        _T_matrix = build_traffic_matrix(args.traffic, args.nodes) if _trace_path is None else None
    else:
        _T_matrix = None
    _booksim_workdir = f"runs/booksim/bo_{_scorer}_N{args.nodes}"
    import shutil
    bwdir = Path(_booksim_workdir)
    if bwdir.exists():
        shutil.rmtree(bwdir, ignore_errors=True)
    try:
        _events = load_study_events(args.traffic)
    except SynthesisTrafficError as exc:
        print(f"BO synthesis refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
    _k = int(math.isqrt(args.nodes))
    _xy = [(x, y) for y in range(_k) for x in range(_k)]

    scorer_label = "BookSim S1 cycle-accurate" if _scorer == "booksim" else "analytical Dijkstra (fast)"
    gb_str = f"{_T_matrix.sum()/1e9:.2f} GB" if _T_matrix is not None else "structural (no T)"
    print(f"=== BO Topology Synthesis ({_scorer} scorer) ===")
    print(f"Nodes: {args.nodes}, Traffic: {gb_str}")
    print(f"Iterations: {args.iters}, Scorer: {scorer_label}")
    print()

    # Ask-and-tell: a failed candidate is recorded with its reason and never
    # told to the surrogate, so failures cannot steer the search and never
    # appear as numeric objectives. gp_minimize cannot express this — every
    # value it is given becomes training data — so the loop is explicit.
    param_names = [d.name for d in search_space]
    opt = Optimizer(search_space, random_state=args.seed)
    succeeded: list = []
    failed: list = []
    n_calls = max(args.iters, 10)
    t0 = time.time()
    for _ in range(n_calls):
        x = opt.ask()
        try:
            lat = objective(x)
        except EvaluationFailed as exc:
            params = {
                name: (int(v) if isinstance(v, (int, np.integer)) else float(v))
                for name, v in zip(param_names, x)
            }
            failed.append({
                "params": params,
                "status": "EVALUATION_FAILED",
                "reason": str(exc),
            })
            print(f"  FAILED: {params} — {exc}")
            continue
        opt.tell(x, lat)
        succeeded.append((x, lat))
    elapsed = time.time() - t0

    print(f"\n=== Results ===")
    if _best_params:
        print(f"Best latency: {_best_lat:.1f} cycles")
    else:
        print("No candidate evaluated successfully.")
    print(f"Best params: {_best_params}")
    print(f"Total time: {elapsed:.1f}s ({elapsed/args.iters:.1f}s/eval)")
    print(f"Successful evals: {len(succeeded)}, failed: {len(failed)}")

    out = {
        "best_latency": _best_lat if _best_params else None,
        "best_params": _best_params,
        "all_evals": [
            {"params": dict(zip(
                ["cluster_size", "express_length", "radix", "intra_weight", "inter_weight"],
                [int(x) if isinstance(x, (int, np.integer)) else float(x) for x in xi]
            )), "latency": float(fi)}
            for xi, fi in succeeded
        ],
        "failed_evals": failed,
        "elapsed": elapsed,
    }
    out_path = Path(f"runs/booksim/bo_results_N{args.nodes}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))
    print(f"Results saved to {out_path}")
    if not _best_params:
        print("BO synthesis failed: every candidate failed evaluation "
              "(see failed_evals with reasons). No winner is declared.",
              file=sys.stderr)
        raise SystemExit(1)

    if _best_params:
        winner_adj = generate_topology(args.nodes, _best_params["cluster_size"],
                                        _best_params["express_length"], _best_params["radix"],
                                        _best_params["intra_weight"], _best_params["inter_weight"],
                                        seed=args.seed)
        winner_path = Path("runs/booksim/topo.anynet")
        winner_path.parent.mkdir(parents=True, exist_ok=True)
        edge_list_to_anynet(winner_adj, winner_path)
        print(f"Winner topology: {winner_path} ({_best_params['edges']} edges)")

    if _best_params and _scorer != "booksim":
        print(f"\n=== BookSim validation of winner ===")
        adj = generate_topology(args.nodes, _best_params["cluster_size"],
                                _best_params["express_length"], _best_params["radix"],
                                _best_params["intra_weight"], _best_params["inter_weight"],
                                seed=args.seed)
        try:
            val_T = _T_matrix if _T_matrix is not None else build_traffic_matrix(args.traffic, args.nodes)
            bs_lat = evaluate_topology(adj, val_T, "runs/booksim/bo_final")
        except EvaluationFailed as e:
            print(f"BookSim validation failed: {e}")
            out["booksim_latency"] = None
            out["booksim_validation_error"] = str(e)
            out_path.write_text(json.dumps(out, indent=1))
        else:
            print(f"BookSim latency: {bs_lat:.1f} cycles on {_best_params['edges']} edges")
            out["booksim_latency"] = bs_lat
            out_path.write_text(json.dumps(out, indent=1))
    elif _scorer == "booksim":
        out["booksim_latency"] = _best_lat
        out_path.write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
