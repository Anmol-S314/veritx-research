"""Slice 35 — canonical serving network backend adapter.

LLMServingSim owns **service** behaviour: request arrival, routing between
serving instances, scheduler queues, batching, prefill/decode separation,
KV/cache state and per-request metrics.  It owns nothing physical.

All physical network execution crosses the already-qualified canonical
boundary established by Slices 31-34::

    canonical fabric -> PreparedBookSimInput -> AstraMachineProjection
      -> AstraExecutionNamespace -> endpoint-indexed Chakra
      -> communicator groups -> current-source ASTRA + canonical BookSim

This module is the only place the two meet.  It accepts *qualified objects*
and never reconstructs semantics: there is no topology generation, no
BookSim config authoring and no model-preset inspection here, because the
historical ``prepare_booksim_config`` path is explicitly not an authority.

Five namespaces stay distinct and are never assumed equal::

    serving instance  !=  canonical rank  !=  physical endpoint
                      !=  BookSim node    !=  router
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.backend.astra_machine import AstraMachineProjection
from veritx_dse.backend.astra_namespace import (
    COMM_GROUP_FILE,
    AstraNamespaceError,
    AstraExecutionNamespace,
    StagedWorkload,
    stage_endpoint_workload,
    write_communicator_groups,
)
from veritx_dse.backend.producer import (
    ProducerError,
    ProducerIdentity,
    recheck_binary_digest,
    resolve_producer_identity,
)
from veritx_dse.core.artifact import content_hash

SERVING_SCHEMA_VERSION = 1
SERVING_BACKEND_ABI = "srota/canonical-serving-backend/v1"

#: the only network evidence tier qualified for communication-producing
#: serving runs in this slice
TIER_ASTRA_OWNED_COLLECTIVE = "ASTRA_OWNED_COLLECTIVE_EXECUTION"
EXPANSION_AUTHORITY_ASTRA = "astra_comm_coll"
#: requesting the canonical-message tier must fail, never silently fall back
MESSAGE_MODE_STATUS = "UNSUPPORTED_RUNTIME_FOR_CANONICAL_MESSAGE_MODE"

#: execution modes -- replay-only can never masquerade as live evidence
MODE_LIVE_CANONICAL = "LIVE_CANONICAL_EXECUTION"
MODE_REPLAY_ONLY = "REPLAY_ONLY_PROTOCOL"

WORKLOAD_ET = "workload.et"


class ServingBoundaryError(ValueError):
    """The serving layer tried to cross the canonical boundary invalidly."""


class CanonicalMessageModeUnsupported(ServingBoundaryError):
    """The runtime cannot execute the canonical SEND/RECV schedule."""

    status = MESSAGE_MODE_STATUS


# ── instance -> rank -> endpoint ──────────────────────────────────────────

@dataclass(frozen=True)
class ServingInstance:
    """One serving instance and the canonical ranks it owns."""

    instance_id: int
    ranks: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.instance_id) is not int or self.instance_id < 0:
            raise ServingBoundaryError("instance_id must be a non-negative int")
        if not self.ranks:
            raise ServingBoundaryError(
                f"serving instance {self.instance_id} owns no canonical rank")
        if len(set(self.ranks)) != len(self.ranks):
            raise ServingBoundaryError(
                f"serving instance {self.instance_id} repeats a rank")


@dataclass(frozen=True)
class ServingNamespaceBinding:
    """serving instance -> canonical rank -> physical endpoint.

    Slices 33/34 own rank -> endpoint; this only adds the serving-instance
    grouping, and every relation is validated against the qualified objects
    rather than derived from numeric coincidence.
    """

    namespace: AstraExecutionNamespace
    instances: tuple[ServingInstance, ...]
    serving_config_id: str

    def __post_init__(self) -> None:
        if not self.instances:
            raise ServingBoundaryError("at least one serving instance required")
        ids = [i.instance_id for i in self.instances]
        if sorted(ids) != list(range(len(ids))):
            raise ServingBoundaryError(
                f"serving instance ids must be 0..N-1, got {sorted(ids)}")
        seen: set[int] = set()
        for instance in self.instances:
            for rank in instance.ranks:
                if rank in seen:
                    raise ServingBoundaryError(
                        f"canonical rank {rank} is owned by more than one "
                        "serving instance")
                if not 0 <= rank < self.namespace.participant_count:
                    raise ServingBoundaryError(
                        f"serving instance {instance.instance_id} names rank "
                        f"{rank} outside the canonical participant namespace")
                seen.add(rank)
        expected = set(range(self.namespace.participant_count))
        if seen != expected:
            missing = sorted(expected - seen)
            raise ServingBoundaryError(
                f"canonical ranks {missing} are not owned by any serving "
                "instance; every participant must be scheduled")

    # -- queries ----------------------------------------------------------
    def endpoints_of(self, instance_id: int) -> tuple[int, ...]:
        return tuple(sorted(self.namespace.endpoint_for(rank)
                            for rank in self.instance_for(instance_id).ranks))

    def instance_for(self, instance_id: int) -> ServingInstance:
        for instance in self.instances:
            if instance.instance_id == instance_id:
                return instance
        raise ServingBoundaryError(f"unknown serving instance {instance_id}")

    def instance_of_rank(self, rank: int) -> int:
        for instance in self.instances:
            if rank in instance.ranks:
                return instance.instance_id
        raise ServingBoundaryError(f"rank {rank} has no serving instance")

    def instance_of_endpoint(self, endpoint: int) -> int | None:
        """Completion attribution needs this, and only this, relation."""
        for rank, candidate in self.namespace.rank_to_endpoint:
            if candidate == endpoint:
                return self.instance_of_rank(rank)
        return None

    def owned_endpoints(self) -> tuple[int, ...]:
        return self.namespace.participant_endpoints()

    def served_instance_set(self) -> tuple[int, ...]:
        return tuple(instance.instance_id for instance in self.instances)

    def rank_to_endpoint(self) -> tuple[tuple[int, int], ...]:
        return self.namespace.rank_to_endpoint

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ServingNamespaceBinding",
            "schema_version": SERVING_SCHEMA_VERSION,
            "serving_config_id": self.serving_config_id,
            "namespace_id": self.namespace.namespace_id(),
            "participant_mapping_id": self.namespace.participant_mapping_id,
            "instances": [[i.instance_id, list(i.ranks)]
                          for i in self.instances],
            "rank_to_endpoint": [[r, e]
                                 for r, e in self.namespace.rank_to_endpoint],
        }

    def binding_id(self) -> str:
        return content_hash("srota/ServingNamespaceBinding", 1,
                            self.identity_dict())


# ── completion attribution ────────────────────────────────────────────────

@dataclass(frozen=True)
class CompletionAttribution:
    """Which serving instance a backend completion actually retires."""

    endpoint: int
    rank: int
    instance: int


def attribute_completions(*, per_endpoint: dict[int, int],
                          binding: ServingNamespaceBinding,
                          dispatched: frozenset[int]
                          ) -> tuple[tuple[CompletionAttribution, ...],
                                     tuple[int, ...]]:
    """Attribute completions through the canonical endpoint namespace.

    Slice 34 showed backend output mixes global and endpoint-specific
    information with different semantics, so a single leading completion
    line must never be read as "sys 0 owns the work".  A completion retires
    work only for the instance that owns that endpoint, and only when that
    instance actually had a batch dispatched.
    """
    rows: list[CompletionAttribution] = []
    unowned: list[int] = []
    for endpoint in sorted(per_endpoint):
        count = per_endpoint[endpoint]
        if count <= 0:
            continue
        instance = binding.instance_of_endpoint(endpoint)
        if instance is None:
            if endpoint in binding.namespace.idle_endpoints():
                raise ServingBoundaryError(
                    f"endpoint {endpoint} is a non-participant fabric "
                    "endpoint but reported a completion")
            unowned.append(endpoint)
            continue
        rank = next(r for r, e in binding.rank_to_endpoint() if e == endpoint)
        if instance not in dispatched:
            # a completion for an instance with nothing in flight cannot
            # retire queued-but-unsent work (the historical pass-echo bug)
            raise ServingBoundaryError(
                f"endpoint {endpoint} completed {count} time(s) for serving "
                f"instance {instance}, which dispatched no batch; pass echoes "
                "must never retire queued-but-unsent work")
        rows.append(CompletionAttribution(endpoint=endpoint, rank=rank,
                                          instance=instance))
    return tuple(rows), tuple(sorted(unowned))


def instances_with_completions(
        attributions: tuple[CompletionAttribution, ...]) -> tuple[int, ...]:
    return tuple(sorted({row.instance for row in attributions}))


# ── the adapter ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CanonicalServingNetworkBackend:
    """The only bridge from serving rounds to physical network execution."""

    machine: AstraMachineProjection
    binding: ServingNamespaceBinding
    astra_binary: str
    astra_binary_sha256: str
    astra_binary_size: int
    astra_source_revision: str | None
    execution_mode: str = MODE_LIVE_CANONICAL
    #: resolved once at construction and rechecked before every spawn; a
    #: fresh re-resolution would compare the binary against itself
    producer: Any = None

    # -- validation --------------------------------------------------------
    def __post_init__(self) -> None:
        if not isinstance(self.machine, AstraMachineProjection):
            raise ServingBoundaryError(
                "the canonical backend requires an AstraMachineProjection")
        if not isinstance(self.binding.namespace, AstraExecutionNamespace):
            raise ServingBoundaryError(
                "the canonical backend requires an AstraExecutionNamespace")
        if self.binding.namespace.machine_id != self.machine.machine_id():
            raise ServingBoundaryError(
                "the serving namespace belongs to a different machine "
                "projection; refusing to bind them")
        if self.execution_mode not in (MODE_LIVE_CANONICAL, MODE_REPLAY_ONLY):
            raise ServingBoundaryError(
                f"unknown execution mode {self.execution_mode!r}")
        if self.execution_mode == MODE_LIVE_CANONICAL:
            if not Path(self.astra_binary).is_file():
                raise ServingBoundaryError(
                    f"qualified ASTRA binary not found: {self.astra_binary}")
            # A caller-supplied digest is a CLAIM, never evidence: resolve the
            # real binary and refuse any disagreement, so a false digest or a
            # substituted binary cannot become scientific evidence.
            identity = resolve_producer_identity(Path(self.astra_binary))
            object.__setattr__(self, "producer", identity)
            if self.astra_binary_sha256 != identity.binary_sha256:
                raise ServingBoundaryError(
                    "declared ASTRA binary digest does not match the binary "
                    f"on disk ({self.astra_binary_sha256[:16]}... != "
                    f"{identity.binary_sha256[:16]}...)")
            if self.astra_binary_size != identity.binary_size:
                raise ServingBoundaryError(
                    "declared ASTRA binary size does not match the binary on "
                    f"disk ({self.astra_binary_size} != "
                    f"{identity.binary_size})")

    def producer_identity(self) -> ProducerIdentity:
        """The ASTRA binary's real identity, resolved from the artifact."""
        if self.producer is not None:
            return self.producer
        try:
            identity = resolve_producer_identity(Path(self.astra_binary))
        except ProducerError as exc:  # pragma: no cover - thin wrapper
            raise ServingBoundaryError(str(exc)) from exc
        object.__setattr__(self, "producer", identity)
        return identity

    def recheck_before_spawn(self) -> None:
        """Last-instant proof the qualified binary is the one being executed."""
        if self.execution_mode != MODE_LIVE_CANONICAL:
            return
        try:
            recheck_binary_digest(self.producer_identity())
        except ProducerError as exc:
            raise ServingBoundaryError(
                f"the ASTRA binary changed before spawn: {exc}") from exc

    def assert_network_authority(self) -> None:
        """Every precondition that makes this a qualified execution."""
        # ``expansion_authority`` is a workload-projection fact carried into
        # the machine identity, so binding machine_id binds it transitively
        authority = self.machine.expansion_authority
        if authority == "srota_logical_messages":
            raise CanonicalMessageModeUnsupported(
                "the runtime cannot execute the canonical logical-message "
                "schedule; serving evidence must use the ASTRA-owned "
                "collective tier instead of silently falling back")
        if authority != EXPANSION_AUTHORITY_ASTRA:
            raise ServingBoundaryError(
                f"unsupported collective expansion authority {authority!r}")
        if self.binding.namespace.router_count != self.machine.router_count:
            raise ServingBoundaryError(
                "the serving namespace and machine projection disagree on "
                "the fabric router count")

    def evidence_tier(self) -> str:
        self.assert_network_authority()
        return TIER_ASTRA_OWNED_COLLECTIVE

    def expansion_authority(self) -> str:
        self.assert_network_authority()
        return self.machine.expansion_authority

    # -- runtime surface ---------------------------------------------------
    def qualified_argv(self, *, workload_path: str, cwd: Path
                       ) -> tuple[str, ...]:
        """The exact ASTRA argv: canonical machine + namespace, nothing else."""
        self.assert_network_authority()
        command = self.machine.runtime_command(
            binary=self.astra_binary,
            workload_configuration=workload_path,
            workload_directory=cwd)
        return tuple(command) + (
            f"--comm-group-configuration={COMM_GROUP_FILE}",)

    def startup_workload_path(self, *, cwd: str | Path) -> Path:
        """The argv workload the frontend executes before interactive mode.

        It deliberately has **no** per-rank ET files, so every ``Sys`` starts
        idle and the real round is delivered later by ``load``/``run``.  This
        matters: ``CollectiveImplLookup`` is stateful per process, so running
        the same ET twice in one backend (startup + re-load) is not the
        supported path.
        """
        return Path(cwd) / "startup.et"

    def stage_round(self, *, workload: Any, directory: str | Path,
                    stem: str = "workload") -> StagedWorkload:
        """Stage one serving round's communication through Slice-34 staging."""
        self.assert_network_authority()
        target = Path(directory)
        self.machine.materialize(target)
        write_communicator_groups(self.binding.namespace, target)
        canonical = target / "canonical"
        workload.write_chakra(directory=canonical, stem=stem)
        return stage_endpoint_workload(
            workload=workload, namespace=self.binding.namespace,
            source_directory=canonical, target_directory=target, stem=stem)

    def covers(self, *, machine_id: str, namespace_id: str,
               participant_mapping_id: str) -> bool:
        """Reuse gate: all three canonical identities must match."""
        return (machine_id == self.machine.machine_id()
                and namespace_id == self.binding.namespace.namespace_id()
                and participant_mapping_id
                == self.binding.namespace.participant_mapping_id)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/CanonicalServingNetworkBackend",
            "schema_version": SERVING_SCHEMA_VERSION,
            "abi": SERVING_BACKEND_ABI,
            "machine_id": self.machine.machine_id(),
            "namespace_id": self.binding.namespace.namespace_id(),
            "participant_mapping_id":
                self.binding.namespace.participant_mapping_id,
            "serving_binding_id": self.binding.binding_id(),
            "astra_binary_sha256": self.astra_binary_sha256,
            "astra_binary_size": self.astra_binary_size,
            "astra_source_revision": self.astra_source_revision,
            "embedded_fabric_abi_version":
                self.machine.embedded_fabric_abi_version,
            "standalone_config_sha256": self.machine.standalone_config_sha256,
            "bootsim_profile_id": self.machine.booksim_profile_id,
            "network_evidence_tier": TIER_ASTRA_OWNED_COLLECTIVE,
            "expansion_authority": EXPANSION_AUTHORITY_ASTRA,
            "instance_count": len(self.binding.instances),
            "execution_mode": self.execution_mode,
        }

    def backend_id(self) -> str:
        return content_hash("srota/CanonicalServingNetworkBackend", 1,
                            self.identity_dict())


