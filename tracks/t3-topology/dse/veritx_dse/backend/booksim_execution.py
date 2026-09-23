"""veritx_dse.backend.booksim_execution — execute prepared bytes, once.

    PreparedBookSimInput
            |
            v
    exact materialized bytes (tamper-closed, re-hashed before spawn)
            |
            v
    identified producer (binary SHA-256 + git provenance)
            |
            v
    supervised real execution (one seam, stdin=DEVNULL, timeout)
            |
            v
    fail-closed parser
            |
            v
    ScientificBackendEvidence  +  separate ExecutionAttempt metadata

Execution consumes ONLY the Slice-31 prepared artifact. It never receives
(or derives) topology, CompileRequest, ResolvedFabric, WorkloadGraph,
logical messages, PhysicalTrafficArtifactV2, routing policy or packet
format: all of those already participated in ``prepared_id()``.
"""
from __future__ import annotations

import hashlib
import math
import platform
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from veritx_dse.backend.booksim_projection import (
    CONFIG_FILE, TOPOLOGY_FILE, TRACE_FILE, PreparedBookSimInput,
)
from veritx_dse.backend.evidence import (
    EVIDENCE_SCHEMA_VERSION, EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
    EXECUTION_TRANSPORT_TEST_INJECTED, BackendEvidenceError, EvidenceRef,
    ExecutionAttempt, ExecutionRecord, PARSER_VERSION,
    ScientificBackendEvidence, write_evidence,
)
from veritx_dse.backend.producer import (
    ProducerError, ProducerIdentity, assert_pinned_producer,
    recheck_binary_digest, resolve_producer_identity,
)

#: the exact set of files an execution materializes
MATERIALIZED_FILES = (CONFIG_FILE, TRACE_FILE, TOPOLOGY_FILE)

#: execution fidelity classes (NOT synonyms for reusable)
FIDELITY_QUALIFIED = "QUALIFIED"
FIDELITY_UNPINNED_PRODUCER = "DIAGNOSTIC_UNPINNED_PRODUCER"
FIDELITY_TEST_INJECTED = "TEST_INJECTED"

#: route-observation classes (honesty about what was actually observed)
ROUTE_OBSERVATION_QUALIFIED_ONLY = "DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED"
ROUTE_OBSERVATION_OBSERVED = "EXECUTED_ROUTE_OBSERVED"

_TIME_RE = re.compile(r"Time taken is (\d+) cycles")
_LOADED_RE = re.compile(r"Loaded (?:text|binary) trace: (\d+) packets")
_INJECTED_RE = re.compile(r"injected=(\d+)")
#: tokens the fork prints when a statistic has no samples
UNAVAILABLE_TOKENS = ("-", "nan", "-nan", "+nan", "inf", "-inf", "+inf",
                      "infinity", "-infinity")
_PLAT_RE = re.compile(r"Packet latency average = ([0-9.eE+-]+)")
_FLAT_RE = re.compile(r"Flit latency average = ([0-9.eE+-]+)")
_HOPS_RE = re.compile(r"hops\((\d+),:\) = ([0-9.,eE+-]+)")
_UNSTABLE_TOKEN = "Simulation unstable"
_ABORT_TOKENS = ("Assertion", "assertion", "failed", "Aborted",
                 "terminate called")


class BookSimExecutionError(ValueError):
    """Execution, materialization or parsing failed closed."""


# ── materialization (tamper-closed) ────────────────────────────────────────

