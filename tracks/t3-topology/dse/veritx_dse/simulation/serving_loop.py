"""Slice 37 — request-driven certified serving orchestration loop (§11).

This is the loop Slice 36 deliberately stopped short of.  It drives a real
request trace through the *real* historical service components and the
*qualified* canonical network boundary, in this order::

    JSONL  ->  Router.route_arrived_requests  ->  Scheduler.schedule
           ->  real Batch  ->  ServingBatchPlan  ->  canonical round
           ->  Scheduler.add_done (retirement)  ->  real TTFT / latency

Nothing here authors a metric.  TTFT, end time, latency and ITL come out of
the vendored ``Request`` object, which is the only thing that may set them.
The service clock is the fabric's own reported cycle count
(``RoundOutcome.backend_cycles``) accumulated round by round; the canonical
machine declares ``ns_per_cycle == 1.0``, so cycles and the trace's
nanosecond arrival times share one domain.

Three namespaces stay distinct, as everywhere else in this track::

    serving instance  !=  virtual NPU  !=  canonical rank  !=  endpoint

The vendored ``Scheduler`` needs a **contiguous** NPU span per instance
(``start_npu .. start_npu + num_npus - 1``) and ``add_done`` will not retire
a batch until both ends of that span report.  Canonical ranks are permuted
onto endpoints and an instance's endpoint set is not contiguous, so this
module introduces an explicit *virtual* NPU namespace and translates it to
canonical ranks/endpoints at round-lowering time — never by numeric
coincidence.

Certified service feature profile (declared, narrow)
----------------------------------------------------
Supported: flat JSONL request traces, real arrival times, RR/LOAD routing,
normal prefill/decode progression, independent instances, collectives
expressed as intent with ``expansion_authority = ASTRA``, the
``ASTRA_OWNED_COLLECTIVE_EXECUTION`` tier.

Deliberately **not** supported here (unchanged from Slice 36): PIM, active
remote-memory timing, CXL semantics, memory-offload timing, canonical-message
ASTRA execution, PD disaggregation, and **partial-membership collectives**.
That last one is the reason a round in this loop spans the *full* participant
set: one certified round carries one communicator group, so every instance's
endpoints execute the round's collective together.  A round therefore serves
a whole service step, and ``dispatched_instances`` is the full instance set;
retirement is gated separately by whether an instance actually had a batch in
flight.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from veritx_dse.backend.canonical_serving import (
    CanonicalServingEvidence,
    CanonicalServingNetworkBackend,
    RequestMetric,
    ServingNamespaceBinding,
)
from veritx_dse.backend.astra_namespace import derive_collective_binding
from veritx_dse.backend.serving_round import (
    CanonicalServingRoundEvidence,
    parse_collective_ledger,
    plan_from_round,
    qualify_round,
    round_evidence_from_outcome,
    validate_collective_ledger_contract,
)
from veritx_dse.core.artifact import content_hash
from veritx_dse.simulation.serving_runtime import (
    RoundOutcome,
    build_serving_evidence,
    run_live_round,
)

SERVICE_LOOP_SCHEMA_VERSION = 1
SERVICE_CLOCK_DOMAIN = "fabric_cycles_at_1ns"
#: the parser that turns runtime output into measured statistics
PARSER_VERSION = "srota/astra-stats-parser/v1"


class ServingLoopError(ValueError):
    """The service loop could not make progress, or a contract broke."""


# ── certified service profile (declared inputs, never measured) ───────────

@dataclass(frozen=True)
class CertifiedServiceProfile:
    """The serving semantics this loop certifies, declared up front.

    ``compute_ns`` and ``collective_bytes`` are *declared* profile inputs, not
    reclaimed upstream measurements: the vendored ``trace_generator`` is
    perf-DB driven (``_load_perf_db(hardware, model, variant, tp_needed,
    model_type)``), and no hardware variant with perf CSVs is qualified here.
    Inventing a substitute would be the dishonest option; declaring a linear
    model and binding it into the profile identity is the honest one.
    """

    model: str
    max_num_seqs: int = 8
    max_num_batched_tokens: int = 1024
    npu_mem_gb: int = 1000
    cpu_mem_gb: int = 1000
    block_size: int = 16
    fp_bits: int = 16
    routing_policy: str = "RR"
    collective_kind: str = "ALLREDUCE"
    collective_bytes_per_rank: int = 4096
    compute_base_ns: int = 10_000
    compute_per_token_ns: int = 1_000
    schema_version: int = SERVICE_LOOP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.model:
            raise ServingLoopError("a certified profile needs a model")
        if self.routing_policy.upper() not in ("RR", "LOAD", "RAND"):
            raise ServingLoopError(
                f"unsupported routing policy {self.routing_policy!r}; the "
                "certified profile supports RR, LOAD and RAND")
        if self.max_num_seqs <= 0:
            raise ServingLoopError("max_num_seqs must be positive")
        if self.max_num_batched_tokens <= 0:
            raise ServingLoopError("max_num_batched_tokens must be positive")
        if self.npu_mem_gb <= 0 or self.cpu_mem_gb <= 0:
            raise ServingLoopError("memory sizes must be positive")
        if self.fp_bits <= 0:
            raise ServingLoopError("fp_bits must be positive")
        if self.collective_bytes_per_rank <= 0:
            raise ServingLoopError(
                "a certified round must carry a positive collective size")
        if self.compute_base_ns <= 0 or self.compute_per_token_ns < 0:
            raise ServingLoopError("the compute model must be positive")

    def compute_ns(self, *, tokens: int) -> int:
        return self.compute_base_ns + self.compute_per_token_ns * max(0, tokens)

    def collective_bytes(self, *, tokens: int) -> int:
        """Declared per-rank collective size for a round of ``tokens``."""
        return self.collective_bytes_per_rank

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/CertifiedServiceProfile",
            "schema_version": self.schema_version,
            "model": self.model,
            "max_num_seqs": self.max_num_seqs,
            "max_num_batched_tokens": self.max_num_batched_tokens,
            "npu_mem_gb": self.npu_mem_gb,
            "cpu_mem_gb": self.cpu_mem_gb,
            "block_size": self.block_size,
            "fp_bits": self.fp_bits,
            "routing_policy": self.routing_policy.upper(),
            "collective_kind": self.collective_kind,
            "collective_bytes_per_rank": self.collective_bytes_per_rank,
            "compute_base_ns": self.compute_base_ns,
            "compute_per_token_ns": self.compute_per_token_ns,
        }

    def profile_id(self) -> str:
        return content_hash("srota/CertifiedServiceProfile", 1,
                            self.identity_dict())


# ── virtual NPU namespace ─────────────────────────────────────────────────

@dataclass(frozen=True)
class VirtualNpuNamespace:
    """serving instance -> contiguous virtual NPU span -> canonical rank.

    The vendored scheduler's NPU ids are a *fourth* namespace, not a synonym
    for canonical rank or endpoint.  Instances are laid out contiguously so
    ``start_npu .. start_npu + num_npus - 1`` is well defined, and every
    translation back to a canonical rank is explicit.
    """

    binding: ServingNamespaceBinding
    schema_version: int = SERVICE_LOOP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sizes = {len(i.ranks) for i in self.binding.instances}
        if len(sizes) != 1:
            raise ServingLoopError(
                "the certified profile requires homogeneous instances; got "
                f"rank counts {sorted(sizes)}")
        if not sizes or next(iter(sizes)) == 0:
            raise ServingLoopError("every instance must own a rank")

    # -- instance -> span --------------------------------------------------
    @property
    def num_npus(self) -> int:
        return len(self.binding.instances[0].ranks)

    def start_npu(self, instance_id: int) -> int:
        self.binding.instance_for(instance_id)
        return instance_id * self.num_npus

    def span(self, instance_id: int) -> tuple[int, ...]:
        start = self.start_npu(instance_id)
        return tuple(range(start, start + self.num_npus))

    def quorum_sys(self, instance_id: int) -> tuple[int, ...]:
        """The NPU ids ``Scheduler.add_done`` needs before it retires.

        Source: ``Scheduler.add_done`` — for a non-PD instance the batch is
        done once ``start_npu`` and ``start_npu + num_npus - 1`` are both in
        ``batch.end``.  A PD *prefill* instance would need
        ``start_npu + 2*num_npus - 1``; PD disaggregation is outside this
        certified profile, so that case is refused rather than guessed.
        """
        start = self.start_npu(instance_id)
        return (start, start + self.num_npus - 1)

    # -- span -> canonical rank -------------------------------------------
    def _ordered_ranks(self, instance_id: int) -> tuple[int, ...]:
        return tuple(sorted(self.binding.instance_for(instance_id).ranks))

    def rank_of_npu(self, npu: int) -> int:
        if not 0 <= npu < self.virtual_npu_count:
            raise ServingLoopError(
                f"virtual NPU {npu} is outside [0, {self.virtual_npu_count})")
        instance_id, local = divmod(npu, self.num_npus)
        return self._ordered_ranks(instance_id)[local]

    def npu_of_rank(self, rank: int) -> int:
        instance_id = self.binding.instance_of_rank(rank)
        local = self._ordered_ranks(instance_id).index(rank)
        return self.start_npu(instance_id) + local

    def endpoint_of_npu(self, npu: int) -> int:
        return self.binding.namespace.endpoint_for(self.rank_of_npu(npu))

    def instance_of_npu(self, npu: int) -> int:
        if not 0 <= npu < self.virtual_npu_count:
            raise ServingLoopError(
                f"virtual NPU {npu} is outside [0, {self.virtual_npu_count})")
        return npu // self.num_npus

    # -- whole-space queries ----------------------------------------------
    @property
    def virtual_npu_count(self) -> int:
        return self.num_npus * len(self.binding.instances)

    def canonical_ranks(self) -> tuple[int, ...]:
        return tuple(sorted(self.rank_of_npu(n)
                            for n in range(self.virtual_npu_count)))

    def canonical_endpoints(self) -> tuple[int, ...]:
        return tuple(sorted(self.endpoint_of_npu(n)
                            for n in range(self.virtual_npu_count)))

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/VirtualNpuNamespace",
            "schema_version": self.schema_version,
            "serving_binding_id": self.binding.binding_id(),
            "namespace_id": self.binding.namespace.namespace_id(),
            "num_npus_per_instance": self.num_npus,
            "npu_to_rank": [[npu, self.rank_of_npu(npu)]
                            for npu in range(self.virtual_npu_count)],
            "npu_to_endpoint": [[npu, self.endpoint_of_npu(npu)]
                                for npu in range(self.virtual_npu_count)],
        }

    def translation_id(self) -> str:
        return content_hash("srota/VirtualNpuNamespace", 1,
                            self.identity_dict())


# ── building the real service components ─────────────────────────────────

def build_schedulers(*, profile: CertifiedServiceProfile,
                     npus: VirtualNpuNamespace, req_num: int = 0) -> tuple[Any, ...]:
    """Real vendored ``Scheduler`` objects, one per serving instance.

    ``pd_type=None`` is upstream's non-disaggregated instance: it is a
    prefill-capable router target and ``add_done`` retires it in place
    instead of transferring to a decode instance.
    """
    try:
        from serving.core.scheduler import Scheduler
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ServingLoopError(
            "the vendored LLMServingSim package is required on sys.path: "
            f"{exc}") from exc

    built = []
    for instance in npus.binding.instances:
        built.append(Scheduler(
            model=profile.model, node_id=0,
            instance_id=instance.instance_id,
            max_num_seqs=profile.max_num_seqs,
            max_num_batched_tokens=profile.max_num_batched_tokens,
            num_npus=len(instance.ranks), tp_size=len(instance.ranks),
            pp_size=1, npu_mem=profile.npu_mem_gb,
            cpu_mem=profile.cpu_mem_gb,
            start_npu=npus.start_npu(instance.instance_id),
            pd_type=None, fp=profile.fp_bits, block_size=profile.block_size,
            req_num=req_num, prioritize_prefill=False,
            enable_prefix_caching=False, enable_prefix_sharing=False,
            prefix_pool=None, prefix_storage=0))
    return tuple(built)


def build_router(*, profile: CertifiedServiceProfile, schedulers: Sequence[Any],
                 req_num: int = 0) -> Any:
    """The real vendored ``Router`` over the built schedulers."""
    try:
        from serving.core.router import Router
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ServingLoopError(
            "the vendored LLMServingSim package is required on sys.path: "
            f"{exc}") from exc
    return Router(num_instances=len(schedulers), schedulers=list(schedulers),
                  req_num=req_num, routing_policy=profile.routing_policy)


def load_request_trace(*, router: Any, dataset: str | Path,
                       load_directory: str | Path, req_num: int = 0) -> Path:
    """Load a JSONL trace through the real ``Router.load_requests``.

    ``Router.load_requests`` opens ``f'../{path}'`` relative to the process
    cwd.  Rather than leave an ambient ``chdir`` inside a service loop, the
    caller names the directory the load happens in and this function computes
    the relative path that resolves to the dataset *from that directory*.
    """
    dataset = Path(dataset).resolve()
    if not dataset.is_file():
        raise ServingLoopError(f"request trace not found: {dataset}")
    load_directory = Path(load_directory).resolve()
    load_directory.mkdir(parents=True, exist_ok=True)
    # upstream resolves '../{path}' against cwd, i.e. load_directory/../path
    relative = os.path.relpath(dataset, load_directory.parent)
    previous = Path.cwd()
    try:
        os.chdir(load_directory)
        router.load_requests(relative)
    finally:
        os.chdir(previous)
    return dataset


# ── round outcomes and run results ────────────────────────────────────────

@dataclass(frozen=True)
class RequestOutcome:
    """One retired request, with only the vendored component's own numbers."""

    request_id: str
    instance_id: int
    arrival_ns: int
    ttft_ns: int
    end_ns: int
    latency_ns: int
    itl_ns: tuple[int, ...]

    def metric(self) -> RequestMetric:
        # the certified clock domain is 1 cycle == 1 ns, so a cycle count and
        # a nanosecond count are the same number here -- never a rescaling
        return RequestMetric(request_id=self.request_id,
                             ttft_cycles=self.ttft_ns,
                             completion_cycles=self.end_ns)


