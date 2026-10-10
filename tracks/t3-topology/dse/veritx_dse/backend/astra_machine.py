"""Slice 33 — canonical ASTRA machine projection.

Rationale: docs/decisions/modules/backend.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import content_hash
from veritx_dse.backend.booksim_projection import (
    TOPOLOGY_FILE,
    SemanticLoss,
    parse_config_values,
)

ASTRA_MACHINE_SCHEMA_VERSION = 1
EMBEDDED_FABRIC_ABI_VERSION = "srota/booksim-embedded-fabric-abi/v1"

EMBEDDED_NETWORK_CLASS_ABI_VERSION = 1
REQUIRED_CLASS_ABI_MULTI_CLASS = 1
MACHINE_PROFILE_VERSION = "srota/astra-machine-profile/v1"
MACHINE_DERIVATION_VERSION = "srota/astra-machine-derivation/v1"

SYSTEM_FILE = "system.json"
NETWORK_FILE = "network.cfg"
LOGICAL_TOPOLOGY_FILE = "logical_topology.json"
MEMORY_FILE = "memory.json"

NETWORK_CONFIG_ABI = "booksim2-network-config/cfg-file/v1"
LEGACY_NETWORK_CONFIG_ABI = "booksim2-network-config/network-json/v1"

DISARMED_NETWORK_KEYS = ("traffic", "injection_rate", "injection_process")

DISARMED_TRAFFIC = "uniform"
DISARMED_INJECTION_PROCESS = "bernoulli"
DISARMED_INJECTION_RATE = 0.0

MACHINE_SEMANTIC_KEYS = (
    "topology", "k", "n", "c", "x", "y", "routing_function", "num_vcs",
    "vc_buf_size", "subnets", "packet_size", "network_file", "topology_file",
    "link_latency", "H", "chi", "delta", "priority", "allocator",
    "vc_allocator", "sw_allocator", "arb_type", "speculative",
    "wait_for_tail_credit", "filter", "no_deadlock", "anynet_max_hops",
    "mesh_class_vc_begin", "mesh_class_vc_end",
)

CONTROLLED_ROUTER_MACHINE_KEYS = (
    "buf_size", "credit_delay", "alloc_iters", "routing_delay",
    "vc_alloc_delay", "sw_alloc_delay", "st_prepare_delay", "st_final_delay",
)

class AstraMachineError(ValueError):
    """Machine projection refused to produce a runtime config."""

class MachineFieldOwner(Enum):
    """Who owns a rendered ASTRA configuration field.