def materialize_prepared(prepared: PreparedBookSimInput, run_dir: Path
                         ) -> dict[str, Path]:
    """Write the exact prepared bytes; refuse stale/conflicting content.

    A reused run directory must not be able to inject old inputs (or old
    outputs) into a new evidence record, so an existing file whose bytes
    differ from the prepared representation refuses.
    """
    if not isinstance(prepared, PreparedBookSimInput):
        raise BookSimExecutionError(
            "execution materializes a PreparedBookSimInput, got "
            f"{type(prepared).__name__}")
    files = prepared.files()
    expected = {name: hashlib.sha256(data).hexdigest()
                for name, data in files.items()}
    if expected != prepared_file_digests(prepared):
        raise BookSimExecutionError(
            "prepared representation is internally inconsistent (file "
            "digests disagree with prepared_id inputs)")
    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    # refuse to let a stale directory contribute anything
    expected_names = set(files) | {EVIDENCE_OUTPUT_NAME}
    for existing in target.iterdir():
        if existing.is_file() and existing.name not in expected_names:
            raise BookSimExecutionError(
                f"run directory {target} holds an unexpected file "
                f"{existing.name!r}; refusing to execute in a stale "
                "directory")
    written: dict[str, Path] = {}
    for name, data in files.items():
        path = target / name
        if path.exists():
            if path.read_bytes() != data:
                raise BookSimExecutionError(
                    f"{path} already holds different bytes; refusing to "
                    "overwrite a prepared input")
        else:
            path.write_bytes(data)
        # re-hash the materialized file and prove it matches
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected[name]:
            raise BookSimExecutionError(
                f"materialized {name} does not match the prepared bytes "
                f"({digest} != {expected[name]}) — input tampered after "
                "materialization")
        written[name] = path
    return written


def prepared_file_digests(prepared: PreparedBookSimInput) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest()
            for name, data in prepared.files().items()}


EVIDENCE_OUTPUT_NAME = "backend-evidence.json"


# ── supervised execution seam ──────────────────────────────────────────────

