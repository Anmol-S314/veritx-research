"""veritx_dse.application.presets — immutable named presets (Wave C).

Two registries, both immutable by construction:

* fabric presets: NAME -> CompileRequest builder. Builders construct
  FRESH sealed model objects on every call, so no caller can mutate a
  shared preset. ``derive_request(name, overrides)`` deep-copies through
  the canonical dict form and applies strict dotted-path overrides
  (unknown paths and type changes refuse).
* workload traces: NAME -> exact trace bytes.
* metric definitions: the smallest honest schema — only metrics the
  BookSim stdout parser genuinely produces, versioned with it.

Only presets reachable through the sealed CompileRequest derivation
live here. Artifact-level test variants that bypass CompileRequest
(single-class / escape VC overrides) are NOT presets; overriding them
would invent semantics Wave C does not own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── fabric presets ────────────────────────────────────────────────────

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

    These are FABRIC presets: a 4-tile mesh carrying a minimal synthetic
    trace (``tiny2`` / ``tiny2x5``). The declared workload is the carrier
    that lets the canonical CompileRequest exist; it is not a model
    workload, and ``tp=ep=dp=1`` means it exercises no parallelism
    structure at all.

    ``model_family`` is therefore DENSE_TRANSFORMER, not MOE. It was MOE
    historically as a placeholder, which made the preset declare a
    workload family its advertised envelope excludes: GUIDED-EXPERT.md
    §preset audit certifies ``mesh4`` under
    ``CAP-ENV-BOOKSIM-MESH-DOR-XY-V1``, whose COND-DENSE-STATIC-WORKLOAD
    requires ``dense_transformer``. A preset must not advertise an
    envelope whose own conditions it fails.

    The correction is identity-only and proven inert for the fabric: for
    ``tp=1, ep=1`` ``Workload.total_npus`` is 1 either way, the traffic is
    trace-driven rather than collective-driven, and every derived artifact
    hash (topology, attachment, mapping, route, resolved route, VC
    assignment, fabric) is byte-identical. Only ``design_hash`` and its
    ``resolved_fabric_hash`` child move, exactly as they did for the
    semantics-v1 -> v2 identity move.
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
    # Overrides invalidate the embedded identity: from_dict recomputes it
    # (a stale design_hash must never survive derivation).
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    return request


# ── workload trace registry ───────────────────────────────────────────

TRACE_REGISTRY: dict[str, bytes] = {
    # 4-endpoint minimal pair (matches the Wave-B golden traces).
    "tiny2": b"0 0 0 3 2\n10 3 0 0 2\n",
    # 5-endpoint minimal pair (HBM preset universe).
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


# ── metric schema (booksim-parse/v2) ─────────────────────────────────
#
# TWO LATENCY POPULATIONS. BookSim's stats block emits both, and they are
# NOT statistics of one distribution — verified in the fork source
# (third_party/booksim2/src/trafficmanager.cpp):
#
#   Packet latency average / \tmaximum        <- _plat_stats[c]      (qtime)
#   p50 / p95 / p99 / honest_avg / pkt_count  <- _all_latencies[c]   (request)
#
#   _plat_stats[c]->AddSample(f->atime - head->ctime)     <- qtime slots,
#       which go STALE across idle gaps and inflate sparse-trace means 100x+
#   _all_latencies[c].push_back(f->atime - <original trace request ts>)
#       <- REQUEST time, the same vector the percentiles are sorted from
#
# v1 put the qtime mean and the request-time percentiles in one
# `sim.latency.*` family, so a consumer could read them as one distribution.
# v2 splits them. `sim.latency.avg_cycles` is RETAINED for backward
# compatibility but its definition now states exactly which population it is.
METRIC_SCHEMA_VERSION = "booksim-parse/v2"


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    unit: str
    definition: str
    aggregation: str


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    # ── stock BookSim qtime/ctime population (_plat_stats) ────────────
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
    # ── VeritX request-time population (_all_latencies) ──────────────
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
    # ── non-latency ──────────────────────────────────────────────────
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

# Evidence stats key -> metric id (only genuinely produced metrics).
#
# The mapping is what ENFORCES the split: a qtime mean can never be filed
# under a request-time id, because each key has exactly one destination.
STATS_TO_METRIC = {
    # stock qtime population
    "latency": "sim.latency.avg_cycles",
    "max_packet_latency": "sim.latency.max_cycles",
    # request-time population
    "honest_latency": "sim.trace_request_latency.avg_cycles",
    "p50": "sim.trace_request_latency.p50_cycles",
    "p95": "sim.trace_request_latency.p95_cycles",
    "p99": "sim.trace_request_latency.p99_cycles",
    "pkt_count": "sim.trace_request_latency.samples",
    # non-latency
    "hops": "sim.hops.avg",
    "throughput": "sim.throughput.rate",
    "delivered": "sim.delivered.packets",
    "completion_time": "sim.completion_time.cycles",
    "flits_injected": "sim.flits.injected",
    "flits_accepted": "sim.flits.accepted",
}

#: Latency metric ids grouped by the statistical population they belong to.
#: A consumer that wants "the latency" must choose a population; there is no
#: single ambiguous family to fall back on.
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
