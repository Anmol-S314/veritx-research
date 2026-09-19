"""veritx_dse.presets — Topology definitions and presets.

Single source of truth for all topology configs. Adding a new topology
means adding one Topology instance here — no other file needs changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Topology:
    """Declarative topology definition.

    Attributes:
        name:       Display name (e.g. "mesh_8x8").
        backend:    BookSim topology type ("mesh", "torus", "flatfly", "gec", "fly", "cmesh", "fattree", "qtree", "tree4", "dragonflynew", "anynet").
        routing:    BookSim routing function name.
        params:     BookSim config overrides (k, n, c, o, d, use_noc_latency, etc.).
        edge_fn:    Callable(extra_params) -> int  — counts edges for this topology.
        needs_noc_latency_zero: If True, sets use_noc_latency=0.
    """
    name: str
    backend: str
    routing: str
    params: dict = field(default_factory=dict)
    edge_fn: Callable[[dict], int] | None = None
    needs_noc_latency_zero: bool = False

    def edges(self, extra: dict | None = None) -> int:
        p = extra or self.params
        if self.edge_fn:
            return self.edge_fn(p)
        return _default_edge_count(self.backend, p)

    def to_dict(self) -> tuple:
        """Legacy tuple format for backward compat: (name, backend, params, routing)."""
        return (self.name, self.backend, dict(self.params), self.routing)


# ── Edge counting helpers ──────────────────────────────────────────────────

def _default_edge_count(backend: str, params: dict) -> int:
    """Compute undirected edge count for standard topologies."""
    if backend == "mesh":
        k = params.get("k", 8)
        n = params.get("n", 2)
        # 2D k×k mesh: 2*k*(k-1) undirected (112 for k=8; per-plane
        # logic consistent with reports.py). General n-dim:
        # n dims × k^(n-1) lines × (k-1) edges per line.
        try:
            return n * (k - 1) * (k ** (n - 1))
        except (TypeError, ValueError, ArithmeticError):
            return 0
    elif backend == "torus":
        k = params.get("k", 8)
        n = params.get("n", 2)
        return n * k ** n  # each dim has k^(n-1)*k edges (wrap), n dims
    elif backend == "flatfly":
        k = params.get("k", 4)
        n_dim = params.get("n", 2)
        c = params.get("c", 4)
        nodes = (k ** n_dim) * c
        r = c + (k - 1) * n_dim
        return nodes // c * (r - c) // 2
    elif backend == "gec":
        # Physical graph per gec.cpp: mesh mode builds ONLY mesh channels
        # (2*k*(k-1) undirected); express (d==1) builds ONLY the full
        # row/column p2p graph (k*k*(k-1) undirected — the old formula added
        # unbuilt mesh edges on top, overcounting by 112 at k=8); MECS keeps
        # the mesh+express proxy (multidrop channels have no p2p equivalent).
        k = params.get("k", 8)
        o = params.get("o", 0)
        d = params.get("d", 1)
        if params.get("mesh"):
            return 2 * k * (k - 1)
        if d == 1 and o >= k - 1:
            return k * k * (k - 1)
        mesh_edges = 2 * k * (k - 1)
        express_edges = o * k * k
        return mesh_edges + express_edges
    elif backend == "fly":
        k = params.get("k", 4)
        n = params.get("n", 3)
        return (n - 1) * k ** n
    elif backend == "cmesh":
        k = params.get("k", 4)
        n = params.get("n", 2)
        return 2 * n * k ** n
    elif backend in ("fattree", "qtree", "tree4"):
        # k-ary n-tree: n levels × k^n links (undirected, approx).
        # NOTE: "fly" (flattened butterfly) is handled above and must NOT
        # appear here — the old ("fly", "fattree", ...) arm was dead for
        # "fly" (matched earlier).
        k = params.get("k", 4)
        n = params.get("n", 3)
        return n * k ** n
    elif backend == "dragonflynew":
        # p=k: a=2p routers/group, g=a*p+1 groups; global + local links.
        p = params.get("k", 2)
        a = 2 * p
        g = a * p + 1
        return g * a * p // 2 + g * a * (2 * p - 1) // 2
    elif backend == "anynet":
        return 0  # counted at runtime from .anynet file
    return 0


# ── Collective spelling + parallelism math (Phase 4d single source) ────
# The same collective is spelled three ways across layers: "allreduce" /
# "alltoall" (DSE presets, compile CollectiveKind values), "all_reduce" /
# "all_to_all" (t3models registry, chakra CLI), "ALL_REDUCE" (chakra ET
# attr path). Normalize at every boundary; canonical = CollectiveKind value.

_COLLECTIVE_CANONICAL = (
    "allreduce", "allgather", "reducescatter", "broadcast", "alltoall",
)


def normalize_collective(name: str) -> str:
    """Map any collective spelling to its canonical CollectiveKind value.

    Accepts any case with optional _, -, or space separators
    ("ALL_REDUCE", "all-reduce", "AllReduce" -> "allreduce"). Raises
    ValueError listing the canonical set for anything unrecognized —
    callers must fail loudly, never guess a collective.
    """
    key = re.sub(r"[\s_\-]+", "", str(name)).lower()
    for canon in _COLLECTIVE_CANONICAL:
        if key == canon:
            return canon
    raise ValueError(
        f"unknown collective {name!r} (canonical: {', '.join(_COLLECTIVE_CANONICAL)})"
    )


def parallel_world_size(tp: int, pp: int = 1, ep: int = 1, dp: int = 1) -> int:
    """Physical device count for 4D parallelism: tp × pp × ep × dp.

    NOTE on the MoE convention question: expert (ep) ranks each hold a
    shard of the MoE layer and collectively span the same device mesh as
    the tp×pp×dp grid in this codebase's accounting (cf. compile
    total_npus = tp×ep for MoE, which ignores pp/dp). This helper reports
    the full product — the conservative upper bound for typo-guard style
    checks. Do NOT substitute it into compile sizing without sim-owner
    review; the sizing path keeps its own rule deliberately.
    """
    return int(tp) * int(pp) * int(ep) * int(dp)


def _parse_anynet_adj(filepath: str) -> dict[int, set[int]]:
    """Parse .anynet into an undirected router adjacency map.

    Delegates to core.anynet — the ONE parser implementing BookSim's
    anynet.cpp grammar (both line dialects, auto-symmetrized edges).
    History: this parser required >=5 tokens and peer-scanning from
    index 4, so two-line link files (configs/anynet16.links style)
    yielded EMPTY adjacency → count 0 / "disconnected".
    """
    from ..core.anynet import AnynetError, parse_anynet_file
    try:
        g = parse_anynet_file(filepath)
    except (OSError, AnynetError):
        # Preserve the historical swallow-on-unreadable contract:
        # callers (count_anynet_edges) report zero rather than crash.
        return {}
    return {r: set(peers) for r, peers in g.router_adj.items()}


def count_anynet_edges(filepath: str) -> tuple[int, int]:
    """Parse .anynet file to count nodes and edges (via core.anynet).

    Returns (num_nodes, num_edges). Unreadable/malformed files yield
    (0, 0) — the synthesis callers treat that as 'unusable candidate'
    rather than crashing.
    """
    from ..core.anynet import AnynetError, count_anynet_edges as _count
    try:
        return _count(filepath)
    except (OSError, AnynetError):
        return 0, 0


def check_anynet_connected(filepath: str) -> tuple[bool, int, int]:
    """BFS connectivity from router 0. Returns (connected, n_nodes, n_unreached).

    Delegates to core.anynet. Missing/unreadable files yield (False, 0, 0)
    — callers report "no routers parsed". BookSim hangs on disconnected
    graphs, so compare and evaluate paths must skip before burning a
    timeout."""
    from ..core.anynet import check_anynet_connected as _check
    return _check(filepath)


def topo_size(topology=None, backend=None, params=None) -> tuple[int, int]:
    """Canonical (nodes, edges) for any topology — single source of truth.

    All other modules must delegate here instead of hand-rolling
    ``k**n`` / edge math.

    Usable from a Topology object OR a backend+params dict::

        topo_size(topo)                      # Topology instance
        topo_size("mesh", {"k": 8, "n": 2})  # backend + params dict
        topo_size(backend="mesh", params={"k": 8, "n": 2})
        topo_size({"backend": "mesh", "k": 8, "n": 2})          # flat dict
        topo_size({"topology": "mesh", "k": 8, "n": 2})         # flat dict
        topo_size({"backend": "mesh", "params": {"k": 8}})      # nested dict

    Returns (num_nodes, num_edges). Unknown backends yield (0, 0);
    anynet with a missing/unreadable file yields (0, 0) via
    :func:`count_anynet_edges`.
    """
    be: str | None = backend
    ps: dict | None = params
    topo_obj: Topology | None = None

    if isinstance(topology, Topology):
        topo_obj = topology
        be = topology.backend
        ps = dict(topology.params)
    elif isinstance(topology, str):
        # topo_size("mesh", {...}) — second positional binds to `backend`.
        be = topology
        if isinstance(backend, dict) and ps is None:
            ps = backend
        elif ps is None:
            ps = {}
    elif isinstance(topology, dict):
        d = topology
        be = d.get("backend", d.get("topology", be))
        nested = d.get("params")
        if isinstance(nested, dict):
            ps = dict(nested)
            # Allow flat keys alongside nested params (flat wins if dup).
            for k, v in d.items():
                if k not in ("backend", "topology", "params", "name", "routing"):
                    ps[k] = v
        else:
            ps = {k: v for k, v in d.items()
                  if k not in ("backend", "topology", "name", "routing")}
            # d itself may already be a pure params dict (e.g. {"k":8}).
            if be is None and ps:
                # No backend key — caller must supply backend=...; else (0,0).
                pass
    # topology is None → use backend=/params= kwargs directly.
    if be is None:
        be = backend
    if ps is None:
        ps = dict(params) if isinstance(params, dict) else {}
    if not isinstance(ps, dict):
        ps = {}
    if be is None:
        return 0, 0

    # Normalise anynet file keys (astrasim_adapter stores "_network_file").
    if be == "anynet":
        nf = ps.get("network_file", ps.get("_network_file", ""))
        if nf:
            return count_anynet_edges(str(nf))
        return 0, 0

    # Node count (mirrors simulation/booksim.topo_size).
    try:
        if be in ("mesh", "torus"):
            nodes = ps.get("k", 8) ** ps.get("n", 2)
        elif be == "flatfly":
            nodes = (ps.get("k", 4) ** ps.get("n", 2)) * ps.get("c", 4)
        elif be == "gec":
            nodes = ps.get("k", 8) ** 2 * ps.get("c", 1)
        elif be == "fly":
            nodes = ps.get("k", 4) ** ps.get("n", 3)
        elif be in ("fattree", "qtree", "tree4"):
            nodes = ps.get("k", 4) ** ps.get("n", 3)
        elif be == "dragonflynew":
            p = ps.get("k", 2)
            a = 2 * p
            nodes = a * p * (a * p + 1)
        elif be == "cmesh":
            nodes = ps.get("c", 4) * ps.get("k", 4) ** ps.get("n", 2)
        else:
            return 0, 0
    except (TypeError, ValueError, ArithmeticError):
        return 0, 0

    # Edge count — respect custom edge_fn on Topology objects.
    try:
        if topo_obj is not None:
            edges = topo_obj.edges()
        else:
            edges = _default_edge_count(be, ps)
    except Exception:
        edges = 0
    return int(nodes), int(edges)


# ── Built-in topologies ────────────────────────────────────────────────────

SWEEP_TOPOS: list[Topology] = [
    Topology("mesh_4x4",  "mesh",    "dim_order",    {"k": 4, "n": 2}),
    Topology("mesh_8x8",  "mesh",    "min_adapt",    {"k": 8, "n": 2}),
    Topology("torus_8x8", "torus",   "dim_order",    {"k": 8, "n": 2}),
    Topology("flatfly_64", "flatfly", "ran_min",      {"k": 4, "n": 2, "c": 4, "x": 4, "y": 4, "xr": 2, "yr": 2}),
    # GEC express: o=7,d=1 → 7 express channels, each to 1 dest
    Topology("gec_express_k8", "gec", "dor", {"k": 8, "c": 1, "o": 7, "d": 1},
             needs_noc_latency_zero=True),
    # GEC MECS: o=1,d=7 → 1 express channel, tapped to 7 dests
    Topology("gec_mecs_k8", "gec", "dor", {"k": 8, "c": 1, "o": 1, "d": 7},
             needs_noc_latency_zero=True),
    # GEC mesh: mesh=1 builds the plain-mesh graph (o/d must be nonzero —
    # BookSim converts o=0/d=0 to full-express defaults, which once made
    # this preset a silent duplicate of gec_express_k8 at identical latency).
    Topology("gec_mesh_k8", "gec", "dor", {"k": 8, "c": 1, "o": 1, "d": 1, "mesh": 1},
             needs_noc_latency_zero=True),
    # Fat-tree (BookSim fly): k-ary n-fly, k=4/n=3 → 64 nodes.
    # Only dest_tag_fly routing is registered for fly.
    # Flattened butterfly (BookSim "fly"): k-ary n-fly, k=4/n=3 → 64 nodes.
    # Only dest_tag_fly routing is registered for fly.
    Topology("fbfly_64", "fly", "dest_tag", {"k": 4, "n": 3}),
    # Concentrated mesh: c=4 nodes/router, k=4/n=2 → 64 nodes.
    # cmesh asserts c==4, n<=2, symmetric x/y (see networks/cmesh.cpp).
    Topology("cmesh_64", "cmesh", "dor",
             {"k": 4, "n": 2, "c": 4, "x": 4, "y": 4, "xr": 2, "yr": 2}),
    # Fat-tree (k-ary n-tree, BookSim "fattree"): k=4/n=3 → 64 nodes.
    # Routings registered: nca (deterministic), anca (adaptive).
    Topology("fattree_k4n3", "fattree", "nca", {"k": 4, "n": 3}),
    # Quad tree / 4-ary tree: both assert k==4/n==3 → 64 nodes.
    Topology("qtree_64", "qtree", "nca", {"k": 4, "n": 3}),
    Topology("tree4_64", "tree4", "nca", {"k": 4, "n": 3}),
    # DragonFly (BookSim "dragonflynew", n must be 1): p=k=2 →
    # a=4 routers/group × g=9 groups × p=2 → 72 nodes (no exact 64).
    # Routings registered: min (minimal), ugal (adaptive).
    Topology("dragonfly_72", "dragonflynew", "min", {"k": 2, "n": 1}),
]

_TOPO_BY_NAME: dict[str, Topology] = {t.name: t for t in SWEEP_TOPOS}
_TOPO_BY_BACKEND: dict[str, list[Topology]] = {}
for _t in SWEEP_TOPOS:
    _TOPO_BY_BACKEND.setdefault(_t.backend, []).append(_t)


def lookup_topo(name: str) -> Topology | None:
    """Look up a topology by name, backend alias, or .anynet file path."""
    # Exact name match
    if name in _TOPO_BY_NAME:
        return _TOPO_BY_NAME[name]
    # Backend alias (e.g. "mesh" → first mesh topology)
    if name in _TOPO_BY_BACKEND:
        return _TOPO_BY_BACKEND[name][0]
    return None


def resolve_fabric(topology_id: str, routing: str | None = None,
                   ) -> tuple[Topology | None, str | None]:
    """One fabric resolver for CLI, API, compiler, serving.

    Returns (Topology, None) or (None, reason). Named presets are
    immutable: routing None (undeclared) or equal to the preset's own
    returns the preset unchanged; anything else is refused, never merged.
    """
    preset = lookup_topo(topology_id)
    if preset is None:
        return None, (
            f"unknown topology id '{topology_id}' — specs reference "
            "registered presets by ID")
    if routing is not None and routing != preset.routing:
        return None, (
            f"topology '{preset.name}' is immutable (routing="
            f"'{preset.routing}'); requested routing '{routing}' "
            "contradicts it — declare a custom fabric instead of "
            "overriding a named preset")
    return preset, None


def make_anynet_topo(filepath: str) -> Topology:
    """Create a Topology from an .anynet file path."""
    p = Path(filepath)
    return Topology(
        name=p.stem,
        backend="anynet",
        routing="min",
        params={"network_file": str(p.resolve())},
    )


# ── Dense presets ──────────────────────────────────────────────────────────

DENSE_PRESETS: dict[str, dict] = {
    "llama70b_ring": {
        "desc": "LLaMA-70B TP=64 ring allreduce",
        "topos": "mesh_8x8,torus_8x8",
        "anynet": ["runs/booksim/grpo_best.anynet", "runs/booksim/mecs64.anynet"],
        "routing_default": "dim_order",
    },
    "llama70b_a2a": {
        "desc": "LLaMA-70B TP=64 all-to-all",
        "topos": "mesh_8x8,torus_8x8",
        "anynet": ["runs/booksim/grpo_best.anynet", "runs/booksim/mecs64.anynet"],
        "routing_default": "dim_order",
    },
    "qwen3_moe": {
        "desc": "Qwen3-30B-A3B MoE 16-rank serving",
        "topos": "mesh_8x8,torus_8x8",
        "anynet": ["runs/booksim/grpo_best.anynet", "runs/booksim/mecs64.anynet"],
        "routing_default": "dor",
    },
}


# ── Built-in workload presets (PRD §5, §16) ──────────────────────────────

WORKLOAD_PRESETS: dict[str, dict] = {
    "qwen3_moe_16npu": {
        "desc": "Qwen3-30B-A3B MoE decode, TP=16 EP=8, 16 NPU",
        "workload": {
            "model_family": "mixture_of_experts",
            "model_name": "Qwen3-30B-A3B",
            "tp": 16, "ep": 8, "dp": 1,
            "serving_mode": "decode_heavy",
            "param_count_b": 30,
            "sequence_length": 4096,
            "precision": "fp8",
            "trace_path": "runs/traces/qwen3_serving_16rank.trace",
            "collectives": [
                {"kind": "alltoall", "group_size": 8},
            ],
        },
        "agents": [
            {"kind": "compute_tile", "count": 16},
            {"kind": "hbm_controller", "count": 4},
        ],
        "requirements": [
            {"qos_class": "latency_critical", "latency_ceiling_cycles": 5000, "binding": True},
        ],
        "dependencies": [
            {"source": "expert_alltoall", "target": "expert_reduce", "kind": "blocking"},
        ],
    },
    "llama70b_tp64": {
        "desc": "LLaMA-70B dense TP=64 ring allreduce",
        "workload": {
            "model_family": "dense_transformer",
            "model_name": "LLaMA-70B",
            "tp": 64, "dp": 1,
            "serving_mode": "mixed",
            "param_count_b": 70,
            "sequence_length": 4096,
            "precision": "fp16",
            "trace_path": "runs/traces/llama70b_tp64_ring.trace",
            "collectives": [
                {"kind": "allreduce", "group_size": 64},
            ],
        },
        "agents": [
            {"kind": "compute_tile", "count": 64},
            {"kind": "hbm_controller", "count": 8},
        ],
        "requirements": [
            {"qos_class": "bandwidth", "bandwidth_floor_gbps": 100, "binding": True},
        ],
        "dependencies": [],
    },
    "llama1b_tp64": {
        "desc": "LLaMA-1B dense TP=64 attention",
        "workload": {
            "model_family": "dense_transformer",
            "model_name": "LLaMA-1B",
            "tp": 64, "dp": 1,
            "serving_mode": "mixed",
            "param_count_b": 1,
            "sequence_length": 2048,
            "precision": "fp16",
            "trace_path": "runs/traces/llama_1b_attention.trace",
        },
        "agents": [
            {"kind": "compute_tile", "count": 64},
            {"kind": "hbm_controller", "count": 4},
        ],
        "requirements": [
            {"qos_class": "latency_critical", "latency_ceiling_cycles": 10000, "binding": False},
        ],
        "dependencies": [],
    },
    "dense_64npu": {
        "desc": "Generic dense 64-NPU mesh",
        "workload": {
            "model_family": "dense_transformer",
            "model_name": "generic_dense",
            "tp": 64, "dp": 1,
            "serving_mode": "mixed",
            "precision": "fp16",
        },
        "agents": [
            {"kind": "compute_tile", "count": 64},
            {"kind": "hbm_controller", "count": 8},
        ],
        "requirements": [],
        "dependencies": [],
    },
    "moe_8npu": {
        "desc": "Generic MoE 8-NPU concentrated mesh",
        "workload": {
            "model_family": "mixture_of_experts",
            "model_name": "generic_moe",
            "tp": 2, "ep": 4, "dp": 1,
            "serving_mode": "decode_heavy",
            "precision": "fp8",
            "collectives": [
                {"kind": "alltoall", "group_size": 4},
            ],
        },
        "agents": [
            {"kind": "compute_tile", "count": 8},
            {"kind": "hbm_controller", "count": 2},
        ],
        "requirements": [
            {"qos_class": "latency_critical", "latency_ceiling_cycles": 2000, "binding": True},
        ],
        "dependencies": [
            {"source": "expert_alltoall", "target": "expert_reduce", "kind": "blocking"},
        ],
    },
    "hpc_wrf128": {
        "desc": "WRF-128 HPC MPI weather simulation, 79K messages",
        "workload": {
            "model_family": "dense_transformer",
            "model_name": "WRF-128",
            "tp": 128, "dp": 1,
            "serving_mode": "mixed",
            "precision": "fp32",
            "trace_path": "runs/traces/hpc_wrf128_ring.trace",
        },
        "agents": [
            {"kind": "compute_tile", "count": 128},
            {"kind": "hbm_controller", "count": 16},
        ],
        "requirements": [
            {"qos_class": "bandwidth", "bandwidth_floor_gbps": 200, "binding": True},
        ],
        "dependencies": [],
    },
    "automotive_adas": {
        "desc": "Automotive ADAS LiDAR + camera fusion, 16 NPU",
        "workload": {
            "model_family": "cnn",
            "model_name": "ADAS-fusion",
            "tp": 16, "dp": 1,
            "serving_mode": "prefill_heavy",
            "precision": "int8",
        },
        "agents": [
            {"kind": "compute_tile", "count": 16},
            {"kind": "nic", "count": 4},
        ],
        "requirements": [
            {"qos_class": "latency_critical", "latency_ceiling_cycles": 500, "binding": True},
        ],
        "dependencies": [
            {"source": "lidar_preprocess", "target": "fusion", "kind": "blocking"},
            {"source": "camera_preprocess", "target": "fusion", "kind": "blocking"},
        ],
    },
    "moe_64npu": {
        "desc": "MoE 64-NPU mesh, TP=16 EP=4 DP=1",
        "workload": {
            "model_family": "mixture_of_experts",
            "model_name": "moe_64n",
            "tp": 16, "ep": 4, "dp": 1,
            "serving_mode": "decode_heavy",
            "precision": "fp8",
            "collectives": [
                {"kind": "alltoall", "group_size": 4},
            ],
        },
        "agents": [
            {"kind": "compute_tile", "count": 64},
            {"kind": "hbm_controller", "count": 8},
        ],
        "requirements": [
            {"qos_class": "latency_critical", "latency_ceiling_cycles": 3000, "binding": True},
        ],
        "dependencies": [
            {"source": "expert_alltoall", "target": "expert_reduce", "kind": "blocking"},
        ],
    },
    "diffusion_64npu": {
        "desc": "Diffusion model 64-NPU image generation",
        "workload": {
            "model_family": "diffusion",
            "model_name": "sdxl-64n",
            "tp": 64, "dp": 1,
            "serving_mode": "prefill_heavy",
            "precision": "fp16",
        },
        "agents": [
            {"kind": "compute_tile", "count": 64},
            {"kind": "hbm_controller", "count": 8},
        ],
        "requirements": [
            {"qos_class": "bandwidth", "bandwidth_floor_gbps": 150, "binding": True},
        ],
        "dependencies": [],
    },
}


def preset_to_compile_request(preset_name: str):
    """Convert a workload preset to a CompileRequest.

    Args:
        preset_name: Key into WORKLOAD_PRESETS.

    Returns:
        CompileRequest instance.

    Raises:
        KeyError: If preset_name not found.
    """
    from .compile_model import (
        CompileRequest, Workload, ModelFamily, ServingMode,
        Agent, AgentKind, Requirement, QoSClass,
        Dependency, DepKind, DependencyGraph, NocConfig, TopologyFamily,
        CollectiveOp,
    )

    p = WORKLOAD_PRESETS[preset_name]

    wl_cfg = p["workload"]
    workload = Workload(
        model_family=ModelFamily(wl_cfg["model_family"]),
        model_name=wl_cfg.get("model_name", ""),
        tp=wl_cfg.get("tp", 1),
        pp=wl_cfg.get("pp", 1),
        ep=wl_cfg.get("ep", 1),
        dp=wl_cfg.get("dp", 1),
        serving_mode=ServingMode(wl_cfg.get("serving_mode", "mixed")),
        param_count_b=wl_cfg.get("param_count_b"),
        sequence_length=wl_cfg.get("sequence_length"),
        precision=wl_cfg.get("precision", "fp16"),
        trace_path=wl_cfg.get("trace_path"),
        collectives=tuple(
            CollectiveOp.from_dict(c) for c in wl_cfg.get("collectives", [])
        ),
    )

    agents = tuple(
        Agent(
            kind=AgentKind(a["kind"]),
            count=a["count"],
            data_width=a.get("data_width", 256),
            addr_width=a.get("addr_width", 64),
            protocol=a.get("protocol", "AXI"),
            clock_domain=a.get("clock_domain"),
            power_domain=a.get("power_domain"),
        )
        for a in p.get("agents", [])
    )

    requirements = tuple(
        Requirement(
            qos_class=QoSClass(r["qos_class"]),
            latency_ceiling_cycles=r.get("latency_ceiling_cycles"),
            bandwidth_floor_gbps=r.get("bandwidth_floor_gbps"),
            binding=r.get("binding", False),
        )
        for r in p.get("requirements", [])
    )

    deps = DependencyGraph([
        Dependency(source=d["source"], target=d["target"],
                   kind=DepKind(d["kind"]))
        for d in p.get("dependencies", [])
    ])

    return CompileRequest(
        workload=workload,
        requirements=requirements,
        agents=agents,
        dependencies=deps,
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )
