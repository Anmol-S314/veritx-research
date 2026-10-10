"""Slice 33 — authenticated ASTRA + embedded-BookSim execution.

Rationale: docs/decisions/modules/backend.md
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from veritx_dse.backend.astra_machine import (
    LOGICAL_TOPOLOGY_FILE,
    MEMORY_FILE,
    NETWORK_FILE,
    NETWORK_CONFIG_ABI,
    SYSTEM_FILE,
    AstraMachineError,
    AstraMachineProjection,
)
from veritx_dse.backend.producer import (
    ProducerIdentity,
    ProducerError,
    recheck_binary_digest,
    resolve_producer_identity,
)

ASTRA_EXECUTION_SCHEMA_VERSION = 1
ASTRA_PARSER_VERSION = "srota/astra-stats-parser/v1"

ASTRA_BUILD_RECIPE_VERSION = "astra-sim+booksim2/v1"

EVIDENCE_TIER_STANDALONE_BOOKSIM = "STANDALONE_BOOKSIM_EXECUTION"
EVIDENCE_TIER_EMBEDDED_FABRIC = "EMBEDDED_BOOKSIM_FABRIC_EXECUTION"
EVIDENCE_TIER_ASTRA_COLLECTIVE = "ASTRA_OWNED_COLLECTIVE_EXECUTION"
EVIDENCE_TIER_ASTRA_MESSAGES = "CANONICAL_MESSAGE_ASTRA_EXECUTION"

STATUS_EXECUTED = "EXECUTED"
STATUS_UNSUPPORTED_MESSAGE_MODE = (
    "UNSUPPORTED_RUNTIME_FOR_CANONICAL_MESSAGE_MODE")

NAMESPACE_BINDING_CANONICAL = "CANONICAL_PARTICIPANT_MAPPING"
NAMESPACE_BINDING_IDENTITY = "IDENTITY_RANK_ENDPOINT_ASSUMED"

EXECUTION_TRANSPORT_SUPERVISED = "SUPERVISED_PROCESS"
EXECUTION_TRANSPORT_TEST_INJECTED = "TEST_INJECTED"

_RANK_RE = re.compile(
    r"sys\[(\d+)\]\s*finished,\s*(\d+)\s*cycles,\s*exposed communication\s*"
    r"(\d+)\s*cycles")
_WALL_RE = re.compile(r"sys\[(\d+)\],\s*Wall time:\s*(\d+)")
_COMM_RE = re.compile(r"sys\[(\d+)\],\s*Comm time:\s*(\d+)")
_GPU_RE = re.compile(r"sys\[(\d+)\],\s*GPU time:\s*(\d+)")
_INJECTED_RE = re.compile(r"\[trace\] All\s+\d+\s+cycles,\s*injected=(\d+)")
_STREAM_RE = re.compile(
    r"\[LEDGER\]\[STREAM\]\s+rank=(\d+)\s+stream_id=(\d+)\s+"
    r"comm_type=(\d+)")
COMTYPE_TO_CLASS_ID = {0: 0, 1: 2, 2: 3, 3: 1, 4: 4, 5: 0}
COLLECTIVE_KIND_TO_COMTYPE = {
    "REDUCESCATTER": 1, "ALLGATHER": 2, "ALLREDUCE": 3,
    "ALLTOALL": 4,
}
_LEGACY_JSON_ABI_TOKEN = b"booksim-config-file"

class AstraExecutionError(ValueError):
    """The runtime deviated from the projected machine."""

@dataclass(frozen=True)
class AstraOutcome:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

@dataclass(frozen=True)
class AstraMoney:
    """Per-rank runtime result."""

    cycles: tuple[tuple[int, int], ...]
    exposed_comm: tuple[tuple[int, int], ...]
    compute: tuple[tuple[int, int], ...]

@dataclass(frozen=True)
class AstraRuntimeEvidence:
    status: str
    evidence_tier: str
    expansion_authority: str
    workload_evidence_scope: str
    machine_id: str
    prepared_id: str
    workload_projection_id: str
    network_config_abi: str
    embedded_fabric_abi_version: str
    astra_binary_sha256: str
    astra_binary_size: int
    astra_source_revision: str | None
    astra_dirty: bool | None
    binary_accepts_legacy_json_abi: bool
    book_sim_source_has_json_unwrap: bool
    packetization_fidelity: str
    flit_bytes: int
    participant_count: int
    autonomous_injection_packets: int | None
    per_rank_cycles: tuple[tuple[int, int], ...]
    per_rank_exposed_comm: tuple[tuple[int, int], ...]
    per_rank_compute: tuple[tuple[int, int], ...]
    aggregate_cycles: int
    aggregate_exposed_comm: int
    rank_count: int
    rank_to_endpoint: tuple[tuple[int, int], ...]
    namespace_id: str
    namespace_binding: str
    endpoint_count: int
    astra_sys_count: int
    idle_fabric_endpoints: tuple[int, ...]
    participant_statistics_present: bool
    per_endpoint_cycles: tuple[tuple[int, int], ...]
    per_endpoint_exposed_comm: tuple[tuple[int, int], ...]
    transport: str
    class_binding_id: str | None = None
    embedded_network_class_abi_version: int = 0
    astra_build_manifest_sha256: str | None = None
    astra_build_recipe_version: str | None = None
    per_class_injected: tuple[tuple[str, int], ...] = ()
    per_class_completed: tuple[tuple[str, int], ...] = ()
    parser_version: str = ASTRA_PARSER_VERSION
    schema_version: int = ASTRA_EXECUTION_SCHEMA_VERSION

    def ranked(self, which: str) -> dict[int, int]:
        return dict({"cycles": self.per_rank_cycles,
                     "exposed_comm": self.per_rank_exposed_comm,
                     "compute": self.per_rank_compute}[which])

    def identity_dict(self) -> dict[str, Any]:
        """Scientific identity — excludes host and wall-clock facts."""
        return {
            "type": "srota/AstraRuntimeEvidence",
            "schema_version": self.schema_version,
            "parser_version": self.parser_version,
            "status": self.status,
            "evidence_tier": self.evidence_tier,
            "expansion_authority": self.expansion_authority,
            "workload_evidence_scope": self.workload_evidence_scope,
            "machine_id": self.machine_id,
            "prepared_id": self.prepared_id,
            "workload_projection_id": self.workload_projection_id,
            "network_config_abi": self.network_config_abi,
            "embedded_fabric_abi_version":
                self.embedded_fabric_abi_version,
            "astra_binary_sha256": self.astra_binary_sha256,
            "astra_binary_size": self.astra_binary_size,
            "astra_source_revision": self.astra_source_revision,
            "astra_dirty": self.astra_dirty,
            "binary_accepts_legacy_json_abi":
                self.binary_accepts_legacy_json_abi,
            "booksim_source_has_json_unwrap":
                self.book_sim_source_has_json_unwrap,
            "packetization_fidelity": self.packetization_fidelity,
            "flit_bytes": self.flit_bytes,
            "participant_count": self.participant_count,
            "autonomous_injection_packets": self.autonomous_injection_packets,
            "per_rank_cycles": {str(r): c for r, c in self.per_rank_cycles},
            "per_rank_exposed_comm": {str(r): c
                                      for r, c in self.per_rank_exposed_comm},
            "per_rank_compute": {str(r): c
                                 for r, c in self.per_rank_compute},
            "aggregate_cycles": self.aggregate_cycles,
            "aggregate_exposed_comm": self.aggregate_exposed_comm,
            "rank_count": self.rank_count,
            "rank_to_endpoint": [[r, e] for r, e in self.rank_to_endpoint],
            "namespace_id": self.namespace_id,
            "namespace_binding": self.namespace_binding,
            "endpoint_count": self.endpoint_count,
            "astra_sys_count": self.astra_sys_count,
            "idle_fabric_endpoints": list(self.idle_fabric_endpoints),
            "participant_statistics_present":
                self.participant_statistics_present,
            "per_endpoint_cycles": {str(e): c
                                    for e, c in self.per_endpoint_cycles},
            "per_endpoint_exposed_comm":
                {str(e): c for e, c in self.per_endpoint_exposed_comm},
            "class_binding_id": self.class_binding_id,
            "embedded_network_class_abi_version":
                self.embedded_network_class_abi_version,
            "astra_build_manifest_sha256":
                self.astra_build_manifest_sha256,
            "astra_build_recipe_version":
                self.astra_build_recipe_version,
            "per_class_injected": [[c, n]
                                      for c, n in self.per_class_injected],
            "per_class_completed": [[c, n]
                                       for c, n in self.per_class_completed],
        }

    def evidence_id(self) -> str:
        from veritx_dse.core.artifact import content_hash
        return content_hash("srota/AstraRuntimeEvidence", 1,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["evidence_id"] = self.evidence_id()
        payload["transport"] = self.transport
        return payload

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_dict(), sort_keys=True, indent=2)
                + "\n").encode("utf-8")

    @classmethod
    def from_dict(cls, doc: Any) -> "AstraRuntimeEvidence":
        """Rebuild exact runtime evidence from its persisted JSON.

        The caller must verify ``evidence_id()`` against the externally
        held identity before reading this as a measurement.
        """
        if not isinstance(doc, dict):
            raise AstraExecutionError(
                f"evidence document must be a JSON object, got "
                f"{type(doc).__name__}")
        try:
            str_fields = {
                name: doc[name] for name in (
                    "status", "evidence_tier", "expansion_authority",
                    "workload_evidence_scope", "machine_id",
                    "prepared_id", "workload_projection_id",
                    "network_config_abi", "embedded_fabric_abi_version",
                    "astra_binary_sha256",
                    "packetization_fidelity", "namespace_id",
                    "namespace_binding", "transport", "parser_version")}
        except KeyError as exc:
            raise AstraExecutionError(
                f"evidence document is missing {exc}") from exc
        for name, value in str_fields.items():
            if not isinstance(value, str) or not value:
                raise AstraExecutionError(
                    f"evidence document field {name!r} must be a "
                    f"non-empty string")
        bool_fields = {}
        for name in ("binary_accepts_legacy_json_abi",
                     "participant_statistics_present"):
            value = doc.get(name)
            if not isinstance(value, bool):
                raise AstraExecutionError(
                    f"evidence document field {name!r} must be a bool")
            bool_fields[name] = value
        unwrap = doc.get("booksim_source_has_json_unwrap")
        if not isinstance(unwrap, bool):
            raise AstraExecutionError(
                "evidence document field "
                "'booksim_source_has_json_unwrap' must be a bool")
        bool_fields["book_sim_source_has_json_unwrap"] = unwrap
        int_fields = {}
        for name in ("astra_binary_size", "flit_bytes",
                     "participant_count", "aggregate_cycles",
                     "aggregate_exposed_comm", "rank_count",
                     "endpoint_count", "astra_sys_count"):
            value = doc.get(name)
            if type(value) is not int or isinstance(value, bool):
                raise AstraExecutionError(
                    f"evidence document field {name!r} must be an int")
            int_fields[name] = value
        rank_maps = {}
        for name in ("per_rank_cycles", "per_rank_exposed_comm",
                     "per_rank_compute", "per_endpoint_cycles",
                     "per_endpoint_exposed_comm"):
            rank_maps[name] = _rank_map(doc.get(name), name)
        injected = doc.get("autonomous_injection_packets")
        if injected is not None and type(injected) is not int:
            raise AstraExecutionError(
                "evidence document autonomous_injection_packets must be "
                "an int or null")
        revision = doc.get("astra_source_revision")
        if revision is not None and not isinstance(revision, str):
            raise AstraExecutionError(
                "evidence document astra_source_revision must be a "
                "string or null")
        dirty = doc.get("astra_dirty")
        if dirty is not None and not isinstance(dirty, bool):
            raise AstraExecutionError(
                "evidence document astra_dirty must be a bool or null")
        binding_id = doc.get("class_binding_id")
        if binding_id is not None and not isinstance(binding_id, str):
            raise AstraExecutionError(
                "evidence document class_binding_id must be a string "
                "or null")
        class_abi = doc.get("embedded_network_class_abi_version", 0)
        if type(class_abi) is not int or isinstance(class_abi, bool) \
                or class_abi < 0:
            raise AstraExecutionError(
                "evidence document embedded_network_class_abi_version "
                "must be a non-negative int")
        manifest_sha = doc.get("astra_build_manifest_sha256")
        if manifest_sha is not None and not isinstance(manifest_sha, str):
            raise AstraExecutionError(
                "evidence document astra_build_manifest_sha256 must be "
                "a string or null")
        recipe = doc.get("astra_build_recipe_version")
        if recipe is not None and not isinstance(recipe, str):
            raise AstraExecutionError(
                "evidence document astra_build_recipe_version must be "
                "a string or null")
        per_class_injected = _class_counts(
            doc.get("per_class_injected", ()), "per_class_injected")
        per_class_completed = _class_counts(
            doc.get("per_class_completed", ()), "per_class_completed")
        idle = doc.get("idle_fabric_endpoints")
        if not isinstance(idle, list) \
                or any(type(e) is not int for e in idle):
            raise AstraExecutionError(
                "evidence document idle_fabric_endpoints must be a list "
                "of ints")
        binding = doc.get("rank_to_endpoint")
        if not isinstance(binding, list):
            raise AstraExecutionError(
                "evidence document rank_to_endpoint must be a list")
        rank_to_endpoint = tuple(
            _endpoint_pair(row) for row in binding)
        schema = doc.get("schema_version",
                         ASTRA_EXECUTION_SCHEMA_VERSION)
        if schema != ASTRA_EXECUTION_SCHEMA_VERSION:
            raise AstraExecutionError(
                f"unsupported evidence schema_version {schema!r}")
        evidence = cls(
            **str_fields, **bool_fields, **int_fields,
            autonomous_injection_packets=injected,
            astra_source_revision=revision, astra_dirty=dirty,
            class_binding_id=binding_id,
            embedded_network_class_abi_version=class_abi,
            astra_build_manifest_sha256=manifest_sha,
            astra_build_recipe_version=recipe,
            per_class_injected=per_class_injected,
            per_class_completed=per_class_completed,
            per_rank_cycles=rank_maps["per_rank_cycles"],
            per_rank_exposed_comm=rank_maps["per_rank_exposed_comm"],
            per_rank_compute=rank_maps["per_rank_compute"],
            per_endpoint_cycles=rank_maps["per_endpoint_cycles"],
            per_endpoint_exposed_comm=rank_maps[
                "per_endpoint_exposed_comm"],
            rank_to_endpoint=rank_to_endpoint,
            idle_fabric_endpoints=tuple(idle),
            schema_version=schema)
        recorded = doc.get("evidence_id")
        if recorded is not None \
                and recorded != evidence.evidence_id():
            raise AstraExecutionError(
                "stored ASTRA evidence_id does not match the recomputed "
                "identity: content forged")
        return evidence

def _rank_map(raw: Any, where: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(raw, dict):
        raise AstraExecutionError(
            f"evidence document {where} must be an object")
    out = []
    for key, value in raw.items():
        try:
            rank = int(key)
        except (TypeError, ValueError):
            raise AstraExecutionError(
                f"evidence document {where} has non-int rank "
                f"{key!r}") from None
        if type(value) is not int:
            raise AstraExecutionError(
                f"evidence document {where}[{key!r}] must be an int")
        out.append((rank, value))
    return tuple(sorted(out))

def _class_counts(raw: Any, where: str) -> tuple[tuple[str, int], ...]:
    """Per-class count rows: [[class, count], ...]; absent means the
    backend did not expose them, never zero."""
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise AstraExecutionError(
            f"evidence document {where} must be a list of "
            "[class, count] rows")
    out = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) != 2 \
                or not isinstance(row[0], str) or not row[0] \
                or type(row[1]) is not int \
                or isinstance(row[1], bool):
            raise AstraExecutionError(
                f"evidence document {where} rows must be "
                "[non-empty class, int count]")
        out.append((row[0], row[1]))
    return tuple(sorted(out))

def _endpoint_pair(row: Any) -> tuple[int, int]:
    if not isinstance(row, (list, tuple)) or len(row) != 2 \
            or type(row[0]) is not int or type(row[1]) is not int:
        raise AstraExecutionError(
            "evidence document rank_to_endpoint rows must be "
            "[rank, endpoint] int pairs")
    return (row[0], row[1])

def booksim_source_has_json_unwrap(source_root: str | Path) -> bool:
    """Does the vendored ``veritx_embed.cpp`` unwrap ``network.json``?

    Source-proven, not guessed: the archived binary carried an
    ``nlohmann::json`` unwrap of ``booksim-config-file``; the current
    canonical source does not.
    """
    path = (Path(source_root) / "third_party" / "booksim2" / "src"
            / "veritx_embed.cpp")
    if not path.is_file():
        raise AstraExecutionError(
            f"vendored veritx_embed.cpp not found at {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    return ("booksim-config-file" in text)

def probe_binary_network_abi(binary: str | Path) -> bool:
    """True if the binary was built from JSON-unwrapping source.

    A compiled artifact carries the JSON member name as a literal, so this
    is a deterministic, execution-free probe of the *binary's* ABI — which
    is exactly what the archived binary's ABI divergence requires.
    """
    path = Path(binary)
    if not path.is_file():
        raise AstraExecutionError(f"ASTRA binary not found: {path}")
    return _LEGACY_JSON_ABI_TOKEN in path.read_bytes()

def parse_astra_stats(stdout: str, stderr: str) -> AstraMoney:
    """Per-rank cycles / exposed comm / compute; fail closed on deviation."""
    if not isinstance(stdout, str):
        raise AstraExecutionError("stdout must be text")
    cycles: dict[int, int] = {}
    exposed: dict[int, int] = {}
    compute: dict[int, int] = {}
    reported: set[int] = set()
    for line in stdout.splitlines():
        match = _RANK_RE.search(line)
        if match:
            rank = int(match.group(1))
            if rank in reported:
                raise AstraExecutionError(
                    f"runtime reported duplicate results for endpoint {rank}")
            reported.add(rank)
            cycles[rank] = int(match.group(2))
    combined = stdout + "\n" + (stderr or "")
    for line in combined.splitlines():
        wall = _WALL_RE.search(line)
        if wall:
            cycles[int(wall.group(1))] = int(wall.group(2))
        comm = _COMM_RE.search(line)
        if comm:
            exposed[int(comm.group(1))] = int(comm.group(2))
        gpu = _GPU_RE.search(line)
        if gpu:
            compute[int(gpu.group(1))] = int(gpu.group(2))
    if not cycles:
        raise AstraExecutionError(
            "runtime reported no per-endpoint results; refusing to treat "
            "this as execution")
    return AstraMoney(cycles=tuple(sorted(cycles.items())),
                      exposed_comm=tuple(sorted(exposed.items())),
                      compute=tuple(sorted(compute.items())))

def autonomous_injection_packets(stderr: str) -> int | None:
    """The embedded fork's autonomous-injection counter, when it prints one.

    With no ``TraceInjectionProcess`` the drain line appears at the first
    step with ``injected=0``: host-injected packets never touch
    ``_injected_packets``.  A non-zero value means the fabric generated
    traffic the workload did not ask for.
    """
    matches = _INJECTED_RE.findall(stderr or "")
    if not matches:
        return None
    values = {int(v) for v in matches}
    if len(values) != 1:
        raise AstraExecutionError(
            f"runtime printed conflicting injection counters {sorted(values)}")
    return values.pop()

def parse_class_stream_ledger(stderr: str) -> dict[int, int]:
    """Per-ComType stream counts from the contract ledger (stderr).

    Empty dict when the runtime emitted no STREAM lines (ledger below
    level 1): absence stays absent, never a zero-filled claim."""
    counts: dict[int, int] = {}
    for line in (stderr or "").splitlines():
        match = _STREAM_RE.search(line)
        if match:
            comtype = int(match.group(3))
            counts[comtype] = counts.get(comtype, 0) + 1
    return counts

def assert_stream_ledger_covers_kinds(
        counts: dict[int, int],
        expected_kinds: tuple[str, ...]) -> dict[int, int]:
    """The executed schedule attributed every projected collective kind.

    Each projected canonical kind must appear as its ComType stream, and
    no unattributable (0/5) or unexpected ComType may appear: an extra
    stream is traffic the workload did not ask for, an unknown one is
    unattributable. Empty ledger data skips (never zero-filled)."""
    if not counts:
        return {}
    expected = set()
    for kind in expected_kinds:
        try:
            expected.add(COLLECTIVE_KIND_TO_COMTYPE[kind])
        except KeyError:
            raise AstraExecutionError(
                f"projected collective kind {kind!r} has no vendored "
                f"ComType mapping: cannot prove schedule attribution") \
                from None
    unknown = sorted(t for t in counts if t not in COMTYPE_TO_CLASS_ID)
    if unknown:
        raise AstraExecutionError(
            f"runtime scheduled streams with unmapped ComType "
            f"{unknown}: refusing unattributable traffic")
    unattributed = sorted(t for t in counts if COMTYPE_TO_CLASS_ID[t] == 0)
    if unattributed:
        raise AstraExecutionError(
            f"runtime scheduled unattributable streams (ComType "
            f"{unattributed}, class 0): refusing flattened attribution")
    missing = sorted(expected - set(counts))
    if missing:
        raise AstraExecutionError(
            f"runtime scheduled no stream for projected ComType "
            f"{missing}: refusing an execution that dropped a class")
    extra = sorted(set(counts) - expected)
    if extra:
        raise AstraExecutionError(
            f"runtime scheduled unexpected ComType {extra}: refusing "
            f"traffic the workload did not ask for")
    return dict(counts)

def assert_astra_gate(money: AstraMoney, *,
                      machine: AstraMachineProjection,
                      injected: int | None,
                      participant_endpoints: tuple[int, ...] | None = None,
                      endpoint_count: int | None = None) -> tuple[int, ...]:
    """Every condition a usable ASTRA measurement must satisfy.