@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _supervised_runner(command: tuple[str, ...], cwd: Path,
                       timeout: int) -> ProcessOutcome:
    """The ONE production process seam. No shell, DEVNULL stdin, timeout."""
    try:
        proc = subprocess.run(
            list(command), cwd=str(cwd), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        return ProcessOutcome(returncode=-1,
                              stdout=(exc.stdout or "") if isinstance(
                                  exc.stdout, str) else "",
                              stderr=(exc.stderr or "") if isinstance(
                                  exc.stderr, str) else "",
                              timed_out=True)
    except OSError as exc:
        raise BookSimExecutionError(
            f"could not spawn the BookSim process: {exc}") from exc
    return ProcessOutcome(returncode=proc.returncode, stdout=proc.stdout,
                          stderr=proc.stderr)


# ── result parsing (versioned, fail-closed) ────────────────────────────────

def _unavailable(token: str) -> bool:
    return token.strip().lower() in UNAVAILABLE_TOKENS


def _optional_number(pattern: re.Pattern, text: str, where: str) -> float | None:
    """An ordinary metric: absent or unavailable becomes None, never 0."""
    match = pattern.search(text)
    if match is None:
        return None
    token = match.group(1).strip()
    if _unavailable(token):
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_booksim_stats(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse only what the backend actually emitted.

    Contract (``PARSER_VERSION``):
      * ``Loaded text trace: N packets`` is REQUIRED trace evidence;
      * ``Time taken is N cycles`` is REQUIRED completion evidence;
      * the trace drain line (stderr, ``[trace] All <c> cycles, injected=N``)
        is RECORDED when present and may be absent in other modes;
      * ordinary latencies/hops that are absent or printed as
        ``-``/``nan``/``inf`` become ``None`` — never 0, never a failure;
      * a non-finite value never enters evidence;
      * instability/abort tokens are recorded and refuse downstream.

    NOTE: packet/flit latency is NOT required for trace-driven runs.
    Trace packets may be injected while ``warming_up`` with
    ``record=false``, so the measured packet-latency statistic can
    legitimately be empty for a fully consumed trace.
    """
    if not isinstance(stdout, str):
        raise BookSimExecutionError("stdout must be text")
    combined = stdout + "\n" + (stderr or "")

    loaded = _LOADED_RE.search(stdout) or _LOADED_RE.search(combined)
    if loaded is None:
        raise BookSimExecutionError(
            "missing required trace evidence 'Loaded text trace: N packets' "
            "— refusing to treat this run as a measurement")
    loaded_packets = int(loaded.group(1))

    match = _TIME_RE.search(stdout)
    if match is None:
        raise BookSimExecutionError(
            "missing required completion evidence 'Time taken is N cycles' "
            "— refusing to treat this run as a measurement")
    completion_cycles = int(match.group(1))

    injected_match = _INJECTED_RE.search(combined)
    injected = int(injected_match.group(1)) if injected_match else None

    hops = {int(rank): [float(v) for v in values.split(",") if v]
            for rank, values in _HOPS_RE.findall(stdout)}
    unstable = _UNSTABLE_TOKEN in stdout or _UNSTABLE_TOKEN in stderr
    abort = next((token for token in _ABORT_TOKENS
                  if token in stdout or token in stderr), None)
    return {
        "parser_version": PARSER_VERSION,
        "loaded_trace_packets": loaded_packets,
        "injected_trace_packets": injected,
        "completion_cycles": completion_cycles,
        "packet_latency_avg": _optional_number(_PLAT_RE, stdout,
                                               "packet latency"),
        "flit_latency_avg": _optional_number(_FLAT_RE, stdout,
                                             "flit latency"),
        "hops": hops,
        # counters this fork does not print in every mode stay absent
        "delivered_packets": None,
        "flits_injected": None,
        "flits_accepted": None,
        "simulation_unstable": unstable,
        "abort_token": abort,
    }


def assert_execution_gate(stats: dict[str, Any], *, expected_packets: int
                          ) -> None:
    """The scientific gate for a trace-driven run."""
    loaded = stats.get("loaded_trace_packets")
    if loaded != expected_packets:
        raise BookSimExecutionError(
            f"trace evidence mismatch: the backend loaded {loaded} packets "
            f"but the prepared trace declares {expected_packets}")
    injected = stats.get("injected_trace_packets")
    if injected is not None and injected != expected_packets:
        raise BookSimExecutionError(
            f"trace evidence mismatch: injected {injected} != declared "
            f"{expected_packets} — the trace was truncated")
    completion = stats.get("completion_cycles")
    if completion is None or completion < 0:
        raise BookSimExecutionError(
            f"completion evidence is not a valid cycle count: {completion!r}")
    if expected_packets > 0 and completion == 0:
        raise BookSimExecutionError(
            "a non-empty trace whose packets traverse the network cannot "
            "complete in zero cycles; refusing the measurement")
    if stats.get("simulation_unstable"):
        raise BookSimExecutionError(
            "the backend reported an unstable simulation")
    if stats.get("abort_token") is not None:
        raise BookSimExecutionError(
            f"the backend reported abort token {stats['abort_token']!r}")


# ── the execution API ──────────────────────────────────────────────────────

def execute_prepared_booksim(
        *, prepared: PreparedBookSimInput, binary: Path, run_dir: Path,
        timeout: int, seed: int = 0,
        runner: Callable[[tuple[str, ...], Path, int], ProcessOutcome]
        | None = None,
        repo_root: Path | None = None,
        require_pinned_producer: bool = False,
        expected_prepared_id: str | None = None,
        write: bool = True) -> ExecutionRecord:
    """Execute exactly the prepared bytes with an identified producer."""
    if not isinstance(prepared, PreparedBookSimInput):
        raise BookSimExecutionError(
            "execution consumes a PreparedBookSimInput only")
    if type(timeout) is not int or timeout <= 0:
        raise BookSimExecutionError("timeout must be a positive int")

    transport = (EXECUTION_TRANSPORT_TEST_INJECTED if runner is not None
                 else EXECUTION_TRANSPORT_SUPERVISED_PROCESS)

    # 1. the prepared object must be self-consistent AND, when the caller
    #    holds the external identity, must match it (catches an object
    #    mutated after preparation, which self-consistency cannot see).
    digests = prepared_file_digests(prepared)
    if expected_prepared_id is not None \
            and prepared.prepared_id() != expected_prepared_id:
        raise BookSimExecutionError(
            "prepared input does not match the externally held "
            f"prepared_id ({prepared.prepared_id()} != "
            f"{expected_prepared_id}): the input was modified after "
            "preparation")

    # 2. producer identity + pre-spawn re-hash
    try:
        identity = resolve_producer_identity(binary, repo_root=repo_root)
        recheck_binary_digest(identity)
    except ProducerError as exc:
        raise BookSimExecutionError(str(exc)) from exc

    fidelity = FIDELITY_QUALIFIED if identity.pinned \
        else FIDELITY_UNPINNED_PRODUCER
    if transport == EXECUTION_TRANSPORT_TEST_INJECTED:
        fidelity = FIDELITY_TEST_INJECTED
    if require_pinned_producer:
        try:
            assert_pinned_producer(identity)
        except ProducerError as exc:
            raise BookSimExecutionError(str(exc)) from exc

    # 3. materialize the exact bytes (tamper-closed)
    materialize_prepared(prepared, Path(run_dir))

    # standalone fork usage: `booksim configfile... [param=value...]`;
    # the cwd is the run directory, so the config path is relative
    command = (str(Path(binary)), CONFIG_FILE)
    run = runner or _supervised_runner
    started = time.monotonic()
    outcome = run(command, Path(run_dir), timeout)
    wall = time.monotonic() - started

    if outcome.timed_out:
        raise BookSimExecutionError(
            f"BookSim timed out after {timeout}s and was killed")
    if outcome.returncode != 0:
        raise BookSimExecutionError(
            f"BookSim exited {outcome.returncode}: "
            f"{(outcome.stderr or '')[-300:]}")

    stats = parse_booksim_stats(outcome.stdout, outcome.stderr)
    assert_execution_gate(stats, expected_packets=prepared.expected_packets)

    evidence = ScientificBackendEvidence(
        prepared_id=prepared.prepared_id(),
        profile_id=prepared.profile_id,
        projection_semantics_version=prepared.semantics_version,
        config_sha256=digests[CONFIG_FILE],
        trace_sha256=digests[TRACE_FILE],
        topology_sha256=digests.get(TOPOLOGY_FILE),
        resolved_fabric_hash=prepared.resolved_fabric_hash,
        physical_traffic_id=prepared.physical_traffic_id,
        message_artifact_id=prepared.message_artifact_id,
        binary_sha256=identity.binary_sha256,
        binary_size=identity.binary_size,
        producer_source_revision=identity.source_revision,
        producer_dirty=identity.dirty,
        seed=seed,
        parser_version=PARSER_VERSION,
        execution_fidelity=fidelity,
        # the current fork has no route-dump hook: qualification yes,
        # runtime route observation NO
        route_observation=ROUTE_OBSERVATION_QUALIFIED_ONLY,
        stats=stats,
        exit_status=outcome.returncode,
        transport=transport,
        schema_version=EVIDENCE_SCHEMA_VERSION,
    )
    attempt = ExecutionAttempt(
        wall_time_s=wall, run_dir=str(Path(run_dir).resolve()),
        binary_path=str(Path(binary).resolve()), command=command,
        host=socket.gethostname(), platform=platform.platform(),
        transport=transport)
    ref = write_evidence(Path(run_dir), {"evidence": evidence.to_dict(),
                                         "attempt": attempt.to_dict()}) \
        if write else None
    return ExecutionRecord(evidence=evidence, attempt=attempt, ref=ref)


__all__ = [
    "BookSimExecutionError", "EVIDENCE_OUTPUT_NAME", "FIDELITY_QUALIFIED",
    "FIDELITY_TEST_INJECTED", "FIDELITY_UNPINNED_PRODUCER",
    "MATERIALIZED_FILES", "ProcessOutcome", "ROUTE_OBSERVATION_OBSERVED",
    "ROUTE_OBSERVATION_QUALIFIED_ONLY", "UNAVAILABLE_TOKENS",
    "assert_execution_gate", "execute_prepared_booksim",
    "materialize_prepared", "parse_booksim_stats", "prepared_file_digests",
]
