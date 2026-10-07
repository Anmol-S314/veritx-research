"""veritx_dse.application.presets — immutable named presets (Wave C).

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

@dataclass(frozen=True)
class Preset:
    """One immutable named fabric preset."""

    name: str
    description: str
    default_trace: str
    endpoint_count: int

def _mesh4_request(*, hbm: bool = False,
                   link_width: int | None = None):
    """Sealed-constructor CompileRequest for the mesh4 family.

Rationale: docs/decisions/modules/application.md
    """
    from veritx_dse.model.compile_model import (
        AddressMap, AddressRange, Agent, AgentKind, CompileRequest,
        DepKind, Dependency, DependencyGraph, ModelFamily, NocConfig,
        TopologyFamily, Workload,
    )
    agents = [Agent(kind=AgentKind.COMPUTE_TILE, count=4, protocol="AXI",
                    data_width=256, addr_width=64)]
    address_map = AddressMap()
    if hbm:
        agents.append(Agent(kind=AgentKind.HBM_CONTROLLER, count=1,
                            addr_width=64))
        address_map = AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),))
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                          tp=1, pp=1, ep=1, dp=1),
        requirements=[],
        agents=agents,
        dependencies=DependencyGraph([
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING)]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH,
                             link_width=link_width),
        address_map=address_map)

def _cmesh_request():
    """16-tile concentrated mesh: 2x2 routers, 4 tiles each.

    The first product preset for a NON-mesh topology: it declares
    CONCENTRATED_MESH explicitly, so ``_product_wired`` sees the family via
    the real generation seam (not a family-name match).
    """
    from veritx_dse.model.compile_model import (
        AddressMap, Agent, AgentKind, CompileRequest, DepKind, Dependency,
        DependencyGraph, ModelFamily, NocConfig, TopologyFamily, Workload,
    )
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                          tp=1, pp=1, ep=1, dp=1),
        requirements=[],
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=16, protocol="AXI",
                      data_width=256, addr_width=64),),
        dependencies=DependencyGraph([
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING)]),
        noc_config=NocConfig(
            topology_family=TopologyFamily.CONCENTRATED_MESH,
            radix=2, concentration=4),
        address_map=AddressMap())

def _typed_workload(tp: int, *, payload_bytes: int = 8192):
    """Carrier workload for a typed-topology preset: ONE TP allreduce."""
    from veritx_dse.model.compile_model import (
        CollectiveDimension, CollectiveIntent, CollectiveKind, ModelFamily,
        ServingMode, WorkloadV3,
    )
    return WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp,
        serving_mode=ServingMode.MIXED,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE,
            dimension=CollectiveDimension.TP,
            payload_bytes=payload_bytes, traffic_class="tp_collective"),))

def _typed_request(topology, *, endpoints: int, tp: int,
                   payload_bytes: int = 8192):
    """A v4 request declaring a TYPED topology intent.

    These presets are v4-native because the families they expose (flatfly,
    gec modes) have no v2 `TopologyFamily` spelling. The v2 mesh4 family is
    left v2: its identity is load-bearing for the guided compile path.
    """
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    return CompileRequestV4(
        workload=_typed_workload(tp, payload_bytes=payload_bytes),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=endpoints,
                      protocol="AXI", data_width=256, addr_width=64),),
        topology=topology,
        noc_controls=NocControls())

def _flatfly16_request():
    from veritx_dse.model.topology_intent import FlatFlyIntent
    return _typed_request(
        FlatFlyIntent(radix_per_dimension=4, dimension_count=2,
                      concentration=1), endpoints=16, tp=16)

def _fattree16_request():
    from veritx_dse.model.topology_intent import FatTreeIntent
    return _typed_request(
        FatTreeIntent(switch_radix=4, level_count=2), endpoints=16, tp=16)

def _gec_mecs16_request():
    """GEC multidrop (MECS): o*d == k-1 with d > 1, so the wires are SHARED.

    k=4, o=1, d=3: one express wire per dimension, three taps per wire, one
    VC per tap. Payload must divide by the tile count; 16*128 is exact.
    """
    from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
    return _typed_request(
        GecTopologyIntent(
            mode=GecMode.MULTIDROP, grid_side_length=4, concentration=1,
            express_channel_groups_per_dimension=1,
            destinations_per_express_channel=3),
        endpoints=16, tp=16, payload_bytes=16 * 128)


def _gec_express16_request():
    from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
    return _typed_request(
        GecTopologyIntent(
            mode=GecMode.EXPRESS, grid_side_length=4, concentration=1,
            express_channel_groups_per_dimension=3,
            destinations_per_express_channel=1), endpoints=16, tp=16)

def _gec_mesh64_request():
    from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
    return _typed_request(
        GecTopologyIntent(mode=GecMode.MESH, grid_side_length=8,
                          concentration=1), endpoints=64, tp=64)

def _srota32_request():
    """SROTA Plane D: 4x4 concentrators, 2 tiles each, row-first only.

    Payload must divide by the tile count; 8192 / 32 is exact.
    """
    from veritx_dse.model.srota_intent import SrotaIntent
    return _typed_request(
        SrotaIntent(side_length=4, concentration=2, mecs_row=True,
                    mecs_col=True, drop_latency=1,
                    planes=frozenset({"d", "t"}), island_columns=(),
                    path_shapes=frozenset({"row"}), vc_policy="none",
                    sidebuf_enable=True, sidebuf_watermark=6, tel_period=4,
                    tel_latency=8),
        endpoints=32, tp=32)


def _torus25_request():
    """An odd-side product torus with declared X/Y ordering dependencies.

    The two VCs are derived from blocking X<->Y dependencies. Odd side length
    avoids BookSim's randomized midpoint ties, so route-dump determinism holds.
    """
    from veritx_dse.model.compile_model import (
        DepKind, Dependency, DependencyGraph,
    )
    from veritx_dse.model.topology_intent import TorusIntent
    request = _typed_request(TorusIntent(side_length=5),
                             endpoints=25, tp=25, payload_bytes=8000)
    return replace(request, dependencies=DependencyGraph((
        Dependency("X", "Y", DepKind.BLOCKING),
        Dependency("Y", "X", DepKind.BLOCKING),
    )))

def _structured_request(family: str, params: dict, *, endpoints: int, tp: int):
    """A v4 request declaring a STRUCTURED topology intent.

    The families below have no v2 `TopologyFamily` spelling; their identity
    is the (family, params) pair, and endpoints seat exactly the graph the
    family builds. See capability_truth._probe_endpoints for the sizing law.
    """
    from veritx_dse.model.topology_intent import StructuredTopologyIntent
    return _typed_request(
        StructuredTopologyIntent(family=family, params=dict(params)),
        endpoints=endpoints, tp=tp)


def _dragonfly4_request():
    return _structured_request(
        "dragonfly", {"radix": 2, "group_count": 2},
        endpoints=4, tp=4)


def _fat_tree4_request():
    return _structured_request(
        "fat_tree", {"radix": 2, "tiers": 2},
        endpoints=4, tp=4)


def _flattened_butterfly16_request():
    return _structured_request(
        "flattened_butterfly", {"radix": 4, "dimensions": 2},
        endpoints=16, tp=16)


def _qtree7_request():
    return _structured_request(
        "qtree", {"radix": 2, "tiers": 2},
        endpoints=7, tp=7)


def _tree4_7_request():
    return _structured_request(
        "tree4", {"radix": 2, "tiers": 2},
        endpoints=7, tp=7)


def _explicit16_request():
    """A CUSTOM topology declared as an explicit graph (16-node 4x4 mesh).

    Uniform link latency + route_weight 1 keep it inside the AnyNet
    profile's representable set (weighted shortest path == min-hop).
    """
    from veritx_dse.model import topology_ir as tir
    from veritx_dse.model.topology_intent import ExplicitTopologyIntent
    k = 4
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                links.append([n, n + 1])
            if y + 1 < k:
                links.append([n, n + k])
    graph = tir.from_dict({
        "name": "explicit16", "kind": "custom", "nodes": k * k,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })
    return _typed_request(ExplicitTopologyIntent(graph=graph),
                          endpoints=k * k, tp=k * k)

TYPED_PRESET_BUILDERS = {
    "flatfly16": _flatfly16_request,
    "fattree16": _fattree16_request,
    "gec_express16": _gec_express16_request,
    "gec_mecs16": _gec_mecs16_request,
    "gec_mesh64": _gec_mesh64_request,
    "srota32": _srota32_request,
    "torus25": _torus25_request,
    "explicit16": _explicit16_request,
    "dragonfly4": _dragonfly4_request,
    "fat_tree4": _fat_tree4_request,
    "flattened_butterfly16": _flattened_butterfly16_request,
    "qtree7": _qtree7_request,
    "tree4_7": _tree4_7_request,
}

def typed_preset_names() -> tuple[str, ...]:
    return tuple(TYPED_PRESET_BUILDERS)

_TYPED_PRESET_DESCRIPTIONS = {
    "dragonfly4": "4-tile dragonfly (radix 2 x 2 groups)",
    "fat_tree4": "4-tile fat tree (radix 2 x 2 tiers)",
    "flattened_butterfly16": "16-tile flattened butterfly (radix 4 x 2 dimensions)",
    "qtree7": "7-tile qtree (radix 2 x 2 tiers)",
    "tree4_7": "7-tile tree4 (radix 2 x 2 tiers)",
    "flatfly16": "16-tile flatfly (radix 4 x 2 dimensions)",
    "fattree16": "16-tile fat tree (switch radix 4 x 2 tiers)",
    "gec_express16": "16-tile GEC express mesh (AnyNet profile)",
    "gec_mecs16": "16-tile GEC multidrop MECS (one shared wire per dimension, 3 taps, 3 VCs)",
    "gec_mesh64": "64-tile GEC nearest-neighbor mesh (canonical mesh profile)",
    "srota32": "32-tile SROTA Plane D (4x4 concentrators, row-first, MECS)",
    "torus25": "25-tile 5x5 torus (odd-side 2-VC dateline DOR profile)",
    "explicit16": "16-node custom explicit graph (AnyNet profile)",
}

def preset_catalog() -> tuple[dict[str, Any], ...]:
    """Every shipped product preset: the v2 mesh4 family (guided-path
    identity) plus the v4-native typed-topology presets."""
    out: list[dict[str, Any]] = []
    for name, (desc, _trace, _endpoints, _builder) in _PRESET_BUILDERS.items():
        out.append({"preset_id": name, "name": name,
                    "description": desc, "generation": "v2"})
    for name in typed_preset_names():
        out.append({"preset_id": name, "name": name,
                    "description": _TYPED_PRESET_DESCRIPTIONS[name],
                    "generation": "v4"})
    return tuple(out)

def build_typed_preset_request(name: str):
    """Fresh canonical v4 CompileRequest for a typed-topology preset."""
    try:
        builder = TYPED_PRESET_BUILDERS[name]
    except KeyError:
        raise KeyError(
            f"unknown typed preset {name!r} "
            f"(known: {list(typed_preset_names())})") from None
    return builder()

_PRESET_BUILDERS = {
    "mesh4": (
        "4-tile mesh fabric (multi-class default derivation)",
        "tiny2", 4, lambda: _mesh4_request()),
    "mesh4_hbm": (
        "4-tile mesh with one HBM controller and address map",
        "tiny2x5", 5, lambda: _mesh4_request(hbm=True)),
    "mesh4_wide128": (
        "4-tile mesh with 128-bit links",
        "tiny2", 4, lambda: _mesh4_request(link_width=128)),
    "cmesh16": (
        "16-tile concentrated mesh (2x2 routers, 4 tiles each)",
        "tiny2", 16, lambda: _cmesh_request()),
}

FABRIC_PRESETS: tuple[Preset, ...] = tuple(
    Preset(name=name, description=desc, default_trace=trace,
                 endpoint_count=endpoints)
    for name, (desc, trace, endpoints, _) in _PRESET_BUILDERS.items())

def preset_names() -> tuple[str, ...]:
    return tuple(p.name for p in FABRIC_PRESETS)

def get_preset(name: str) -> Preset:
    for preset in FABRIC_PRESETS:
        if preset.name == name:
            return preset
    raise KeyError(
        f"unknown fabric preset {name!r} (known: {list(preset_names())})")

def build_preset_request(name: str):
    """A FRESH CompileRequest for the preset (never a shared object)."""
    try:
        _, _, _, builder = _PRESET_BUILDERS[name]
    except KeyError:
        raise KeyError(
            f"unknown fabric preset {name!r} "
            f"(known: {list(preset_names())})") from None
    return builder()

def _apply_dotted(target: dict[str, Any], path: str, value: Any) -> None:
    """Set an existing leaf via dotted path (strict: no new paths)."""
    if value is not None and not isinstance(value, (int, float, str, bool)):
        raise TypeError(
            f"override {path!r} must be a JSON scalar, got "
            f"{type(value).__name__}")
    node: Any = target
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(
                f"override path {path!r} does not exist in the preset "
                f"request")
        node = node[part]
    leaf = parts[-1]
    if not isinstance(node, dict) or leaf not in node:
        raise KeyError(
            f"override path {path!r} does not exist in the preset request")
    current = node[leaf]
    if current is not None and not isinstance(value, type(current)):
        raise TypeError(
            f"override {path!r} changes type "
            f"{type(current).__name__} -> {type(value).__name__}; "
            f"refusing")
    node[leaf] = value

def derive_request(name: str,
                   overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Preset request dict + strict overrides (preset source untouched).

    Returns a NEW canonical request dict; the registry builder is
    re-invoked every call so repeated derivation can never observe a
    previous override. Unknown dotted paths and type changes refuse.
    """
    request = build_preset_request(name).to_dict()
    for path, value in dict(overrides or {}).items():
        _apply_dotted(request, path, value)
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    return request