Rationale: docs/decisions/modules/backend.md
    """
    cycles = dict(money.cycles)
    exposed = dict(money.exposed_comm)
    namespace_size = machine.astra_sys_count
    attached_size = namespace_size if endpoint_count is None else endpoint_count
    if attached_size > namespace_size:
        raise AstraExecutionError("attached endpoint namespace exceeds the rendered native fabric")
    expected = set(range(machine.participant_count)
                   if participant_endpoints is None
                   else participant_endpoints)
    got = set(exposed)
    missing = sorted(expected - got)
    if missing:
        raise AstraExecutionError(
            f"runtime did not report the projected endpoints "
            f"(missing={missing})")
    unexpected = sorted(set(cycles) - set(range(namespace_size)))
    extra = sorted(set(range(namespace_size)) - expected)
    if unexpected:
        raise AstraExecutionError(
            "runtime reported ranks that are neither participants nor "
            f"canonical fabric nodes: {unexpected}")
    for rank in sorted(expected):
        if cycles[rank] <= 0:
            raise AstraExecutionError(
                f"participant rank {rank} reported {cycles[rank]} cycles; "
                "refusing to treat this as execution")
    for endpoint in extra:
        if exposed.get(endpoint, 0) > 0:
            raise AstraExecutionError(
                f"non-participant fabric endpoint {endpoint} carried "
                f"{exposed[endpoint]} cycles of communication; the fabric "
                "simulated traffic the workload did not ask for")
    if injected is not None and injected != 0:
        raise AstraExecutionError(
            f"the embedded fabric injected {injected} packets of its own; "
            "autonomous BookSim traffic was not disabled")
    if machine.expansion_authority == "astra_comm_coll":
        aggregate = max(cycles[r] for r in expected)
        if aggregate <= machine.workload_compute_floor:
            raise AstraExecutionError(
                "silent non-simulation: every rank finished inside the "
                "declared compute floor, so no communication was simulated")
        if machine.workload_payload_bytes > 0 \
                and max(exposed.get(r, 0) for r in expected) <= 0:
            raise AstraExecutionError(
                "silent non-simulation: the workload projects "
                f"{machine.workload_payload_bytes} bytes of communication "
                "but no rank exposed any communication time")
    # Native Sys ids include unused concentrator seats. Validate ALL of them
    # above, but retain the attached-endpoint scope of this evidence field.
    return tuple(endpoint for endpoint in extra if endpoint < attached_size)

def resolve_astra_identity(binary: str | Path, *,
                           repo_root: str | Path | None = None
                           ) -> ProducerIdentity:
    try:
        return resolve_producer_identity(
            Path(binary), repo_root=repo_root,
            require_manifest_recipe=ASTRA_BUILD_RECIPE_VERSION)
    except ProducerError as exc:  # pragma: no cover - thin wrapper
        raise AstraExecutionError(str(exc)) from exc

def materialize_machine(machine: AstraMachineProjection,
                        directory: str | Path) -> dict[str, Path]:
    """Write the projected bytes, verifying what lands on disk."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    written = machine.materialize(target)
    expected = machine.files()
    for name, path in written.items():
        actual = path.read_bytes()
        if actual != expected[name]:
            raise AstraExecutionError(
                f"{path} does not hold the projected bytes; refusing to run")
    for required in (SYSTEM_FILE, NETWORK_FILE, LOGICAL_TOPOLOGY_FILE,
                     MEMORY_FILE):
        if required not in written:
            raise AstraExecutionError(
                f"machine projection is missing required config {required}")
    return written