# ── serving evidence ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class RequestMetric:
    request_id: str
    ttft_cycles: int | None
    completion_cycles: int | None


@dataclass(frozen=True)
class CanonicalServingEvidence:
    """Service evidence that is useless without the canonical identities."""

    workload_id: str
    serving_config_id: str
    machine_id: str
    namespace_id: str
    participant_mapping_id: str
    serving_binding_id: str
    backend_id: str
    astra_binary_sha256: str
    astra_binary_size: int
    astra_source_revision: str | None
    embedded_fabric_abi_version: str
    standalone_config_sha256: str
    network_evidence_tier: str
    expansion_authority: str
    execution_mode: str
    instance_count: int
    served_instances: tuple[int, ...]
    instances_with_completions: tuple[int, ...]
    request_count: int
    request_metrics: tuple[RequestMetric, ...]
    rounds: int
    endpoint_completions: tuple[tuple[int, int], ...]
    backend_evidence_ids: tuple[str, ...]
    autonomous_injection_packets: tuple[int | None, ...] = ()
    schema_version: int = SERVING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_mode not in (MODE_LIVE_CANONICAL,
                                       MODE_REPLAY_ONLY):
            raise ServingBoundaryError(
                f"unknown execution mode {self.execution_mode!r}")
        if self.execution_mode == MODE_LIVE_CANONICAL:
            # live evidence must carry a complete canonical identity
            for name, value in (
                    ("machine_id", self.machine_id),
                    ("namespace_id", self.namespace_id),
                    ("participant_mapping_id", self.participant_mapping_id),
                    ("astra_binary_sha256", self.astra_binary_sha256)):
                if not value:
                    raise ServingBoundaryError(
                        f"live serving evidence is missing {name}; a result "
                        "without the canonical identity is not reusable")

    def reusable(self) -> bool:
        return (self.execution_mode == MODE_LIVE_CANONICAL
                and self.network_evidence_tier == TIER_ASTRA_OWNED_COLLECTIVE)

    def every_instance_served(self) -> bool:
        return (self.instances_with_completions
                == tuple(range(self.instance_count)))

    def identity_dict(self) -> dict[str, Any]:
        """Scientific identity -- no paths, PIDs, temp dirs or host time."""
        return {
            "type": "srota/CanonicalServingEvidence",
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "serving_config_id": self.serving_config_id,
            "machine_id": self.machine_id,
            "namespace_id": self.namespace_id,
            "participant_mapping_id": self.participant_mapping_id,
            "serving_binding_id": self.serving_binding_id,
            "backend_id": self.backend_id,
            "astra_binary_sha256": self.astra_binary_sha256,
            "astra_binary_size": self.astra_binary_size,
            "astra_source_revision": self.astra_source_revision,
            "embedded_fabric_abi_version":
                self.embedded_fabric_abi_version,
            "standalone_config_sha256": self.standalone_config_sha256,
            "network_evidence_tier": self.network_evidence_tier,
            "expansion_authority": self.expansion_authority,
            "execution_mode": self.execution_mode,
            "instance_count": self.instance_count,
            "served_instances": list(self.served_instances),
            "instances_with_completions":
                list(self.instances_with_completions),
            "request_count": self.request_count,
            "request_metrics": [
                [m.request_id, m.ttft_cycles, m.completion_cycles]
                for m in self.request_metrics],
            "rounds": self.rounds,
            "endpoint_completions": [[e, c]
                                     for e, c in self.endpoint_completions],
            "backend_evidence_ids": list(self.backend_evidence_ids),
            "autonomous_injection_packets":
                list(self.autonomous_injection_packets),
        }

    def evidence_id(self) -> str:
        return content_hash("srota/CanonicalServingEvidence", 1,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["evidence_id"] = self.evidence_id()
        payload["reusable"] = self.reusable()
        payload["every_instance_served"] = self.every_instance_served()
        return payload

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_dict(), sort_keys=True, indent=2)
                + "\n").encode("utf-8")

    # -- guards ------------------------------------------------------------
    def assert_live(self) -> None:
        """Replay-only evidence must never pass as live network evidence."""
        if self.execution_mode != MODE_LIVE_CANONICAL:
            raise ServingBoundaryError(
                "replay-only serving evidence does not prove live network "
                "integration; it cannot be the scientific gate")
        if self.network_evidence_tier != TIER_ASTRA_OWNED_COLLECTIVE:
            raise ServingBoundaryError(
                f"live serving evidence requires the "
                f"{TIER_ASTRA_OWNED_COLLECTIVE} tier, got "
                f"{self.network_evidence_tier}")

    def assert_all_instances_served(self) -> None:
        if not self.every_instance_served():
            raise ServingBoundaryError(
                "not every serving instance completed work: served "
                f"{list(self.instances_with_completions)} of "
                f"{list(range(self.instance_count))}; a total request count "
                "is not sufficient evidence")