@dataclass(frozen=True)
class RoundRecord:
    round_index: int
    plan_id: str
    qualification_id: str
    evidence_id: str
    #: the round's collective binding and its deterministic group numbers
    collective_binding_id: str
    group_ids: tuple[int, ...]
    batch_ids: tuple[tuple[int, int], ...]
    dispatched_instances: tuple[int, ...]
    backend_cycles: int | None
    clock_after: int
    retired_request_ids: tuple[str, ...]
    #: instances that participated in the round but had no batch in flight;
    #: they must not report execution work
    idle_instances: tuple[int, ...]


@dataclass(frozen=True)
class ServiceRunResult:
    workload_id: str
    profile_id: str
    virtual_npu_id: str
    clock: int
    requests: tuple[RequestOutcome, ...]
    rounds: tuple[RoundRecord, ...]
    round_evidence: tuple[CanonicalServingRoundEvidence, ...]
    evidence: CanonicalServingEvidence
    schema_version: int = SERVICE_LOOP_SCHEMA_VERSION

    def request_metrics(self) -> tuple[RequestMetric, ...]:
        return tuple(r.metric() for r in self.requests)

    def every_request_retired(self, expected: int) -> bool:
        return len(self.requests) == expected

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ServiceRunResult",
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "profile_id": self.profile_id,
            "virtual_npu_id": self.virtual_npu_id,
            "clock": self.clock,
            "request_metrics": [
                [m.request_id, m.ttft_cycles, m.completion_cycles]
                for m in self.request_metrics()],
            "rounds": [
                [r.round_index, r.plan_id, r.qualification_id,
                 r.evidence_id, r.backend_cycles, r.clock_after,
                 list(r.retired_request_ids)]
                for r in self.rounds],
            "evidence_id": self.evidence.evidence_id(),
        }

    def run_id(self) -> str:
        return content_hash("srota/ServiceRunResult", 1, self.identity_dict())