def execute_astra_machine(
        *, machine: AstraMachineProjection, binary: str | Path,
        run_dir: str | Path, workload_configuration: str | Path,
        timeout_s: int = 600,
        runner: Callable[[tuple[str, ...], Path, int], AstraOutcome]
        | None = None,
        repo_root: str | Path | None = None,
        booksim_source_root: str | Path | None = None,
        require_canonical_packetization: bool = False,
        expected_machine_id: str | None = None,
        namespace: Any = None,
        write: bool = True,
        class_binding_id: str | None = None,
        expected_collective_kinds: tuple[str, ...] | None = None
        ) -> AstraRuntimeEvidence:
    """Run the projected machine and authenticate what came back.

Rationale: docs/decisions/modules/backend.md
    """
    if not isinstance(machine, AstraMachineProjection):
        raise AstraExecutionError(
            "execution consumes only an AstraMachineProjection")
    if expected_machine_id is not None \
            and machine.machine_id() != expected_machine_id:
        raise AstraExecutionError(
            "machine projection does not match the externally held "
            "machine_id; the projection was modified after qualification")
    if namespace is not None \
            and namespace.machine_id != machine.machine_id():
        raise AstraExecutionError(
            "the execution namespace belongs to a different machine "
            "projection; refusing to run a mismatched binding")
    if require_canonical_packetization \
            and machine.packetization_fidelity != "CANONICAL_FLIT_WIDTH":
        raise AstraExecutionError(
            "canonical network fidelity was required but the projection is "
            f"{machine.packetization_fidelity}")

    binary_path = Path(binary)
    identity = resolve_astra_identity(binary_path, repo_root=repo_root)
    recheck_binary_digest(identity)
    if runner is None:
        from veritx_dse.backend.producer import (
            ProducerError as _ProducerError, assert_pinned_producer,
        )
        try:
            assert_pinned_producer(identity)
        except _ProducerError as exc:
            raise AstraExecutionError(
                f"ASTRA producer not pinned, refusing spawn: {exc}"
            ) from exc
    accepts_legacy = probe_binary_network_abi(binary_path)

    workload = Path(workload_configuration)
    if not workload.exists():
        raise AstraExecutionError(
            f"workload configuration not found: {workload}")

    run_directory = Path(run_dir)
    materialize_machine(machine, run_directory)
    for name in (SYSTEM_FILE, NETWORK_FILE, LOGICAL_TOPOLOGY_FILE,
                 MEMORY_FILE):
        if not (run_directory / name).is_file():
            raise AstraExecutionError(
                f"missing config {name} in the run directory")

    command = machine.runtime_command(
        binary=binary_path.resolve(), workload_configuration=workload.resolve(),
        workload_directory=run_directory)
    command = _with_comm_group(command, namespace, run_directory)
    _assert_machine_fields_in_command(command, machine)

    supervised = runner is None
    if supervised:
        def runner(cmd, cwd, timeout):  # pragma: no cover - real process
            try:
                env = dict(os.environ)
                try:
                    level = int(env.get("VERITX_LEDGER", "0") or "0")
                except ValueError:
                    level = 0
                if level < 1:
                    env["VERITX_LEDGER"] = "1"
                proc = subprocess.run(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True,
                                      timeout=timeout, env=env)
            except subprocess.TimeoutExpired:
                return AstraOutcome(returncode=-1, stdout="", stderr="",
                                    timed_out=True)
            return AstraOutcome(returncode=proc.returncode,
                                stdout=proc.stdout or "",
                                stderr=proc.stderr or "")
    transport = (EXECUTION_TRANSPORT_SUPERVISED if supervised
                 else EXECUTION_TRANSPORT_TEST_INJECTED)
    outcome = runner(command, run_directory, timeout_s)
    if outcome.timed_out:
        raise AstraExecutionError(
            f"ASTRA runtime timed out after {timeout_s}s")
    if outcome.returncode != 0:
        raise AstraExecutionError(
            f"ASTRA runtime exited {outcome.returncode}: "
            f"{(outcome.stderr or '')[-400:]}")
    from veritx_dse.backend.booksim_execution import (
        BookSimExecutionError, validate_mesh_class_vc_observations)
    try:
        validate_mesh_class_vc_observations(machine.network_config_text,
            outcome.stdout + '\n' + outcome.stderr)
    except BookSimExecutionError as exc:
        raise AstraExecutionError(str(exc)) from exc
    money = parse_astra_stats(outcome.stdout, outcome.stderr)
    injected = autonomous_injection_packets(outcome.stderr)
    if expected_collective_kinds is not None:
        assert_stream_ledger_covers_kinds(
            parse_class_stream_ledger(outcome.stderr),
            tuple(expected_collective_kinds))
    if namespace is not None:
        participant_endpoints = namespace.participant_endpoints()
        endpoint_count = namespace.endpoint_count
        rank_to_endpoint = namespace.rank_to_endpoint
        namespace_id = namespace.namespace_id()
        namespace_binding = NAMESPACE_BINDING_CANONICAL
    else:
        participant_endpoints = tuple(range(machine.participant_count))
        endpoint_count = machine.astra_sys_count
        rank_to_endpoint = tuple(
            (r, r) for r in range(machine.participant_count))
        namespace_id = _identity_namespace_id(machine)
        namespace_binding = NAMESPACE_BINDING_IDENTITY
    message_mode_unreported = (
        machine.expansion_authority == "srota_logical_messages"
        and not money.exposed_comm
        and not money.compute
        and injected in (None, 0))
    if message_mode_unreported:
        idle_ranks = tuple(sorted(set(range(endpoint_count))
                                  - set(participant_endpoints)))
        money = AstraMoney(cycles=(), exposed_comm=(), compute=())
    else:
        idle_ranks = assert_astra_gate(
            money, machine=machine, injected=injected,
            participant_endpoints=participant_endpoints,
            endpoint_count=endpoint_count)

    cycles = dict(money.cycles)
    exposed = dict(money.exposed_comm)
    compute = dict(money.compute)
    statistics_present = bool(cycles) or bool(exposed)
    aggregate = max((cycles.get(e, 0) for e in participant_endpoints),
                    default=0)
    aggregate_exposed = max(
        (exposed.get(e, 0) for e in participant_endpoints), default=0)
    per_rank_cycles = tuple(sorted(
        (rank, cycles.get(endpoint, 0)) for rank, endpoint in rank_to_endpoint))
    per_rank_exposed = tuple(sorted(
        (rank, exposed.get(endpoint, 0)) for rank, endpoint in rank_to_endpoint))
    per_rank_compute = tuple(sorted(
        (rank, compute.get(endpoint, 0)) for rank, endpoint in rank_to_endpoint))

    status = STATUS_EXECUTED
    if machine.expansion_authority == "srota_logical_messages" \
            and (aggregate_exposed <= 0 or not statistics_present):
        status = STATUS_UNSUPPORTED_MESSAGE_MODE
    tier = _tier(machine)

    source_has_unwrap = (booksim_source_has_json_unwrap(booksim_source_root)
                         if booksim_source_root is not None else False)

    evidence = AstraRuntimeEvidence(
        status=status,
        evidence_tier=tier,
        expansion_authority=machine.expansion_authority,
        workload_evidence_scope=machine.workload_evidence_scope,
        machine_id=machine.machine_id(),
        prepared_id=machine.prepared_id,
        workload_projection_id=machine.workload_projection_id,
        network_config_abi=machine.network_config_abi,
        embedded_fabric_abi_version=machine.embedded_fabric_abi_version,
        astra_binary_sha256=identity.binary_sha256,
        astra_binary_size=identity.binary_size,
        astra_source_revision=identity.source_revision,
        astra_dirty=identity.dirty,
        astra_build_manifest_sha256=identity.build_manifest_sha256,
        astra_build_recipe_version=identity.build_recipe_version,
        class_binding_id=class_binding_id,
        embedded_network_class_abi_version=
        machine.embedded_network_class_abi_version,
        binary_accepts_legacy_json_abi=accepts_legacy,
        book_sim_source_has_json_unwrap=source_has_unwrap,
        packetization_fidelity=machine.packetization_fidelity,
        flit_bytes=machine.flit_bytes,
        participant_count=machine.participant_count,
        autonomous_injection_packets=injected,
        per_rank_cycles=per_rank_cycles,
        per_rank_exposed_comm=per_rank_exposed,
        per_rank_compute=per_rank_compute,
        per_endpoint_cycles=tuple(sorted(cycles.items())),
        per_endpoint_exposed_comm=tuple(sorted(exposed.items())),
        participant_statistics_present=statistics_present,
        rank_to_endpoint=rank_to_endpoint,
        namespace_id=namespace_id,
        namespace_binding=namespace_binding,
        endpoint_count=endpoint_count,
        astra_sys_count=machine.astra_sys_count,
        aggregate_cycles=aggregate,
        aggregate_exposed_comm=aggregate_exposed,
        rank_count=len(per_rank_cycles),
        idle_fabric_endpoints=tuple(idle_ranks),
        transport=transport,
    )
    if write:
        evidence_path = run_directory / "astra_evidence.json"
        text = evidence.canonical_bytes().decode("utf-8")
        if evidence_path.exists() \
                and evidence_path.read_text(encoding="utf-8") != text:
            raise AstraExecutionError(
                f"{evidence_path} already holds different evidence; refusing "
                "to overwrite a scientific claim")
        evidence_path.write_text(text, encoding="utf-8")
    return evidence