Rationale: docs/decisions/modules/backend.md
    """

    CANONICAL = "CANONICAL"
    WORKLOAD_DERIVED = "WORKLOAD_DERIVED"
    BACKEND_PROFILE = "BACKEND_PROFILE"
    RUNTIME_REQUIRED = "RUNTIME_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"

@dataclass(frozen=True)
class SystemField:
    name: str
    owner: MachineFieldOwner
    source: str
    note: str = ""

SYSTEM_FIELDS: tuple[SystemField, ...] = (
    SystemField("inter-node-communication", MachineFieldOwner.BACKEND_PROFILE,
                "astra_scheduler_profile",
                "Unset -> ASTRA's documented default (disabled when absent)"),
    SystemField("scheduling-policy", MachineFieldOwner.BACKEND_PROFILE,
                "astra_scheduler_profile", "LIFO/FIFO; scheduling only"),
    SystemField("endpoint-delay", MachineFieldOwner.BACKEND_PROFILE,
                "astra_scheduler_profile",
                "per-comm-event fixed delay; NOT network timing"),
    SystemField("active-chunks-per-dimension",
                MachineFieldOwner.BACKEND_PROFILE, "astra_scheduler_profile"),
    SystemField("preferred-dataset-splits", MachineFieldOwner.BACKEND_PROFILE,
                "astra_scheduler_profile"),
    SystemField("boost-mode", MachineFieldOwner.BACKEND_PROFILE,
                "astra_scheduler_profile"),
    SystemField("collective-optimization", MachineFieldOwner.BACKEND_PROFILE,
                "astra_scheduler_profile",
                "baseline|localBWAware; bandwidth-aware splitting only"),
    SystemField("all-reduce-implementation", MachineFieldOwner.BACKEND_PROFILE,
                "astra_collective_profile",
                "only authority when expansion_authority == ASTRA"),
    SystemField("all-gather-implementation", MachineFieldOwner.BACKEND_PROFILE,
                "astra_collective_profile", "same"),
    SystemField("reduce-scatter-implementation",
                MachineFieldOwner.BACKEND_PROFILE, "astra_collective_profile",
                "same"),
    SystemField("all-to-all-implementation", MachineFieldOwner.BACKEND_PROFILE,
                "astra_collective_profile", "same"),
    SystemField("system-name", MachineFieldOwner.RUNTIME_REQUIRED,
                "derived_label",
                "cosmetic label; derived deterministically, never tuned"),
    SystemField("local-mem-bw", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
    SystemField("local-mem-trace-filename", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
    SystemField("local-reduction-delay", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
    SystemField("model-shared-bus", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
    SystemField("peak-perf", MachineFieldOwner.UNSUPPORTED,
                "canonical_roofline_not_reclaimed", "never rendered"),
    SystemField("roofline-enabled", MachineFieldOwner.UNSUPPORTED,
                "canonical_roofline_not_reclaimed", "never rendered"),
    SystemField("track-local-mem", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
    SystemField("trace-enabled", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
    SystemField("replay-only", MachineFieldOwner.UNSUPPORTED,
                "canonical_memory_not_reclaimed", "never rendered"),
)
SYSTEM_FIELD_OWNERS = {f.name: f.owner for f in SYSTEM_FIELDS}

RENDERED_SYSTEM_FIELDS = (
    "scheduling-policy", "endpoint-delay", "active-chunks-per-dimension",
    "preferred-dataset-splits", "boost-mode", "collective-optimization",
    "all-reduce-implementation", "all-gather-implementation",
    "reduce-scatter-implementation", "all-to-all-implementation",
    "system-name",
)

ASTRA_SCHEDULER_PROFILE = {
    "scheduling-policy": "LIFO",
    "endpoint-delay": 10,
    "active-chunks-per-dimension": 1,
    "preferred-dataset-splits": 1,
    "boost-mode": 0,
    "collective-optimization": "localBWAware",
}
ASTRA_COLLECTIVE_IMPLEMENTATIONS = {
    "all-reduce-implementation": ["ring"],
    "all-gather-implementation": ["ring"],
    "reduce-scatter-implementation": ["ring"],
    "all-to-all-implementation": ["direct"],
}
ASTRA_COLLECTIVE_PROFILE_VERSION = "srota/astra-collective-profile/v1"

MEMORY_SCOPE_RUNTIME_REQUIRED_INERT = "RUNTIME_REQUIRED_MEMORY_SEMANTICALLY_INERT"
MEMORY_SCOPE_UNSUPPORTED = "UNSUPPORTED_MEMORY_SEMANTICS"
MEMORY_PROFILE_VERSION = "srota/astra-memory-runtime-required/v1"
RUNTIME_REQUIRED_MEMORY = {
    "memory-type": "PER_NODE_MEMORY_EXPANSION",
    "num-npus-per-node": 1,
    "remote-mem-latency": 0,
    "remote-mem-bw": 0,
}

PACKETIZATION_CANONICAL = "CANONICAL_FLIT_WIDTH"
PACKETIZATION_COARSE = "COARSE_FLIT_WIDTH_LOWER_FIDELITY"
HISTORICAL_COARSE_FLIT_BYTES = 128
CANONICAL_NS_PER_CYCLE = 1.0

MEMORY_ACTIVATING_PREFIXES = ("PIM",)

def _config_names(text: str) -> set[str]:
    """The key names a .cfg text assigns (comments and blanks excluded)."""
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        names.add(stripped.split("=", 1)[0].strip())
    return names


#: The qualified ASTRA build links the canonical fork (BOOKSIM2_SRC_DIR),
#: NOT ASTRA's unused nested BookSim copy. Rebuild and verify the producer
#: manifest when this surface changes; source declarations alone do not
#: establish that an old installed binary supports the new fields.
_ASTRA_NETWORK_CONFIG_SOURCE = "third_party/booksim2/src/booksim_config.cpp"
_FIELD_DECLARATION = re.compile(r'Add\w+Field\(\s*"([^"]+)"')
_MAP_DECLARATION = re.compile(
    r'_(?:int|float|str)_map\[\s*"([^"]+)"\s*\]')

_DECLARED_RUNTIME_FIELDS: frozenset[str] | None = None


def declared_runtime_config_fields() -> frozenset[str]:
    """Every config name the canonical ASTRA build's parser declares.

    Derived from the linked canonical BookSim sources (string fields via
    ``Add*Field``, numeric fields via the typed maps), because the runtime
    hard-fails on a name it does not declare — ``Parse error : Unknown
    string field``. Reading its source keeps the check honest: it follows the
    vendored backend instead of a transcription that can rot beside it. A
    source that cannot be read REFUSES rather than assuming acceptance.
    """
    global _DECLARED_RUNTIME_FIELDS
    if _DECLARED_RUNTIME_FIELDS is not None:
        return _DECLARED_RUNTIME_FIELDS
    from veritx_dse.core.paths import REPO
    source = REPO / _ASTRA_NETWORK_CONFIG_SOURCE
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AstraMachineError(
            "cannot read the installed ASTRA runtime's config surface at "
            f"{source} ({exc}); refusing to render an embedded fabric "
            "configuration whose fields cannot be checked against the "
            "parser that will read it") from exc
    names = set(_FIELD_DECLARATION.findall(text)) \
        | set(_MAP_DECLARATION.findall(text))
    if not names:
        raise AstraMachineError(
            f"the ASTRA runtime config source at {source} declares no "
            "fields; refusing to guess its accepted name set")
    _DECLARED_RUNTIME_FIELDS = frozenset(names)
    return _DECLARED_RUNTIME_FIELDS


@dataclass(frozen=True)
class EmbeddedFabricConfig:
    """The ASTRA-owned BookSim fabric configuration.

Rationale: docs/decisions/modules/backend.md
    """

    text: str
    abi_version: str
    standalone_config_sha256: str
    machine_values: tuple[tuple[str, str], ...]
    disarmed_values: tuple[tuple[str, str], ...]
    carries_trace_reference: bool

def _standalone_values(prepared: Any) -> dict[str, str]:
    return parse_config_values(prepared.config_text)

def embedded_fabric_config(prepared: Any, *, embedded_classes: int
                           ) -> EmbeddedFabricConfig:
    """Disarm standalone injection; keep every machine fact intact.

