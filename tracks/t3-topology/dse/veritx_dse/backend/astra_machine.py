"""Slice 33 — canonical ASTRA machine projection.

The historical authority for an ASTRA run was five hand-authored files
(``system.json``, ``network.json``, ``logical_topology.json``,
``memory.json``, ``mesh4x4.cfg``).  This module replaces that authority:
every deterministic runtime byte is *derived* from canonical artifacts and
content-addressed.

Two things are deliberately kept apart:

``standalone BookSim execution``
    Slice 31/32.  BookSim's own ``TrafficManager`` owns packet injection, so
    the config carries ``traffic = trace(workload.trace)``.

``embedded BookSim fabric execution``
    here.  ASTRA injects every packet through ``EmbedTM::InjectUnicast``, so
    the workload-driving fields must be *disarmed* while every
    machine-semantic field stays byte-identical to the Slice-31 projection.

There is exactly one BookSim machine-semantics authority (Slice 31); this
module only re-derives the workload-driving surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import content_hash
from veritx_dse.backend.booksim_projection import (
    SemanticLoss,
    parse_config_values,
)

ASTRA_MACHINE_SCHEMA_VERSION = 1
#: bumped whenever the embedded transform or the rendered config ABI changes
EMBEDDED_FABRIC_ABI_VERSION = "srota/booksim-embedded-fabric-abi/v1"
MACHINE_PROFILE_VERSION = "srota/astra-machine-profile/v1"
#: bumped when the logical-topology / memory derivation changes semantics
MACHINE_DERIVATION_VERSION = "srota/astra-machine-derivation/v1"

SYSTEM_FILE = "system.json"
NETWORK_FILE = "network.cfg"
LOGICAL_TOPOLOGY_FILE = "logical_topology.json"
MEMORY_FILE = "memory.json"

#: The network-configuration ABI the *currently vendored* frontend source
#: accepts.  ``CreateEmbeddedTM`` feeds the argument straight to
#: ``ParseArgs`` -> ``BookSimConfig``'s yacc grammar, so it must be a real
#: BookSim ``.cfg``.  The historical ``network.json`` wrapper was a property
#: of the *archived binary* (its ``veritx_embed.cpp`` carried an
#: ``nlohmann::json`` unwrap of ``booksim-config-file``); the vendored source
#: has no such unwrap, so JSON is NOT part of this ABI.
NETWORK_CONFIG_ABI = "booksim2-network-config/cfg-file/v1"
#: The legacy wrapper the archived binary also accepts.  Never emitted.
LEGACY_NETWORK_CONFIG_ABI = "booksim2-network-config/network-json/v1"

#: Network-configuration keys that are workload-driving in standalone BookSim
#: and MUST be disarmed for the embedded runtime (ASTRA owns injection).
DISARMED_NETWORK_KEYS = ("traffic", "injection_rate", "injection_process")

#: The disarmed values.  ``uniform`` is a pattern with no injection mechanism
#: of its own (``TraceTrafficPattern`` is the only one that has one), and
#: ``bernoulli`` at rate 0 makes ``BernoulliInjectionProcess::test`` return
#: ``RandomFloat() < 0.0`` — false for every draw in [0,1).
DISARMED_TRAFFIC = "uniform"
DISARMED_INJECTION_PROCESS = "bernoulli"
DISARMED_INJECTION_RATE = 0.0

#: Keys whose VALUE IS MACHINE SEMANTICS.  The embedded projection must carry
#: them byte-identically from the Slice-31 config; a mismatch is a refusal,
#: never a silent re-derivation.
MACHINE_SEMANTIC_KEYS = (
    "topology", "k", "n", "c", "x", "y", "routing_function", "num_vcs",
    "vc_buf_size", "subnets", "packet_size", "network_file", "topology_file",
    "link_latency", "H", "chi", "delta", "priority", "allocator",
    "vc_allocator", "sw_allocator", "arb_type", "speculative",
    "wait_for_tail_credit", "filter", "no_deadlock", "anynet_max_hops",
)


class AstraMachineError(ValueError):
    """Machine projection refused to produce a runtime config."""


class MachineFieldOwner(Enum):
    """Who owns a rendered ASTRA configuration field.

    ``MAGIC`` does not exist: a field is either derived, profile-owned,
    runtime-required, or it is not rendered at all.
    """

    CANONICAL = "CANONICAL"                  # a Fabric artifact fact
    WORKLOAD_DERIVED = "WORKLOAD_DERIVED"    # from the canonical workload
    BACKEND_PROFILE = "BACKEND_PROFILE"      # a declared, versioned choice
    RUNTIME_REQUIRED = "RUNTIME_REQUIRED"    # the binary needs it; inert
    UNSUPPORTED = "UNSUPPORTED"              # not reclaimed; never rendered


@dataclass(frozen=True)
class SystemField:
    name: str
    owner: MachineFieldOwner
    source: str
    note: str = ""


#: Closure over every ``system.json`` key the vendored ``Sys.cc`` reads
#: (``get<...>("...")`` / ``contains("...")``).  A test asserts closure.
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

#: Fields this projector renders.  Everything else in SYSTEM_FIELDS is
#: either UNSUPPORTED (refused if the workload needs it) or has an ASTRA
#: default we deliberately do not override.
RENDERED_SYSTEM_FIELDS = (
    "scheduling-policy", "endpoint-delay", "active-chunks-per-dimension",
    "preferred-dataset-splits", "boost-mode", "collective-optimization",
    "all-reduce-implementation", "all-gather-implementation",
    "reduce-scatter-implementation", "all-to-all-implementation",
    "system-name",
)

#: The ASTRA scheduler/collective profile.  These are *declared choices*, not
#: Fabric facts: they change ASTRA's timing model, not the fabric.
ASTRA_SCHEDULER_PROFILE = {
    "scheduling-policy": "LIFO",
    "endpoint-delay": 10,
    "active-chunks-per-dimension": 1,
    "preferred-dataset-splits": 1,
    "boost-mode": 0,
    "collective-optimization": "localBWAware",
}
#: ASTRA-owned collective expansion.  Only used when
#: ``expansion_authority == "astra_comm_coll"``.
ASTRA_COLLECTIVE_IMPLEMENTATIONS = {
    "all-reduce-implementation": ["ring"],
    "all-gather-implementation": ["ring"],
    "reduce-scatter-implementation": ["ring"],
    "all-to-all-implementation": ["direct"],
}
ASTRA_COLLECTIVE_PROFILE_VERSION = "srota/astra-collective-profile/v1"

#: Memory: canonical memory semantics are NOT reclaimed (later slice).  The
#: analytical remote-memory backend still requires a file, so we emit the
#: smallest explicit runtime-required profile and *prove* it is inert.
MEMORY_SCOPE_RUNTIME_REQUIRED_INERT = "RUNTIME_REQUIRED_MEMORY_SEMANTICALLY_INERT"
MEMORY_SCOPE_UNSUPPORTED = "UNSUPPORTED_MEMORY_SEMANTICS"
MEMORY_PROFILE_VERSION = "srota/astra-memory-runtime-required/v1"
RUNTIME_REQUIRED_MEMORY = {
    "memory-type": "PER_NODE_MEMORY_EXPANSION",
    "num-npus-per-node": 1,
    "remote-mem-latency": 0,
    "remote-mem-bw": 0,
}

#: Packetization fidelity tiers.  ``CANONICAL`` == the Slice-31 packet
#: format's flit width; anything coarser is explicitly a lower tier.
PACKETIZATION_CANONICAL = "CANONICAL_FLIT_WIDTH"
PACKETIZATION_COARSE = "COARSE_FLIT_WIDTH_LOWER_FIDELITY"
#: historical ASTRA runs used this for speed; not the canonical width
HISTORICAL_COARSE_FLIT_BYTES = 128
#: 1 fabric cycle == 1 ns.  The canonical workload's compute durations are
#: cycles-at-1ns (`declared_compute_cycles` divides ns by 1000), so this
#: keeps ASTRA's ns domain and the fabric's cycle domain aligned.
CANONICAL_NS_PER_CYCLE = 1.0

#: Operation kinds that would make the analytical memory model ACTIVE.
MEMORY_ACTIVATING_PREFIXES = ("PIM",)


# ── embedded fabric projection ────────────────────────────────────────────

@dataclass(frozen=True)
class EmbeddedFabricConfig:
    """The ASTRA-owned BookSim fabric configuration.

    Derived mechanically from the qualified Slice-31 standalone config: the
    machine-semantic surface is carried byte-identically, the
    workload-driving surface is disarmed.
    """

    text: str
    abi_version: str
    standalone_config_sha256: str
    machine_values: tuple[tuple[str, str], ...]
    disarmed_values: tuple[tuple[str, str], ...]
    carries_trace_reference: bool


def _standalone_values(prepared: Any) -> dict[str, str]:
    return parse_config_values(prepared.config_text)


def embedded_fabric_config(prepared: Any) -> EmbeddedFabricConfig:
    """Disarm standalone injection; keep every machine fact intact."""
    text = getattr(prepared, "config_text", None)
    if not isinstance(text, str) or not text.strip():
        raise AstraMachineError(
            "embedded fabric projection requires a PreparedBookSimInput")
    stripped = text.lstrip("\ufeff").lstrip()
    if stripped.startswith("{"):
        raise AstraMachineError(
            "the network configuration is JSON (the legacy "
            f"{LEGACY_NETWORK_CONFIG_ABI} wrapper); the vendored frontend "
            "source feeds the argument straight to the BookSim yacc parser, "
            "which accepts only a .cfg")
    values = _standalone_values(prepared)

    # A trace-driven standalone config is the expected input; refusing a
    # config that already looks embedded would hide the transform.
    machine = tuple(sorted((k, values[k]) for k in MACHINE_SEMANTIC_KEYS
                           if k in values))
    disarmed: list[tuple[str, str]] = [
        ("traffic", DISARMED_TRAFFIC),
        ("injection_process", DISARMED_INJECTION_PROCESS),
        ("injection_rate", repr(DISARMED_INJECTION_RATE)),
    ]

    ordered = _render_config(values, disarmed)
    carried = "trace(" in ordered
    if carried:
        raise AstraMachineError(
            "embedded fabric configuration still references a standalone "
            "trace; autonomous injection would double-count ASTRA traffic")
    for key, value in disarmed:
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
    # ``parse_config_values`` returns key -> value; keep the canonical order
    # used by Slice 31 so the two renderings are comparable.
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


# ── logical topology ──────────────────────────────────────────────────────

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
        if len(sizes) != 1:
            raise AstraMachineError(
                "logical topology cannot be derived: collectives span "
                f"unequal participant sets {sorted(sizes)}")
        inner = sizes.pop()
        if participants % inner != 0:
            raise AstraMachineError(
                f"collective group size {inner} does not divide the "
                f"participant count {participants}")
        dims = (participants // inner, inner)
        derivation = "collective_group_structure"
    topology = LogicalTopology(dimensions=dims, derivation=derivation)
    if topology.product() != participants:
        raise AstraMachineError(
            f"logical dimensions {dims} do not multiply to the participant "
            f"count {participants}")
    return topology


# ── memory scope ──────────────────────────────────────────────────────────

def memory_scope(logical: Any = None, projection: Any = None
                 ) -> tuple[str, bool]:
    """(scope, semantically_active).

    Canonical memory timing is not reclaimed, so a workload that would
    exercise the analytical memory model is refused outright rather than
    measured with invented constants.  ``logical`` is the canonical
    ``LogicalMessageArtifactV2``: its operation kinds are the authority for
    whether any memory/PIM semantics are in play.
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


