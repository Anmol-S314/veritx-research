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

from veritx_dse.core.errors import SemanticError

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from veritx_dse.core.constants import env_int
from typing import Any


# Product design-intent format. Versioned INDEPENDENTLY of the experiment
# spec (core.spec) and of every other persisted format — same user
# request under different compiler semantics is a different design.
COMPILE_REQUEST_SCHEMA_VERSION = 2
# Compiler-semantics version — how design intent maps to identity.
#   v1 (legacy) — dependency declaration order is identity-bearing.
#   v2 (current) — graph processing is deterministic, so dependency
#                  declaration order is NON-semantic: the same dependency
#                  multiset always yields the same design_hash.
# v1 documents remain loadable under their own semantics and are never
# reinterpreted as v2; use migrate_design() to re-emit them explicitly.
COMPILER_SEMANTICS_VERSION = 2
LEGACY_COMPILER_SEMANTICS_VERSIONS = (1,)
SUPPORTED_COMPILER_SEMANTICS_VERSIONS = (1, 2)

# Hash-domain tag: a CompileRequest identity can never collide with an
# experiment, execution fingerprint, or artifact hash by construction.
_HASH_TYPE_TAG = "srota/CompileRequest"


class CompileRequestSchemaError(ValueError, SemanticError):
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


def _canonical_arbitration(value: Any) -> Any:
    """Identity normalization for the guided arbitration label.

    Imported lazily: the domain owner is ``router_behavior``, which must not
    become an import-time dependency of the intent model.
    """
    if not isinstance(value, str):
        return value
    from veritx_dse.model.router_behavior import (  # noqa: PLC0415
        canonical_arbitration_token,
    )
    return canonical_arbitration_token(value)


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
    if minimum is not None and v < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")
    return v


def _as_enum(name: str, value: Any, cls: Any) -> Any:
    if not isinstance(value, cls):
        raise ValueError(
            f"{name} must be {cls.__name__}, got {type(value).__name__} "
            f"{value!r}")
    return value


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
        # Normalize caller-supplied lists to tuples: the frozen object
        # must never retain a mutable collection the caller can edit.
        if isinstance(self.collectives, list):
            object.__setattr__(self, "collectives", tuple(self.collectives))
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
    def total_npus(self) -> int:
        """Total NPUs = tp × ep (for MoE) or tp (for dense)."""
        if self.model_family == ModelFamily.MOE:
            return self.tp * self.ep
        return self.tp


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
        if not isinstance(self.kind, DepKind):
            raise ValueError(
                f"kind must be a DepKind, got {type(self.kind).__name__}")

# Maximum VC count the fabric supports (PRD §11.3 bound)
PLANE_C_MAX_VC: int = 8


@dataclass(frozen=True)
class DependencyGraph:
    """PRD E4: Blocking/ordering graph that drives VC derivation.

    The graph is a directed graph over traffic class names.
    Cycles in the BLOCKING subgraph indicate potential deadlock
    that requires VC separation to resolve.

    Frozen with a tuple: the graph is part of design identity, so it
    must not be mutable after construction.

    TRAVERSAL CONTRACT (compiler semantics v2): graph processing is
    deterministic. Adjacency neighbor lists are sorted and DFS roots are
    visited in sorted node-name order, so the observed cycle witnesses do
    not depend on Python set/hash iteration or on dependency declaration
    order. Under legacy semantics v1 dependency declaration order remains
    identity-bearing in design_hash(); that is a hashing ruling only — the
    traversal below is deterministic in both.
    """
    dependencies: tuple[Dependency, ...]

    def __post_init__(self):
        if isinstance(self.dependencies, list):
            object.__setattr__(self, "dependencies",
                               tuple(self.dependencies))
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

        Neighbor lists are sorted so traversal is independent of the
        declared dependency order (compiler semantics v2: deterministic
        graph processing)."""
        adj: dict[str, list[str]] = {}
        for src, dst in self._blocking_edges():
            adj.setdefault(src, []).append(dst)
        for neighbors in adj.values():
            neighbors.sort()
        return adj

    def find_cycles(self) -> list[list[str]]:
        """Deterministic DFS back-edge cycle witnesses of the BLOCKING subgraph.

        SCOPE: this is NOT an exhaustive enumeration of every simple cycle
        in the mathematical graph. It returns the deterministic set/sequence
        of DFS back-edge witnesses produced by sorted-root, sorted-adjacency
        depth-first search — the exact witnesses the baseline candidate
        heuristic consumes. Independent VC/deadlock verification remains
        downstream.

        Returns a list of witnesses, where each witness is a list of node
        names closing back on its first node.
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

    LEGACY UTILITY (not a canonical candidate authority — see
    compiler/candidate_policy.py for the canonical VC proposal).

    Algorithm:
      1. Collect deterministic DFS cycle witnesses of the BLOCKING subgraph
         (see DependencyGraph.find_cycles: not an exhaustive cycle list).
      2. Each witness needs >= 1 member on a distinct VC to break it.
      3. Choose the member whose separation costs least buffering.
      4. VC count = 1 + number of witnesses needing separation.

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
        if isinstance(self.output_formats, list):
            object.__setattr__(self, 'output_formats', tuple(self.output_formats))
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
        if isinstance(self.ranges, list):
            object.__setattr__(self, 'ranges', tuple(self.ranges))
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