TRACE_REGISTRY: dict[str, bytes] = {
    "tiny2": b"0 0 0 3 2\n10 3 0 0 2\n",
    "tiny2x5": b"0 0 0 4 2\n10 4 0 0 2\n",
}

def trace_names() -> tuple[str, ...]:
    return tuple(TRACE_REGISTRY)

def resolve_trace_bytes(ref: str) -> bytes:
    try:
        return TRACE_REGISTRY[ref]
    except KeyError:
        raise KeyError(
            f"unknown trace {ref!r} (known: {list(trace_names())}; "
            f"external traces use trace_file)") from None

METRIC_SCHEMA_VERSION = "booksim-parse/v2"

@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    unit: str
    definition: str
    aggregation: str

METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "sim.latency.avg_cycles", "cycles",
        "BookSim 'Packet latency average' — the STOCK qtime/ctime-based "
        "_plat_stats mean. NOT the same population as "
        "sim.trace_request_latency.*; do not read the two as one "
        "distribution.",
        "mean"),
    MetricDefinition(
        "sim.latency.max_cycles", "cycles",
        "BookSim '\\tmaximum' following 'Packet latency average' — stock "
        "qtime/ctime _plat_stats max.",
        "max"),
    MetricDefinition(
        "sim.trace_request_latency.avg_cycles", "cycles",
        "VeritX fork 'honest_avg' = arrival time minus the ORIGINAL trace "
        "request timestamp (_all_latencies). Same population as the "
        "percentiles below.",
        "mean"),
    MetricDefinition(
        "sim.trace_request_latency.p50_cycles", "cycles",
        "VeritX fork p50 of _all_latencies (request time).",
        "percentile-50"),
    MetricDefinition(
        "sim.trace_request_latency.p95_cycles", "cycles",
        "VeritX fork p95 of _all_latencies (request time).",
        "percentile-95"),
    MetricDefinition(
        "sim.trace_request_latency.p99_cycles", "cycles",
        "VeritX fork p99 of _all_latencies (request time).",
        "percentile-99"),
    MetricDefinition(
        "sim.trace_request_latency.samples", "packets",
        "Size of the request-latency vector (_all_latencies) — the sample "
        "count the request-time percentiles are computed over.",
        "count"),
    MetricDefinition("sim.hops.avg", "hops",
                     "BookSim average hops line", "mean"),
    MetricDefinition("sim.throughput.rate", "packets/cycle",
                     "BookSim accepted packet rate average line", "mean"),
    MetricDefinition("sim.delivered.packets", "packets",
                     "BookSim 'Trace replay complete: delivered N packets'",
                     "count"),
    MetricDefinition("sim.completion_time.cycles", "cycles",
                     "BookSim completion/time-taken cycles line", "total"),
    MetricDefinition("sim.flits.injected", "flits",
                     "BookSim flits injected counter", "count"),
    MetricDefinition("sim.flits.accepted", "flits",
                     "BookSim flits accepted counter", "count"),
)