def _identity_namespace_id(machine: AstraMachineProjection) -> str:
    """Identity for the explicitly-declared rank==endpoint assumption."""
    from veritx_dse.core.artifact import content_hash
    return content_hash("srota/AstraExecutionNamespace", 1, {
        "type": "srota/AstraExecutionNamespace",
        "namespace_binding": NAMESPACE_BINDING_IDENTITY,
        "machine_id": machine.machine_id(),
        "participant_count": machine.participant_count,
        "endpoint_count": machine.astra_sys_count,
    })

def _tier(machine: AstraMachineProjection) -> str:
    if machine.expansion_authority == "astra_comm_coll":
        return EVIDENCE_TIER_ASTRA_COLLECTIVE
    return EVIDENCE_TIER_ASTRA_MESSAGES

def _with_comm_group(command: tuple[str, ...], namespace: Any,
                     run_directory: Path) -> tuple[str, ...]:
    """Add ``--comm-group-configuration`` when the namespace defines groups."""
    if namespace is None:
        return command
    from veritx_dse.backend.astra_namespace import (
        COMM_GROUP_FILE, write_communicator_groups,
    )
    write_communicator_groups(namespace, run_directory)
    return command + (f"--comm-group-configuration={COMM_GROUP_FILE}",)

def _assert_machine_fields_in_command(command: tuple[str, ...],
                                      machine: AstraMachineProjection
                                      ) -> None:
    joined = " ".join(command)
    if machine.flit_bytes is not None \
            and f"--booksim2-flit-bytes={machine.flit_bytes}" not in joined:
        raise AstraExecutionError(
            "runtime command does not carry the projected flit width")
    if f"--network-configuration={NETWORK_FILE}" not in joined:
        raise AstraExecutionError(
            "runtime command does not carry the projected network config")

def assert_comparable(a: AstraRuntimeEvidence,
                      b: AstraRuntimeEvidence) -> None:
    """Two evidential tiers may not be compared as if interchangeable."""
    if a.evidence_tier != b.evidence_tier:
        raise AstraExecutionError(
            f"evidence tiers are not interchangeable: {a.evidence_tier} vs "
            f"{b.evidence_tier}")
    if a.expansion_authority != b.expansion_authority:
        raise AstraExecutionError(
            "collective expansion authority differs; these runs do not "
            "measure the same schedule")
    if a.machine_id != b.machine_id:
        raise AstraExecutionError(
            "machine projections differ; these runs did not execute the "
            "same machine")