Rationale: docs/decisions/modules/backend.md
    """
    text = getattr(prepared, "config_text", None)
    if not isinstance(text, str) or not text.strip():
        raise AstraMachineError(
            "embedded fabric projection requires a PreparedBookSimInput")
    if not isinstance(embedded_classes, int) \
            or isinstance(embedded_classes, bool) \
            or embedded_classes < 1:
        raise AstraMachineError(
            f"embedded class envelope must be a positive int, got "
            f"{embedded_classes!r}")
    stripped = text.lstrip("\ufeff").lstrip()
    if stripped.startswith("{"):
        raise AstraMachineError(
            "the network configuration is JSON (the legacy "
            f"{LEGACY_NETWORK_CONFIG_ABI} wrapper); the vendored frontend "
            "source feeds the argument straight to the BookSim yacc parser, "
            "which accepts only a .cfg")
    values = _standalone_values(prepared)
    from veritx_dse.backend.booksim_execution import mesh_class_vc_ranges_from_config
    ranges = mesh_class_vc_ranges_from_config(text)
    if ranges:
        if len(set(ranges)) != 1:
            raise AstraMachineError(
                "ASTRA's embedded class ABI identifies collective kinds, not "
                "canonical traffic classes; distinct class VC ranges cannot "
                "be represented without a traffic-class ABI extension")
        # One canonical class may use several collective kinds. Each of
        # those runtime-kind slots MUST keep that same canonical VC range.
        start, end = ranges[0]
        values['mesh_class_vc_begin'] = '{' + ','.join([str(start)] * embedded_classes) + '}'
        values['mesh_class_vc_end'] = '{' + ','.join([str(end)] * embedded_classes) + '}'
    if values.get("topology") == "gec" and values.get("routing_function") == "dor_gec":
        # Standalone accepts a fully-qualified registry key. ASTRA's IQRouter
        # appends _<topology>, so dor_gec became the nonexistent dor_gec_gec.
        # This is a config-name alias for the SAME registered dor_gec function.
        from veritx_dse.core.paths import REPO
        routing_source = REPO / "third_party/booksim2/src/networks/gec.cpp"
        if not re.search(r'gRoutingFunctionMap\[\s*"dor_gec"\s*\]\s*=\s*&dor_gec\s*;',
                         routing_source.read_text()):
            raise AstraMachineError("ASTRA does not declare the dor_gec routing alias")
        values["routing_function"] = "dor"

    from veritx_dse.backend.router_controls import CONTROLLED_BASE
    machine_keys = MACHINE_SEMANTIC_KEYS
    if getattr(prepared, "profile_id", None) in CONTROLLED_BASE:
        machine_keys += CONTROLLED_ROUTER_MACHINE_KEYS
    machine = tuple(sorted((k, values[k]) for k in machine_keys if k in values))
    declared: list[tuple[str, str]] = [
        ("classes", str(embedded_classes)),
    ]
    disarmed: list[tuple[str, str]] = [
        ("traffic", DISARMED_TRAFFIC),
        ("injection_process", DISARMED_INJECTION_PROCESS),
        ("injection_rate", repr(DISARMED_INJECTION_RATE)),
    ]

    ordered = _render_config(values, disarmed + declared)
    undeclared = sorted(
        name for name in _config_names(ordered)
        if name not in declared_runtime_config_fields())
    if undeclared:
        raise AstraMachineError(
            "the canonical ASTRA build's BookSim parser declares no field "
            f"{undeclared}, so the embedded network it would read cannot "
            "represent this fabric: the ASTRA-backed questions are "
            "unsupported for this design (a standalone question may still "
            "be answerable). Refusing rather than executing to a runtime "
            "parse failure.")
    carried = "trace(" in ordered
    if carried:
        raise AstraMachineError(
            "embedded fabric configuration still references a standalone "
            "trace; autonomous injection would double-count ASTRA traffic")
    for key, value in disarmed + declared:
        if not _config_has(ordered, key, value):
            raise AstraMachineError(
                f"embedded fabric configuration failed to pin {key}={value}")
    for key, value in machine:
        if not _config_has(ordered, key, value):
            raise AstraMachineError(
                f"embedded fabric configuration lost machine field "
                f"{key}={value} from the Slice-31 projection")
    return EmbeddedFabricConfig(
        text=ordered,
        abi_version=EMBEDDED_FABRIC_ABI_VERSION,
        standalone_config_sha256=content_hash(
            "srota/PreparedBookSimConfig", 1, {"text": text}),
        machine_values=machine,
        disarmed_values=tuple(disarmed),
        carries_trace_reference=False,
    )

def _render_config(values: dict[str, str],
                   overrides: list[tuple[str, str]]) -> str:
    """Rewrite the standalone config with the embedded overrides applied."""
    forced = dict(overrides)
    lines: list[str] = []
    from veritx_dse.backend.booksim_projection import CONFIG_KEY_ORDER
    emitted = set()
    for key in CONFIG_KEY_ORDER:
        if key in values and key not in forced:
            lines.append(f"{key} = {values[key]};")
            emitted.add(key)
    for key in forced:
        lines.append(f"{key} = {forced[key]};")
    for key in sorted(set(values) - emitted):
        if key in forced or key.startswith("__"):
            continue
        lines.append(f"{key} = {values[key]};")
    return "\n".join(lines) + "\n"

def _config_has(text: str, key: str, value: str) -> bool:
    return f"{key} = {value};" in text

@dataclass(frozen=True)
class LogicalTopology:
    dimensions: tuple[int, ...]
    derivation: str

    def product(self) -> int:
        result = 1
        for d in self.dimensions:
            result *= d
        return result

def derive_logical_dimensions(projection: Any) -> LogicalTopology:
    """Derive the ASTRA logical topology from the canonical workload.

    Refuses the historical ``if tp*pp == num_nodes`` heuristic: dimensions
    come from the collective participant structure actually present in the
    canonical projection, and must multiply to the participant count (no
    silent rank replication).

    A single ``[logical-dimensions]`` vector can encode ONE regular
    communicator structure. A real MoE workload carries SEVERAL at once
    (e.g. TP groups of 2 AND EP groups of 4 over the same 8 ranks), which no
    one vector can express. Refusing there — the historical behavior — made
    every MoE workload unexecutable. Instead the per-collective membership
    is carried by the execution namespace's communicator groups (ASTRA's
    ``--comm-group-configuration`` path, which builds a ring topology per
    group and ignores the global dims), and the global logical axis is the
    participant namespace itself. The derivation records the distinct
    communicator sizes so the choice stays auditable.
    """
    ranks = tuple(projection.ranks())
    participants = projection.participant_count
    if not ranks or len(ranks) != participants:
        raise AstraMachineError(
            "logical topology requires a dense participant namespace")
    groups = {tuple(sorted(parts))
              for _, _, _, parts in projection.collective_operations}
    groups = {g for g in groups if g}
    nontrivial = {g for g in groups if len(g) != participants}
    if not nontrivial:
        dims = (participants,)
        derivation = "flat_all_participants"
    else:
        sizes = {len(g) for g in nontrivial}
        for size in sizes:
            if size < 2 or participants % size != 0:
                raise AstraMachineError(
                    f"collective group size {size} does not divide the "
                    f"participant count {participants}")
        if len(sizes) == 1:
            inner = sizes.pop()
            dims = (participants // inner, inner)
            derivation = "collective_group_structure"
        else:
            dims = (participants,)
            derivation = ("communicator_group_structure("
                          + ",".join(str(s) for s in sorted(sizes)) + ")")
    topology = LogicalTopology(dimensions=dims, derivation=derivation)
    if topology.product() != participants:
        raise AstraMachineError(
            f"logical dimensions {dims} do not multiply to the participant "
            f"count {participants}")
    return topology

def memory_scope(logical: Any = None, projection: Any = None
                 ) -> tuple[str, bool]:
    """(scope, semantically_active).

