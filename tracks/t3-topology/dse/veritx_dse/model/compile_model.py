"""veritx_dse.compile_model — Srota Engine compile data model (E1–E5).

Implements the PRD §11.1 data model with guardrails enforced by type
system (§11.2). LOCKED parameters have no field in NocConfig — the
override is inexpressible, not merely refused.

Design principles (from PRD §3):
  - Derive, don't ask: VC count derived from dependency graph
  - Guardrails visible: Tier enum with badge strings
  - Type-system enforcement: frozen dataclasses, absent LOCKED fields

Architecture:
  CompileRequest (E1–E5 unified)
  ├── Workload (E1): model family, parallelism, trace binding
  ├── Requirements (E2): per-class latency/BW bounds
  ├── Agents (E3): typed nodes with attributes
  ├── DependencyGraph (E4): blocking/ordering → VC derivation
  └── NocConfig (E5): GUIDED + FREE fields only (no LOCKED)
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from veritx_dse.core.constants import PLANE_C_MAX_VC, env_int


# Product design-intent format. Versioned INDEPENDENTLY of the experiment
# spec (core.spec) and of every other persisted format — same user
# request under different compiler semantics is a different design.
COMPILE_REQUEST_SCHEMA_VERSION = 2
# Compiler-semantics version — how design intent maps to identity.
#   v1 (legacy) — dependency edge order is identity-bearing.
#   v2 (current) — graph processing is deterministic, so dependency edge
#                  order is NON-semantic: the same edge set always yields
#                  the same design_hash.
# v1 documents remain loadable and are never reinterpreted under v2; use
# migrate_design() / `migrate-design --to-semantics 2` to re-emit them.
COMPILER_SEMANTICS_VERSION = 2
LEGACY_COMPILER_SEMANTICS_VERSIONS = (1,)
SUPPORTED_COMPILER_SEMANTICS_VERSIONS = (1, 2)

# Hash-domain tag: a CompileRequest identity can never collide with an
# experiment, execution fingerprint, or artifact hash by construction.
_HASH_TYPE_TAG = "srota/CompileRequest"


class CompileRequestSchemaError(ValueError):
    """Rejected CompileRequest document: unknown field, unsupported
    schema, or a value that cannot represent a design."""


# Allowed keys per level. Unknown keys FAIL CLOSED: a typo must never
# silently vanish (which would let two different intents hash equal).
_TOP_KEYS = frozenset({
    "schema_version", "compiler_semantics_version", "workload",
    "requirements", "agents", "dependencies", "noc_config", "address_map",
    "physical", "design_hash", "guardrail_hash",
    # Root documentation metadata: non-semantic, explicitly allowlisted.
    "_comment", "_docs",
})
_WORKLOAD_KEYS = frozenset({
    "model_family", "model_name", "tp", "pp", "ep", "dp", "param_count_b",
    "sequence_length", "batch_size", "precision", "serving_mode",
    "collectives", "trace_path",
})
_COLLECTIVE_KEYS = frozenset({"kind", "group_size", "bytes_per_element"})
_REQUIREMENT_KEYS = frozenset({
    "qos_class", "latency_ceiling_cycles", "bandwidth_floor_gbps", "binding",
})
_AGENT_KEYS = frozenset({
    "kind", "count", "data_width", "addr_width", "protocol",
    "clock_domain", "power_domain",
})
_DEPENDENCY_KEYS = frozenset({"source", "target", "kind"})
_NOC_KEYS = frozenset({
    "topology_family", "radix", "concentration", "arbitration",
    "rcu_enabled", "link_width", "output_formats", "obfuscation_level",
    "mcast_groups", "mcast_setup_cycles",
})
_ADDRESS_MAP_KEYS = frozenset({"ranges"})
_ADDRESS_RANGE_KEYS = frozenset({
    "name", "base", "size", "target_agent_idx",
})
_PHYSICAL_KEYS = frozenset({
    "clock_freq_mhz", "data_width", "num_power_domains", "process_node_nm",
})


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _strict_keys(d: Any, allowed: frozenset, where: str) -> None:
    """Reject unknown keys at a boundary (``extra="forbid"`` semantics)."""
    if not isinstance(d, dict):
        raise CompileRequestSchemaError(f"{where} must be a JSON object")
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise CompileRequestSchemaError(f"unknown field {where}.{unknown[0]}")


def _need(d: dict, key: str, where: str) -> Any:
    if key not in d:
        raise CompileRequestSchemaError(
            f"missing required field {where}.{key}")
    return d[key]


def _enum(cls_: Any, value: Any, where: str) -> Any:
    try:
        return cls_(value)
    except (ValueError, TypeError) as e:
        raise CompileRequestSchemaError(f"invalid {where}: {value!r}") from e


# Strict primitive typing (Wave B1.1). `bool` is an `int` subclass in
# Python, so `type(x) is int` is the only reliable integer check; and an
# int/float distinction in the canonical JSON would otherwise let
# `1000` and `1000.0` hash differently for one semantic value.
def _as_int(name: str, value: Any, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(
            f"{name} must be an int, got {type(value).__name__} {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_real(name: str, value: Any, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a real number, got {type(value).__name__} "
            f"{value!r}")
    v = float(value)  # canonical: int and float forms share one identity
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if v == 0.0:
        v = 0.0  # -0.0 and 0.0 are the same bound, one identity
    if minimum is not None and v < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")
    return v


def _as_tuple(name: str, value: Any) -> tuple:
    """JSON-facing list or in-memory tuple only; snapshot to a tuple.

    Any other container (deque, set, dict, generator, str) is refused:
    the design-intent graph must store actual immutable tuples, never a
    caller-owned mutable iterable.
    """
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, tuple):
        return value
    raise ValueError(
        f"{name} must be a list or tuple, got {type(value).__name__}")


def _as_enum(name: str, value: Any, cls: Any) -> Any:
    if not isinstance(value, cls):
        raise ValueError(
            f"{name} must be {cls.__name__}, got {type(value).__name__} "
            f"{value!r}")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError(
            f"{name} must be a bool, got {type(value).__name__} {value!r}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise ValueError(f"{name} must be non-empty")
    return value


# ══════════════════════════════════════════════════════════════════════════════
# §11.2 — Tier System
# ══════════════════════════════════════════════════════════════════════════════

class Tier(Enum):
    """Parameter tier: who owns the decision.

    LOCKED: Compiler derives. No override, no expert mode.
    GUIDED: User proposes; optimizer may adjust.
    FREE: User's call, no second-guessing.
    """
    LOCKED = "locked"
    GUIDED = "guided"
    FREE = "free"

    def __gt__(self, other):
        if not isinstance(other, Tier):
            return NotImplemented
        order = {Tier.LOCKED: 3, Tier.GUIDED: 2, Tier.FREE: 1}
        return order[self] > order[other]

    @property
    def badge(self) -> str:
        return {
            Tier.LOCKED: "🔒 LOCKED",
            Tier.GUIDED: "🔧 GUIDED",
            Tier.FREE: "🆓 FREE",
        }[self]


# ══════════════════════════════════════════════════════════════════════════════
# §4.1–4.2 — Agent Model (E3)
# ══════════════════════════════════════════════════════════════════════════════

class AgentKind(Enum):
    """PRD §4.1: Typed agent kinds."""
    COMPUTE_TILE = "compute_tile"
    HBM_CONTROLLER = "hbm_controller"
    NIC = "nic"
    PERIPHERAL = "peripheral"
    UCIE_PORT = "ucie_port"


@dataclass(frozen=True)
class Agent:
    """PRD §4.1–4.2: An agent is a typed node with required attributes.

    Attributes:
        kind: Agent kind (compute_tile, hbm_controller, nic, etc.)
        count: Number of instances of this agent kind.
        data_width: Payload width at agent interface (bits). Default 256.
        addr_width: Address width the agent drives/decodes (bits). Default 64.
        protocol: Interface protocol (AXI, CHI, custom streaming). Default AXI.
    """
    kind: AgentKind
    count: int
    data_width: int = 256
    addr_width: int = 64
    protocol: str = "AXI"
    clock_domain: str | None = None  # PRD §4.2
    power_domain: str | None = None  # PRD §4.2

    def __post_init__(self):
        _as_enum("kind", self.kind, AgentKind)
        _as_int("count", self.count, minimum=1)
        _as_int("data_width", self.data_width, minimum=8)
        _as_int("addr_width", self.addr_width, minimum=8)
        _as_str("protocol", self.protocol, allow_empty=False)
        if self.clock_domain is not None:
            _as_str("clock_domain", self.clock_domain, allow_empty=False)
        if self.power_domain is not None:
            _as_str("power_domain", self.power_domain, allow_empty=False)


# ══════════════════════════════════════════════════════════════════════════════
# §5 — Workload (E1)
# ══════════════════════════════════════════════════════════════════════════════

class ModelFamily(Enum):
    """PRD §5.1 Level A: Model family."""
    DENSE_TRANSFORMER = "dense_transformer"
    MOE = "mixture_of_experts"
    DIFFUSION = "diffusion"
    CNN = "cnn"
    CUSTOM = "custom"


class ServingMode(Enum):
    """PRD §5.1 Level A: Serving mode."""
    PREFILL_HEAVY = "prefill_heavy"
    DECODE_HEAVY = "decode_heavy"
    MIXED = "mixed"


class CollectiveKind(Enum):
    """PRD §5.2 Level B: Collective operation kinds."""
    ALLREDUCE = "allreduce"
    ALLGATHER = "allgather"
    REDUCESCATTER = "reducescatter"
    BROADCAST = "broadcast"
    ALLTOALL = "alltoall"


@dataclass(frozen=True)
class CollectiveOp:
    """PRD §5.2: A collective communication operation."""
    kind: CollectiveKind
    group_size: int = 1
    bytes_per_element: int = 2048

    def __post_init__(self):
        _as_enum("kind", self.kind, CollectiveKind)
        _as_int("group_size", self.group_size, minimum=1)
        _as_int("bytes_per_element", self.bytes_per_element, minimum=1)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (JSON-safe)."""
        return {
            "kind": self.kind.value,
            "group_size": self.group_size,
            "bytes_per_element": self.bytes_per_element,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CollectiveOp:
        """Deserialize from dict. Unknown kind raises ValueError."""
        return cls(
            kind=CollectiveKind(d["kind"]),
            group_size=d.get("group_size", 1),
            bytes_per_element=d.get("bytes_per_element", 2048),
        )


@dataclass(frozen=True)
class Workload:
    """PRD E1: Workload description — models, phases, parallelism, trace binding.

    Covers Level A (model & serving) and optionally Level B (phases via trace).
    
    SOURCE OF TRUTH RULES:
    - tp/pp/ep/dp describe the MODEL configuration (Level A)
    - trace_path describes the ACTUAL TRAFFIC (Level C)
    - If both are present, trace_path is the ground truth for simulation
    - tp/pp/ep/dp are used for topology sizing and VC derivation
    - The two are consistent: trace was generated from this model config
    """
    model_family: ModelFamily
    model_name: str = ""
    # Parallelism (PRD §5.1)
    tp: int = 1       # tensor parallelism
    pp: int = 1       # pipeline parallelism
    ep: int = 1       # expert parallelism
    dp: int = 1       # data parallelism
    # Shape (PRD §5.1 Level A)
    param_count_b: float | None = None   # parameter count in billions
    sequence_length: int | None = None
    batch_size: int = 1
    precision: str = "fp16"  # fp16, fp8, int8, bf16
    # Serving (PRD §5.1)
    serving_mode: ServingMode = ServingMode.MIXED
    # Collectives (PRD §5.2 Level B)
    collectives: tuple[CollectiveOp, ...] = ()
    # Trace binding (our extension — bridges to existing trace files)
    trace_path: str | None = None

    def __post_init__(self):
        _as_enum("model_family", self.model_family, ModelFamily)
        _as_enum("serving_mode", self.serving_mode, ServingMode)
        # Normalize caller-supplied sequences to tuples: the frozen object
        # must never retain a mutable/odd container the caller can edit.
        object.__setattr__(self, "collectives",
                           _as_tuple("collectives", self.collectives))
        for c in self.collectives:
            if not isinstance(c, CollectiveOp):
                raise ValueError(
                    f"collectives must contain CollectiveOp, got {type(c).__name__}")
        for field_name in ("tp", "pp", "ep", "dp"):
            _as_int(field_name, getattr(self, field_name), minimum=1)
        _as_int("batch_size", self.batch_size, minimum=1)
        if self.sequence_length is not None:
            _as_int("sequence_length", self.sequence_length, minimum=1)
        if self.param_count_b is not None:
            object.__setattr__(
                self, "param_count_b",
                _as_real("param_count_b", self.param_count_b, minimum=0.0))
            if self.param_count_b <= 0:
                raise ValueError(
                    f"param_count_b must be > 0, got {self.param_count_b!r}")
        _as_str("model_name", self.model_name)
        _as_str("precision", self.precision, allow_empty=False)
        if self.trace_path is not None:
            _as_str("trace_path", self.trace_path)
            p = Path(self.trace_path)
            if p.exists() and p.is_dir():
                raise ValueError(f"trace_path is a directory, not a file: {self.trace_path}")

    @property
    def world_size(self) -> int:
        """Physical device count: tp × pp × ep × dp (full 4D parallelism)."""
        from .presets import parallel_world_size
        return parallel_world_size(self.tp, self.pp, self.ep, self.dp)

    @property
    def total_npus(self) -> int:
        """Deprecated alias for ``world_size`` (was tp×ep for MoE,tp for dense).

        The old formula silently dropped pp and dp. Kept one wave for
        compatibility; use ``world_size`` or ``NodeInventory.rank_count``.
        """
        return self.world_size


# ══════════════════════════════════════════════════════════════════════════════
# §5.3 / E2 — Requirements
# ══════════════════════════════════════════════════════════════════════════════

class QoSClass(Enum):
    """PRD §5.3 Level C: QoS class for traffic."""
    LATENCY_CRITICAL = "latency_critical"
    BANDWIDTH = "bandwidth"
    BEST_EFFORT = "best_effort"


@dataclass(frozen=True)
class Requirement:
    """PRD E2: Per-class latency/BW bound with binding flag."""
    qos_class: QoSClass
    latency_ceiling_cycles: float | None = None
    bandwidth_floor_gbps: float | None = None
    binding: bool = False  # if True, must be met or design fails

    def __post_init__(self):
        _as_enum("qos_class", self.qos_class, QoSClass)
        _as_bool("binding", self.binding)
        for name, val in (("latency_ceiling_cycles", self.latency_ceiling_cycles),
                          ("bandwidth_floor_gbps", self.bandwidth_floor_gbps)):
            if val is None:
                continue
            object.__setattr__(self, name,
                               _as_real(name, val, minimum=0.0))


# ══════════════════════════════════════════════════════════════════════════════
# §11.3 / E4 — Dependency Graph + VC Derivation
# ══════════════════════════════════════════════════════════════════════════════

class DepKind(Enum):
    """PRD E4: Dependency type."""
    BLOCKING = "blocking"    # target cannot start until source completes
    ORDERING = "ordering"    # target must follow source's ordering
    INDEPENDENT = "independent"  # no constraint


@dataclass(frozen=True)
class Dependency:
    """PRD E4: A directed dependency between two traffic classes."""
    source: str
    target: str
    kind: DepKind

    def __post_init__(self):
        _as_str("source", self.source, allow_empty=False)
        _as_str("target", self.target, allow_empty=False)
        _as_enum("kind", self.kind, DepKind)


# NOTE: PLANE_C_MAX_VC lives in core.constants (env-overridable via
# VERITX_MAX_VC) and is imported above — do not redefine it here.


@dataclass(frozen=True)
class DependencyGraph:
    """PRD E4: Blocking/ordering graph that drives VC derivation.

    The graph is a directed graph over traffic class names.
    Cycles in the BLOCKING subgraph indicate potential deadlock
    that requires VC separation to resolve.

    Frozen with a tuple: the graph is part of design identity, so it
    must not be mutable after construction.

    TEMPORARY B1 RULING: edge order is identity-bearing only because the
    current compiler observes it (adjacency insertion order feeds DFS).
    MANDATORY B3 FIX: make graph processing deterministic, then make
    dependency edge ordering non-semantic and bump the semantics version.
    """
    dependencies: tuple[Dependency, ...]

    def __post_init__(self):
        object.__setattr__(self, "dependencies",
                           _as_tuple("dependencies", self.dependencies))
        for d in self.dependencies:
            if not isinstance(d, Dependency):
                raise ValueError(
                    f"dependencies must contain Dependency, got "
                    f"{type(d).__name__}")

    def _blocking_edges(self) -> list[tuple[str, str]]:
        """Return only BLOCKING edges (the ones that can form deadlock cycles)."""
        return [(d.source, d.target) for d in self.dependencies
                if d.kind == DepKind.BLOCKING]

    def _adjacency(self) -> dict[str, list[str]]:
        """Build adjacency from blocking edges, canonically ordered.

        Neighbors are sorted so traversal is independent of the declared
        dependency order (Wave B3.0-pre: graph processing deterministic).
        """
        adj: dict[str, list[str]] = {}
        for src, dst in self._blocking_edges():
            adj.setdefault(src, []).append(dst)
        for neighbors in adj.values():
            neighbors.sort()
        return adj

    def find_cycles(self) -> list[list[str]]:
        """Find all cycles in the BLOCKING subgraph using DFS.

        Returns list of cycles, where each cycle is a list of node names.
        """
        adj = self._adjacency()
        all_nodes = set(adj.keys())
        for targets in adj.values():
            all_nodes.update(targets)

        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: list[list[str]] = []

        def _dfs(node: str, path: list[str]):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    _dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Found cycle — extract it
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
            path.pop()
            rec_stack.discard(node)

        for node in sorted(all_nodes):
            if node not in visited:
                _dfs(node, [])

        return cycles

    def has_cycles(self) -> bool:
        """Check if the BLOCKING subgraph has any cycles."""
        return len(self.find_cycles()) > 0


def derive_vc_count(graph: DependencyGraph) -> int:
    """PRD §11.3: Derive VC count from dependency graph.

    Algorithm:
      1. Find all cycles in the BLOCKING subgraph.
      2. Each cycle needs >= 1 member on a distinct VC to break it.
      3. Choose the member whose separation costs least buffering.
      4. VC count = 1 + number of independent cycles needing separation.

    If vc_count > PLANE_C_MAX_VC, the design is infeasible.

    Args:
        graph: DependencyGraph with blocking/ordering edges.

    Returns:
        Minimum VC count needed for deadlock-freedom.
    """
    cycles = graph.find_cycles()

    if not cycles:
        return 1  # no separation needed

    # Count independent cycles (simplified: each cycle needs its own VC)
    # In production, this would use cycle overlap analysis to share VCs
    # between cycles that can be broken by separating the same node.
    independent_cycles = len(cycles)

    # Each independent cycle needs one VC separation → VC count = 1 + cycles
    # (VC 0 is the default; each separation adds one more VC)
    vc_count = 1 + independent_cycles

    # Cap at fabric maximum
    return min(vc_count, PLANE_C_MAX_VC)


# ══════════════════════════════════════════════════════════════════════════════
# §4.4 / E5 — NocConfig (GUIDED + FREE only, no LOCKED fields)
# ══════════════════════════════════════════════════════════════════════════════

class TopologyFamily(Enum):
    """PRD §4.4: GUIDED topology family knob."""
    MESH = "mesh"
    TORUS = "torus"
    CONCENTRATED_MESH = "concentrated_mesh"
    GEC = "gec"
    FAT_TREE = "fat_tree"


class OutputFormat(Enum):
    """PRD §4.4: FREE output format knob."""
    SYSTEMVERILOG = "systemverilog"
    SYSTEMC = "systemc"
    UVM = "uvm"
    PDF = "pdf"
    JSON = "json"


@dataclass(frozen=True)
class NocConfig:
    """PRD §11.2: GUIDED + FREE knobs only.

    CRITICAL DESIGN: This type deliberately has NO fields for:
      - routing_function (LOCKED — derived from dependency graph)
      - turn_restrictions (LOCKED — derived from topology + routing)
      - vc_map (LOCKED — derived from dependency graph via derive_vc_count)

    An override isn't something the compiler refuses — it's something
    that cannot be expressed. A type with no field for the value cannot
    be overridden.
    """
    # GUIDED knobs (user proposes, engine may adjust)
    topology_family: TopologyFamily | None = None
    radix: int | None = None
    concentration: int | None = None
    arbitration: str | None = None
    rcu_enabled: bool | None = None
    link_width: int | None = None
    # GUIDED multicast knobs (switch multicast engine limits).
    # None = unconstrained (engine assumes ideal multicast).
    mcast_groups: int | None = None  # max hardware multicast groups
    mcast_setup_cycles: int | None = None  # per-group reconfiguration cost
    # FREE knobs (user's call)
    output_formats: tuple[OutputFormat, ...] = (OutputFormat.SYSTEMVERILOG,)
    obfuscation_level: int = 0  # 0=none, 1=light, 2=full

    def __post_init__(self):
        object.__setattr__(self, "output_formats",
                           _as_tuple("output_formats", self.output_formats))
        for o in self.output_formats:
            if not isinstance(o, OutputFormat):
                raise ValueError(
                    f"output_formats must contain OutputFormat, got "
                    f"{type(o).__name__}")
        if self.topology_family is not None \
                and not isinstance(self.topology_family, TopologyFamily):
            raise ValueError("topology_family must be a TopologyFamily")
        for name in ("radix", "concentration", "link_width", "mcast_groups"):
            val = getattr(self, name)
            if val is not None:
                _as_int(f"noc_config.{name}", val, minimum=1)
        if self.mcast_setup_cycles is not None:
            _as_int("noc_config.mcast_setup_cycles",
                    self.mcast_setup_cycles, minimum=0)
        _as_int("noc_config.obfuscation_level", self.obfuscation_level,
                minimum=0)
        if self.arbitration is not None:
            _as_str("noc_config.arbitration", self.arbitration,
                    allow_empty=False)
        if self.rcu_enabled is not None:
            _as_bool("noc_config.rcu_enabled", self.rcu_enabled)


# ══════════════════════════════════════════════════════════════════════════════
# §4.3 — Address Map
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AddressRange:
    """A single address range owned by a target agent."""
    name: str                   # e.g. "HBM0", "DRAM",
    base: int                   # start address (inclusive)
    size: int                   # size in bytes
    target_agent_idx: int = 0   # index into agents tuple

    def __post_init__(self):
        _as_str("AddressRange.name", self.name, allow_empty=False)
        _as_int("AddressRange.base", self.base, minimum=0)
        _as_int("AddressRange.size", self.size, minimum=1)
        _as_int("AddressRange.target_agent_idx", self.target_agent_idx,
                minimum=0)


@dataclass(frozen=True)
class AddressMap:
    """PRD §4.3: System address map — ranges each target owns.

    Accepts three forms per PRD:
      - Interactive: built programmatically
      - Import: parsed from CSV/IP-XACT/JSON
      - Inherit: cloned from previous revision

    This is the minimal representation. The full PRD address map
    includes initiator→target decode, which we derive from the
    agent positions in the topology.
    """
    ranges: tuple[AddressRange, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "ranges",
                           _as_tuple("ranges", self.ranges))
        for r in self.ranges:
            if not isinstance(r, AddressRange):
                raise ValueError(
                    f"ranges must contain AddressRange, got "
                    f"{type(r).__name__}")

    @classmethod
    def from_dict(cls, d: dict) -> AddressMap:
        """Parse from JSON-serializable dict."""
        ranges = tuple(
            AddressRange(
                name=r["name"], base=r["base"], size=r["size"],
                target_agent_idx=r.get("target_agent_idx", 0),
            )
            for r in d.get("ranges", [])
        )
        return cls(ranges=ranges)

    @classmethod
    def from_csv(cls, csv_path: str) -> AddressMap:
        """Parse address map from CSV file.

        Expected columns: name, base (hex or int), size (hex or int), target_agent_idx (optional).
        Lines starting with '#' are comments. Empty lines are skipped.

        Example CSV:
            name,base,size,target_agent_idx
            HBM0,0x00000000,0x10000000,0
            SRAM0,0x20000000,0x00100000,1
        """
        import csv
        ranges = []
        with open(csv_path, newline="") as f:
            for row in csv.reader(f):
                if not row or row[0].strip().startswith("#"):
                    continue
                # Skip header row (first cell is 'name')
                if row[0].strip().lower() == "name":
                    continue
                name = row[0].strip()
                base = int(row[1].strip(), 0)  # auto-detect hex (0x) or decimal
                size = int(row[2].strip(), 0)
                idx = int(row[3].strip()) if len(row) > 3 and row[3].strip() else 0
                ranges.append(AddressRange(name=name, base=base, size=size, target_agent_idx=idx))
        return cls(ranges=tuple(ranges))

    @classmethod
    def from_ipxact(cls, ipxact_path: str) -> AddressMap:
        """Parse address map from IP-XACT XML file.

        IP-XACT (IEEE 1685) is the standard XML format for hardware component descriptions.
        This parser extracts memoryMap elements with addressBlock children.

        Expected structure:
            <component>
              <memoryMaps>
                <memoryMap>
                  <addressBlock>
                    <name>HBM0</name>
                    <baseAddress>0x00000000</baseAddress>
                    <range>0x10000000</range>
                  </addressBlock>
                </memoryMap>
              </memoryMaps>
            </component>
        """
        import xml.etree.ElementTree as ET
        tree = ET.parse(ipxact_path)
        root = tree.getroot()
        ranges = []
        # Handle namespace (IP-XACT uses http://www.accellera.org/XMLSchema/IPXACT)
        ns = {'ipxact': 'http://www.accellera.org/XMLSchema/IPXACT'}
        # Try with namespace first, then without
        memory_maps = root.findall('.//ipxact:memoryMap', ns)
        if not memory_maps:
            memory_maps = root.findall('.//memoryMap')
        for mm in memory_maps:
            blocks = mm.findall('ipxact:addressBlock', ns)
            if not blocks:
                blocks = mm.findall('addressBlock')
            for block in blocks:
                name_el = block.find('ipxact:name', ns)
                if name_el is None:
                    name_el = block.find('name')
                base_el = block.find('ipxact:baseAddress', ns)
                if base_el is None:
                    base_el = block.find('baseAddress')
                range_el = block.find('ipxact:range', ns)
                if range_el is None:
                    range_el = block.find('range')
                if name_el is not None and base_el is not None and range_el is not None:
                    name = name_el.text or 'unknown'
                    base = int(base_el.text.strip(), 0) if base_el.text else 0
                    size = int(range_el.text.strip(), 0) if range_el.text else 0
                    ranges.append(AddressRange(name=name, base=base, size=size, target_agent_idx=0))
        return cls(ranges=tuple(ranges))

    def total_bytes(self) -> int:
        """Total addressable space across all ranges."""
        return sum(r.size for r in self.ranges)

    def validate_no_overlaps(self) -> list[str]:
        """Check for overlapping address ranges. Returns error list."""
        errors: list[str] = []
        sorted_ranges = sorted(self.ranges, key=lambda r: r.base)
        for i in range(len(sorted_ranges) - 1):
            a = sorted_ranges[i]
            b = sorted_ranges[i + 1]
            a_end = a.base + a.size
            if a_end > b.base:
                errors.append(
                    f"Address overlap: {a.name} [0x{a.base:X}-0x{a_end:X}] "
                    f"overlaps {b.name} [0x{b.base:X}-0x{b.base + b.size:X}]"
                )
        return errors


# ══════════════════════════════════════════════════════════════════════════════
# §10 / Physical Context
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PhysicalContext:
    """Physical implementation context: clock, reset, power domains.

    PRD §4.2 lists these as per-agent attributes, but they also
    have system-level defaults. This captures the system-level context.
    """
    default_clock_freq_mhz: float = 1000.0
    default_data_width: int = 256
    num_power_domains: int = 1
    process_node_nm: int = 7  # technology node

    def __post_init__(self):
        object.__setattr__(
            self, "default_clock_freq_mhz",
            _as_real("default_clock_freq_mhz", self.default_clock_freq_mhz))
        if self.default_clock_freq_mhz <= 0:
            raise ValueError(
                "default_clock_freq_mhz must be > 0, got "
                f"{self.default_clock_freq_mhz!r}")
        _as_int("default_data_width", self.default_data_width, minimum=8)
        _as_int("num_power_domains", self.num_power_domains, minimum=1)
        _as_int("process_node_nm", self.process_node_nm, minimum=1)


# ══════════════════════════════════════════════════════════════════════════════
# §5.2 Level B — Collective VC floor (worst-case-concurrency assumption)
# ══════════════════════════════════════════════════════════════════════════════

def collective_vc_floor(collectives: tuple[CollectiveOp, ...]) -> int:
    """Minimum VCs so declared collective contexts don't share one VC.

    Assumption (documented, worst-case): declared collectives are
    potentially concurrent. Concurrent collectives sharing a VC can
    deadlock via cyclic buffer waits (rank A holds buffers for collective 1
    waiting on B; B holds buffers for collective 2 waiting on A) — the same
    reason MPI separates communicator contexts and IB maps classes to
    distinct service levels. Phase overlap is NOT modeled, so this is a
    floor, not a proof: VC0 covers the first context, each additional
    multi-rank collective needs one more VC.

    Single-rank (group_size == 1) collectives need no fabric VC.
    """
    return sum(1 for c in collectives if c.group_size > 1)


def collective_vc_map(collectives: tuple[CollectiveOp, ...]) -> dict[int, int]:
    """GUIDED integration hint: collective index → reserved VC.

    Context 0 → VC0, context k → VC k. Consumed by future traffic-class
    mapping into BookSim; today it documents intent (which VC each
    collective context must use) so integration, not simulation, binds it.
    """
    return {
        i: k
        for k, i in enumerate(
            idx for idx, c in enumerate(collectives) if c.group_size > 1
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
# §11.3 — VC Separation (execution, not just counting)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class VCSeparation:
    """Result of VC derivation: which dependency gets which VC."""
    vc_count: int
    separated_deps: tuple[str, ...]  # source→target strings that need VC separation
    routing_function: str = "min_adapt"  # LOCKED — derived from topology + cycles


@dataclass(frozen=True)
class VCAssignment:
    """Complete VC assignment for a CompileRequest.

    This is the LOCKED output that the user cannot override.
    It determines the fabric's virtual channel structure.
    """
    vc_count: int
    per_class_vc: dict[str, int]  # traffic_class → assigned VC
    routing_function: str
    turn_restrictions: list[str] = field(default_factory=list)
    collective_vc_map: dict[int, int] = field(default_factory=dict)


    def __post_init__(self):
        if isinstance(self.turn_restrictions, list):
            object.__setattr__(self, 'turn_restrictions', tuple(self.turn_restrictions))


def derive_vc_assignment(cr: CompileRequest) -> VCAssignment:
    """PRD §11.3: Derive VC assignment from dependency graph.

    Algorithm (from PRD listing 11.2):
      1. Build blocking dependency graph
      2. Find cycles in BLOCKING subgraph
      3. For each cycle, choose the victim (least separation cost)
      4. Assign victim to a distinct VC
      5. Derive routing function from topology + cycle structure

    The routing function and turn restrictions are LOCKED — derived,
    not chosen by the user.

    Args:
        cr: CompileRequest with dependencies populated.

    Returns:
        VCAssignment with vc_count, per-class assignments, and
        derived routing function.
    """
    graph = cr.dependencies
    cycles = graph.find_cycles()
    vc_count = derive_vc_count(graph)

    # Collective floor: each potentially-concurrent multi-rank collective
    # context needs its own VC (see collective_vc_floor). Final count is
    # the max — graph cycles and collective contexts are independent
    # deadlock risks, so neither subsumes the other. Cap enforced below
    # by the caller-visible PLANE_C_MAX_VC bound (validate() errors).
    floor = collective_vc_floor(cr.workload.collectives)
    vc_count = max(vc_count, floor)
    vc_count = min(vc_count, PLANE_C_MAX_VC)

    # Assign VCs: default class gets VC 0, each cycle victim gets VC 1, 2, ...
    per_class_vc: dict[str, int] = {}
    separated: list[str] = []

    if not cycles:
        # No cycles → everyone on VC 0, use dimension-order routing
        routing = "dim_order"
    else:
        # Multiple cycles → need adaptive routing to avoid deadlock
        # The routing function is LOCKED: derived from cycle structure
        routing = "min_adapt" if vc_count > 2 else "dor"

        for i, cycle in enumerate(cycles):
            # Choose victim: the node in the cycle with fewest edges
            # (least disruption to separate)
            adj = graph._adjacency()
            victim = min(cycle[:-1],  # exclude duplicate end node
                        key=lambda n: len(adj.get(n, [])),
                        default=cycle[0])
            # Assign victim to VC i+1 (VC 0 is the default)
            per_class_vc[victim] = i + 1
            separated.append(victim)

    # Default: all unassigned classes on VC 0
    all_classes = set()
    for dep in graph.dependencies:
        all_classes.add(dep.source)
        all_classes.add(dep.target)
    for cls in sorted(all_classes):
        if cls not in per_class_vc:
            per_class_vc[cls] = 0

    # Derive turn restrictions from routing function
    turn_restrictions: list[str] = []
    if routing == "dim_order":
        # DOR: no turns allowed (strict dimension-order)
        turn_restrictions = ["no_negative_dimension_turns"]
    elif routing == "dor":
        turn_restrictions = ["west_first", "north_last"]
    # min_adapt: no explicit turn restrictions (adaptive)

    return VCAssignment(
        vc_count=vc_count,
        per_class_vc=per_class_vc,
        routing_function=routing,
        turn_restrictions=list(turn_restrictions),
        collective_vc_map=collective_vc_map(cr.workload.collectives),
    )


# ══════════════════════════════════════════════════════════════════════════════
# §11.1 / §13 — CompileRequest (E1–E5 unified)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CompileRequest:
    """PRD §11.1: The single structured object the engine consumes.

    Combines all five entities (E1–E5) into one immutable revision.

    Identity (Wave B1): ``design_hash()`` is the AUTHORITATIVE product
    design-intent identity — SHA-256 over the canonical semantic envelope
    (domain-tagged and versioned by schema + compiler semantics).
    ``guardrail_hash()`` is a retained compatibility name for the same
    value; new code calls ``design_hash()``. Execution provenance (git
    commit, binaries, host, timestamps, seeds) is deliberately NOT part
    of either hash.
    """
    workload: Workload
    requirements: tuple[Requirement, ...]
    agents: tuple[Agent, ...]
    dependencies: DependencyGraph
    noc_config: NocConfig
    # Extended fields (PRD §4.3, §10)
    address_map: AddressMap = field(default_factory=AddressMap)
    physical: PhysicalContext = field(default_factory=PhysicalContext)
    # Envelope versions: the SAME user fields under different compiler
    # semantics are a different design. Independent of core.spec.
    schema_version: int = COMPILE_REQUEST_SCHEMA_VERSION
    compiler_semantics_version: int = COMPILER_SEMANTICS_VERSION

    def __post_init__(self):
        # Normalize caller-owned mutable collections: a frozen request
        # must never retain a list the caller can still edit.
        object.__setattr__(self, 'requirements',
                           _as_tuple('requirements', self.requirements))
        object.__setattr__(self, 'agents',
                           _as_tuple('agents', self.agents))
        deps = self.dependencies
        if isinstance(deps, list):
            deps = DependencyGraph(deps)
        elif not isinstance(deps, DependencyGraph):
            raise ValueError(
                "dependencies must be a DependencyGraph or list, got "
                f"{type(deps).__name__}")
        object.__setattr__(self, 'dependencies', deps)
        for r in self.requirements:
            if not isinstance(r, Requirement):
                raise ValueError(
                    f"requirements must contain Requirement, got "
                    f"{type(r).__name__}")
        for a in self.agents:
            if not isinstance(a, Agent):
                raise ValueError(
                    f"agents must contain Agent, got {type(a).__name__}")
        if not isinstance(self.noc_config, NocConfig):
            raise ValueError("noc_config must be a NocConfig")
        if not isinstance(self.address_map, AddressMap):
            raise ValueError("address_map must be an AddressMap")
        if not isinstance(self.physical, PhysicalContext):
            raise ValueError("physical must be a PhysicalContext")
        if len(self.agents) == 0:
            raise ValueError("agents list cannot be empty — need at least one agent kind")
        # The version fields describe the semantics THIS class implements;
        # they are not user-adjustable knobs. Unsupported versions are
        # unrepresentable in memory, exactly as they are refused on load.
        if _as_int("schema_version", self.schema_version) \
                != COMPILE_REQUEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version} "
                f"(this build implements v{COMPILE_REQUEST_SCHEMA_VERSION})")
        if _as_int("compiler_semantics_version",
                   self.compiler_semantics_version) \
                not in SUPPORTED_COMPILER_SEMANTICS_VERSIONS:
            raise ValueError(
                f"unsupported compiler_semantics_version "
                f"{self.compiler_semantics_version} (this build speaks "
                f"{SUPPORTED_COMPILER_SEMANTICS_VERSIONS})")

    @property
    def total_nodes(self) -> int:
        """Total number of nodes across all agent kinds."""
        return sum(a.count for a in self.agents)

    # ── one serialization per entity (canonical + to_dict share it) ────

    @staticmethod
    def _requirement_dict(r: Requirement) -> dict:
        return {"qos_class": r.qos_class.value,
                "latency_ceiling_cycles": r.latency_ceiling_cycles,
                "bandwidth_floor_gbps": r.bandwidth_floor_gbps,
                "binding": r.binding}

    @staticmethod
    def _agent_dict(a: Agent) -> dict:
        return {"kind": a.kind.value, "count": a.count,
                "data_width": a.data_width, "addr_width": a.addr_width,
                "protocol": a.protocol, "clock_domain": a.clock_domain,
                "power_domain": a.power_domain}

    @staticmethod
    def _dependency_dict(dep: Dependency) -> dict:
        return {"source": dep.source, "target": dep.target,
                "kind": dep.kind.value}

    @staticmethod
    def _address_dict(r: AddressRange) -> dict:
        return {"name": r.name, "base": r.base, "size": r.size,
                "target_agent_idx": r.target_agent_idx}

    def _noc_dict(self) -> dict:
        return {
            "topology_family": self.noc_config.topology_family.value
                if self.noc_config.topology_family else None,
            "radix": self.noc_config.radix,
            "concentration": self.noc_config.concentration,
            "arbitration": self.noc_config.arbitration,
            "rcu_enabled": self.noc_config.rcu_enabled,
            "link_width": self.noc_config.link_width,
            "output_formats": [o.value for o in self.noc_config.output_formats],
            "obfuscation_level": self.noc_config.obfuscation_level,
            "mcast_groups": self.noc_config.mcast_groups,
            "mcast_setup_cycles": self.noc_config.mcast_setup_cycles,
        }

    def _physical_dict(self) -> dict:
        return {"clock_freq_mhz": self.physical.default_clock_freq_mhz,
                "data_width": self.physical.default_data_width,
                "num_power_domains": self.physical.num_power_domains,
                "process_node_nm": self.physical.process_node_nm}

    def _workload_dict(self) -> dict:
        return {
            "model_family": self.workload.model_family.value,
            "model_name": self.workload.model_name,
            "tp": self.workload.tp,
            "pp": self.workload.pp,
            "ep": self.workload.ep,
            "dp": self.workload.dp,
            "param_count_b": self.workload.param_count_b,
            "sequence_length": self.workload.sequence_length,
            "batch_size": self.workload.batch_size,
            "precision": self.workload.precision,
            "serving_mode": self.workload.serving_mode.value,
            "collectives": [c.to_dict() for c in self.workload.collectives],
            "trace_path": self.workload.trace_path,
        }

    def _semantic_dict(self) -> dict:
        """Every semantic field, declared insertion order preserved."""
        return {
            "workload": self._workload_dict(),
            "requirements": [self._requirement_dict(r)
                             for r in self.requirements],
            "agents": [self._agent_dict(a) for a in self.agents],
            "dependencies": [self._dependency_dict(dep)
                             for dep in self.dependencies.dependencies],
            "noc_config": self._noc_dict(),
            "address_map": {"ranges": [self._address_dict(r)
                                       for r in self.address_map.ranges]},
            "physical": self._physical_dict(),
        }

    def canonical_dict(self) -> dict:
        """Canonical semantic envelope — the sole input to design_hash().

        Ordering policy (authoritative table lives in
        tests/test_design_intent_identity.py):
          ORDERED   collectives (index to VC map), agents
                    (target_agent_idx indexes the tuple)
          UNORDERED dependencies (semantics v2; graph processing is
                    deterministic), requirements, address ranges,
                    output_formats

        Under legacy semantics v1, dependency edge order was identity-
        bearing; v1 documents are hashed in declared order so their stored
        design_hash still validates.
        """
        d = self._semantic_dict()
        d["requirements"] = sorted(d["requirements"], key=_canonical_json)
        d["address_map"]["ranges"] = sorted(d["address_map"]["ranges"],
                                            key=_canonical_json)
        d["noc_config"]["output_formats"] = sorted(
            d["noc_config"]["output_formats"])
        if self.compiler_semantics_version >= 2:
            d["dependencies"] = sorted(d["dependencies"], key=_canonical_json)
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            **d,
        }

    def design_hash(self) -> str:
        """AUTHORITATIVE design-intent identity (SHA-256, domain-separated).

        Answers only "what exact product design did the customer
        request?". No git/binary/host/seed/timestamp provenance enters.
        """
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}/"
                f"c{self.compiler_semantics_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def guardrail_hash(self) -> str:
        """Deprecated compatibility name for :meth:`design_hash`.

        Retained so existing report/CLI call sites keep one authoritative
        value; it no longer computes an incomplete field set.
        """
        return self.design_hash()

    def to_dict(self) -> dict[str, Any]:
        """Lossless serialization: every semantic field survives.

        Carries the schema/semantics envelope and the derived
        ``design_hash`` (also as ``guardrail_hash`` for compatibility).
        ``from_dict(to_dict()) == self`` holds.
        """
        d = {
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            **self._semantic_dict(),
        }
        d["design_hash"] = self.design_hash()
        d["guardrail_hash"] = d["design_hash"]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CompileRequest:
        """Strict, versioned, lossless deserialization.

        Fails closed on: unknown fields at any level, missing or
        unsupported schema_version, unsupported compiler_semantics_version,
        and any value that cannot represent a design. A supplied
        design_hash/guardrail_hash must match the recomputed identity.
        """
        _strict_keys(d, _TOP_KEYS, "root")
        if "schema_version" not in d:
            raise CompileRequestSchemaError(
                "missing schema_version — refusing to guess a schema; add "
                f"\"schema_version\": {COMPILE_REQUEST_SCHEMA_VERSION}")
        if type(d["schema_version"]) is not int \
                or d["schema_version"] != COMPILE_REQUEST_SCHEMA_VERSION:
            raise CompileRequestSchemaError(
                f"unsupported CompileRequest schema_version "
                f"{d['schema_version']!r} (this build speaks "
                f"v{COMPILE_REQUEST_SCHEMA_VERSION}) — old documents are "
                "never reinterpreted under new semantics")
        semantics = _need(d, "compiler_semantics_version", "root")
        if type(semantics) is not int \
                or semantics not in SUPPORTED_COMPILER_SEMANTICS_VERSIONS:
            raise CompileRequestSchemaError(
                f"unsupported compiler_semantics_version {semantics!r} "
                f"(this build speaks {SUPPORTED_COMPILER_SEMANTICS_VERSIONS})")

        wl = _need(d, "workload", "root")
        _strict_keys(wl, _WORKLOAD_KEYS, "workload")
        collectives = []
        for i, c in enumerate(wl.get("collectives", [])):
            _strict_keys(c, _COLLECTIVE_KEYS, f"workload.collectives[{i}]")
            collectives.append(CollectiveOp.from_dict(c))
        workload = Workload(
            model_family=_enum(ModelFamily,
                               _need(wl, "model_family", "workload"),
                               "workload.model_family"),
            model_name=wl.get("model_name", ""),
            tp=wl.get("tp", 1),
            pp=wl.get("pp", 1),
            ep=wl.get("ep", 1),
            dp=wl.get("dp", 1),
            param_count_b=wl.get("param_count_b"),
            sequence_length=wl.get("sequence_length"),
            batch_size=wl.get("batch_size", 1),
            precision=wl.get("precision", "fp16"),
            serving_mode=_enum(ServingMode, wl.get("serving_mode", "mixed"),
                               "workload.serving_mode"),
            collectives=tuple(collectives),
            trace_path=wl.get("trace_path"),
        )
        requirements = []
        for i, r in enumerate(d.get("requirements", [])):
            _strict_keys(r, _REQUIREMENT_KEYS, f"requirements[{i}]")
            requirements.append(Requirement(
                qos_class=_enum(QoSClass,
                                _need(r, "qos_class", f"requirements[{i}]"),
                                f"requirements[{i}].qos_class"),
                latency_ceiling_cycles=r.get("latency_ceiling_cycles"),
                bandwidth_floor_gbps=r.get("bandwidth_floor_gbps"),
                binding=r.get("binding", False),
            ))
        agents = []
        for i, a in enumerate(d.get("agents", [])):
            _strict_keys(a, _AGENT_KEYS, f"agents[{i}]")
            agents.append(Agent(
                kind=_enum(AgentKind, _need(a, "kind", f"agents[{i}]"),
                           f"agents[{i}].kind"),
                count=_need(a, "count", f"agents[{i}]"),
                data_width=a.get("data_width", 256),
                addr_width=a.get("addr_width", 64),
                protocol=a.get("protocol", "AXI"),
                clock_domain=a.get("clock_domain"),
                power_domain=a.get("power_domain"),
            ))
        deps = []
        for i, dep in enumerate(d.get("dependencies", [])):
            _strict_keys(dep, _DEPENDENCY_KEYS, f"dependencies[{i}]")
            deps.append(Dependency(
                source=_need(dep, "source", f"dependencies[{i}]"),
                target=_need(dep, "target", f"dependencies[{i}]"),
                kind=_enum(DepKind, _need(dep, "kind", f"dependencies[{i}]"),
                           f"dependencies[{i}].kind"),
            ))
        nc_d = d.get("noc_config", {})
        _strict_keys(nc_d, _NOC_KEYS, "noc_config")
        noc_config = NocConfig(
            topology_family=(_enum(TopologyFamily, nc_d["topology_family"],
                                   "noc_config.topology_family")
                             if nc_d.get("topology_family") else None),
            radix=nc_d.get("radix"),
            concentration=nc_d.get("concentration"),
            arbitration=nc_d.get("arbitration"),
            rcu_enabled=nc_d.get("rcu_enabled"),
            link_width=nc_d.get("link_width"),
            output_formats=tuple(
                _enum(OutputFormat, o, "noc_config.output_formats")
                for o in nc_d.get("output_formats", ["systemverilog"])),
            obfuscation_level=nc_d.get("obfuscation_level", 0),
            mcast_groups=nc_d.get("mcast_groups"),
            mcast_setup_cycles=nc_d.get("mcast_setup_cycles"),
        )
        am_d = d.get("address_map", {})
        _strict_keys(am_d, _ADDRESS_MAP_KEYS, "address_map")
        ranges = []
        for i, r in enumerate(am_d.get("ranges", [])):
            _strict_keys(r, _ADDRESS_RANGE_KEYS, f"address_map.ranges[{i}]")
            ranges.append(AddressRange(
                name=_need(r, "name", f"address_map.ranges[{i}]"),
                base=_need(r, "base", f"address_map.ranges[{i}]"),
                size=_need(r, "size", f"address_map.ranges[{i}]"),
                target_agent_idx=r.get("target_agent_idx", 0)))
        ph_d = d.get("physical", {})
        _strict_keys(ph_d, _PHYSICAL_KEYS, "physical")
        physical = PhysicalContext(
            default_clock_freq_mhz=ph_d.get("clock_freq_mhz", 1000.0),
            default_data_width=ph_d.get("data_width", 256),
            num_power_domains=ph_d.get("num_power_domains", 1),
            process_node_nm=ph_d.get("process_node_nm", 7),
        )

        obj = cls(
            workload=workload,
            requirements=tuple(requirements),
            agents=tuple(agents),
            dependencies=DependencyGraph(deps),
            noc_config=noc_config,
            address_map=AddressMap(ranges=tuple(ranges)),
            physical=physical,
            schema_version=d["schema_version"],
            compiler_semantics_version=semantics,
        )
        for key in ("design_hash", "guardrail_hash"):
            if key in d and d[key] != obj.design_hash():
                raise CompileRequestSchemaError(
                    f"{key} does not match the recomputed design identity "
                    "— document tampered with or drifted")
        return obj