STATS_TO_METRIC = {
    "latency": "sim.latency.avg_cycles",
    "max_packet_latency": "sim.latency.max_cycles",
    "honest_latency": "sim.trace_request_latency.avg_cycles",
    "p50": "sim.trace_request_latency.p50_cycles",
    "p95": "sim.trace_request_latency.p95_cycles",
    "p99": "sim.trace_request_latency.p99_cycles",
    "pkt_count": "sim.trace_request_latency.samples",
    "hops": "sim.hops.avg",
    "throughput": "sim.throughput.rate",
    "delivered": "sim.delivered.packets",
    "completion_time": "sim.completion_time.cycles",
    "flits_injected": "sim.flits.injected",
    "flits_accepted": "sim.flits.accepted",
}

LATENCY_POPULATIONS = {
    "booksim_qtime": ("sim.latency.avg_cycles", "sim.latency.max_cycles"),
    "trace_request": (
        "sim.trace_request_latency.avg_cycles",
        "sim.trace_request_latency.p50_cycles",
        "sim.trace_request_latency.p95_cycles",
        "sim.trace_request_latency.p99_cycles",
        "sim.trace_request_latency.samples",
    ),
}

def metric_ids() -> tuple[str, ...]:
    return tuple(d.metric_id for d in METRIC_DEFINITIONS)

def get_metric_definition(metric_id: str) -> MetricDefinition:
    for definition in METRIC_DEFINITIONS:
        if definition.metric_id == metric_id:
            return definition
    raise KeyError(
        f"unknown metric {metric_id!r} (known: {list(metric_ids())})")

__all__ = [
    "FABRIC_PRESETS",
    "LATENCY_POPULATIONS",
    "METRIC_DEFINITIONS",
    "METRIC_SCHEMA_VERSION",
    "STATS_TO_METRIC",
    "TRACE_REGISTRY",
    "Preset",
    "MetricDefinition",
    "build_preset_request",
    "derive_request",
    "get_metric_definition",
    "get_preset",
    "metric_ids",
    "preset_names",
    "resolve_trace_bytes",
    "trace_names",
]
