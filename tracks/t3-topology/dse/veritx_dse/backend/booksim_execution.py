"""veritx_dse.backend.booksim_execution — execute prepared bytes, once.

Rationale: docs/decisions/modules/backend.md
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
    GEC_MECS_PROFILE, GEC_HYBRID_PROFILE, GEC_HYBRID_OBSERVATION_FILE,
    SROTA_ROW_FIRST_PROFILE,
    ANYNET_PROFILE, CMESH_DOR_PROFILE, CONFIG_FILE, FLATFLY_MIN_PROFILE,
    MESH_DOR_MC_PROFILE, MESH_DOR_PROFILE, ROUTE_DUMP_FILE, TOPOLOGY_FILE,
    TORUS_DOR_PROFILE, TRACE_FILE, PreparedBookSimInput,
    parse_config_values,
)
from veritx_dse.backend.evidence import (
    BOOKSIM_BUILD_RECIPE_VERSION, EVIDENCE_SCHEMA_VERSION,
    EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
    EXECUTION_TRANSPORT_TEST_INJECTED, BackendEvidenceError, EvidenceRef,
    ExecutionAttempt, ExecutionRecord, PARSER_VERSION,
    ScientificBackendEvidence, write_evidence,
)
from veritx_dse.backend.producer import (
    ProducerError, ProducerIdentity, assert_pinned_producer,
    recheck_binary_digest, resolve_producer_identity,
)

MATERIALIZED_FILES = (CONFIG_FILE, TRACE_FILE, TOPOLOGY_FILE)

FIDELITY_QUALIFIED = "QUALIFIED"
FIDELITY_UNPINNED_PRODUCER = "DIAGNOSTIC_UNPINNED_PRODUCER"
FIDELITY_TEST_INJECTED = "TEST_INJECTED"

ROUTE_OBSERVATION_QUALIFIED_ONLY = "DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED"
ROUTE_OBSERVATION_OBSERVED = "EXECUTED_ROUTE_OBSERVED"

_WINDOW_RE = re.compile(r"Time taken is (\d+) cycles")
_COMPLETION_RE = re.compile(r"Completion time is (\d+) cycles")
_LOADED_RE = re.compile(r"Loaded (?:text|binary) trace: (\d+) packets")
_INJECTED_RE = re.compile(r"injected=(\d+)")
_DELIVERED_RE = re.compile(r"Trace replay complete: delivered (\d+) packets")
_FLITS_INJECTED_RE = re.compile(r"VeritX: injected flits total = (\d+)")
_FLITS_ACCEPTED_RE = re.compile(r"VeritX: accepted flits total = (\d+)")
_CLASS_FLITS_RE = re.compile(
    r"VeritX: class (\d+) injected flits = (\d+), accepted flits = (\d+)")
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
    from veritx_dse.core.run_bundle import CHECKSUMS_NAME
    expected_names = set(files) | {EVIDENCE_OUTPUT_NAME, CHECKSUMS_NAME}
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

#: Profiles whose certified route offers MORE THAN ONE first hop per pair,
#: so the executed realization is a sample of the union rather than a
#: deterministic answer. SROTA's row+column pair belongs here because the
#: FIU picks the shape from live telemetry load.
_ADAPTIVE_ROUTE_PROFILES: frozenset[str] = frozenset({
    "CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1",
    "CERTIFIED_BOOKSIM_GEC_HYBRID_V1",
})


def parse_booksim_stats(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse only what the backend actually emitted.
    NOTE: packet/flit latency is NOT required for trace-driven runs.
    Trace packets may be injected while ``warming_up`` with
    ``record=false``, so the measured packet-latency statistic can
    legitimately be empty for a fully consumed trace.

Rationale: docs/decisions/modules/backend.md
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

    match = _COMPLETION_RE.search(stdout)
    if match is None:
        raise BookSimExecutionError(
            "missing required completion evidence 'Completion time is N "
            "cycles' (the last-ejected-flit cycle; F-0001) — refusing to "
            "treat this run as a measurement. 'Time taken is' is a "
            "sampling-window value and is not a completion measurement.")
    completion_cycles = int(match.group(1))

    window_match = _WINDOW_RE.search(stdout)
    sample_window_cycles = (int(window_match.group(1))
                            if window_match is not None else None)
    if sample_window_cycles is not None \
            and completion_cycles > sample_window_cycles:
        raise BookSimExecutionError(
            f"completion evidence {completion_cycles} exceeds the run "
            f"window {sample_window_cycles} — inconsistent timing evidence")

    injected_match = _INJECTED_RE.search(combined)
    injected = int(injected_match.group(1)) if injected_match else None

    delivered_match = _DELIVERED_RE.search(combined)
    delivered = int(delivered_match.group(1)) if delivered_match else None
    flits_inj_match = _FLITS_INJECTED_RE.search(combined)
    flits_injected = (int(flits_inj_match.group(1))
                      if flits_inj_match else None)
    flits_acc_match = _FLITS_ACCEPTED_RE.search(combined)
    flits_accepted = (int(flits_acc_match.group(1))
                      if flits_acc_match else None)

    hops = {int(rank): [float(v) for v in values.split(",") if v]
            for rank, values in _HOPS_RE.findall(stdout)}
    flits_by_class: dict[int, dict[str, int]] = {}
    for rank_s, inj_s, acc_s in _CLASS_FLITS_RE.findall(combined):
        flits_by_class[int(rank_s)] = {"injected": int(inj_s),
                                       "accepted": int(acc_s)}
    unstable = _UNSTABLE_TOKEN in stdout or _UNSTABLE_TOKEN in stderr
    abort = next((token for token in _ABORT_TOKENS
                  if token in stdout or token in stderr), None)
    return {
        "parser_version": PARSER_VERSION,
        "loaded_trace_packets": loaded_packets,
        "injected_trace_packets": injected,
        "completion_cycles": completion_cycles,
        "sample_window_cycles": sample_window_cycles,
        "packet_latency_avg": _optional_number(_PLAT_RE, stdout,
                                               "packet latency"),
        "flit_latency_avg": _optional_number(_FLAT_RE, stdout,
                                             "flit latency"),
        "hops": hops,
        "delivered_packets": delivered,
        "flits_injected": flits_injected,
        "flits_accepted": flits_accepted,
        "flits_by_class": flits_by_class,
        "simulation_unstable": unstable,
        "abort_token": abort,
    }

def assert_execution_gate(stats: dict[str, Any], *, expected_packets: int,
                          expected_flits: int | None = None,
                          expected_flits_by_class: dict[int, int] | None = None,
                          require_conservation: bool = False) -> None:
    """The scientific gate for a trace-driven run.

    ``require_conservation`` is set for a supervised production execution:
    the fork's emitted delivered-packet and injected/accepted-flit totals
    must then be present and must conserve. Injected-runner diagnostics
    (TEST_INJECTED) may omit them.
    """
    loaded = stats.get("loaded_trace_packets")
    if loaded != expected_packets:
        raise BookSimExecutionError(
            f"trace evidence mismatch: the backend loaded {loaded} packets "
            f"but the prepared trace declares {expected_packets}")
    injected = stats.get("injected_trace_packets")
    if require_conservation and injected is None:
        raise BookSimExecutionError(
            "conservation evidence missing: the backend did not emit the "
            "trace-injected packet count ('injected=N'); a supervised run "
            "must prove loaded == injected == delivered == declared")
    if injected is not None and injected != expected_packets:
        raise BookSimExecutionError(
            f"trace evidence mismatch: injected {injected} != declared "
            f"{expected_packets} — the trace was truncated")
    if require_conservation:
        delivered = stats.get("delivered_packets")
        if delivered is None:
            raise BookSimExecutionError(
                "conservation evidence missing: the backend did not emit "
                "'Trace replay complete: delivered N packets'")
        if delivered != expected_packets:
            raise BookSimExecutionError(
                f"packet conservation failed: delivered {delivered} != "
                f"declared {expected_packets}")
        flits_in = stats.get("flits_injected")
        flits_accepted = stats.get("flits_accepted")
        if flits_in is None or flits_accepted is None:
            raise BookSimExecutionError(
                "conservation evidence missing: the backend did not emit "
                "the injected/accepted flit totals")
        if expected_flits is not None and (
                flits_in != expected_flits
                or flits_accepted != expected_flits):
            raise BookSimExecutionError(
                f"flit conservation failed: injected {flits_in} / accepted "
                f"{flits_accepted} != declared {expected_flits}")
        if flits_in != flits_accepted:
            raise BookSimExecutionError(
                f"flit conservation failed: injected {flits_in} != accepted "
                f"{flits_accepted}")
    if expected_flits_by_class:
        per_class = stats.get("flits_by_class") or {}
        for class_index, expected in sorted(expected_flits_by_class.items()):
            counters = per_class.get(class_index)
            if counters is None:
                raise BookSimExecutionError(
                    f"class conservation evidence missing: the backend did "
                    f"not emit per-class flit counters for trace class "
                    f"{class_index}")
            if counters["injected"] != expected \
                    or counters["accepted"] != expected:
                raise BookSimExecutionError(
                    f"class {class_index} flit conservation failed: "
                    f"injected {counters['injected']} / accepted "
                    f"{counters['accepted']} != declared {expected}")
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

def execute_prepared_booksim(
        *, prepared: PreparedBookSimInput, binary: Path, run_dir: Path,
        timeout: int, seed: int | None = None,
        runner: Callable[[tuple[str, ...], Path, int], ProcessOutcome]
        | None = None,
        repo_root: Path | None = None,
        require_pinned_producer: bool = False,
        require_manifest_recipe: str | None = None,
        expected_prepared_id: str | None = None,
        write: bool = True) -> ExecutionRecord:
    """Execute exactly the prepared bytes with an identified producer."""
    if not isinstance(prepared, PreparedBookSimInput):
        raise BookSimExecutionError(
            "execution consumes a PreparedBookSimInput only")
    from veritx_dse.application.booksim_qualification_registry import (
        resolve_execution_handler,
    )
    _handler, _handler_err = resolve_execution_handler(
        prepared.profile_id)
    if _handler is None:
        raise BookSimExecutionError(
            f"refusing to execute unregistered BookSim profile "
            f"{prepared.profile_id!r}: {_handler_err}")
    _trace_indices: set[int] = set()
    for _line in prepared.trace_text.splitlines():
        _fields = _line.split()
        if not _fields:
            continue
        if len(_fields) != 5:
            raise BookSimExecutionError(
                "prepared trace has a malformed line (expected 'cyc src "
                "cl dst sz'): refusing a non-canonical trace")
        try:
            _trace_indices.add(int(_fields[2]))
        except ValueError:
            raise BookSimExecutionError(
                "prepared trace has a non-integer class index: "
                "refusing a non-canonical trace") from None
    if prepared.profile_id == MESH_DOR_MC_PROFILE.profile_id:
        if not prepared.trace_class_map:
            raise BookSimExecutionError(
                "multi-class prepared input binds no class map: "
                "refusing an unbound multi-class execution")
        if not _trace_indices <= set(range(len(prepared.trace_class_map))):
            raise BookSimExecutionError(
                f"multi-class trace indices {sorted(_trace_indices)} "
                f"exceed the bound class map "
                f"{list(prepared.trace_class_map)}: refusing a "
                f"class-swapped or collapsed trace")
    elif prepared.profile_id == SROTA_ROW_FIRST_PROFILE.profile_id:
        # A multi-plane SROTA fabric renders subnets = 2 with a per-class
        # subnet map, so it legitimately carries a multi-class trace. A
        # single-plane SROTA fabric stays single-class.
        multi_plane = parse_config_values(
            prepared.config_text).get("subnets") == "2"
        if multi_plane:
            if not prepared.trace_class_map:
                raise BookSimExecutionError(
                    "multi-plane prepared input binds no class map: "
                    "refusing an unbound multi-class execution")
            if not _trace_indices <= set(
                    range(len(prepared.trace_class_map))):
                raise BookSimExecutionError(
                    f"multi-plane trace indices {sorted(_trace_indices)} "
                    f"exceed the bound class map "
                    f"{list(prepared.trace_class_map)}: refusing a "
                    "class-swapped or collapsed trace")
        elif not _trace_indices <= {0}:
            raise BookSimExecutionError(
                f"single-class profile {prepared.profile_id!r} carries "
                f"trace class indices {sorted(_trace_indices)}: "
                f"refusing a multi-class trace on a single-class profile")
    elif prepared.profile_id in (MESH_DOR_PROFILE.profile_id,
                                  CMESH_DOR_PROFILE.profile_id,
                                  ANYNET_PROFILE.profile_id,
                                  TORUS_DOR_PROFILE.profile_id,
                                  FLATFLY_MIN_PROFILE.profile_id,
                                  GEC_MECS_PROFILE.profile_id,
                                  GEC_HYBRID_PROFILE.profile_id):
        if not _trace_indices <= {0}:
            raise BookSimExecutionError(
                f"single-class profile {prepared.profile_id!r} carries "
                f"trace class indices {sorted(_trace_indices)}: "
                f"refusing a multi-class trace on a single-class profile")
    else:
        raise BookSimExecutionError(
            f"profile {prepared.profile_id!r} has no trace class-domain "
            f"rule: refusing execution until the domain is declared")
    if (prepared.profile_id == GEC_HYBRID_PROFILE.profile_id
            and not prepared.expected_hybrid_candidates):
        raise BookSimExecutionError("hybrid prepared input binds no runtime candidate set")
    if type(timeout) is not int or timeout <= 0:
        raise BookSimExecutionError("timeout must be a positive int")

    if seed is None:
        seed = prepared.seed
    elif seed != prepared.seed:
        raise BookSimExecutionError(
            f"run seed {seed} does not match the prepared identity seed "
            f"{prepared.seed}; the executed seed is fixed at preparation")

    transport = (EXECUTION_TRANSPORT_TEST_INJECTED if runner is not None
                 else EXECUTION_TRANSPORT_SUPERVISED_PROCESS)

    digests = prepared_file_digests(prepared)
    if expected_prepared_id is not None \
            and prepared.prepared_id() != expected_prepared_id:
        raise BookSimExecutionError(
            "prepared input does not match the externally held "
            f"prepared_id ({prepared.prepared_id()} != "
            f"{expected_prepared_id}): the input was modified after "
            "preparation")

    try:
        identity = resolve_producer_identity(
            binary, repo_root=repo_root,
            require_manifest_recipe=require_manifest_recipe)
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

    materialize_prepared(prepared, Path(run_dir))

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
    declared_by_class = (dict(prepared.expected_flits_by_class)
                         if prepared.expected_flits_by_class else {})
    expected_by_index = (
        {i: declared_by_class[cls]
         for i, cls in enumerate(prepared.trace_class_map)}
        if prepared.trace_class_map else None)
    assert_execution_gate(
        stats, expected_packets=prepared.expected_packets,
        expected_flits=prepared.expected_flits,
        expected_flits_by_class=expected_by_index,
        require_conservation=(
            transport != EXECUTION_TRANSPORT_TEST_INJECTED))

    route_observation = ROUTE_OBSERVATION_QUALIFIED_ONLY
    route_dump_sha256: str | None = None
    if transport != EXECUTION_TRANSPORT_TEST_INJECTED \
            and prepared.expected_route_rows:
        dump_path = Path(run_dir) / ROUTE_DUMP_FILE
        try:
            dump_text = dump_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BookSimExecutionError(
                f"executed route dump missing at {dump_path} ({exc}); the "
                "certified profile requires executed-route evidence") from exc
        from veritx_dse.backend.route_observation import (
            RouteObservationError, compare_route_realization,
        )
        try:
            # An adaptive profile (SROTA's row+column pair) executes one of
            # several certified hops, so its comparison is membership.
            compare_route_realization(
                expected_rows=prepared.expected_route_rows,
                dump_text=dump_text,
                adaptive=prepared.profile_id
                in _ADAPTIVE_ROUTE_PROFILES)
        except RouteObservationError as exc:
            raise BookSimExecutionError(str(exc)) from exc
        route_observation = ROUTE_OBSERVATION_OBSERVED
        route_dump_sha256 = hashlib.sha256(dump_text.encode()).hexdigest()

    if (transport != EXECUTION_TRANSPORT_TEST_INJECTED
            and prepared.profile_id == GEC_HYBRID_PROFILE.profile_id):
        from veritx_dse.backend.route_observation import (
            RouteObservationError, compare_hybrid_runtime_choices,
        )
        path = Path(run_dir) / GEC_HYBRID_OBSERVATION_FILE
        try:
            observation = compare_hybrid_runtime_choices(
                expected=prepared.expected_hybrid_candidates,
                text=path.read_text(encoding="utf-8"))
        except (OSError, RouteObservationError) as exc:
            raise BookSimExecutionError(f"hybrid runtime routing evidence invalid: {exc}") from exc
        stats["hybrid_route_choices"] = observation

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
        route_observation=route_observation,
        stats=stats,
        exit_status=outcome.returncode,
        transport=transport,
        build_manifest_sha256=identity.build_manifest_sha256,
        build_recipe_version=identity.build_recipe_version,
        route_dump_sha256=route_dump_sha256,
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
    if ref is not None:
        from veritx_dse.core.run_bundle import finalize_run_bundle
        finalize_run_bundle(Path(run_dir))
    return ExecutionRecord(evidence=evidence, attempt=attempt, ref=ref)

__all__ = [
    "BOOKSIM_BUILD_RECIPE_VERSION", "BookSimExecutionError",
    "EVIDENCE_OUTPUT_NAME", "FIDELITY_QUALIFIED",
    "FIDELITY_TEST_INJECTED", "FIDELITY_UNPINNED_PRODUCER",
    "MATERIALIZED_FILES", "ProcessOutcome", "ROUTE_OBSERVATION_OBSERVED",
    "ROUTE_OBSERVATION_QUALIFIED_ONLY", "UNAVAILABLE_TOKENS",
    "assert_execution_gate", "execute_prepared_booksim",
    "materialize_prepared", "parse_booksim_stats", "prepared_file_digests",
]