# ── packetization ─────────────────────────────────────────────────────────

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


# ── the artifact ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AstraMachineProjection:
    """Deterministic ASTRA runtime inputs, derived and content-addressed."""

    # -- canonical parents (all hashes, no paths) -------------------------
    resolved_fabric_hash: str
    mapping_hash: str
    attachment_hash: str
    topology_hash: str
    packet_format_hash: str
    vc_resource_hash: str
    route_artifact_hash: str
    # -- BookSim machine authority ---------------------------------------
    prepared_id: str
    booksim_profile_id: str
    embedded_fabric_abi_version: str
    standalone_config_sha256: str
    # -- ASTRA workload authority ----------------------------------------
    workload_projection_id: str
    workload_semantics_version: int
    et_granularity: str
    expansion_authority: str
    workload_evidence_scope: str
    # -- machine profile --------------------------------------------------
    machine_profile_version: str
    machine_derivation_version: str
    astra_collective_profile_version: str
    memory_profile_version: str
    network_config_abi: str
    # -- derived facts ----------------------------------------------------
    participant_count: int
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
    # -- rendered bytes ---------------------------------------------------
    system_config_text: str
    network_config_text: str
    logical_topology_text: str
    memory_config_text: str
    schema_version: int = ASTRA_MACHINE_SCHEMA_VERSION

    # -- files ------------------------------------------------------------
    def files(self) -> dict[str, bytes]:
        return {
            SYSTEM_FILE: _json_bytes(self.system_config_text),
            NETWORK_FILE: self.network_config_text.encode("utf-8"),
            LOGICAL_TOPOLOGY_FILE:
                _json_bytes(self.logical_topology_text),
            MEMORY_FILE: _json_bytes(self.memory_config_text),
        }

    def file_digests(self) -> dict[str, str]:
        return {name: content_hash("srota/AstraMachineConfig", 1,
                                   {"name": name,
                                    "text": blob.decode("utf-8")})
                for name, blob in self.files().items()}

    # -- identity ---------------------------------------------------------
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
            "workload_projection_id": self.workload_projection_id,
            "workload_semantics_version": self.workload_semantics_version,
            "et_granularity": self.et_granularity,
            "expansion_authority": self.expansion_authority,
            "workload_evidence_scope": self.workload_evidence_scope,
            "participant_count": self.participant_count,
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

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["machine_id"] = self.machine_id()
        payload["system_config"] = json.loads(self.system_config_text)
        payload["logical_topology_config"] = json.loads(
            self.logical_topology_text)
        payload["memory_config"] = json.loads(self.memory_config_text)
        return payload

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_dict(), sort_keys=True, indent=2)
                + "\n").encode("utf-8")

    # -- materialization ---------------------------------------------------
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
            # defence in depth: the config bytes already pin it
            command.append(
                f"--booksim2-extra=injection_rate={DISARMED_INJECTION_RATE}")
        return tuple(command)