Rationale: docs/decisions/modules/backend.md
    """
    operations = tuple(getattr(getattr(logical, "graph", None),
                               "operations", ()) or ())
    for operation in operations:
        kind = str(getattr(operation, "kind", "") or "")
        if kind.startswith(MEMORY_ACTIVATING_PREFIXES):
            raise SemanticLoss(
                f"UNSUPPORTED: operation {getattr(operation, 'operation_id', kind)!r} "
                f"(kind={kind}) needs canonical memory semantics, which "
                "Slice 33 does not reclaim")
    for op_id in (op for op, _ in getattr(projection, "compute_operations",
                                          ()) or ()):
        if any(str(op_id).upper().startswith(p)
               for p in MEMORY_ACTIVATING_PREFIXES):
            raise SemanticLoss(
                f"UNSUPPORTED: operation {op_id!r} needs canonical memory "
                "semantics, which Slice 33 does not reclaim")
    return MEMORY_SCOPE_RUNTIME_REQUIRED_INERT, False

def packetization(packet_format: Any, *,
                  flit_bytes: int | None = None
                  ) -> tuple[int, str, str]:
    """(flit_bytes, fidelity, justification) from the canonical packet format.

    The canonical flit width (``PacketFormatArtifact.flit_width_bits``, the
    same artifact Slice 31 binds by ``packet_format_hash``) is
    authoritative.  A coarser width is allowed only as an explicitly
    lower-fidelity tier, never as canonical network fidelity.
    """
    canonical_bits = getattr(packet_format, "flit_width_bits", None)
    if canonical_bits is None:
        raise AstraMachineError(
            "the canonical PacketFormatArtifact is required to choose a "
            "flit width; refusing to guess one")
    if not isinstance(canonical_bits, int) or canonical_bits <= 0:
        raise AstraMachineError(
            f"canonical flit width must be a positive bit count, got "
            f"{canonical_bits!r}")
    if canonical_bits % 8 != 0:
        raise AstraMachineError(
            f"canonical flit width {canonical_bits} bits is not a whole "
            "number of bytes; the runtime ABI is byte-granular")
    width = canonical_bits // 8
    if flit_bytes is not None and flit_bytes != width:
        if flit_bytes < width:
            raise AstraMachineError(
                f"requested flit width {flit_bytes} B is narrower than the "
                f"canonical {width} B; packing is not reclaimable here")
        return (flit_bytes, PACKETIZATION_COARSE,
                f"coarse flit width {flit_bytes} B vs canonical {width} B: "
                "lower-fidelity execution tier")
    return (width, PACKETIZATION_CANONICAL,
            f"canonical packet-format flit width {width} B")

@dataclass(frozen=True)
class AstraMachineProjection:
    """Deterministic ASTRA runtime inputs, derived and content-addressed."""

    resolved_fabric_hash: str
    mapping_hash: str
    attachment_hash: str
    topology_hash: str
    packet_format_hash: str
    vc_resource_hash: str
    route_artifact_hash: str
    prepared_id: str
    booksim_profile_id: str
    embedded_fabric_abi_version: str
    standalone_config_sha256: str
    workload_projection_id: str
    workload_semantics_version: int
    et_granularity: str
    expansion_authority: str
    workload_evidence_scope: str
    machine_profile_version: str
    machine_derivation_version: str
    astra_collective_profile_version: str
    memory_profile_version: str
    network_config_abi: str
    participant_count: int
    astra_sys_count: int
    workload_compute_floor: int
    workload_payload_bytes: int
    logical_dimensions: tuple[int, ...]
    logical_derivation: str
    router_count: int
    endpoint_count: int
    num_vcs: int
    flit_bytes: int
    packetization_fidelity: str
    ns_per_cycle: float
    memory_scope: str
    memory_semantically_active: bool
    system_config_text: str
    network_config_text: str
    logical_topology_text: str
    memory_config_text: str
    topology_file_text: str = ""
    embedded_network_class_abi_version: int = 0
    schema_version: int = ASTRA_MACHINE_SCHEMA_VERSION

    def files(self) -> dict[str, bytes]:
        out = {
            SYSTEM_FILE: _json_bytes(self.system_config_text),
            NETWORK_FILE: self.network_config_text.encode("utf-8"),
            LOGICAL_TOPOLOGY_FILE:
                _json_bytes(self.logical_topology_text),
            MEMORY_FILE: _json_bytes(self.memory_config_text),
        }
        if self.topology_file_text:
            out[TOPOLOGY_FILE] = self.topology_file_text.encode("utf-8")
        return out

    def file_digests(self) -> dict[str, str]:
        return {name: content_hash("srota/AstraMachineConfig", 1,
                                   {"name": name,
                                    "text": blob.decode("utf-8")})
                for name, blob in self.files().items()}

    def identity_dict(self) -> dict[str, Any]:
        """Scientific identity.  No filesystem location appears here."""
        return {
            "type": "srota/AstraMachineProjection",
            "schema_version": self.schema_version,
            "machine_profile_version": self.machine_profile_version,
            "machine_derivation_version": self.machine_derivation_version,
            "embedded_fabric_abi_version": self.embedded_fabric_abi_version,
            "astra_collective_profile_version":
                self.astra_collective_profile_version,
            "memory_profile_version": self.memory_profile_version,
            "network_config_abi": self.network_config_abi,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "mapping_hash": self.mapping_hash,
            "attachment_hash": self.attachment_hash,
            "topology_hash": self.topology_hash,
            "packet_format_hash": self.packet_format_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "route_artifact_hash": self.route_artifact_hash,
            "prepared_id": self.prepared_id,
            "booksim_profile_id": self.booksim_profile_id,
            "standalone_config_sha256": self.standalone_config_sha256,
            "embedded_network_class_abi_version":
                self.embedded_network_class_abi_version,
            "workload_projection_id": self.workload_projection_id,
            "workload_semantics_version": self.workload_semantics_version,
            "et_granularity": self.et_granularity,
            "expansion_authority": self.expansion_authority,
            "workload_evidence_scope": self.workload_evidence_scope,
            "participant_count": self.participant_count,
            "astra_sys_count": self.astra_sys_count,
            "workload_compute_floor": self.workload_compute_floor,
            "workload_payload_bytes": self.workload_payload_bytes,
            "logical_dimensions": list(self.logical_dimensions),
            "logical_derivation": self.logical_derivation,
            "router_count": self.router_count,
            "endpoint_count": self.endpoint_count,
            "num_vcs": self.num_vcs,
            "flit_bytes": self.flit_bytes,
            "packetization_fidelity": self.packetization_fidelity,
            "ns_per_cycle": self.ns_per_cycle,
            "memory_scope": self.memory_scope,
            "memory_semantically_active": self.memory_semantically_active,
            "config_digests": self.file_digests(),
        }

    def machine_id(self) -> str:
        return content_hash("srota/AstraMachineProjection", 1,
                            self.identity_dict())

    def physical_id(self) -> str:
        """Stable machine facts only -- independent of the workload.