# ── the loop (§11) ────────────────────────────────────────────────────────

def _next_schedulable_time(schedulers: Sequence[Any], router: Any,
                           clock: int) -> int | None:
    """The earliest future time at which a batch could become schedulable."""
    candidates: list[int] = []
    if router.has_pending_requests():
        pending = router.get_next_pending_arrival()
        if pending is not None:
            candidates.append(int(pending))
    for scheduler in schedulers:
        if scheduler.request:
            candidates.append(int(scheduler.request[0].arrival))
    future = [t for t in candidates if t > clock]
    return min(future) if future else None


def _quiescent(schedulers: Sequence[Any], router: Any) -> bool:
    return (all(s.is_request_empty() for s in schedulers)
            and not router.has_pending_requests()
            and not router.has_deferred_sessions())


def run_request_driven_service(
        *, backend: CanonicalServingNetworkBackend, machine: Any,
        profile: CertifiedServiceProfile, npus: VirtualNpuNamespace,
        router: Any, schedulers: Sequence[Any], run_dir: str | Path,
        workload_id: str, lowering: Any,
        timeout_s: int = 900, max_rounds: int = 10_000,
        session_factory: Any = None, ledger: bool = True,
        expected_requests: int = 0) -> ServiceRunResult:
    """Drive a real request trace to real per-request service metrics.

    One iteration of the loop is one certified round: route arrivals, ask
    every instance's real scheduler for a real ``Batch``, lower the round to
    the canonical boundary as collective *intent*, execute it, retire what
    the runtime actually finished, and advance the service clock by the
    fabric's own cycle count.
    """
    backend.assert_network_authority()
    if len(schedulers) != len(npus.binding.instances):
        raise ServingLoopError(
            f"{len(schedulers)} schedulers for "
            f"{len(npus.binding.instances)} serving instances")
    for scheduler in schedulers:
        if scheduler.pd_type == "prefill":
            raise ServingLoopError(
                "PD disaggregation is outside the certified profile; a "
                "prefill instance needs a second NPU span to retire")

    run_dir = Path(run_dir)
    expected_endpoints = npus.canonical_endpoints()
    namespace = npus.binding.namespace
    if expected_endpoints != namespace.participant_endpoints():
        raise ServingLoopError(
            "the virtual NPU namespace does not cover the canonical "
            "participant endpoints")
    # the serving namespace is the graph's participant namespace, so a TP
    # group of two ranks inside it stays explicit -- no DP axis is invented
    participant_count = namespace.participant_count
    instance_ranks = {instance.instance_id: tuple(sorted(instance.ranks))
                      for instance in npus.binding.instances}

    clock = 0
    retired: list[RequestOutcome] = []
    seen: set[str] = set()
    records: list[RoundRecord] = []
    outcomes: list[RoundOutcome] = []
    round_evidence: list[CanonicalServingRoundEvidence] = []

    for round_index in range(max_rounds):
        router.route_arrived_requests(clock)
        batches: dict[int, Any] = {}
        for scheduler in schedulers:
            batch = scheduler.schedule(clock, npus.start_npu(scheduler.instance_id))
            if batch is not None:
                batches[scheduler.instance_id] = batch

        if not batches:
            if _quiescent(schedulers, router):
                break
            nxt = _next_schedulable_time(schedulers, router, clock)
            if nxt is None:
                raise ServingLoopError(
                    f"no instance can schedule at clock {clock} and no "
                    "future arrival exists; the trace is stuck")
            clock = nxt
            continue

        # a batch handed to the fabric is 'sent' -- the historical pass-echo
        # guard: an unsent batch must never be retired by a fabric echo
        for batch in batches.values():
            batch.sent = True

        # only instances that actually supplied a batch are dispatched; an
        # idle instance gets no compute and no collective, so it must report
        # no execution work (attribute_completions refuses if it does)
        dispatched = frozenset(batches)

        plan = plan_from_round(
            round_id=round_index, batches=batches,
            instance_ranks=instance_ranks,
            participant_count=participant_count,
            collective_kind=profile.collective_kind,
            collective_bytes_for=profile.collective_bytes,
            compute_ns_for=profile.compute_ns)

        projection = plan.to_round_projection(
            resolved_fabric=lowering.resolved_fabric, mapping=lowering.mapping,
            attachment=lowering.attachment, parallelism=lowering.parallelism)
        # the round's collective memberships over the STABLE namespace; the
        # fabric is never regenerated here
        collective_binding = derive_collective_binding(
            namespace=namespace, workload=projection)
        stem = f"round{round_index:06d}"
        staged = backend.stage_round(workload=projection, directory=run_dir,
                                     stem=stem,
                                     collective_binding=collective_binding)
        qualification, projection = qualify_round(
            machine=machine, plan=plan, backend=backend, staged=staged,
            directory=run_dir, resolved_fabric=lowering.resolved_fabric,
            mapping=lowering.mapping, attachment=lowering.attachment,
            parallelism=lowering.parallelism,
            collective_binding=collective_binding)

        outcome = run_live_round(
            backend=backend, workload=projection, run_dir=run_dir,
            dispatched_instances=dispatched, round_index=round_index,
            timeout_s=timeout_s, session_factory=session_factory,
            stem=stem, ledger=ledger, staged=staged)

        # the runtime's own ledger is an execution contract per collective,
        # keyed by ASTRA node id -- never an aggregate count
        validate_collective_ledger_contract(
            parse_collective_ledger(outcome.collective_ledger),
            contract=qualification.collective_contract)

        cycles = outcome.backend_cycles
        clock += cycles if cycles and cycles > 0 else 1

        # every dispatched instance must show execution evidence; an idle one
        # must not (already enforced by attribute_completions)
        exercised = {row.instance for row in outcome.attributions}
        silent = sorted(set(dispatched) - exercised)
        if silent:
            raise ServingLoopError(
                f"round {round_index} dispatched serving instance(s) "
                f"{silent} but they produced no endpoint execution evidence; "
                "retirement is bookkeeping, not execution proof")

        # retire through the real Scheduler, using the virtual NPU quorum
        round_retired: list[str] = []
        for instance_id in sorted(batches):
            batch = batches[instance_id]
            scheduler = schedulers[instance_id]
            for sys_id in npus.quorum_sys(instance_id):
                _prompt, _gen, finished = scheduler.add_done(
                    batch.batch_id, sys_id, clock)
                for request in finished:
                    key = str(request.id)
                    if key in seen:  # pragma: no cover - defensive
                        continue
                    if request.ttft < 0:
                        raise ServingLoopError(
                            f"request {key} retired without a first-token "
                            "time; refusing to invent a TTFT")
                    seen.add(key)
                    retired.append(RequestOutcome(
                        request_id=key, instance_id=instance_id,
                        arrival_ns=int(request.arrival),
                        ttft_ns=int(request.ttft),
                        end_ns=int(request.end_time),
                        latency_ns=int(request.latency),
                        itl_ns=tuple(int(v) for v in request.itl)))
                    round_retired.append(key)

        evidence = round_evidence_from_outcome(
            qualification=qualification, outcome=outcome, machine=machine,
            parser_version=PARSER_VERSION)
        outcomes.append(outcome)
        round_evidence.append(evidence)
        records.append(RoundRecord(
            round_index=round_index, plan_id=plan.plan_id(),
            qualification_id=qualification.round_id(),
            evidence_id=evidence.evidence_id(),
            collective_binding_id=collective_binding.binding_id(),
            group_ids=collective_binding.groups.group_ids(),
            batch_ids=tuple(sorted((i, b.batch_id)
                                   for i, b in batches.items())),
            dispatched_instances=tuple(sorted(dispatched)),
            backend_cycles=cycles, clock_after=clock,
            retired_request_ids=tuple(round_retired),
            idle_instances=tuple(sorted(
                set(npus.binding.served_instance_set()) - set(batches)))))

        if _quiescent(schedulers, router):
            break
    else:
        raise ServingLoopError(
            f"the service loop did not converge within {max_rounds} rounds")

    if expected_requests and len(retired) != expected_requests:
        raise ServingLoopError(
            f"the trace declared {expected_requests} requests but "
            f"{len(retired)} retired; a partial run is not service evidence")

    request_metrics = tuple(r.metric() for r in retired)
    evidence = build_serving_evidence(
        backend=backend, rounds=tuple(outcomes), workload_id=workload_id,
        request_metrics=request_metrics, round_evidence=tuple(round_evidence))
    return ServiceRunResult(
        workload_id=workload_id, profile_id=profile.profile_id(),
        virtual_npu_id=npus.translation_id(), clock=clock,
        requests=tuple(retired), rounds=tuple(records),
        round_evidence=tuple(round_evidence), evidence=evidence)


@dataclass(frozen=True)
class CanonicalLowering:
    """The qualified objects a round is lowered against (Slices 29-33)."""

    resolved_fabric: Any
    mapping: Any
    attachment: Any
    parallelism: Any