def _json_bytes(text: str) -> bytes:
    return (json.dumps(json.loads(text), sort_keys=True, indent=2)
            + "\n").encode("utf-8")


# ── qualification ─────────────────────────────────────────────────────────

def qualify_astra_machine(*, parents: Any, prepared: Any, projection: Any,
                          logical: Any = None,
                          flit_bytes: int | None = None,
                          astra_collective_authority: bool | None = None
                          ) -> AstraMachineProjection:
    """Build the machine projection from canonical artifacts only."""
    if prepared is None:
        raise AstraMachineError("a PreparedBookSimInput is required")
    if projection is None:
        raise AstraMachineError("an AstraWorkloadProjection is required")
    if not hasattr(projection, "identity_dict"):
        raise AstraMachineError(
            "the workload projection must be an AstraWorkloadProjection")

    embedded = embedded_fabric_config(prepared)
    derived_topology = derive_logical_dimensions(projection)
    scope, active = memory_scope(logical, projection)
    authority = projection.expansion_authority()
    if authority not in ("srota_logical_messages", "astra_comm_coll"):
        raise AstraMachineError(
            f"unknown collective expansion authority {authority!r}")
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
    memory = {**RUNTIME_REQUIRED_MEMORY, "num-nodes": prepared.router_count}
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


# ── workload staging ──────────────────────────────────────────────────────

WORKLOAD_BASE_NAME = "workload"
WORKLOAD_ET = f"{WORKLOAD_BASE_NAME}.et"


def stage_workload(projection: Any, directory: str | Path
                   ) -> tuple[Path, tuple[int, ...]]:
    """Stage the canonical Chakra ETs so only participants run the trace.

    The frontend resolves a rank's workload as ``<base>.<rank>.et`` and
    falls back to ``<base>`` when that file is absent — which would silently
    replicate the trace onto *every* fabric node, including the driver
    endpoint.  So every projected rank must have its own file, and the
    staged rank set is returned so the caller can assert it.
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