Rationale: docs/decisions/modules/backend.md
        """
        return content_hash("srota/AstraMachinePhysical", 1, {
            "type": "srota/AstraMachinePhysical",
            "schema_version": self.schema_version,
            "machine_profile_version": self.machine_profile_version,
            "machine_derivation_version": self.machine_derivation_version,
            "embedded_fabric_abi_version": self.embedded_fabric_abi_version,
            "astra_collective_profile_version":
                self.astra_collective_profile_version,
            "memory_profile_version": self.memory_profile_version,
            "network_config_abi": self.network_config_abi,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "mapping_hash": self.mapping_hash,
            "attachment_hash": self.attachment_hash,
            "topology_hash": self.topology_hash,
            "packet_format_hash": self.packet_format_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "route_artifact_hash": self.route_artifact_hash,
            "prepared_id": self.prepared_id,
            "booksim_profile_id": self.booksim_profile_id,
            "standalone_config_sha256": self.standalone_config_sha256,
            "embedded_network_class_abi_version":
                self.embedded_network_class_abi_version,
            "astra_sys_count": self.astra_sys_count,
            "router_count": self.router_count,
            "endpoint_count": self.endpoint_count,
            "num_vcs": self.num_vcs,
            "flit_bytes": self.flit_bytes,
            "packetization_fidelity": self.packetization_fidelity,
            "ns_per_cycle": self.ns_per_cycle,
            "memory_scope": self.memory_scope,
            "config_digests": self.file_digests(),
        })

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["machine_id"] = self.machine_id()
        payload["system_config"] = json.loads(self.system_config_text)
        payload["logical_topology_config"] = json.loads(
            self.logical_topology_text)
        payload["memory_config"] = json.loads(self.memory_config_text)
        return payload

    @classmethod
    def from_dict(cls, doc: Any) -> "AstraMachineProjection":
        """Rebuild the exact projected machine from its persisted JSON.

        Accepts the identity dict or the full to_dict payload (derived
        keys are ignored, never trusted). The caller must verify
        ``machine_id()`` against the externally held identity: content
        equality here is necessary but not sufficient for reuse.
        """
        if not isinstance(doc, dict):
            raise AstraMachineError(
                f"machine document must be a JSON object, got "
                f"{type(doc).__name__}")
        try:
            text_fields = {
                name: doc[name] for name in (
                    "system_config_text", "network_config_text",
                    "logical_topology_text", "memory_config_text")}
            str_fields = {
                name: doc[name] for name in (
                    "resolved_fabric_hash", "mapping_hash",
                    "attachment_hash", "topology_hash",
                    "packet_format_hash", "vc_resource_hash",
                    "route_artifact_hash", "prepared_id",
                    "booksim_profile_id", "embedded_fabric_abi_version",
                    "standalone_config_sha256", "workload_projection_id",
                    "et_granularity", "expansion_authority",
                    "workload_evidence_scope", "machine_profile_version",
                    "machine_derivation_version",
                    "astra_collective_profile_version",
                    "memory_profile_version", "network_config_abi",
                    "logical_derivation", "packetization_fidelity",
                    "memory_scope")}
            int_fields = {
                name: doc[name] for name in (
                    "workload_semantics_version", "participant_count",
                    "astra_sys_count", "workload_compute_floor",
                    "workload_payload_bytes", "router_count",
                    "endpoint_count", "num_vcs", "flit_bytes")}
        except KeyError as exc:
            raise AstraMachineError(
                f"machine document is missing {exc}") from exc
        for name, value in {**text_fields, **str_fields}.items():
            if not isinstance(value, str) or not value:
                raise AstraMachineError(
                    f"machine document field {name!r} must be a "
                    f"non-empty string")
        for name, value in int_fields.items():
            if type(value) is not int or isinstance(value, bool):
                raise AstraMachineError(
                    f"machine document field {name!r} must be an int")
        dimensions = doc.get("logical_dimensions")
        if not isinstance(dimensions, list) or not dimensions \
                or any(type(d) is not int or d <= 0 for d in dimensions):
            raise AstraMachineError(
                "machine document logical_dimensions must be a "
                "non-empty list of positive ints")
        ns_per_cycle = doc.get("ns_per_cycle")
        if not isinstance(ns_per_cycle, (int, float)) \
                or isinstance(ns_per_cycle, bool):
            raise AstraMachineError(
                "machine document ns_per_cycle must be a number")
        active = doc.get("memory_semantically_active")
        if not isinstance(active, bool):
            raise AstraMachineError(
                "machine document memory_semantically_active must be a "
                "bool")
        schema = doc.get("schema_version",
                         ASTRA_MACHINE_SCHEMA_VERSION)
        if schema != ASTRA_MACHINE_SCHEMA_VERSION:
            raise AstraMachineError(
                f"unsupported machine schema_version {schema!r}")
        class_abi = doc.get("embedded_network_class_abi_version", 0)
        if type(class_abi) is not int or isinstance(class_abi, bool) \
                or class_abi < 0:
            raise AstraMachineError(
                "machine document embedded_network_class_abi_version "
                "must be a non-negative int")
        return cls(
            **str_fields, **int_fields, **text_fields,
            logical_dimensions=tuple(dimensions),
            ns_per_cycle=float(ns_per_cycle),
            memory_semantically_active=active,
            embedded_network_class_abi_version=class_abi,
            schema_version=schema)

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_dict(), sort_keys=True, indent=2)
                + "\n").encode("utf-8")

    def materialize(self, directory: str | Path) -> dict[str, Path]:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for name, blob in self.files().items():
            path = target / name
            path.write_bytes(blob)
            written[name] = path
        return written

    def runtime_command(self, *, binary: str | Path,
                        workload_configuration: str | Path,
                        workload_directory: str | Path,
                        injection_override: bool = True
                        ) -> tuple[str, ...]:
        """The exact ASTRA argv for this machine projection."""
        command = [
            str(binary),
            f"--system-configuration={SYSTEM_FILE}",
            f"--network-configuration={NETWORK_FILE}",
            f"--logical-topology-configuration={LOGICAL_TOPOLOGY_FILE}",
            f"--workload-configuration={workload_configuration}",
            f"--memory-configuration={MEMORY_FILE}",
            f"--remote-memory-configuration={MEMORY_FILE}",
            f"--booksim2-flit-bytes={self.flit_bytes}",
            f"--booksim2-ns-per-cycle={self.ns_per_cycle}",
        ]
        if injection_override:
            command.append(
                f"--booksim2-extra=injection_rate={DISARMED_INJECTION_RATE}")
        return tuple(command)

def _json_bytes(text: str) -> bytes:
    return (json.dumps(json.loads(text), sort_keys=True, indent=2)
            + "\n").encode("utf-8")

def qualify_astra_machine(*, parents: Any, prepared: Any, projection: Any,
                          logical: Any = None,
                          flit_bytes: int | None = None,
                          astra_collective_authority: bool | None = None,
                          embedded_classes: int | None = None,
                          ) -> AstraMachineProjection:
    """Build the machine projection from canonical artifacts only.