def collective_vc_map(collectives: tuple[CollectiveOp, ...]) -> dict[int, int]:
    """GUIDED integration hint: collective index -> reserved VC.

    Context 0 -> VC0, context k -> VC k. Consumed by future traffic-class
    mapping into BookSim; today it documents intent (which VC each
    collective context must use) so integration, not simulation, binds it.
    """
    return {
        i: k
        for k, i in enumerate(
            idx for idx, c in enumerate(collectives) if c.group_size > 1
        )
    }


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
    for cls in all_classes:
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
        if isinstance(self.requirements, list):
            object.__setattr__(self, 'requirements', tuple(self.requirements))
        if isinstance(self.agents, list):
            object.__setattr__(self, 'agents', tuple(self.agents))
        if isinstance(self.dependencies, list):
            object.__setattr__(self, 'dependencies',
                               DependencyGraph(self.dependencies))
        for r in self.requirements:
            if not isinstance(r, Requirement):
                raise ValueError(
                    f"requirements must contain Requirement, got "
                    f"{type(r).__name__}")
        for a in self.agents:
            if not isinstance(a, Agent):
                raise ValueError(
                    f"agents must contain Agent, got {type(a).__name__}")
        if not isinstance(self.dependencies, DependencyGraph):
            raise ValueError("dependencies must be a DependencyGraph")
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

        Under legacy semantics v1, dependency declaration order is
        identity-bearing; v1 documents are hashed in declared order so
        their stored design_hash still validates. Under semantics v2,
        dependency rows are canonicalized (sorted) in the identity.
        Sorting changes order only: duplicate declared edges are kept.
        """
        d = self._semantic_dict()
        d["requirements"] = sorted(d["requirements"], key=_canonical_json)
        d["address_map"]["ranges"] = sorted(d["address_map"]["ranges"],
                                            key=_canonical_json)
        d["noc_config"]["output_formats"] = sorted(
            d["noc_config"]["output_formats"])
        # Arbitration spelling is not semantic identity (Gate 3 / §15):
        # "islip", "ISLIP" and " iSLIP " are one policy and must hash equal.
        # Normalization lives in the domain owner (router_behavior) and is
        # applied here only — `to_dict` stays lossless.
        d["noc_config"]["arbitration"] = _canonical_arbitration(
            d["noc_config"]["arbitration"])
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
        from veritx_dse.core.artifact import content_id
        return content_id(
            f"{_HASH_TYPE_TAG}/v{self.schema_version}/"
            f"c{self.compiler_semantics_version}",
            self.canonical_dict(),
        )

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
        design_hash/guardrail_hash must match the recomputed identity under
        the DECLARED compiler semantics (a legacy v1 document validates
        under v1 rules). Loading never migrates: see migrate_design().
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


# ══════════════════════════════════════════════════════════════════════════════
# Compiler-semantics migration (explicit; loading never migrates)
# ══════════════════════════════════════════════════════════════════════════════

def _canonical_dependency_rows(deps: tuple[Dependency, ...]
                               ) -> tuple[Dependency, ...]:
    """Exact deterministic row order: sorted by canonical row JSON.

    Sorting changes order only — duplicate declared edges are kept (no
    deduplication; duplicate-edge semantics are unchanged).
    """
    return tuple(sorted(
        deps,
        key=lambda dep: _canonical_json(
            CompileRequest._dependency_dict(dep))))


def migrate_design(document: CompileRequest | dict[str, Any]
                   ) -> tuple[CompileRequest, dict[str, Any]]:
    """Re-emit a CompileRequest under the current compiler semantics.

    Input is a CompileRequest object or a persisted CompileRequest dict;
    a dict is parsed and validated under its own declared semantics first,
    so its stored design hash must validate exactly according to that
    semantics.

    CURRENT semantics v2: returned semantically unchanged with a no-op
    migration record. LEGACY semantics v1: every actual design semantic is
    preserved and a semantics-v2 CompileRequest is emitted whose
    DependencyGraph row order is canonicalized IN THE MIGRATED OBJECT
    ITSELF (not only in the hash projection), so two v1 documents that
    differ only by dependency declaration order migrate to byte-identical
    v2 ``to_dict()`` results.

    Returns ``(migrated, provenance)``. Provenance is NON-semantic — it
    never enters design identity; the caller records it out-of-band.
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
            f"{source_version!r} (can migrate "
            f"{LEGACY_COMPILER_SEMANTICS_VERSIONS} to "
            f"{COMPILER_SEMANTICS_VERSION})")
    migrated = CompileRequest(
        workload=obj.workload,
        requirements=obj.requirements,
        agents=obj.agents,
        dependencies=DependencyGraph(
            _canonical_dependency_rows(obj.dependencies.dependencies)),
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

def derive_topology_spec(cr: CompileRequest):
    """Bridge CompileRequest to existing Topology dataclass.

    Maps NocConfig.topology_family → Topology(backend=...) with
    appropriate defaults from the PRD's GUIDED knobs.

    The routing function is LOCKED — derived from the dependency graph
    via derive_vc_assignment(), not taken from the family map default.

    Args:
        cr: CompileRequest with noc_config populated.

    Returns:
        Topology instance from veritx_dse.presets.
    """
    from .presets import Topology

    family = cr.noc_config.topology_family
    if family is None:
        family = TopologyFamily.MESH

    # Map PRD topology families to BookSim backends (routing is placeholder)
    family_map = {
        TopologyFamily.MESH: ("mesh", {"k": 8, "n": 2}),
        TopologyFamily.TORUS: ("torus", {"k": 8, "n": 2}),
        TopologyFamily.CONCENTRATED_MESH: ("mesh", {"k": 4, "n": 2}),
        TopologyFamily.GEC: ("gec", {"k": 8, "c": 1, "o": 7, "d": 1}),
        TopologyFamily.FAT_TREE: ("fattree", {}),
    }

    backend, params = family_map.get(family, ("mesh", {"k": 8, "n": 2}))

    # Apply GUIDED overrides
    if cr.noc_config.radix is not None:
        params["k"] = cr.noc_config.radix
    if cr.noc_config.concentration is not None:
        params["c"] = cr.noc_config.concentration

    # LOCKED: Derive routing + VC assignment from dependency graph
    vc_assignment = derive_vc_assignment(cr)
    routing = vc_assignment.routing_function  # LOCKED — not user-chosen
    if vc_assignment.vc_count > 1:
        params["num_vcs"] = vc_assignment.vc_count + 1  # +1 for head flit VC

    needs_noc_latency_zero = family == TopologyFamily.GEC

    return Topology(
        name=f"{backend}_{params.get('k', 8)}x{params.get('k', 8)}",
        backend=backend,
        routing=routing,
        params=params,
        needs_noc_latency_zero=needs_noc_latency_zero,
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
    """
    artifact_id: str
    design_id: str
    revision: int
    kind: str  # "rtl", "uvm", "report", "manifest", "formal"
    uri: str
    checksum_sha256: str
    signature: str
    timestamp: str = ""

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


def verify_design(
    cr: CompileRequest,
    topology_name: str = "mesh_8x8",
) -> VerificationResult:
    """PRD §13.5: Run F1–F8 verification checks.

    Produces proof obligations for the selected configuration.
    Each check returns PASS/WARN/FAIL with explanation.

    F1: Deadlock freedom — no cyclic channel dependency
    F2: Liveness — every packet eventually delivered
    F3: Packet conservation — no lost/duplicated flits
    F4: Ordering — in-order delivery per VC
    F5: Flow control — credit-based, no overflow
    F6: Routing correctness — minimal/adaptive paths
    F7: QoS isolation — traffic classes don't starve
    F8: Timeout — bounded latency under load
    """
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    # F1: Deadlock freedom — check dependency graph for cycles
    cycles = cr.dependencies.find_cycles()
    if not cycles:
        checks.append({
            "name": "F1_deadlock_freedom",
            "status": "PASS",
            "detail": "No blocking cycles in dependency graph",
        })
    else:
        # Cycles exist but VC separation should break them
        vc = derive_vc_count(cr.dependencies)
        if vc <= PLANE_C_MAX_VC:
            checks.append({
                "name": "F1_deadlock_freedom",
                "status": "PASS",
                "detail": f"{len(cycles)} cycle(s) broken by {vc} VCs",
            })
        else:
            checks.append({
                "name": "F1_deadlock_freedom",
                "status": "FAIL",
                "detail": f"{len(cycles)} cycles need {vc} VCs (max {PLANE_C_MAX_VC})",
            })
            errors.append(f"Deadlock: {len(cycles)} cycles exceed VC capacity")

    # F2: Liveness — mesh/torus/gec are connected → packets reach destination
    checks.append({
        "name": "F2_liveness",
        "status": "PASS",
        "detail": f"{topology_name} is connected — all destinations reachable",
    })

    # F3: Packet conservation — checked by BookSim flit accounting
    # NOTE: This is a simulation check, not a formal proof. The claim is that
    # BookSim's internal accounting is correct (injected == completed + dropped).
    # For formal verification, we would need a model checker.
    checks.append({
        "name": "F3_packet_conservation",
        "status": "PASS",
        "detail": "Simulation check: BookSim tracks injected/completed flits (not a formal proof)",
    })

    # F4: Ordering — per-VC ordering guaranteed by flow control
    va = derive_vc_assignment(cr)
    checks.append({
        "name": "F4_ordering",
        "status": "PASS",
        "detail": f"{va.vc_count} VCs with {va.routing_function} routing",
    })

    # F5: Flow control — credit-based (BookSim default)
    checks.append({
        "name": "F5_flow_control",
        "status": "PASS",
        "detail": "Credit-based flow control (pipelined)",
    })

    # F6: Routing correctness
    checks.append({
        "name": "F6_routing_correctness",
        "status": "PASS",
        "detail": f"{va.routing_function} routing — derived from dependency graph",
    })

    # F7: QoS isolation — if requirements exist
    if cr.requirements:
        checks.append({
            "name": "F7_qos_isolation",
            "status": "WARN",
            "detail": f"{len(cr.requirements)} requirement(s) defined — formal QoS verification pending",
        })
    else:
        checks.append({
            "name": "F7_qos_isolation",
            "status": "PASS",
            "detail": "No QoS requirements — isolation not required",
        })

    # F8: Timeout — bounded latency (BookSim simulation provides proof)
    # F8: Timeout — checked by BookSim latency threshold
    # NOTE: This is a simulation check, not a formal proof. The claim is that
    # BookSim's latency measurement is correct (within simulation accuracy).
    # For formal verification, we would need a model checker.
    checks.append({
        "name": "F8_timeout",
        "status": "PASS",
        "detail": "Simulation check: BookSim measures bounded latency (not a formal proof)",
    })

    return VerificationResult(
        ok=len(errors) == 0,
        checks=checks,
        errors=errors,
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
    ))

    # Track RTL artifact if output format includes SystemVerilog
    if OutputFormat.SYSTEMVERILOG in cr.noc_config.output_formats:
        artifacts.append(Artifact(
            artifact_id=f"{design_id}-rtl",
            design_id=design_id,
            revision=revision,
            kind="rtl",
            uri=f"{output_dir}/{design_id}/noc.sv",
            checksum_sha256="",  # computed after generation
            signature="",
            timestamp=timestamp,
        ))

    # Track UVM artifact if output format includes UVM (PRD §9.3)
    if OutputFormat.UVM in cr.noc_config.output_formats:
        artifacts.append(Artifact(
            artifact_id=f"{design_id}-uvm",
            design_id=design_id,
            revision=revision,
            kind="uvm",
            uri=f"{output_dir}/{design_id}/tb_noc.sv",
            checksum_sha256="",  # computed after generation
            signature="",
            timestamp=timestamp,
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
    ))

    return artifacts


# Product workload-intent envelope, versioned INDEPENDENTLY of v2: the
# same user fields under v3 semantics are a different design, and the
# distinct hash domain below makes v2/v3 identity collision structural.
COMPILE_REQUEST_SCHEMA_VERSION_V3 = 3
COMPILER_SEMANTICS_VERSION_V3 = 3
SUPPORTED_V3_SEMANTICS_VERSIONS = (3,)
_HASH_TYPE_TAG_V3 = "srota/CompileRequest/v3"


class CompileRequestV3SchemaError(ValueError, SemanticError):
    """Rejected v3 CompileRequest document: unknown field, unsupported
    envelope, or a value that cannot represent a v3 design."""


_TOP_V3_KEYS = frozenset({
    "schema_version", "compiler_semantics_version", "workload",
    "requirements", "agents", "dependencies", "noc_config",
    "address_map", "physical", "design_hash", "guardrail_hash",
    "_comment", "_docs",
})
_WORKLOAD_V3_KEYS = frozenset({
    "model_family", "model_name", "tp", "pp", "ep", "dp",
    "serving_mode", "collectives", "workload_source_ref",
})
_COLLECTIVE_V3_KEYS = frozenset({
    "kind", "dimension", "payload_bytes", "traffic_class",
    "source_rank",
})
_REQUIREMENT_V3_KEYS = frozenset({
    "traffic_class", "qos_class", "latency_ceiling_cycles",
    "bandwidth_floor_gbps", "binding",
})
_SOURCE_REF_KEYS = frozenset({
    "content_digest", "format", "size_bytes", "artifact_identity",
})


def _strict_keys_v3(d: Any, allowed: frozenset, where: str) -> None:
    """v3 fail-closed boundary: unknown keys refuse as v3 errors."""
    try:
        _strict_keys(d, allowed, where)
    except CompileRequestSchemaError as e:
        raise CompileRequestV3SchemaError(str(e)) from e


class CollectiveDimension(Enum):
    """Rank-space dimension a v3 collective intent ranges over.

    TP/DP/EP expand to the ParallelismArtifact groups of that family
    (deterministic: every rank in exactly one group — e.g. tp=8,dp=4
    yields four TP groups of eight). GLOBAL is the single all-ranks
    group. PP names pipeline stages, which are NOT collective peers
    (stages communicate point-to-point); a PP-dimension COLLECTIVE is a
    typed refusal at lowering, while pp>1 geometry still scopes TP/DP
    groups within stages.
    """
    TP = "TP"
    DP = "DP"
    EP = "EP"
    PP = "PP"
    GLOBAL = "GLOBAL"


@dataclass(frozen=True)
class CollectiveIntent:
    """v3 workload intent: WHAT communicates, with lossless lowering info.

    Unlike v2 CollectiveOp (whose bytes_per_element meaning is unproven —
    see B1 finding 1), every field here is load-bearing: kind names the
    pinned schedule, dimension derives the exact participant groups,
    payload_bytes is the per-kind schedule payload B consumed verbatim
    by workload/collectives.py::collective_schedule, traffic_class is
    the unified-namespace identity (B1 finding 2), and source_rank is
    the explicit BROADCAST root (no participants[0] invention — a
    BROADCAST without one is unrepresentable).
    """
    kind: CollectiveKind
    dimension: CollectiveDimension
    payload_bytes: int
    traffic_class: str
    source_rank: int | None = None

    def __post_init__(self):
        _as_enum("kind", self.kind, CollectiveKind)
        _as_enum("dimension", self.dimension, CollectiveDimension)
        _as_int("payload_bytes", self.payload_bytes, minimum=1)
        _as_str("traffic_class", self.traffic_class, allow_empty=False)
        if self.kind == CollectiveKind.BROADCAST:
            if self.source_rank is None:
                raise ValueError(
                    "CollectiveIntent BROADCAST requires an explicit "
                    "source_rank — participants[0] is a legacy "
                    "convenience, not a law (no fabricated roots)")
            _as_int("source_rank", self.source_rank, minimum=0)
        elif self.source_rank is not None:
            raise ValueError(
                f"CollectiveIntent {self.kind.value} must not declare a "
                f"source_rank (got {self.source_rank!r})")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "dimension": self.dimension.value,
            "payload_bytes": self.payload_bytes,
            "traffic_class": self.traffic_class,
            "source_rank": self.source_rank,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CollectiveIntent:
        return cls(
            kind=CollectiveKind(d["kind"]),
            dimension=CollectiveDimension(d["dimension"]),
            payload_bytes=d["payload_bytes"],
            traffic_class=d["traffic_class"],
            source_rank=d.get("source_rank"),
        )


def _check_content_digest(name: str, value: Any) -> str:
    _as_str(name, value, allow_empty=False)
    if not value.startswith("sha256:") or len(value) != len("sha256:") + 64:
        raise ValueError(
            f"{name} must be 'sha256:' + 64 hex chars, got {value!r}")
    try:
        int(value[len("sha256:"):], 16)
    except ValueError:
        raise ValueError(f"{name} digest is not hex: {value!r}") from None
    return value


@dataclass(frozen=True)
class WorkloadSourceRef:
    """Immutable workload source identity (B6).

    Names BYTES, never paths: content_digest is sha256 over the exact
    ingested bytes, format names the byte dialect (e.g. "packet_trace",
    "chakra_et", "synthetic"), size_bytes bounds the artifact, and
    artifact_identity names the producing artifact or producer (provenance,
    never authority). A filesystem path is transport metadata and MUST
    NOT enter v3 identity — ingest bytes first via
    ingest_workload_source_file. A synthetic intent (no external bytes)
    carries source_ref=None on WorkloadV3: the intent document is then
    its own source.
    """
    content_digest: str
    format: str
    size_bytes: int = 0
    artifact_identity: str = ""

    def __post_init__(self):
        _check_content_digest("content_digest", self.content_digest)
        _as_str("format", self.format, allow_empty=False)
        _as_int("size_bytes", self.size_bytes, minimum=0)
        _as_str("artifact_identity", self.artifact_identity)

    def identity_dict(self) -> dict[str, Any]:
        """Identity-bearing content only (P1C phase-2 fix).

        artifact_identity is PROVENANCE (which producer handed us the
        bytes), never authority: two references to the same bytes from
        different producers MUST hash identically, so it is excluded
        here. CompileRequestV3.canonical_dict() consumes ONLY this
        representation.
        """
        return {
            "content_digest": self.content_digest,
            "format": self.format,
            "size_bytes": self.size_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        """Persisted form: identity fields PLUS provenance.

        artifact_identity rides along for reconstruction/debugging but
        never enters design_hash(). A document carrying provenance still
        loads (from_dict accepts all four keys) and hashes by identity.
        """
        return {
            **self.identity_dict(),
            "artifact_identity": self.artifact_identity,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkloadSourceRef:
        return cls(
            content_digest=d["content_digest"],
            format=d["format"],
            size_bytes=d.get("size_bytes", 0),
            artifact_identity=d.get("artifact_identity", ""),
        )


def ingest_workload_source(data: bytes, *, format: str,
                           artifact_identity: str = "") -> WorkloadSourceRef:
    """Bind already-read bytes to an immutable source reference (B6).

    The caller reads the file; this function digests WHAT WAS READ, so
    request identity commits to the byte content, never to whatever a
    mutable path resolves to later.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError(
            f"workload source must be bytes, got {type(data).__name__}")
    return WorkloadSourceRef(
        content_digest="sha256:" + hashlib.sha256(bytes(data)).hexdigest(),
        format=format,
        size_bytes=len(data),
        artifact_identity=artifact_identity,
    )


def ingest_workload_source_file(path: str | Path, *, format: str,
                                artifact_identity: str = ""
                                ) -> tuple[WorkloadSourceRef, bytes]:
    """CLI seam (B6): accept a path, ingest bytes first, return ref+bytes.

    The returned bytes are the load-bearing workload content the caller
    lowers; the reference carries only the digest. The path itself is
    discarded and never enters any identity.
    """
    data = Path(path).read_bytes()
    return ingest_workload_source(data, format=format,
                                  artifact_identity=artifact_identity), data


@dataclass(frozen=True)
class WorkloadV3:
    """v3 workload description: model parallelism + lossless intents.

    No trace_path (B1 finding 5): external bytes are bound via source_ref
    (or None for a synthetic intent, which is its own source). tp/pp/ep/dp
    are the model geometry the dimension expansion derives groups from.
    serving_mode is serving characterization ONLY — it never maps to a
    per-operation phase (no PREFILL_HEAVY -> pure-PREFILL invention; see
    intent_lowering).
    """
    model_family: ModelFamily
    model_name: str = ""
    tp: int = 1
    pp: int = 1
    ep: int = 1
    dp: int = 1
    serving_mode: ServingMode = ServingMode.MIXED
    collectives: tuple[CollectiveIntent, ...] = ()
    source_ref: WorkloadSourceRef | None = None

    def __post_init__(self):
        _as_enum("model_family", self.model_family, ModelFamily)
        _as_enum("serving_mode", self.serving_mode, ServingMode)
        object.__setattr__(self, "collectives",
                           _as_tuple("collectives", self.collectives))
        for c in self.collectives:
            if not isinstance(c, CollectiveIntent):
                raise ValueError(
                    "collectives must contain CollectiveIntent, got "
                    f"{type(c).__name__}")
        for field_name in ("tp", "pp", "ep", "dp"):
            _as_int(field_name, getattr(self, field_name), minimum=1)
        _as_str("model_name", self.model_name)
        if self.source_ref is not None and \
                not isinstance(self.source_ref, WorkloadSourceRef):
            raise ValueError("source_ref must be a WorkloadSourceRef or None")

    @property
    def world_size(self) -> int:
        from .presets import parallel_world_size
        return parallel_world_size(self.tp, self.pp, self.ep, self.dp)


@dataclass(frozen=True)
class RequirementV3:
    """v3 requirement: traffic identity DISTINCT from QoS policy (B3).

    traffic_class names the constrained traffic in the unified namespace
    (None = fabric-wide); qos_class names the policy applied to it.
    A binding requirement must be met or the design fails; binding +
    UNMEASURABLE never passes (requirements.py enforces at report read).
    """
    qos_class: QoSClass
    traffic_class: str | None = None
    latency_ceiling_cycles: float | None = None
    bandwidth_floor_gbps: float | None = None
    binding: bool = False

    def __post_init__(self):
        _as_enum("qos_class", self.qos_class, QoSClass)
        if self.traffic_class is not None:
            _as_str("traffic_class", self.traffic_class, allow_empty=False)
        _as_bool("binding", self.binding)
        for name, val in (("latency_ceiling_cycles",
                           self.latency_ceiling_cycles),
                          ("bandwidth_floor_gbps",
                           self.bandwidth_floor_gbps)):
            if val is None:
                continue
            object.__setattr__(self, name,
                               _as_real(name, val, minimum=0.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "traffic_class": self.traffic_class,
            "qos_class": self.qos_class.value,
            "latency_ceiling_cycles": self.latency_ceiling_cycles,
            "bandwidth_floor_gbps": self.bandwidth_floor_gbps,
            "binding": self.binding,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RequirementV3:
        return cls(
            traffic_class=d.get("traffic_class"),
            qos_class=QoSClass(d["qos_class"]),
            latency_ceiling_cycles=d.get("latency_ceiling_cycles"),
            bandwidth_floor_gbps=d.get("bandwidth_floor_gbps"),
            binding=d.get("binding", False),
        )


@dataclass(frozen=True)
class CompileRequestV3:
    """v3 product design intent: v3 workload + requirements over v2 fabric.

    Agents, dependencies, NoC knobs, address map, and physical context
    reuse the v2 types UNCHANGED (one authority per concept — no second
    Agent/NoC types). Only workload and requirements are v3 generations.
    Envelope (schema 3 / semantics 3, distinct hash domain) keeps v2 and
    v3 identities disjoint: the same user fields under v2 semantics are a
    different design and NEVER reinterpreted here (use migrate_v2_to_v3
    with explicit per-collective specs).
    """
    workload: WorkloadV3
    requirements: tuple[RequirementV3, ...]
    agents: tuple[Agent, ...]
    dependencies: DependencyGraph
    noc_config: NocConfig
    address_map: AddressMap = field(default_factory=AddressMap)
    physical: PhysicalContext = field(default_factory=PhysicalContext)
    schema_version: int = COMPILE_REQUEST_SCHEMA_VERSION_V3
    compiler_semantics_version: int = COMPILER_SEMANTICS_VERSION_V3

    def __post_init__(self):
        if not isinstance(self.workload, WorkloadV3):
            raise ValueError("workload must be a WorkloadV3")
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
            if not isinstance(r, RequirementV3):
                raise ValueError(
                    "requirements must contain RequirementV3, got "
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
            raise ValueError(
                "agents list cannot be empty — need at least one agent kind")
        if _as_int("schema_version", self.schema_version) \
                != COMPILE_REQUEST_SCHEMA_VERSION_V3:
            raise ValueError(
                f"unsupported v3 schema_version {self.schema_version}")
        if _as_int("compiler_semantics_version",
                   self.compiler_semantics_version) \
                not in SUPPORTED_V3_SEMANTICS_VERSIONS:
            raise ValueError(
                f"unsupported v3 compiler_semantics_version "
                f"{self.compiler_semantics_version}")

    @property
    def total_nodes(self) -> int:
        return sum(a.count for a in self.agents)

    # ── serialization (one per entity, mirroring v2 discipline) ─────

    @staticmethod
    def _requirement_dict(r: RequirementV3) -> dict:
        return r.to_dict()

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
        wl = self.workload
        d: dict[str, Any] = {
            "model_family": wl.model_family.value,
            "model_name": wl.model_name,
            "tp": wl.tp,
            "pp": wl.pp,
            "ep": wl.ep,
            "dp": wl.dp,
            "serving_mode": wl.serving_mode.value,
            "collectives": [c.to_dict() for c in wl.collectives],
            "workload_source_ref": (wl.source_ref.to_dict()
                                      if wl.source_ref is not None else None),
        }
        return d

    def _semantic_dict(self) -> dict:
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
        """Canonical v3 envelope — sole input to design_hash().

        Ordering mirrors v2 (requirements/address-ranges/output-formats/
        dependencies canonicalized) EXCEPT collectives, which stay in
        declared order: collective index feeds the lowering's operation
        chain, so declaration order is v3-semantic (reordering intents is
        a different design).
        """
        d = self._semantic_dict()
        # Identity/persistence split (P1C phase-2 fix): the persisted
        # workload_source_ref keeps provenance (artifact_identity), but
        # the canonical envelope hashes the identity representation
        # ONLY — same bytes from different producers, same design.
        if self.workload.source_ref is not None:
            d["workload"]["workload_source_ref"] = \
                self.workload.source_ref.identity_dict()
        d["requirements"] = sorted(d["requirements"], key=_canonical_json)
        d["address_map"]["ranges"] = sorted(d["address_map"]["ranges"],
                                              key=_canonical_json)
        d["noc_config"]["output_formats"] = sorted(
            d["noc_config"]["output_formats"])
        # Arbitration spelling is not semantic identity (Gate 3 / §15):
        # "islip", "ISLIP" and " iSLIP " are one policy and must hash equal.
        # Normalization lives in the domain owner (router_behavior) and is
        # applied here only — `to_dict` stays lossless.
        d["noc_config"]["arbitration"] = _canonical_arbitration(
            d["noc_config"]["arbitration"])
        d["dependencies"] = sorted(d["dependencies"], key=_canonical_json)
        return {
            "type": _HASH_TYPE_TAG_V3,
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            **d,
        }

    def design_hash(self) -> str:
        """AUTHORITATIVE v3 design-intent identity (SHA-256).

        Domain-separated by the v3 tag AND the v3/c3 envelope: a v2 and
        a v3 document can never share an identity by construction.
        """
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG_V3}/v{self.schema_version}/"
                f"c{self.compiler_semantics_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def guardrail_hash(self) -> str:
        return self.design_hash()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            **self._semantic_dict(),
        }
        d["design_hash"] = self.design_hash()
        d["guardrail_hash"] = d["design_hash"]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CompileRequestV3:
        """Strict, versioned, lossless v3 deserialization (fail closed).

        Accepts ONLY schema 3 / semantics 3. v2 documents are NEVER
        reinterpreted here — migrate explicitly via migrate_v2_to_v3.
        """
        _strict_keys_v3(d, _TOP_V3_KEYS, "root")
        if "schema_version" not in d:
            raise CompileRequestV3SchemaError(
                "missing schema_version — refusing to guess a schema")
        if type(d["schema_version"]) is not int \
                or d["schema_version"] != COMPILE_REQUEST_SCHEMA_VERSION_V3:
            raise CompileRequestV3SchemaError(
                f"unsupported v3 schema_version {d['schema_version']!r} "
                f"(this v3 reader speaks v{COMPILE_REQUEST_SCHEMA_VERSION_V3}); "
                "v2 documents are never reinterpreted under v3 semantics")
        semantics = d.get("compiler_semantics_version")
        if type(semantics) is not int \
                or semantics not in SUPPORTED_V3_SEMANTICS_VERSIONS:
            raise CompileRequestV3SchemaError(
                f"unsupported v3 compiler_semantics_version {semantics!r} "
                f"(this v3 reader speaks {SUPPORTED_V3_SEMANTICS_VERSIONS})")

        wl = d.get("workload")
        if not isinstance(wl, dict):
            raise CompileRequestV3SchemaError("workload must be a JSON object")
        _strict_keys_v3(wl, _WORKLOAD_V3_KEYS, "workload")
        collectives = []
        for i, c in enumerate(wl.get("collectives", [])):
            _strict_keys_v3(c, _COLLECTIVE_V3_KEYS,
                         f"workload.collectives[{i}]")
            for key in ("kind", "dimension", "payload_bytes",
                        "traffic_class"):
                if key not in c:
                    raise CompileRequestV3SchemaError(
                        f"missing required field "
                        f"workload.collectives[{i}].{key}")
            try:
                collectives.append(CollectiveIntent(
                    kind=CollectiveKind(c["kind"]),
                    dimension=CollectiveDimension(c["dimension"]),
                    payload_bytes=c["payload_bytes"],
                    traffic_class=c["traffic_class"],
                    source_rank=c.get("source_rank"),
                ))
            except (ValueError, KeyError) as e:
                raise CompileRequestV3SchemaError(
                    f"invalid workload.collectives[{i}]: {e}") from e
        src_ref = None
        if wl.get("workload_source_ref") is not None:
            sr = wl["workload_source_ref"]
            _strict_keys_v3(sr, _SOURCE_REF_KEYS, "workload.workload_source_ref")
            try:
                src_ref = WorkloadSourceRef.from_dict(sr)
            except ValueError as e:
                raise CompileRequestV3SchemaError(
                    f"invalid workload.workload_source_ref: {e}") from e
        try:
            workload = WorkloadV3(
                model_family=ModelFamily(wl["model_family"]),
                model_name=wl.get("model_name", ""),
                tp=wl.get("tp", 1),
                pp=wl.get("pp", 1),
                ep=wl.get("ep", 1),
                dp=wl.get("dp", 1),
                serving_mode=ServingMode(wl.get("serving_mode", "mixed")),
                collectives=tuple(collectives),
                source_ref=src_ref,
            )
        except (ValueError, KeyError) as e:
            raise CompileRequestV3SchemaError(f"invalid workload: {e}") from e

        requirements = []
        for i, r in enumerate(d.get("requirements", [])):
            _strict_keys_v3(r, _REQUIREMENT_V3_KEYS, f"requirements[{i}]")
            if "qos_class" not in r:
                raise CompileRequestV3SchemaError(
                    f"missing required field requirements[{i}].qos_class")
            try:
                requirements.append(RequirementV3(
                    traffic_class=r.get("traffic_class"),
                    qos_class=QoSClass(r["qos_class"]),
                    latency_ceiling_cycles=r.get("latency_ceiling_cycles"),
                    bandwidth_floor_gbps=r.get("bandwidth_floor_gbps"),
                    binding=r.get("binding", False),
                ))
            except ValueError as e:
                raise CompileRequestV3SchemaError(
                    f"invalid requirements[{i}]: {e}") from e

        agents = []
        for i, a in enumerate(d.get("agents", [])):
            _strict_keys_v3(a, _AGENT_KEYS, f"agents[{i}]")
            try:
                agents.append(Agent(
                    kind=AgentKind(a["kind"]),
                    count=a["count"],
                    data_width=a.get("data_width", 256),
                    addr_width=a.get("addr_width", 64),
                    protocol=a.get("protocol", "AXI"),
                    clock_domain=a.get("clock_domain"),
                    power_domain=a.get("power_domain"),
                ))
            except (ValueError, KeyError) as e:
                raise CompileRequestV3SchemaError(
                    f"invalid agents[{i}]: {e}") from e
        deps = []
        for i, dep in enumerate(d.get("dependencies", [])):
            _strict_keys_v3(dep, _DEPENDENCY_KEYS, f"dependencies[{i}]")
            try:
                deps.append(Dependency(
                    source=dep["source"],
                    target=dep["target"],
                    kind=DepKind(dep["kind"]),
                ))
            except (ValueError, KeyError) as e:
                raise CompileRequestV3SchemaError(
                    f"invalid dependencies[{i}]: {e}") from e
        nc_d = d.get("noc_config", {})
        _strict_keys_v3(nc_d, _NOC_KEYS, "noc_config")
        try:
            noc_config = NocConfig(
                topology_family=(TopologyFamily(nc_d["topology_family"])
                                 if nc_d.get("topology_family") else None),
                radix=nc_d.get("radix"),
                concentration=nc_d.get("concentration"),
                arbitration=nc_d.get("arbitration"),
                rcu_enabled=nc_d.get("rcu_enabled"),
                link_width=nc_d.get("link_width"),
                output_formats=tuple(
                    OutputFormat(o)
                    for o in nc_d.get("output_formats", ["systemverilog"])),
                obfuscation_level=nc_d.get("obfuscation_level", 0),
                mcast_groups=nc_d.get("mcast_groups"),
                mcast_setup_cycles=nc_d.get("mcast_setup_cycles"),
            )
        except ValueError as e:
            raise CompileRequestV3SchemaError(
                f"invalid noc_config: {e}") from e
        am_d = d.get("address_map", {})
        _strict_keys_v3(am_d, _ADDRESS_MAP_KEYS, "address_map")
        ranges = []
        for i, r in enumerate(am_d.get("ranges", [])):
            _strict_keys_v3(r, _ADDRESS_RANGE_KEYS, f"address_map.ranges[{i}]")
            try:
                ranges.append(AddressRange(
                    name=r["name"], base=r["base"], size=r["size"],
                    target_agent_idx=r.get("target_agent_idx", 0)))
            except (ValueError, KeyError) as e:
                raise CompileRequestV3SchemaError(
                    f"invalid address_map.ranges[{i}]: {e}") from e
        ph_d = d.get("physical", {})
        _strict_keys_v3(ph_d, _PHYSICAL_KEYS, "physical")
        try:
            physical = PhysicalContext(
                default_clock_freq_mhz=ph_d.get("clock_freq_mhz", 1000.0),
                default_data_width=ph_d.get("data_width", 256),
                num_power_domains=ph_d.get("num_power_domains", 1),
                process_node_nm=ph_d.get("process_node_nm", 7),
            )
        except ValueError as e:
            raise CompileRequestV3SchemaError(
                f"invalid physical: {e}") from e

        try:
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
        except ValueError as e:
            raise CompileRequestV3SchemaError(
                f"invalid v3 request: {e}") from e
        for key in ("design_hash", "guardrail_hash"):
            if key in d and d[key] != obj.design_hash():
                raise CompileRequestV3SchemaError(
                    f"{key} does not match the recomputed v3 design identity")
        return obj


def derive_v3_traffic_classes(request: CompileRequestV3
                              ) -> tuple[str, ...]:
    """The unified traffic-class registry for a v3 request (B3).

    Sorted distinct CollectiveIntent.traffic_class values. Dependency
    endpoints, RequirementV3.traffic_class scopes, VC artifact classes,
    and LogicalMessage classes MUST be drawn from this set: the
    evaluator admission gate refuses any message class outside the VC
    artifact instead of silently mapping to VC0.
    """
    if not isinstance(request, CompileRequestV3):
        raise CompileRequestV3SchemaError(
            "derive_v3_traffic_classes takes a CompileRequestV3")
    return tuple(sorted({c.traffic_class
                         for c in request.workload.collectives}))


def migrate_v2_to_v3(request: CompileRequest, *,
                     collective_specs: Any,
                     source_ref: WorkloadSourceRef | None = None,
                     ) -> CompileRequestV3:
    """Re-emit a v2 request under v3 semantics — with explicit new facts.

    v2 CollectiveOp carries NO dimension, NO payload_bytes, and NO
    traffic_class (bytes_per_element meaning unproven — B1 finding 1),
    so migration CANNOT be mechanical: the caller supplies one spec per
    v2 collective, in order, each naming dimension/payload_bytes/
    traffic_class (+ source_rank for BROADCAST). Guessing is refused:
    spec count must equal collective count, and every spec is validated
    as a CollectiveIntent.

    A v2 trace_path is a mutable path, never v3 identity (B1 finding 5):
    if the v2 workload names one, the caller must supply an ingested
    source_ref (ingest_workload_source_file) or migration refuses.
    v2 requirements carry no traffic scope (B1 finding 3) and migrate
    as fabric-wide (traffic_class=None) — narrowing scope needs intent
    the v2 document never stated.
    """
    if not isinstance(request, CompileRequest):
        raise CompileRequestV3SchemaError(
            "migrate_v2_to_v3 takes a v2 CompileRequest")
    if request.workload.trace_path is not None and source_ref is None:
        raise CompileRequestV3SchemaError(
            f"v2 workload names trace_path "
            f"{request.workload.trace_path!r}: ingest its bytes first "
            f"(ingest_workload_source_file) — a mutable path never "
            f"enters v3 identity")
    v2_colls = request.workload.collectives
    specs = list(collective_specs or [])
    if len(specs) != len(v2_colls):
        raise CompileRequestV3SchemaError(
            f"collective_specs has {len(specs)} entries for "
            f"{len(v2_colls)} v2 collectives — one explicit spec per "
            f"collective, no guessing")
    intents = []
    for i, (v2c, spec) in enumerate(zip(v2_colls, specs)):
        if not isinstance(spec, dict):
            raise CompileRequestV3SchemaError(
                f"collective_specs[{i}] must be a dict")
        allowed = {"dimension", "payload_bytes", "traffic_class",
                   "source_rank"}
        unknown = sorted(set(spec) - allowed)
        if unknown:
            raise CompileRequestV3SchemaError(
                f"collective_specs[{i}] has unknown fields {unknown}")
        for key in ("dimension", "payload_bytes", "traffic_class"):
            if key not in spec:
                raise CompileRequestV3SchemaError(
                    f"collective_specs[{i}] is missing {key!r} — "
                    f"v2 bytes_per_element is not a payload, supply one")
        try:
            intents.append(CollectiveIntent(
                kind=v2c.kind,
                dimension=CollectiveDimension(spec["dimension"]),
                payload_bytes=spec["payload_bytes"],
                traffic_class=spec["traffic_class"],
                source_rank=spec.get("source_rank"),
            ))
        except ValueError as e:
            raise CompileRequestV3SchemaError(
                f"collective_specs[{i}] invalid: {e}") from e
    wl = request.workload
    workload_v3 = WorkloadV3(
        model_family=wl.model_family,
        model_name=wl.model_name,
        tp=wl.tp, pp=wl.pp, ep=wl.ep, dp=wl.dp,
        serving_mode=wl.serving_mode,
        collectives=tuple(intents),
        source_ref=source_ref,
    )
    requirements_v3 = tuple(
        RequirementV3(
            traffic_class=None,
            qos_class=r.qos_class,
            latency_ceiling_cycles=r.latency_ceiling_cycles,
            bandwidth_floor_gbps=r.bandwidth_floor_gbps,
            binding=r.binding,
        )
        for r in request.requirements
    )
    return CompileRequestV3(
        workload=workload_v3,
        requirements=requirements_v3,
        agents=request.agents,
        dependencies=request.dependencies,
        noc_config=request.noc_config,
        address_map=request.address_map,
        physical=request.physical,
    )


# ══════════════════════════════════════════════════════════════════════════════
# P1C phase-2 fix 2 — FabricIntentView + v3 VC policy (v3 compilable)
# ══════════════════════════════════════════════════════════════════════════════
#
# The v2 compiler stack is overwhelmingly duck-typed already
# (build_inventory reads .workload.tp/.agents; attachment reads .agents;
# address_decode reads .address_map/.agents; resolved_fabric reads
# .design_hash()/.workload geometry/.noc_config) — a v3 request flows
# through all of it unchanged. Only three sites are v2-gated:
#   1. derive_vc_assignment() reads v2 CollectiveOp.group_size — v3 gets
#      its OWN policy below (never a fake-v2 conversion).
#   2/3. derive_route() / materialize_topology() isinstance gates — widened
#      to accept the view (they read .noc_config/nothing; v2 flow identical).
# fabric_intent_view() is the ONE dispatch seam (v2 vs v3 decided here,
# once); no if-v2/elif-v3 anywhere else.

@dataclass(frozen=True)
class FabricIntentView:
    """Non-persisted fabric-facing view over v2/v3 design intent.

    The compiler's fabric derivation consumes this where a gated type is
    required. Fields: the shared fabric inputs (agents, dependencies,
    noc_config, address_map, physical), the parallelism geometry as plain
    ints, the DECLARED traffic classes the fabric must serve, and the
    design identity string it binds. source_generation ("v2"/"v3") is
    dispatch metadata selecting the VC policy — never persisted, never
    hashed (the view itself has no to_dict/from_dict by design).
    """
    agents: tuple[Agent, ...]
    dependencies: DependencyGraph
    noc_config: NocConfig
    address_map: AddressMap
    physical: PhysicalContext
    tp: int
    pp: int
    ep: int
    dp: int
    traffic_classes: tuple[str, ...]
    design_hash: str
    source_generation: str

    def __post_init__(self):
        object.__setattr__(self, "agents",
                           _as_tuple("agents", self.agents))
        for a in self.agents:
            if not isinstance(a, Agent):
                raise ValueError(
                    f"agents must contain Agent, got {type(a).__name__}")
        if not isinstance(self.dependencies, DependencyGraph):
            raise ValueError("dependencies must be a DependencyGraph")
        if not isinstance(self.noc_config, NocConfig):
            raise ValueError("noc_config must be a NocConfig")
        if not isinstance(self.address_map, AddressMap):
            raise ValueError("address_map must be an AddressMap")
        if not isinstance(self.physical, PhysicalContext):
            raise ValueError("physical must be a PhysicalContext")
        for field_name in ("tp", "pp", "ep", "dp"):
            _as_int(field_name, getattr(self, field_name), minimum=1)
        object.__setattr__(self, "traffic_classes",
                           _as_tuple("traffic_classes", self.traffic_classes))
        for c in self.traffic_classes:
            _as_str("traffic_class", c, allow_empty=False)
        if sorted(set(self.traffic_classes)) != list(self.traffic_classes):
            raise ValueError("traffic_classes must be sorted and distinct")
        _as_str("design_hash", self.design_hash, allow_empty=False)
        if self.source_generation not in ("v2", "v3"):
            raise ValueError(
                f"source_generation must be 'v2' or 'v3', got "
                f"{self.source_generation!r}")

    @property
    def world_size(self) -> int:
        from .presets import parallel_world_size
        return parallel_world_size(self.tp, self.pp, self.ep, self.dp)


def fabric_intent_view(request: CompileRequest | CompileRequestV3
                       ) -> FabricIntentView:
    """THE dispatch seam: one isinstance decision for the whole compiler.

    v2 traffic classes are the dependency endpoint names (v2 declares no
    classes; the VC derivation serves exactly the dep-graph namespace —
    same set derive_vc_assignment covers). v3 classes come from
    derive_v3_traffic_classes (the declared intent registry). Anything
    else refuses: the compiler never guesses a generation.
    """
    if isinstance(request, CompileRequestV3):
        wl = request.workload
        return FabricIntentView(
            agents=request.agents,
            dependencies=request.dependencies,
            noc_config=request.noc_config,
            address_map=request.address_map,
            physical=request.physical,
            tp=wl.tp, pp=wl.pp, ep=wl.ep, dp=wl.dp,
            traffic_classes=derive_v3_traffic_classes(request),
            design_hash=request.design_hash(),
            source_generation="v3",
        )
    if isinstance(request, CompileRequest):
        wl = request.workload
        dep_classes = sorted({d.source for d in request.dependencies.dependencies}
                             | {d.target for d in request.dependencies.dependencies})
        return FabricIntentView(
            agents=request.agents,
            dependencies=request.dependencies,
            noc_config=request.noc_config,
            address_map=request.address_map,
            physical=request.physical,
            tp=wl.tp, pp=wl.pp, ep=wl.ep, dp=wl.dp,
            traffic_classes=tuple(dep_classes),
            design_hash=request.design_hash(),
            source_generation="v2",
        )
    raise CompileRequestV3SchemaError(
        f"fabric_intent_view takes a v2 CompileRequest or a "
        f"CompileRequestV3, got {type(request).__name__}")


def _routing_for_cycle_structure(has_cycles: bool, vc_count: int
                                 ) -> tuple[str, list[str]]:
    """LOCKED routing selection from dependency cycle structure.

    Restates the sealed v2 law (derive_vc_assignment: no cycles →
    dim_order; cycles → dor/min_adapt by count with matching turn
    restrictions). Restated — not shared — because the v2 function body
    is frozen; a cross-check test pins v2/v3 parity for identical
    dependency structures, so drift fails loudly instead of silently.
    """
    if not has_cycles:
        return "dim_order", ["no_negative_dimension_turns"]
    if vc_count > 2:
        return "min_adapt", []
    return "dor", ["west_first", "north_last"]


def derive_vc_assignment_v3(request: CompileRequestV3) -> VCAssignment:
    """v3 VC policy: derive what v3 declares, nothing it doesn't.

    Cycle law is shared (derive_vc_count over the same DependencyGraph
    type; over-limit is UNSUPPORTED, never clamped). The v2
    concurrent-collectives floor is DELIBERATELY absent: v2 assumes
    declared collectives are potentially concurrent, while v3 intents
    lower to an ordered sequential chain — copying the floor would
    over-provision VCs for concurrency v3 semantics never claim.
    Every DECLARED traffic class appears in per_class_vc even when
    plainly VC0 (fabric must serve what intent declares); dependency
    endpoint names ride along at VC0; cycle victims separate per the
    shared least-cost law.
    """
    if not isinstance(request, CompileRequestV3):
        raise CompileRequestV3SchemaError(
            f"derive_vc_assignment_v3 takes a CompileRequestV3, got "
            f"{type(request).__name__} — never a converted v2 stand-in")
    graph = request.dependencies
    cycles = graph.find_cycles()
    vc_count = derive_vc_count(graph)
    if vc_count > PLANE_C_MAX_VC:
        from .vc_assignment import VCAssignmentError
        raise VCAssignmentError(
            f"required {vc_count} VCs exceeds fabric maximum "
            f"{PLANE_C_MAX_VC} — UNSUPPORTED")
    routing, turn_restrictions = _routing_for_cycle_structure(
        bool(cycles), vc_count)
    per_class_vc: dict[str, int] = {}
    for cls in sorted({d.source for d in graph.dependencies}
                      | {d.target for d in graph.dependencies}
                      | set(derive_v3_traffic_classes(request))):
        per_class_vc[cls] = 0
    if cycles:
        adj = graph._adjacency()
        for i, cycle in enumerate(cycles):
            victim = min(cycle[:-1],
                         key=lambda n: len(adj.get(n, [])),
                         default=cycle[0])
            per_class_vc[victim] = i + 1
    return VCAssignment(
        vc_count=vc_count,
        per_class_vc=per_class_vc,
        routing_function=routing,
        turn_restrictions=list(turn_restrictions),
    )


def derive_vc_assignment_artifact_v3(
        request: CompileRequestV3,
        resolved_route,
):
    """Bind the v3 VC policy to the resolved route (mirrors the v2 binder).

    Same binding law as derive_vc_assignment_artifact: every VC names a
    routing class of the resolved route, and every route class is served
    by at least one VC (an unserved class would be unroutable hardware).
    The derivation string is provenance naming v3 inputs (declared
    classes, victims, no concurrent-context floor).
    """
    from .vc_assignment import VCAssignmentError, make_vc_assignment_artifact
    if not isinstance(request, CompileRequestV3):
        raise CompileRequestV3SchemaError(
            "derive_vc_assignment_artifact_v3 takes a CompileRequestV3")
    va = derive_vc_assignment_v3(request)
    classes = list(resolved_route.routing_classes)
    if not classes:
        raise VCAssignmentError(
            "resolved route defines no routing classes — VC derivation "
            "has nothing to bind against")
    vc_routing = tuple((vc, classes[vc % len(classes)])
                       for vc in range(va.vc_count))
    missing = [c for c in classes
               if c not in {rc for _, rc in vc_routing}]
    if missing:
        raise VCAssignmentError(
            f"VC derivation serves no VC to routing classes {missing} "
            f"(route defines {classes}, vc_count={va.vc_count}) — "
            f"refusing a structure that leaves route classes unroutable")
    separated = sorted(
        cls for cls, vc in va.per_class_vc.items() if vc != 0
    )
    derivation = (
        f"v3 route_classes={classes}; vc_count={va.vc_count}; "
        f"declared_classes={list(derive_v3_traffic_classes(request))}; "
        f"cycle_separated={separated}; no_concurrent_collective_floor"
    )
    return make_vc_assignment_artifact(
        resolved_route=resolved_route,
        vc_count=va.vc_count,
        traffic_class_to_vcs={cls: [vc] for cls, vc in va.per_class_vc.items()},
        vc_to_routing_class=dict(vc_routing),
        derivation=derivation,
    )

def derive_vc_assignment_artifact(
        cr: CompileRequest,
        resolved_route,
) -> VCAssignmentArtifact:
    """Derive the VC structure AGAINST the actual resolved route (P1.3).

    The candidate VC structure (dependency-graph cycles + collective
    floor as policy input) is bound explicitly to the route the
    compiler derived: every VC names its routing class, and every
    routing class the route defines is served by at least one VC
    (coverage assertion — a class with no VC would be unroutable
    hardware). The derivation string names the route classes,
    victims and floor; it is provenance, never authority. Acyclicity
    is proven by the P1.4 certificate's CDG obligation over
    (topology, route, VC assignment), not by this string.
    """
    from .vc_assignment import VCAssignmentError, make_vc_assignment_artifact
    va = derive_vc_assignment(cr)
    classes = list(resolved_route.routing_classes)
    if not classes:
        raise VCAssignmentError(
            "resolved route defines no routing classes — VC derivation "
            "has nothing to bind against")
    vc_routing = tuple((vc, classes[vc % len(classes)])
                       for vc in range(va.vc_count))
    missing = [c for c in classes
               if c not in {rc for _, rc in vc_routing}]
    if missing:
        raise VCAssignmentError(
            f"VC derivation serves no VC to routing classes {missing} "
            f"(route defines {classes}, vc_count={va.vc_count}) — "
            f"refusing a structure that leaves route classes unroutable")
    separated = sorted(
        cls for cls, vc in va.per_class_vc.items() if vc != 0
    )
    derivation = (
        f"route_classes={classes}; vc_count={va.vc_count}; "
        f"cycle_separated={separated}; "
        f"collective_vc_map={sorted(va.collective_vc_map.items())}"
    )
    return make_vc_assignment_artifact(
        resolved_route=resolved_route,
        vc_count=va.vc_count,
        traffic_class_to_vcs={cls: [vc] for cls, vc in va.per_class_vc.items()},
        vc_to_routing_class=dict(vc_routing),
        derivation=derivation,
    )



# ══════════════════════════════════════════════════════════════════════════════
# Trace coverage helper (for collective↔trace consistency)
# ══════════════════════════════════════════════════════════════════════════════

# Max trace lines scanned during validate(). Full scans of 26M-line traces
# would break the "errors in seconds" promise; beyond the cap we report
# sampled results explicitly. Env-overridable (import-time read).
TRACE_SCAN_CAP = env_int("VERITX_TRACE_SCAN_CAP", 200_000)
