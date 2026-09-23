"""Slice 35 — canonical serving round driver.

Drives one serving round across the qualified boundary using the reclaimed
``ServingBackendSession`` wire protocol (never ad-hoc subprocess code), then
attributes completions through the canonical endpoint namespace.

The serving layer decides *when* a round happens and *which* instances
participate; the canonical adapter decides *how* the fabric runs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from veritx_dse.backend.canonical_serving import (
    CanonicalServingEvidence,
    CanonicalServingNetworkBackend,
    CompletionAttribution,
    RequestMetric,
    ServingBoundaryError,
    attribute_completions,
    instances_with_completions,
)
from veritx_dse.backend.astra_namespace import StagedWorkload
from veritx_dse.simulation.llmserving_protocol import (
    BackendReply,
    ProtocolError,
    ServingBackendSession,
)

#: the frontend prints ONE global wall time per Sys, idle ones included, so
#: this line enumerates the endpoint namespace and nothing more
_ENDPOINT_RE = re.compile(r"sys\[(\d+)\]\s*finished")
#: per-endpoint participation comes from the statistics logger, which emits an
#: entry only for an endpoint that actually executed work
_COMM_RE = re.compile(r"sys\[(\d+)\],\s*Comm time:\s*(\d+)")
_INJECTED_RE = re.compile(r"injected=(\d+)")


@dataclass(frozen=True)
class RoundOutcome:
    round_index: int
    dispatched_instances: tuple[int, ...]
    endpoints_enumerated: tuple[int, ...]
    endpoint_completions: tuple[tuple[int, int], ...]
    attributions: tuple[CompletionAttribution, ...]
    unowned_endpoints: tuple[int, ...]
    autonomous_injection_packets: int | None
    backend_cycles: int | None
    reply_lines: int
    #: ``[LEDGER][COLL]`` contract lines: expansion authority + group members
    collective_ledger: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServingRunResult:
    evidence: CanonicalServingEvidence
    rounds: tuple[RoundOutcome, ...]
    staged: StagedWorkload


def parse_round_output(*, reply_text: str, stderr_text: str
                       ) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...],
                                  int | None, int | None]:
    """(enumerated endpoints, per-endpoint Comms, injected, backend cycles)."""
    enumerated = tuple(sorted({int(m) for m in
                               _ENDPOINT_RE.findall(reply_text)}))
    comm: dict[int, int] = {}
    for rank_text, value in _COMM_RE.findall(stderr_text + "\n" + reply_text):
        comm[int(rank_text)] = comm.get(int(rank_text), 0) + int(value)
    injected_matches = {int(v) for v in
                        _INJECTED_RE.findall(stderr_text + reply_text)}
    if len(injected_matches) > 1:
        raise ServingBoundaryError(
            f"backend reported conflicting injection counters "
            f"{sorted(injected_matches)}")
    injected = injected_matches.pop() if injected_matches else None
    cycles: int | None = None
    for line in reply_text.splitlines():
        match = re.search(r"finished,\s*(\d+)\s*cycles", line)
        if match:
            value = int(match.group(1))
            cycles = value if cycles is None else max(cycles, value)
    return enumerated, tuple(sorted(comm.items())), injected, cycles


def run_live_round(*, backend: CanonicalServingNetworkBackend,
                   workload: Any, run_dir: str | Path,
                   dispatched_instances: frozenset[int],
                   round_index: int = 0, timeout_s: int = 900,
                   session_factory: Callable[..., Any] | None = None,
                   stem: str = "workload", ledger: bool = True,
                   staged: StagedWorkload | None = None) -> RoundOutcome:
    """Stage one round and execute it on the real canonical backend.

    The frontend runs its argv workload during startup, so that one is left
    deliberately idle and the round is delivered through the real
    ``load``/``run`` protocol instead of being executed twice in one process.

    ``staged`` lets a caller that already staged this round (to qualify it)
    reuse the staging instead of translating the same workload twice; the
    staging is deterministic, so this is an optimisation, not a second
    authority.
    """
    backend.assert_network_authority()
    # last-instant proof the qualified binary is the one being executed
    backend.recheck_before_spawn()
    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    if staged is None:
        staged = backend.stage_round(workload=workload, directory=target,
                                     stem=stem)
    startup = backend.startup_workload_path(cwd=target)
    argv = backend.qualified_argv(workload_path=str(startup), cwd=target)

    env = {"VERITX_LEDGER": "1"} if ledger else None
    if session_factory is None:
        # a real canonical round can take minutes, so the protocol's default
        # 30s startup budget is far too small; size both budgets to the round
        session = ServingBackendSession(list(argv), cwd=target, env=env,
                                        startup_timeout_s=float(timeout_s),
                                        reply_timeout_s=float(timeout_s))
    else:
        session = session_factory(list(argv), cwd=target)
    with session:
        session.read_startup()
        session.command(f"load {staged.base}", expect_reply=False)
        reply = session.command("run", timeout=timeout_s)
        if reply is None:  # pragma: no cover - defensive
            raise ProtocolError("backend produced no reply to 'run'")
        # stdout and stderr are separate pipes: let the drain catch up before
        # reading evidence, or measured statistics are silently lost
        quiesce = getattr(session, "await_stderr_quiescence", None)
        if callable(quiesce):
            quiesce()
        stderr_text = session.stderr_text()
    enumerated, comm, injected, cycles = parse_round_output(
        reply_text=reply.text(), stderr_text=stderr_text)
    if injected is not None and injected != 0:
        raise ServingBoundaryError(
            f"the embedded fabric injected {injected} packets of its own; "
            "autonomous BookSim traffic was not disabled")
    per_endpoint = dict(comm)
    attributions, unowned = attribute_completions(
        per_endpoint=per_endpoint, binding=backend.binding,
        dispatched=dispatched_instances)
    return RoundOutcome(
        round_index=round_index,
        dispatched_instances=tuple(sorted(dispatched_instances)),
        endpoints_enumerated=enumerated,
        endpoint_completions=tuple(sorted(per_endpoint.items())),
        attributions=attributions,
        unowned_endpoints=unowned,
        autonomous_injection_packets=injected,
        backend_cycles=cycles,
        reply_lines=len(reply.lines),
        collective_ledger=collective_ledger_lines(stderr_text),
    )


#: the runtime's collective-submission line (Workload.cc: veritx_ledger_coll_submit)
_LEDGER_SUBMIT = "[LEDGER][COLL_SUBMIT]"


def collective_ledger_lines(stderr_text: str) -> tuple[str, ...]:
    """The runtime's own collective-submission contract lines.

    ``VERITX_LEDGER=1`` makes the frontend emit ``[LEDGER][COLL_SUBMIT]``
    with the collective type, size, members and whether a communicator group
    was used.  That is the runtime's own statement of expansion authority --
    evidence, not inference.

    The match is on the full ``[LEDGER][COLL_SUBMIT]`` tag, not a
    ``[LEDGER][COLL]`` prefix: every ledger tag the runtime emits
    (``COLL_SUBMIT``/``COLL_CONSTRUCTED``/``COLL_COMPLETE``) carries a suffix,
    so a prefix match silently yields no lines and makes the ledger
    validation unreachable.
    """
    return tuple(line.strip() for line in stderr_text.splitlines()
                 if _LEDGER_SUBMIT in line)


def build_serving_evidence(*, backend: CanonicalServingNetworkBackend,
                           rounds: tuple[RoundOutcome, ...],
                           workload_id: str,
                           request_metrics: tuple[RequestMetric, ...] = (),
                           served_instances: tuple[int, ...] | None = None,
                           round_evidence: tuple[Any, ...] = ()
                           ) -> CanonicalServingEvidence:
    """Compose round outcomes into content-addressed serving evidence."""
    merged: dict[int, int] = {}
    for outcome in rounds:
        for endpoint, count in outcome.endpoint_completions:
            merged[endpoint] = merged.get(endpoint, 0) + count
    done = instances_with_completions(
        tuple(row for outcome in rounds for row in outcome.attributions))
    injected = tuple(outcome.autonomous_injection_packets for outcome in rounds)
    return CanonicalServingEvidence(
        workload_id=workload_id,
        serving_config_id=backend.binding.serving_config_id,
        machine_id=backend.machine.machine_id(),
        namespace_id=backend.binding.namespace.namespace_id(),
        participant_mapping_id=backend.binding.namespace.participant_mapping_id,
        serving_binding_id=backend.binding.binding_id(),
        backend_id=backend.backend_id(),
        astra_binary_sha256=backend.astra_binary_sha256,
        astra_binary_size=backend.astra_binary_size,
        astra_source_revision=backend.astra_source_revision,
        embedded_fabric_abi_version=backend.machine.embedded_fabric_abi_version,
        standalone_config_sha256=backend.machine.standalone_config_sha256,
        network_evidence_tier=backend.evidence_tier(),
        expansion_authority=backend.expansion_authority(),
        execution_mode=backend.execution_mode,
        instance_count=len(backend.binding.instances),
        served_instances=(served_instances
                          if served_instances is not None
                          else backend.binding.served_instance_set()),
        instances_with_completions=done,
        request_count=len(request_metrics),
        request_metrics=request_metrics,
        rounds=len(rounds),
        endpoint_completions=tuple(sorted(merged.items())),
        # real, content-addressed round evidence ids -- never a synthetic
        # ``backend_id:round_index`` string dressed up as evidence identity
        backend_evidence_ids=tuple(
            evidence.evidence_id() for evidence in round_evidence),
        autonomous_injection_packets=injected,
    )
