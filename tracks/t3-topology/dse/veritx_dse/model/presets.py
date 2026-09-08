"""veritx_dse.presets — Topology definitions and presets.

Single source of truth for all topology configs. Adding a new topology
means adding one Topology instance here — no other file needs changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Topology:
    """Declarative topology definition.

    Attributes:
        name:       Display name (e.g. "mesh_8x8").
        backend:    BookSim topology type ("mesh", "torus", "flatfly", "gec", "anynet").
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
    if backend in ("mesh", "torus"):
        k = params.get("k", 8)
        n = params.get("n", 2)
        return n * k ** n  # each dim has k^(n-1)*(k-1) edges, n dims
    elif backend == "flatfly":
        k = params.get("k", 4)
        n_dim = params.get("n", 2)
        c = params.get("c", 4)
        nodes = (k ** n_dim) * c
        r = c + (k - 1) * n_dim
        return nodes // c * (r - c) // 2
    elif backend == "gec":
        k = params.get("k", 8)
        o = params.get("o", 0)
        mesh_edges = 2 * k * (k - 1)
        express_edges = o * k * k
        return mesh_edges + express_edges
    elif backend == "anynet":
        return 0  # counted at runtime from .anynet file
    return 0


def count_anynet_edges(filepath: str) -> tuple[int, int]:
    """Parse .anynet file to count nodes and edges.

    Format: 'router <id> node <nid> router <peer1> router <peer2> ...'
    Returns (num_nodes, num_edges).
    """
    nodes: set[int] = set()
    edges: set[tuple[int, int]] = set()
    try:
        with open(filepath) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 5 or parts[0] != "router":
                    continue
                rid = int(parts[1])
                nodes.add(rid)
                i = 4
                while i < len(parts):
                    if parts[i] == "router" and i + 1 < len(parts):
                        peer_id = int(parts[i + 1])
                        nodes.add(peer_id)
                        edge = (min(rid, peer_id), max(rid, peer_id))
                        edges.add(edge)
                        i += 2
                    else:
                        i += 1
    except Exception:
        pass
    return len(nodes), len(edges)


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
    # GEC mesh: o=0 → no express channels (degrades to plain mesh)
    Topology("gec_mesh_k8", "gec", "dor", {"k": 8, "c": 1, "o": 0, "d": 0},
             needs_noc_latency_zero=True),
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