Rationale: docs/decisions/modules/backend.md
    """
    if prepared is None:
        raise AstraMachineError("a PreparedBookSimInput is required")
    from veritx_dse.backend.router_controls import CONTROLLED_BASE
    if (prepared.profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1"
            or prepared.profile_id in CONTROLLED_BASE):
        from veritx_dse.application.booksim_qualification_registry import qualification_of
        if not qualification_of(prepared.profile_id).is_qualified:
            raise AstraMachineError("selected BookSim profile requires qualification; no qualified ASTRA execution is advertised")
    if projection is None:
        raise AstraMachineError("an AstraWorkloadProjection is required")
    if not hasattr(projection, "identity_dict"):
        raise AstraMachineError(
            "the workload projection must be an AstraWorkloadProjection")

    from veritx_dse.backend.astra import (
        AstraLoweringRefused, required_embedded_classes,
    )
    try:
        if embedded_classes is None:
            embedded_classes = required_embedded_classes(
                projection.collective_operations)
        embedded = embedded_fabric_config(
            prepared, embedded_classes=embedded_classes)
    except AstraLoweringRefused as exc:
        raise AstraMachineError(
            f"cannot declare the embedded class envelope: {exc}"
        ) from exc
    derived_topology = derive_logical_dimensions(projection)
    scope, active = memory_scope(logical, projection)
    authority = projection.expansion_authority()
    if authority not in ("srota_logical_messages", "astra_comm_coll"):
        raise AstraMachineError(
            f"unknown collective expansion authority {authority!r}")
    projected_classes = projection.traffic_classes()
    if len(projected_classes) > 1 \
            and EMBEDDED_NETWORK_CLASS_ABI_VERSION < \
            REQUIRED_CLASS_ABI_MULTI_CLASS:
        raise AstraMachineError(
            f"multi-class workload ({len(projected_classes)} classes: "
            f"{list(projected_classes)}) requires embedded network "
            f"class ABI >= {REQUIRED_CLASS_ABI_MULTI_CLASS}, but the "
            "qualified runtime proves "
            f"{EMBEDDED_NETWORK_CLASS_ABI_VERSION}: old runtimes fail "
            "qualification rather than executing classes unattributed")
    if astra_collective_authority is not None:
        wants_astra = authority == "astra_comm_coll"
        if astra_collective_authority != wants_astra:
            raise SemanticLoss(
                "the machine profile's collective authority does not match "
                f"the workload projection's ({authority})")

    packet_format = getattr(parents, "packet_format", None)
    width, fidelity, _ = packetization(packet_format,
                                       flit_bytes=flit_bytes)

    participant_count = projection.participant_count
    mapping = getattr(parents, "mapping", None)
    mapping_ranks = getattr(mapping, "rank_count", None)
    if mapping_ranks is not None and participant_count != mapping_ranks:
        raise SemanticLoss(
            f"participant mismatch: the workload projects {participant_count} "
            f"ranks but the canonical mapping places {mapping_ranks}")
    attached = {getattr(e, "endpoint_id", None)
                for e in getattr(getattr(parents, "attachment", None),
                                 "endpoints", ())}
    unattached = sorted(set(projection.ranks()) - attached)
    if unattached:
        raise SemanticLoss(
            f"the canonical attachment does not cover ranks {unattached}; "
            "the logical topology would not describe the executed machine")
    if participant_count > prepared.endpoint_count:
        raise SemanticLoss(
            f"participant mismatch: the workload projects {participant_count} "
            f"ranks but the fabric attaches only {prepared.endpoint_count} "
            "endpoints")

    system = {
        "scheduling-policy": ASTRA_SCHEDULER_PROFILE["scheduling-policy"],
        "endpoint-delay": ASTRA_SCHEDULER_PROFILE["endpoint-delay"],
        "active-chunks-per-dimension":
            ASTRA_SCHEDULER_PROFILE["active-chunks-per-dimension"],
        "preferred-dataset-splits":
            ASTRA_SCHEDULER_PROFILE["preferred-dataset-splits"],
        "boost-mode": ASTRA_SCHEDULER_PROFILE["boost-mode"],
        "collective-optimization":
            ASTRA_SCHEDULER_PROFILE["collective-optimization"],
        "system-name": _system_name(prepared, participant_count),
        **ASTRA_COLLECTIVE_IMPLEMENTATIONS,
    }
    _assert_rendered_ownership(system)
    sys_count = fabric_node_count(prepared)
    if sys_count < prepared.endpoint_count:
        raise AstraMachineError(
            f"the fabric has {sys_count} nodes but {prepared.endpoint_count} "
            "agent endpoints are attached; the ASTRA Sys namespace cannot be "
            "smaller than the attached endpoint set")
    memory = {**RUNTIME_REQUIRED_MEMORY, "num-nodes": sys_count}
    logical_config = {"logical-dimensions": list(derived_topology.dimensions)}

    return AstraMachineProjection(
        resolved_fabric_hash=prepared.resolved_fabric_hash,
        mapping_hash=prepared.mapping_hash,
        attachment_hash=prepared.attachment_hash,
        topology_hash=prepared.topology_hash,
        packet_format_hash=prepared.packet_format_hash,
        vc_resource_hash=prepared.vc_resource_hash,
        route_artifact_hash=prepared.route_artifact_hash,
        prepared_id=prepared.prepared_id(),
        booksim_profile_id=prepared.profile_id,
        embedded_fabric_abi_version=embedded.abi_version,
        embedded_network_class_abi_version=
        EMBEDDED_NETWORK_CLASS_ABI_VERSION,
        standalone_config_sha256=embedded.standalone_config_sha256,
        workload_projection_id=projection.projection_id(),
        workload_semantics_version=projection.schema_version,
        et_granularity=projection.et_granularity,
        expansion_authority=authority,
        workload_evidence_scope=projection.evidence_scope(),
        machine_profile_version=MACHINE_PROFILE_VERSION,
        machine_derivation_version=MACHINE_DERIVATION_VERSION,
        astra_collective_profile_version=ASTRA_COLLECTIVE_PROFILE_VERSION,
        memory_profile_version=MEMORY_PROFILE_VERSION,
        network_config_abi=NETWORK_CONFIG_ABI,
        participant_count=participant_count,
        astra_sys_count=sys_count,
        workload_compute_floor=projection.declared_compute_cycles(),
        workload_payload_bytes=projection.total_payload_bytes(),
        logical_dimensions=derived_topology.dimensions,
        logical_derivation=derived_topology.derivation,
        router_count=prepared.router_count,
        endpoint_count=prepared.endpoint_count,
        num_vcs=prepared.num_vcs,
        flit_bytes=width,
        packetization_fidelity=fidelity,
        ns_per_cycle=CANONICAL_NS_PER_CYCLE,
        memory_scope=scope,
        memory_semantically_active=active,
        system_config_text=json.dumps(system, sort_keys=True, indent=2),
        network_config_text=embedded.text,
        logical_topology_text=json.dumps(logical_config, sort_keys=True,
                                         indent=2),
        memory_config_text=json.dumps(memory, sort_keys=True, indent=2),
        topology_file_text=str(getattr(prepared, "topology_text", "") or ""),
    )

def _system_name(prepared: Any, participants: int) -> str:
    """Deterministic cosmetic label; no tuning value may live here."""
    return (f"srota-{prepared.router_count}r-{participants}rank-"
            f"{prepared.profile_id.rsplit('/', 1)[-1][:16]}")

def _assert_rendered_ownership(system: dict[str, Any]) -> None:
    for key in system:
        owner = SYSTEM_FIELD_OWNERS.get(key)
        if owner is None:
            raise AstraMachineError(
                f"rendered system field {key!r} has no declared owner")
        if owner is MachineFieldOwner.UNSUPPORTED:
            raise AstraMachineError(
                f"system field {key!r} is UNSUPPORTED and must not be "
                "rendered")

def fabric_node_count(prepared: Any) -> int:
    """The ASTRA ``Sys.id`` namespace size: BookSim's NODE count.