def migrate_design(document: CompileRequest | dict[str, Any]
                   ) -> tuple[CompileRequest, dict[str, Any]]:
    """Re-emit a CompileRequest under the current compiler semantics.

    Wave B3.0-pre migration path. A legacy document is loaded under its
    own semantics (its stored design_hash is validated there), then
    re-emitted as a current-semantics request. Because current semantics
    treat dependency edge order as non-semantic, the migrated identity is
    order-independent; it differs from the legacy identity whenever the
    semantics version contributes to the hash body (always, on a bump).

    Returns ``(migrated, provenance)``. Provenance is NON-semantic — the
    caller records it out-of-band (stdout/log/sidecar); it never enters
    any artifact identity. An already-current document is returned
    unchanged with a no-op provenance record.
    """
    obj = (document if isinstance(document, CompileRequest)
           else CompileRequest.from_dict(document))
    source_version = obj.compiler_semantics_version
    if source_version == COMPILER_SEMANTICS_VERSION:
        return obj, {
            "from_semantics": source_version,
            "to_semantics": source_version,
            "from_design_hash": obj.design_hash(),
            "to_design_hash": obj.design_hash(),
            "changed": False,
            "dependency_order_canonicalized": False,
        }
    if source_version not in LEGACY_COMPILER_SEMANTICS_VERSIONS:
        raise CompileRequestSchemaError(
            f"migrate_design: unsupported source compiler_semantics_version "
            f"{source_version!r} (can migrate {LEGACY_COMPILER_SEMANTICS_VERSIONS} "
            f"to {COMPILER_SEMANTICS_VERSION})")
    migrated = CompileRequest(
        workload=obj.workload,
        requirements=obj.requirements,
        agents=obj.agents,
        dependencies=obj.dependencies,
        noc_config=obj.noc_config,
        address_map=obj.address_map,
        physical=obj.physical,
        schema_version=obj.schema_version,
        compiler_semantics_version=COMPILER_SEMANTICS_VERSION,
    )
    src_hash = obj.design_hash()
    dst_hash = migrated.design_hash()
    return migrated, {
        "from_semantics": source_version,
        "to_semantics": COMPILER_SEMANTICS_VERSION,
        "from_design_hash": src_hash,
        "to_design_hash": dst_hash,
        "changed": src_hash != dst_hash,
        "dependency_order_canonicalized": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# §13 — Validate Stage
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Trace coverage helper (for collective↔trace consistency)
# ══════════════════════════════════════════════════════════════════════════════

# Max trace lines scanned during validate(). Full scans of 26M-line traces
# would break the "errors in seconds" promise; beyond the cap we report
# sampled results explicitly. Env-overridable (import-time read).
TRACE_SCAN_CAP = env_int("VERITX_TRACE_SCAN_CAP", 200_000)


def _trace_node_ids(trace_path: str, cap: int = TRACE_SCAN_CAP,
                    ) -> tuple[set[int], bool, str | None]:
    """Collect distinct node IDs from a packet trace (capped scan).

    On-disk column order is `cycle src class dst size` (see
    simulation/traces.py detect_trace_stats — NOT the README order).

    Returns (node_ids, truncated, resolved_path_or_None).
    Missing/unreadable files return (empty set, False, None) — callers
    decide severity (compile tolerates a missing trace, so warn, not error).
    """
    if not trace_path:
        return set(), False, None
    from veritx_dse.core.paths import REPO
    candidates = [Path(trace_path)]
    if not candidates[0].is_absolute():
        candidates.append(REPO / trace_path)
    resolved = next((c for c in candidates if c.is_file()), None)
    if resolved is None:
        return set(), False, None
    ids: set[int] = set()
    truncated = False
    try:
        with open(resolved) as f:
            for i, line in enumerate(f):
                if i >= cap:
                    truncated = True
                    break
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    ids.add(int(parts[1]))
                    ids.add(int(parts[3]))
    except (OSError, ValueError):
        return set(), False, None
    return ids, truncated, str(resolved)


@dataclass
class ValidationResult:
    """Result of CompileRequest validation."""
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    vc_count: int = 1
    total_nodes: int = 0


def validate(cr: CompileRequest) -> ValidationResult:
    """PRD §13: Validate a CompileRequest before synthesis.

    Catches config errors in seconds, not minutes. Checks:
      - At least one agent with count > 0
      - Dependency graph cycle detection (warnings, not errors)
      - VC count derivation
      - Total node count

    Args:
        cr: The CompileRequest to validate.

    Returns:
        ValidationResult with ok flag, errors, warnings, and derived values.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check agents
    if not cr.agents:
        errors.append("No agents defined — at least one agent kind is required")
    else:
        for a in cr.agents:
            if a.count <= 0:
                errors.append(f"Agent {a.kind.value} has count={a.count} (must be > 0)")

    # Check dependency graph
    if cr.dependencies.has_cycles():
        cycles = cr.dependencies.find_cycles()
        warnings.append(
            f"Dependency graph has {len(cycles)} cycle(s) — "
            f"VC separation required for deadlock-freedom"
        )

    # Derive VC count
    vc_count = derive_vc_count(cr.dependencies)
    if vc_count > PLANE_C_MAX_VC:
        errors.append(
            f"VC count {vc_count} exceeds fabric maximum {PLANE_C_MAX_VC} — "
            f"reduce dependency cycles or declare non-blocking dependencies"
        )

    total_nodes = cr.total_nodes

    # Collective floor infeasibility (reachable, unlike the capped graph
    # count above): more concurrent contexts than fabric VCs.
    floor = collective_vc_floor(cr.workload.collectives)
    if floor > PLANE_C_MAX_VC:
        errors.append(
            f"Collective VC floor {floor} exceeds fabric maximum "
            f"{PLANE_C_MAX_VC} — declare fewer concurrent collectives"
        )

    # Collective↔fabric consistency (declared collectives must fit the fabric)
    for coll in cr.workload.collectives:
        if coll.group_size > total_nodes:
            errors.append(
                f"Collective {coll.kind.value} group_size={coll.group_size} "
                f"exceeds fabric nodes={total_nodes} — ranks would have no home"
            )
        elif coll.group_size == 1 and coll.kind in (
            CollectiveKind.ALLREDUCE, CollectiveKind.ALLTOALL,
            CollectiveKind.BROADCAST,
        ):
            warnings.append(
                f"Collective {coll.kind.value} group_size=1 is a no-op — "
                f"likely a config mistake"
            )

    # Collective↔trace coverage (trace must span the declared collective).
    # Missing trace is a warning: compile tolerates it (analytical fallback).
    if cr.workload.collectives and cr.workload.trace_path:
        need = max(c.group_size for c in cr.workload.collectives)
        ids, truncated, resolved = _trace_node_ids(cr.workload.trace_path)
        if resolved is None:
            warnings.append(
                f"Trace not found: {cr.workload.trace_path} — "
                f"skipping collective coverage check"
            )
        elif len(ids) < need:
            scope = f" (scanned first {TRACE_SCAN_CAP} lines)" if truncated else ""
            warnings.append(
                f"Trace covers {len(ids)} nodes but collectives need {need} — "
                f"collective would be under-exercised{scope}"
            )

    # Multicast group fit (Astera's complaint, modeled honestly): a switch
    # with mcast_groups hardware groups can accelerate at most that many
    # multicast collective contexts; the excess falls back to unicast
    # (slower, not infeasible → warning, not error). Unset knob means the
    # engine assumes ideal multicast (no check).
    if cr.noc_config.mcast_groups is not None:
        mcast_need = [
            c for c in cr.workload.collectives
            if c.group_size > 1 and c.kind in (
                CollectiveKind.ALLTOALL, CollectiveKind.ALLGATHER,
                CollectiveKind.BROADCAST,
            )
        ]
        if len(mcast_need) > cr.noc_config.mcast_groups:
            warnings.append(
                f"{len(mcast_need)} multicast collectives need groups but "
                f"fabric has mcast_groups={cr.noc_config.mcast_groups} — "
                f"excess falls back to unicast"
            )

    return ValidationResult(
        ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        vc_count=vc_count,
        total_nodes=total_nodes,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Integration: CompileRequest → existing types
# ══════════════════════════════════════════════════════════════════════════════

def derive_topology_artifact(cr: CompileRequest):
    """Materialize the fabric: the authoritative topology for this request.

    Wave B3.1b. Sizing inputs are the hardware NodeInventory and the GUIDED
    knobs (family/radix/concentration) — NOT a hardcoded k/n and NOT the
    model rank count. GEC and fat-tree are refused by the materializer
    rather than silently downgraded to a mesh.

    Returns a TopologyArtifact (routers, directed channels, local seats).
    """
    from .placement import build_inventory
    from .topology_artifact import materialize_topology
    return materialize_topology(build_inventory(cr), cr)


def derive_topology_spec(cr: CompileRequest):
    """Bridge the materialized TopologyArtifact to presets.Topology.

    The backend/k/c come from the materialized artifact (one topology truth);
    the routing function stays LOCKED — derived from the dependency graph via
    derive_vc_assignment(), not taken from the family map default.

    Args:
        cr: CompileRequest with noc_config populated.

    Returns:
        Topology instance from veritx_dse.presets.
    """
    from .presets import Topology
    from .topology_artifact import MaterializedFamily

    artifact = derive_topology_artifact(cr)
    family = artifact.family
    routers = artifact.router_count

    if family in (MaterializedFamily.MESH, MaterializedFamily.TORUS,
                  MaterializedFamily.CONCENTRATED_MESH):
        k = math.isqrt(routers)
        if k * k != routers:
            raise ValueError(
                f"materialized {family.value} is not a square grid "
                f"({routers} routers) — refusing to guess a k")
        if family == MaterializedFamily.TORUS:
            backend, params = "torus", {"k": k, "n": 2}
        elif family == MaterializedFamily.CONCENTRATED_MESH:
            # Concentration is a meshed fabric with several local seats per
            # router; the backend that can express it is cmesh.
            backend = "cmesh"
            params = {"k": k, "n": 2,
                      "c": artifact.routers[0].seat_capacity}
        else:
            backend, params = "mesh", {"k": k, "n": 2}
    elif family == MaterializedFamily.RING:
        backend, params = "torus", {"k": routers, "n": 1}
    else:  # pragma: no cover - enum is closed
        raise ValueError(f"unhandled materialized family {family}")

    # LOCKED: Derive routing + VC assignment from dependency graph
    vc_assignment = derive_vc_assignment(cr)
    routing = vc_assignment.routing_function  # LOCKED — not user-chosen
    if vc_assignment.vc_count > 1:
        # B3.3 owns the VC-count semantics (this +1 head-flit VC and the
        # clamp are known defects; not repaired in the sizing wave).
        params["num_vcs"] = vc_assignment.vc_count + 1

    name = (f"{backend}_{params['k']}x{params['k']}_c{params['c']}"
            if backend == "cmesh" else f"{backend}_{params['k']}x{params['k']}")

    return Topology(
        name=name,
        backend=backend,
        routing=routing,
        params=params,
        # GEC (the only needs_noc_latency_zero family) is refused by the
        # materializer, so this is always False now.
        needs_noc_latency_zero=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# §12.8 — Result Entity
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Result:
    """PRD §12.8: Simulation result for a design.

    Captures the numeric outcomes from BookSim simulation and
    area/power/timing estimation. Frozen for immutability.
    """
    design_id: str
    revision: int
    latency_cycles: float
    throughput_gbps: float | None = None
    area_mm2: float = 0.0
    power_w: float = 0.0
    fmax_mhz: float = 0.0
    energy_pj_per_bit: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "design_id": self.design_id,
            "revision": self.revision,
            "latency_cycles": self.latency_cycles,
            "throughput_gbps": self.throughput_gbps,
            "area_mm2": self.area_mm2,
            "power_w": self.power_w,
            "fmax_mhz": self.fmax_mhz,
            "energy_pj_per_bit": self.energy_pj_per_bit,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Result:
        """Deserialize from dict."""
        return cls(
            design_id=d["design_id"],
            revision=d["revision"],
            latency_cycles=d["latency_cycles"],
            throughput_gbps=d.get("throughput_gbps"),
            area_mm2=d.get("area_mm2", 0.0),
            power_w=d.get("power_w", 0.0),
            fmax_mhz=d.get("fmax_mhz", 0.0),
            energy_pj_per_bit=d.get("energy_pj_per_bit", 0.0),
        )


# ══════════════════════════════════════════════════════════════════════════════
# §12.9 — Artifact Entity
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Artifact:
    """PRD §12.9: Generated artifact with integrity proof.

    Each artifact (RTL file, UVM testbench, report, manifest) is
    tracked with its checksum and signature for provenance.

    ``generated`` is the PR-B honesty flag: False means the artifact is
    REGISTERED but the file has not been produced (and its checksum is
    correspondingly empty). Consumers — reports, exports — must treat
    generated=False entries as placeholders, never as generated content.
    """
    artifact_id: str
    design_id: str
    revision: int
    kind: str  # "rtl", "uvm", "report", "manifest", "formal"
    uri: str
    checksum_sha256: str
    signature: str
    timestamp: str = ""
    generated: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "artifact_id": self.artifact_id,
            "design_id": self.design_id,
            "revision": self.revision,
            "kind": self.kind,
            "uri": self.uri,
            "checksum_sha256": self.checksum_sha256,
            "signature": self.signature,
            "timestamp": self.timestamp,
            "generated": self.generated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Artifact:
        """Deserialize from dict."""
        return cls(
            artifact_id=d["artifact_id"],
            design_id=d["design_id"],
            revision=d["revision"],
            kind=d["kind"],
            uri=d["uri"],
            checksum_sha256=d["checksum_sha256"],
            signature=d["signature"],
            timestamp=d.get("timestamp", ""),
            generated=d.get("generated", False),
        )


# ══════════════════════════════════════════════════════════════════════════════
# §13.5 — Verify Stage
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VerificationResult:
    """Result of formal/design verification checks."""
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Verification status contract (verified-PRD Integrity PR B, §4.1):
# A PASS is emitted ONLY when a defined check actually executed against its
# referenced evidence and satisfied the acceptance rule. ASSUMPTION records
# architectural intent. NOT_RUN records unexecuted checks honestly.
VERIFICATION_STATUSES = (
    "PASS", "FAIL", "NOT_RUN", "UNSUPPORTED", "INCONCLUSIVE", "ASSUMPTION",
)


def topology_adjacency(topo) -> dict[int, set[int]] | None:
    """Adjacency of the topology that will actually be simulated (F2 evidence).

    Supports the backends derive_topology_spec can emit. For anynet,
    reads the network file through core.anynet (the ONE parser). An
    unsupported backend returns None — the caller then reports F2
    NOT_RUN (no evidence) instead of fabricating an adjacency.
    """
    backend = getattr(topo, "backend", "")
    params = getattr(topo, "params", {}) or {}
    if backend in ("mesh", "cmesh"):
        k, n = int(params.get("k", 8)), int(params.get("n", 2))
        nodes = k ** n
        adj: dict[int, set[int]] = {i: set() for i in range(nodes)}
        for i in range(nodes):
            dims = []
            v = i
            for _ in range(n):
                dims.append(v % k)
                v //= k
            for d in range(n):
                for delta in (-1, 1):
                    nd = dims[d] + delta
                    if 0 <= nd < k:  # mesh: no wraparound
                        j = i + delta * (k ** d)
                        adj[i].add(j)
        return adj
    if backend == "torus":
        k, n = int(params.get("k", 8)), int(params.get("n", 2))
        nodes = k ** n
        adj = {i: set() for i in range(nodes)}
        for i in range(nodes):
            dims = []
            v = i
            for _ in range(n):
                dims.append(v % k)
                v //= k
            for d in range(n):
                for delta in (-1, 1):
                    nd = (dims[d] + delta) % k  # torus: wraps
                    j = i + (nd - dims[d]) * (k ** d)
                    adj[i].add(j)
        return adj
    if backend == "anynet":
        nf = params.get("network_file", "")
        if not nf:
            return None
        from .presets import _parse_anynet_adj
        adj = _parse_anynet_adj(nf)
        return adj or None
    return None


def latency_bound_from_requirements(requirements) -> float | None:
    """F8's latency bound: min over declared latency ceilings (E2).

    Requirements without a ceiling contribute nothing; no requirements
    → no bound → F8 stays NOT_RUN. The bound is a declared scientific
    constraint, never a defaulted number.
    """
    ceilings = [float(r.latency_ceiling_cycles) for r in (requirements or [])
                if r.latency_ceiling_cycles is not None]
    return min(ceilings) if ceilings else None


def verify_design(
    cr: CompileRequest,
    topology_name: str = "mesh_8x8",
    evidence: dict[str, Any] | None = None,
) -> VerificationResult:
    """PRD §13.5: Run F1–F8 verification checks.

    Each check returns a status from VERIFICATION_STATUSES with an explicit
    statement (what was verified, at what scope), the method used, and the
    evidence it consumed. F1–F8:

    F1: Deadlock freedom — abstract dependency graph acyclic (heuristic
        scope; the (channel,VC) CDG certificate is a separate artifact)
    F2: Liveness — requires topology connectivity evidence
    F3: Packet conservation — requires BookSim flit accounting evidence
    F4: Ordering — architectural assumption (per-VC FIFO)
    F5: Flow control — architectural assumption (credit-based)
    F6: Routing correctness — requires route-table equivalence evidence
    F7: QoS isolation — unsupported until a formal QoS check exists
    F8: Timeout — requires BookSim latency-bound evidence

    ``evidence`` carries optional simulation results keyed by name; checks
    upgrade from NOT_RUN to PASS/FAIL only when their evidence is present.

    Gate B (verified-PRD §12.1): no code path may emit PASS without
    executing its acceptance check.
    """
    ev = evidence or {}
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add(name: str, status: str, statement: str, method: str,
            detail: str, evidence_used: dict[str, Any] | None = None) -> None:
        assert status in VERIFICATION_STATUSES, status
        checks.append({
            "name": name,
            "status": status,
            "statement": statement,
            "method": method,
            "detail": detail,
            "evidence": evidence_used,
        })

    # F1: Deadlock freedom — cycle detection on the abstract dependency graph.
    # The executed check is real but its scope is the abstract graph; a full
    # deadlock claim requires the (channel,VC) CDG certificate (PR D+).
    cycles = cr.dependencies.find_cycles()
    if not cycles:
        add("F1_deadlock_freedom", "PASS",
            "Abstract dependency graph is acyclic",
            "cycle_detection",
            "No blocking cycles in the abstract dependency graph. Scope: "
            "abstract graph only — NOT a (channel,VC) CDG deadlock certificate.",
            {"graph": "abstract_dependency"})
    else:
        # Cycles exist; VC separation is claimed to break them. That is a
        # heuristic, not a proof at (channel,VC) granularity (§3.4).
        vc = derive_vc_count(cr.dependencies)
        if vc <= PLANE_C_MAX_VC:
            add("F1_deadlock_freedom", "ASSUMPTION",
                f"{len(cycles)} abstract cycle(s) assumed broken by {vc} VCs",
                "vc_count_heuristic",
                "VC-count heuristic applied to abstract cycles — unproven at "
                "(channel,VC) dependency level.",
                {"graph": "abstract_dependency", "cycles": len(cycles),
                 "vc_count": vc})
            warnings.append(
                f"F1: {len(cycles)} cycle(s) broken only by a VC-count "
                f"assumption, not a (channel,VC) certificate")
        else:
            add("F1_deadlock_freedom", "FAIL",
                f"{len(cycles)} abstract cycle(s) need {vc} VCs "
                f"(max {PLANE_C_MAX_VC})",
                "vc_count_heuristic",
                "Cycles exceed declared VC capacity.",
                {"graph": "abstract_dependency", "cycles": len(cycles),
                 "vc_count": vc})
            errors.append(f"Deadlock: {len(cycles)} cycles exceed VC capacity")

    # F2: Liveness — real check when topology adjacency evidence is
    # provided (Phase-13 precursor): every node reachable from node 0.
    # A name is not evidence (verified-PRD §3.11); an adjacency set from
    # the actually-executed topology is.
    adj_ev = ev.get("topology_adjacency")
    if isinstance(adj_ev, dict) and adj_ev:
        try:
            adj = {int(k): set(v) for k, v in adj_ev.items()}
            n = len(adj)
            seen = {0}
            stack = [0]
            while stack:
                u = stack.pop()
                for v in adj.get(u, ()):
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            connected = len(seen) == n
        except (TypeError, ValueError):
            connected = None
        if connected is True:
            add("F2_liveness", "PASS",
                "Every packet eventually delivered — all nodes reachable",
                "topology_connectivity (executed topology adjacency)",
                f"{n} nodes, all reachable from node 0 (BFS over the "
                "executed topology's adjacency).",
                {"nodes": n})
        elif connected is False:
            add("F2_liveness", "FAIL",
                "Every packet eventually delivered — topology disconnected",
                "topology_connectivity (executed topology adjacency)",
                f"only {len(seen)} of {n} nodes reachable from node 0 — "
                "packets to unreachable nodes can never deliver.",
                {"nodes": n, "reachable": len(seen)})
            errors.append(
                f"F2: topology disconnected ({len(seen)}/{n} reachable)")
        else:
            add("F2_liveness", "FAIL",
                "Liveness evidence malformed",
                "topology_connectivity (executed topology adjacency)",
                "topology_adjacency present but not parseable as "
                "{node_id: [neighbors]} — refusing to guess.")
            errors.append("F2: malformed topology_adjacency evidence")
    else:
        add("F2_liveness", "NOT_RUN",
            "Every packet eventually delivered — requires topology connectivity "
            "evidence",
            "topology_connectivity (pending)",
            f"Not executed: only the topology name '{topology_name}' is available "
            "to this check; connectivity was NOT verified.")

    # F3: Packet conservation — real check when BookSim accounting evidence
    # is provided. Two evidence shapes:
    #   a) injected/completed/dropped all present: the classic identity
    #      injected == completed + dropped (all three measured/fork-declared)
    #   b) injected/completed present, dropped absent (the VeritX fork's
    #      totals print): complete-delivery semantics on a drained run —
    #      any injected-vs-ejected gap is loss inside the fabric. We do
    #      NOT derive dropped = injected - accepted and feed it back
    #      through (a): that is an arithmetic identity, verifying nothing.
    inj = ev.get("booksim_injected_flits")
    com = ev.get("booksim_completed_flits")
    dro = ev.get("booksim_dropped_flits")
    if None not in (inj, com, dro):
        conserved = int(inj) == int(com) + int(dro)
        add("F3_packet_conservation", "PASS" if conserved else "FAIL",
            "Injected flits equal completed plus dropped flits",
            "booksim_flit_accounting",
            f"injected={inj}, completed={com}, dropped={dro}",
            {"injected": inj, "completed": com, "dropped": dro})
        if not conserved:
            errors.append(
                f"F3: flit conservation violated "
                f"({inj} != {com} + {dro})")
    elif None not in (inj, com):
        conserved = int(inj) == int(com)
        add("F3_packet_conservation", "PASS" if conserved else "FAIL",
            "All injected flits reached ejection (complete delivery)",
            "booksim_flit_accounting",
            f"injected={inj}, ejected={com}"
            + ("" if conserved else f", lost={int(inj) - int(com)}"),
            {"injected": inj, "completed": com})
        if not conserved:
            errors.append(
                f"F3: flits lost inside the fabric "
                f"({int(inj) - int(com)} of {inj} never ejected)")
    else:
        add("F3_packet_conservation", "NOT_RUN",
            "No lost/duplicated flits — requires BookSim run evidence",
            "booksim_flit_accounting (pending)",
            "Not executed: no BookSim flit-accounting evidence provided.")

    # F4: Ordering — per-VC FIFO is an architectural assumption of the
    # credit-based wormhole design, not a verified property.
    va = derive_vc_assignment(cr)
    add("F4_ordering", "ASSUMPTION",
        "Per-VC in-order delivery follows from the credit-based wormhole "
        "architecture",
        "architectural_intent",
        f"{va.vc_count} VCs with {va.routing_function} routing — ordering "
        "assumed from architecture, not checked.",
        {"vc_count": va.vc_count, "routing_function": va.routing_function})

    # F5: Flow control — credit-based flow control is the designed mechanism;
    # no overflow analysis is executed here.
    add("F5_flow_control", "ASSUMPTION",
        "Credit-based flow control prevents overflow by design",
        "architectural_intent",
        "Credit-based (pipelined) design intent — no overflow analysis "
        "executed.")

    # F6: Routing correctness — the routes the simulator/RTL execute must
    # equal the resolved fabric routing. Evidence model (Wave B3.2):
    #   resolved_route_artifact  ResolvedRouteArtifact (topology+attachment+
    #                            router routes), self-integrity checked here
    #   executed_route_evidence  {provenance, resolved_route_hash, matches}
    #                            from the backend that actually executed
    # INVARIANT: two independently generated replicas of the same Python
    # algorithm are NOT evidence. Provenance must be an independent emitter;
    # replica provenance is INCONCLUSIVE, never PASS.
    _INDEPENDENT_ROUTE_PROVENANCE = frozenset({
        "booksim_dumped_table", "booksim_ingested_artifact",
        "rtl_emitted_table",
    })
    _REPLICA_ROUTE_PROVENANCE = frozenset({
        "python_replica", "anynet_replica", "booksim_first_hop_table",
        "replica",
    })
    resolved_d = ev.get("resolved_route_artifact")
    executed_ev = ev.get("executed_route_evidence")
    hash_note = None
    rra = None
    if resolved_d is not None:
        try:
            from .resolved_route import ResolvedRouteArtifact
            rra = ResolvedRouteArtifact.from_dict(resolved_d)
        except Exception as e:  # malformed evidence must FAIL, not crash
            hash_note = str(e)
    if hash_note is not None:
        add("F6_routing_correctness", "FAIL",
            "Executed routes equal resolved fabric routes",
            "resolved_route_equivalence (ResolvedRouteArtifact)",
            f"ResolvedRouteArtifact untrusted: {hash_note}", {})
        errors.append(
            f"F6: ResolvedRouteArtifact failed integrity verification: "
            f"{hash_note}")
    elif rra is None:
        add("F6_routing_correctness", "NOT_RUN",
            "Executed routes equal resolved fabric routes — requires a "
            "ResolvedRouteArtifact plus backend-executed route evidence",
            "resolved_route_equivalence (ResolvedRouteArtifact)",
            "Not executed: no ResolvedRouteArtifact binding topology, "
            "attachment and router routes. A router-level table or a derived "
            f"label ('{va.routing_function}') is not a fabric routing proof.")
    elif executed_ev is None:
        add("F6_routing_correctness", "NOT_RUN",
            "Executed routes equal resolved fabric routes — requires "
            "independently executed route evidence",
            "resolved_route_equivalence (ResolvedRouteArtifact)",
            "Not executed: no backend-emitted executed route table. A "
            "locally replicated routing algorithm cannot certify F6.",
            {"resolved_route_hash": rra.resolved_route_hash()})
    else:
        provenance = str(executed_ev.get("provenance", ""))
        if not provenance or provenance in _REPLICA_ROUTE_PROVENANCE:
            add("F6_routing_correctness", "INCONCLUSIVE",
                "Executed routes equal resolved fabric routes",
                "resolved_route_equivalence (ResolvedRouteArtifact)",
                f"Replica-vs-replica: route evidence provenance "
                f"{provenance or '<missing>'!r} is a Python replica, not an "
                "independent emitter. Python agreeing with Python is not a "
                "routing proof.",
                {"resolved_route_hash": rra.resolved_route_hash()})
        elif provenance not in _INDEPENDENT_ROUTE_PROVENANCE:
            add("F6_routing_correctness", "UNSUPPORTED",
                "Executed routes equal resolved fabric routes",
                "resolved_route_equivalence (ResolvedRouteArtifact)",
                f"Unknown route-evidence provenance {provenance!r}; supported "
                f"independent emitters: "
                f"{sorted(_INDEPENDENT_ROUTE_PROVENANCE)}",
                {"resolved_route_hash": rra.resolved_route_hash()})
        elif executed_ev.get("resolved_route_hash") \
                != rra.resolved_route_hash():
            add("F6_routing_correctness", "FAIL",
                "Executed routes equal resolved fabric routes",
                "resolved_route_equivalence (ResolvedRouteArtifact)",
                "executed evidence references a different resolved route "
                "hash — it certifies a different fabric",
                {"resolved_route_hash": rra.resolved_route_hash()})
            errors.append(
                "F6: executed route evidence references a different resolved "
                "route hash")
        elif executed_ev.get("matches") is True:
            add("F6_routing_correctness", "PASS",
                "Executed routes equal resolved fabric routes",
                "resolved_route_equivalence (ResolvedRouteArtifact)",
                f"resolved_route_hash={rra.resolved_route_hash()} matched by "
                f"independent emitter {provenance!r}",
                {"resolved_route_hash": rra.resolved_route_hash()})
        elif executed_ev.get("matches") is False:
            add("F6_routing_correctness", "FAIL",
                "Executed routes equal resolved fabric routes",
                "resolved_route_equivalence (ResolvedRouteArtifact)",
                f"independent emitter {provenance!r} reported divergence "
                "from the resolved route table",
                {"resolved_route_hash": rra.resolved_route_hash()})
            errors.append("F6: executed routes diverge from the resolved "
                          "route table")
        else:
            add("F6_routing_correctness", "INCONCLUSIVE",
                "Executed routes equal resolved fabric routes",
                "resolved_route_equivalence (ResolvedRouteArtifact)",
                f"provenance {provenance!r} declared but no comparison "
                "result was supplied",
                {"resolved_route_hash": rra.resolved_route_hash()})

    # F7: QoS isolation — no formal QoS check is implemented.
    if cr.requirements:
        add("F7_qos_isolation", "UNSUPPORTED",
            "Traffic classes do not starve — no implemented check",
            "none",
            f"{len(cr.requirements)} requirement(s) declared; formal QoS "
            "verification is not implemented.")
        warnings.append("F7: QoS isolation declared but no check implemented")
    else:
        add("F7_qos_isolation", "NOT_RUN",
            "Traffic classes do not starve",
            "none",
            "No QoS requirements declared — nothing to verify.")

    # F8: Timeout — real check when BookSim latency evidence is provided.
    lat = ev.get("max_packet_latency_cycles")
    bound = ev.get("latency_bound_cycles")
    if None not in (lat, bound):
        within = float(lat) <= float(bound)
        add("F8_timeout", "PASS" if within else "FAIL",
            "Maximum packet latency within the declared bound",
            "booksim_latency_bound",
            f"max_latency={lat}c, bound={bound}c",
            {"max_packet_latency_cycles": lat, "latency_bound_cycles": bound})
        if not within:
            errors.append(
                f"F8: latency bound exceeded ({lat}c > {bound}c)")
    else:
        add("F8_timeout", "NOT_RUN",
            "Bounded latency under load — requires BookSim latency evidence",
            "booksim_latency_bound (pending)",
            "Not executed: no BookSim latency evidence provided.")

    return VerificationResult(
        ok=len(errors) == 0,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )


# ══════════════════════════════════════════════════════════════════════════════
# §13.6 — Generate Stage
# ══════════════════════════════════════════════════════════════════════════════

import time as _time
import uuid as _uuid


def generate_artifacts(
    cr: CompileRequest,
    output_dir: str = "runs/artifacts",
) -> list[Artifact]:
    """PRD §13.6: Generate design artifacts.

    Produces a manifest artifact for each CompileRequest.
    RTL/UVM generation is delegated to external tools but tracked here.

    Args:
        cr: The CompileRequest.
        output_dir: Directory for generated files.

    Returns:
        List of Artifact entities with checksums.
    """
    design_id = str(_uuid.uuid4())[:8]
    revision = 1
    timestamp = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    artifacts: list[Artifact] = []

    # Integrity honesty (verified-PRD Integrity PR B, §3.13): this function
    # REGISTERS intended artifacts; it does not generate files. Entries for
    # files that do not exist yet are marked generated=False and must not be
    # presented (or exported) as generated content. The manifest is the one
    # exception: its checksum is computed over the actual CompileRequest
    # serialization held in memory, so it is real on creation.

    # Always generate manifest artifact
    manifest_content = json.dumps(cr.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    manifest_checksum = hashlib.sha256(manifest_content).hexdigest()
    artifacts.append(Artifact(
        artifact_id=f"{design_id}-manifest",
        design_id=design_id,
        revision=revision,
        kind="manifest",
        uri=f"{output_dir}/{design_id}/manifest.json",
        checksum_sha256=manifest_checksum,
        signature="",  # signed by DesignManifest
        timestamp=timestamp,
        generated=True,
    ))

    # Track RTL artifact if output format includes SystemVerilog
    if OutputFormat.SYSTEMVERILOG in cr.noc_config.output_formats:
        artifacts.append(Artifact(
            artifact_id=f"{design_id}-rtl",
            design_id=design_id,
            revision=revision,
            kind="rtl",
            uri=f"{output_dir}/{design_id}/noc.sv",
            checksum_sha256="",  # computable only after actual generation
            signature="",
            timestamp=timestamp,
            generated=False,  # registered, not yet produced
        ))

    # Track UVM artifact if output format includes UVM (PRD §9.3)
    if OutputFormat.UVM in cr.noc_config.output_formats:
        artifacts.append(Artifact(
            artifact_id=f"{design_id}-uvm",
            design_id=design_id,
            revision=revision,
            kind="uvm",
            uri=f"{output_dir}/{design_id}/tb_noc.sv",
            checksum_sha256="",  # computable only after actual generation
            signature="",
            timestamp=timestamp,
            generated=False,  # registered, not yet produced
        ))

    # Track report artifact
    artifacts.append(Artifact(
        artifact_id=f"{design_id}-report",
        design_id=design_id,
        revision=revision,
        kind="report",
        uri=f"{output_dir}/{design_id}/report.json",
        checksum_sha256="",
        signature="",
        timestamp=timestamp,
        generated=False,  # registered, not yet produced
    ))

    return artifacts