Rationale: docs/decisions/modules/backend.md
    """
    values = parse_config_values(prepared.config_text)
    topology = values.get("topology", "").strip()
    if topology == "anynet":
        text = prepared.topology_text
        if not text:
            raise AstraMachineError(
                "an anynet projection must carry its rendered topology "
                "file")
        nodes: set[int] = set()
        for line in text.splitlines():
            line = line.split("#")[0].split("//")[0].strip()
            tokens = line.replace(",", " ").split()
            for index, token in enumerate(tokens):
                if token == "node" and index + 1 < len(tokens):
                    try:
                        nodes.add(int(tokens[index + 1]))
                    except ValueError:
                        raise AstraMachineError(
                            f"malformed anynet node id "
                            f"{tokens[index + 1]!r}") from None
        if not nodes:
            raise AstraMachineError(
                "the rendered anynet topology names no nodes")
        return len(nodes)
    from veritx_dse.model.family_registry import (
        FamilyRegistryError, resolve_node_count,
    )
    try:
        count, _witness = resolve_node_count(
            topology=topology, values=values,
            endpoint_count=int(getattr(prepared, "endpoint_count", 0)))
    except FamilyRegistryError as exc:
        raise AstraMachineError(str(exc)) from None
    return count

WORKLOAD_BASE_NAME = "workload"
WORKLOAD_ET = f"{WORKLOAD_BASE_NAME}.et"

def stage_workload(projection: Any, directory: str | Path
                   ) -> tuple[Path, tuple[int, ...]]:
    """Stage the canonical Chakra ETs so only participants run the trace.

Rationale: docs/decisions/modules/backend.md
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    staged = projection.write_chakra(directory=target,
                                     stem=WORKLOAD_BASE_NAME)
    base = target / WORKLOAD_ET
    if not base.is_file():
        raise AstraMachineError(
            f"the canonical Chakra writer did not emit {WORKLOAD_ET}")
    ranks = tuple(sorted(projection.ranks()))
    for rank in ranks:
        rank_file = target / f"{WORKLOAD_ET}.{rank}.et"
        if not rank_file.is_file():
            raise AstraMachineError(
                f"rank {rank} has no staged workload file {rank_file.name}; "
                "the frontend would silently replicate the base trace")
    return base, ranks
