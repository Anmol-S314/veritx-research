"""veritx_dse.backend.booksim_execution — execute prepared bytes, once.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import hashlib
import json
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
    ANYNET_MC_PROFILE, ANYNET_PROFILE, CMESH_DOR_PROFILE, CONFIG_FILE,
    FLATFLY_MIN_PROFILE,
    MESH_DOR_CLASS_PRIORITY_PROFILE, MESH_DOR_CLASS_VC_PROFILE,
    MESH_DOR_MC_PROFILE, MESH_DOR_PROFILE,
    ROUTE_DUMP_FILE, TOPOLOGY_FILE, TORUS_DOR_PROFILE, TRACE_FILE,
    PreparedBookSimInput, parse_config_values,
)
from veritx_dse.backend.qtree_projection import PROFILE as QTREE_PROFILE
from veritx_dse.backend.tree4_projection import PROFILE as TREE4_PROFILE
from veritx_dse.backend.ring_projection import PROFILE as RING_PROFILE
from veritx_dse.backend.fly_projection import PROFILE as FLY_PROFILE
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
# The fork prints exact request-time percentiles next to the stock mean.
# They are the population trace work is ranked on, not the qtime mean above.
_P50_RE = re.compile(r"^\s*p50 = ([0-9.eE+-]+)\s*$", re.MULTILINE)
_P95_RE = re.compile(r"^\s*p95 = ([0-9.eE+-]+)\s*$", re.MULTILINE)
_P99_RE = re.compile(r"^\s*p99 = ([0-9.eE+-]+)\s*$", re.MULTILINE)
_PKT_COUNT_RE = re.compile(r"^\s*pkt_count = (\d+)\s*$", re.MULTILINE)
_HONEST_AVG_RE = re.compile(r"^\s*honest_avg = ([0-9.eE+-]+)\s*$", re.MULTILINE)

# Per-class latency blocks. ``TrafficManager::DisplayStats`` prints one
# ``Class N:`` block per measured traffic class, at the end of every sample
# period. The same header is also printed while draining, but those blocks
# carry only "Remaining flits" (no latency fields), so a block contributes
# only the latency fields it actually printed.
_CLASS_HEADER_RE = re.compile(r"^Class (\d+):\s*$", re.MULTILINE)
_CLASS_BLOCK_END_RE = re.compile(
    r"^(?:Draining remaining packets|={6} Overall Traffic Statistics)",
    re.MULTILINE)
_CLASS_LATENCY_FIELDS: tuple[tuple[str, re.Pattern, bool], ...] = (
    ("packet_latency_avg",
     re.compile(r"^\s*Packet latency average = ([0-9.eE+-]+)\s*$",
                re.MULTILINE), False),
    ("flit_latency_avg",
     re.compile(r"^\s*Flit latency average = ([0-9.eE+-]+)\s*$",
                re.MULTILINE), False),
    ("p50", re.compile(r"^\s*p50 = ([0-9.eE+-]+)\s*$", re.MULTILINE),
     False),
    ("p95", re.compile(r"^\s*p95 = ([0-9.eE+-]+)\s*$", re.MULTILINE),
     False),
    ("p99", re.compile(r"^\s*p99 = ([0-9.eE+-]+)\s*$", re.MULTILINE),
     False),
    ("pkt_count", re.compile(r"^\s*pkt_count = (\d+)\s*$", re.MULTILINE),
     True),
    ("honest_latency",
     re.compile(r"^\s*honest_avg = ([0-9.eE+-]+)\s*$", re.MULTILINE),
     False),
)
_HOPS_RE = re.compile(r"hops\((\d+),:\) = ([0-9.,eE+-]+)")
_UNSTABLE_TOKEN = "Simulation unstable"
_ABORT_TOKENS = ("Assertion", "assertion", "failed", "Aborted",
                 "terminate called")

class BookSimExecutionError(ValueError):
    """Execution, materialization or parsing failed closed."""

def mesh_class_vc_ranges_from_config(text: str) -> tuple[tuple[int, int], ...]:
    values = parse_config_values(text)
    names = ('mesh_class_vc_begin', 'mesh_class_vc_end')
    if not any(name in values for name in names):
        return ()
    ranges = []
    for name in names:
        value = values.get(name, '')
        if not re.fullmatch(r'\{\s*\d+(?:\s*,\s*\d+)*\s*\}', value):
            raise BookSimExecutionError('malformed mesh class VC table')
        ranges.append(tuple(int(v) for v in value.strip('{}').split(',')))
    classes, count = int(values['classes']), int(values['num_vcs'])
    if len(ranges[0]) != classes or len(ranges[1]) != classes:
        raise BookSimExecutionError('incomplete mesh class VC table')
    bound = tuple(zip(*ranges))
    if any(not 0 <= start <= end < count for start, end in bound):
        raise BookSimExecutionError('invalid mesh class VC range')
    return bound


def validate_class_priority_config(prepared: PreparedBookSimInput) -> None:
    """Refuse a priority claim the rendered bytes do not actually carry.

    The profile can only be honest if ``priority = class`` stamps flits,
    ``class_priority`` is the declared dense vector, and the switch allocator
    is the stock priority-honouring ``select`` allocator. A swapped or
    uniform vector is a dead field, not a QoS result.
    """
    if prepared.profile_id != MESH_DOR_CLASS_PRIORITY_PROFILE.profile_id:
        if prepared.priority_class_map:
            raise BookSimExecutionError(
                f"profile {prepared.profile_id!r} binds a class priority "
                "map but is not the certified priority profile")
        return
    if not prepared.priority_class_map:
        raise BookSimExecutionError(
            "priority profile prepared input binds no class priority map")
    if tuple(cls for cls, _rank in prepared.priority_class_map) \
            != prepared.trace_class_map:
        raise BookSimExecutionError(
            "class priority map does not follow the bound trace class order")
    values = parse_config_values(prepared.config_text)
    if values.get("priority") != "class":
        raise BookSimExecutionError(
            "priority profile config does not select priority = class")
    if values.get("sw_allocator") != "select":
        raise BookSimExecutionError(
            "priority profile config does not use the priority-honouring "
            "select switch allocator")
    if values.get("vc_allocator", "islip") != "islip":
        raise BookSimExecutionError(
            "priority profile config uses a VC allocator outside the "
            "certified surface")
    if values.get("vc_priority_donation", "0") != "0":
        raise BookSimExecutionError(
            "priority profile config enables VC priority donation: the "
            "declared class rank must not be donated to another head flit")
    raw = values.get("class_priority", "")
    if not re.fullmatch(r'\{\s*\d+(?:\s*,\s*\d+)*\s*\}', raw):
        raise BookSimExecutionError("malformed class_priority vector")
    ranks = tuple(int(v) for v in raw.strip("{}").split(","))
    expected = tuple(rank for _cls, rank in prepared.priority_class_map)
    if ranks != expected:
        raise BookSimExecutionError(
            "rendered class_priority does not match the declared QoS plan")
    if len(set(ranks)) < 2:
        raise BookSimExecutionError(
            "class_priority is uniform: the priority field cannot affect "
            "arbitration")
    if values.get("classes") is None \
            or int(values["classes"]) != len(ranks):
        raise BookSimExecutionError(
            "class_priority length does not equal the configured class count")


def validate_mesh_class_vc_observations(config: str, text: str, *,
                                      expected_classes: set[int] | None = None) -> dict[str, dict[str, int]]:
    """Observed input-VC membership at native route computation, not paths."""
    ranges = mesh_class_vc_ranges_from_config(config)
    if not ranges:
        return {}
    observations: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        if not line.startswith('VeritX: mesh route class = '):
            continue
        match = re.fullmatch(r'VeritX: mesh route class = (\d+), vc = (\d+)', line)
        if not match:
            raise BookSimExecutionError('malformed mesh class VC observation')
        cls, vc = (int(v) for v in match.groups())
        if cls >= len(ranges) or not ranges[cls][0] <= vc <= ranges[cls][1]:
            raise BookSimExecutionError('observed mesh VC outside its canonical class range')
        counts = observations.setdefault(str(cls), {})
        counts[str(vc)] = counts.get(str(vc), 0) + 1
    if not observations or (expected_classes is not None and
            {int(cls) for cls in observations} != expected_classes):
        raise BookSimExecutionError('missing or foreign mesh class VC observations')
    return observations


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

# ---- Sampled series amendment (simulation-overlay Phase F) ----
#
# Production runs opt in by passing sample_period_cycles (plus the two
# widths the capacity quotient is derived from). Execution then amends
# the run_dir-local config copy AFTER materialize_prepared has verified
# the prepared bytes, so the prepared identity never covers keys the
# preparation never saw. The evidence records both digests.
SERIES_RUN_DOMAIN = "veritx/series-run/v1"
SERIES_OUTPUT_FILE = "channel_timeseries.json"


def series_run_hash(*, prepared_config_sha256: str, trace_sha256: str,
                    binary_sha256: str, seed: int,
                    sample_period_cycles: int, link_capacity: int,
                    link_width_bits: int, flit_width_bits: int) -> str:
    """Identity of one sampled run (bare hex64, gateway- and fork-safe).

    The prepared config digest (not the amended one) goes in: the amended
    bytes embed this hash, so hashing them would be circular. Period and
    capacity are inputs — two samplings of one preparation are two runs.
    """
    from veritx_dse.core.artifact import content_id
    return content_id(SERIES_RUN_DOMAIN, {
        "prepared_config_sha256": prepared_config_sha256,
        "trace_sha256": trace_sha256,
        "binary_sha256": binary_sha256,
        "seed": seed,
        "sample_period_cycles": sample_period_cycles,
        "link_capacity_flits_per_cycle": link_capacity,
        "link_width_bits": link_width_bits,
        "flit_width_bits": flit_width_bits,
    })


def series_capacity_or_refuse(link_width_bits: Any,
                              flit_width_bits: Any) -> int:
    """Link capacity in whole flits per cycle — derived, never declared."""
    for name, value in (("series_link_width_bits", link_width_bits),
                        ("series_flit_width_bits", flit_width_bits)):
        if not isinstance(value, int) or isinstance(value, bool) \
                or value <= 0:
            raise BookSimExecutionError(
                f"{name} must be a positive int, got {value!r}")
    if link_width_bits % flit_width_bits:
        raise BookSimExecutionError(
            f"series link width {link_width_bits} does not divide evenly "
            f"into {flit_width_bits}-bit flits — refusing a fractional "
            f"link capacity")
    return link_width_bits // flit_width_bits


#: Bounded watch budget. The native watch log is a debug capture, not a
#: sampling profiler: the budget is what keeps one run's log readable and
#: the digest cheap, and the stride is what makes the sample cover the whole
#: run instead of only its cold start.
OBSERVED_WATCH_BUDGET = 96

def observed_watch_plan(trace_text: str,
                        budget: int = OBSERVED_WATCH_BUDGET
                        ) -> tuple[list[int], dict[str, Any]]:
    """The deterministic watch sample: stride across every declared packet.

    Native packet ids are assigned in injection order, so a prefix of ids
    is a cold-start sample. A stride over the declared packet count spreads
    the watched packets across the whole run, and the rule is recorded in
    the evidence so the sample can be reproduced or challenged.
    """
    total = sum(1 for line in trace_text.splitlines()
                if line.strip() and not line.lstrip().startswith(("#", "%")))
    if total <= 0:
        return [], {"rule": "no declared packets; no watch sample",
                    "declared_packets": 0, "stride": None,
                    "sampled_packets": 0}
    stride = max(1, -(-total // budget))
    ids = list(range(0, total, stride))[:budget]
    return ids, {"rule": (f"every {stride}th declared packet id, capped at "
                          f"{budget} samples"),
                 "declared_packets": total, "stride": stride,
                 "sampled_packets": len(ids)}

def amend_config_for_series(config_text: str, *, sample_period_cycles: int,
                            run_hash: str, binary_sha256: str,
                            link_capacity: int, trace_sha256: str,
                            config_sha256: str,
                            watch_packet_ids: tuple[int, ...] = ()) -> str:
    """Append the series keys; the prepared text above is untouched."""
    block = (
        "\n"
        "// VeritX execution amendment: sampled series keys. Not part of "
        "the prepared identity (prepared_id); covered by "
        "executed_config_sha256 in the evidence.\n"
        f"channel_timeseries_output = {SERIES_OUTPUT_FILE};\n"
        f"sample_period_cycles = {sample_period_cycles};\n"
        f"run_hash = {run_hash};\n"
        f"run_binary_hash = {binary_sha256};\n"
        f"link_capacity_flits_per_cycle = {link_capacity};\n"
        f"run_input_hashes = {trace_sha256},{config_sha256};\n"
        # A watch file with no selected packet ids is empty by construction, so
        # the keys are omitted rather than left behind as a misleading artifact.
        + ("// Bounded observed debug capture: a recorded stride sample of "
           "native packet IDs.\n"
           "watch_out = observed_hops.log;\n"
           f"watch_packets = {{{','.join(str(i) for i in watch_packet_ids)}}};\n"
           if watch_packet_ids else "")
    )
    return config_text + block

EVIDENCE_OUTPUT_NAME = "backend-evidence.json"

@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

def _supervised_runner(command: tuple[str, ...], cwd: Path,
                       timeout: int) -> ProcessOutcome:
    """The ONE production process seam. Stream raw logs to the run directory
    so timeout/OOM evidence survives even when the simulator fails early.
    No shell, DEVNULL stdin, finite timeout.
    """
    stdout_path = cwd / "booksim.stdout.log"
    stderr_path = cwd / "booksim.stderr.log"
    try:
        with stdout_path.open("wb") as stdout_log, \
                stderr_path.open("wb") as stderr_log:
            try:
                proc = subprocess.run(
                    list(command), cwd=str(cwd), stdin=subprocess.DEVNULL,
                    stdout=stdout_log, stderr=stderr_log, timeout=timeout,
                    shell=False)
                timed_out = False
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                returncode = -1
    except OSError as exc:
        raise BookSimExecutionError(
            f"could not spawn the BookSim process: {exc}") from exc
    stdout_bytes = stdout_path.read_bytes()
    stderr_bytes = stderr_path.read_bytes()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    log_manifest = {
        "schema": "veritx/booksim-process-logs/1",
        "returncode": returncode,
        "timed_out": timed_out,
        "logs": {
            "stdout": {"path": stdout_path.name,
                       "size_bytes": len(stdout_bytes),
                       "sha256": hashlib.sha256(stdout_bytes).hexdigest()},
            "stderr": {"path": stderr_path.name,
                       "size_bytes": len(stderr_bytes),
                       "sha256": hashlib.sha256(stderr_bytes).hexdigest()},
        },
    }
    (cwd / "booksim-process-logs.json").write_text(
        json.dumps(log_manifest, indent=2) + "\n", encoding="utf-8")
    return ProcessOutcome(returncode=returncode, stdout=stdout,
                          stderr=stderr, timed_out=timed_out)

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


def _class_latency_blocks(stdout: str) -> dict[int, dict[str, float | int]]:
    """Every per-class latency reading the fork actually printed.

    Class index -> the latency fields present in that class's block. A
    later sample's block for the same class replaces an earlier one field
    by field, so the last sampled reading wins; drain blocks carry no
    latency and can never erase a measured reading. An unprintable /
    unavailable value is omitted, never zero-filled.
    """
    headers = list(_CLASS_HEADER_RE.finditer(stdout))
    by_class: dict[int, dict[str, float | int]] = {}
    for index, header in enumerate(headers):
        start = header.end()
        end = (headers[index + 1].start()
               if index + 1 < len(headers) else len(stdout))
        boundary = _CLASS_BLOCK_END_RE.search(stdout, start, end)
        if boundary is not None:
            end = boundary.start()
        segment = stdout[start:end]
        parsed: dict[str, float | int] = {}
        for key, pattern, is_count in _CLASS_LATENCY_FIELDS:
            match = pattern.search(segment)
            if match is None:
                continue
            token = match.group(1).strip()
            if _unavailable(token):
                continue
            if is_count:
                parsed[key] = int(token)
                continue
            value = float(token)
            if math.isfinite(value):
                parsed[key] = value
        if parsed:
            by_class.setdefault(int(header.group(1)), {}).update(parsed)
    return by_class


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
    latency_by_class = _class_latency_blocks(stdout)
    # ``Class N:`` blocks are PER CLASS. In a multi-class run the first
    # block is class 0, not an aggregate, so the historical scalar latency
    # keys below are labelled rather than silently presented as aggregate.
    latency_scope = ("PER_CLASS" if len(latency_by_class) > 1
                     else "SINGLE_CLASS" if latency_by_class else None)
    return {
        "parser_version": PARSER_VERSION,
        "loaded_trace_packets": loaded_packets,
        "injected_trace_packets": injected,
        "completion_cycles": completion_cycles,
        "sample_window_cycles": sample_window_cycles,
        # Historical scalar keys: keep them byte-identically present. In a
        # multi-class run each matches the FIRST ``Class N:`` block (class
        # 0), which latency_scope labels as PER_CLASS rather than aggregate.
        "packet_latency_avg": _optional_number(_PLAT_RE, stdout,
                                               "packet latency"),
        "flit_latency_avg": _optional_number(_FLAT_RE, stdout,
                                             "flit latency"),
        "p50": _optional_number(_P50_RE, stdout, "p50 latency"),
        "p95": _optional_number(_P95_RE, stdout, "p95 latency"),
        "p99": _optional_number(_P99_RE, stdout, "p99 latency"),
        "honest_latency": _optional_number(_HONEST_AVG_RE, stdout,
                                          "honest average latency"),
        "pkt_count": (int(match.group(1))
                      if (match := _PKT_COUNT_RE.search(stdout)) else None),
        "latency_by_class": latency_by_class,
        "latency_scope": latency_scope,
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
        allow_unqualified_profile: bool = False,
        require_manifest_recipe: str | None = None,
        expected_prepared_id: str | None = None,
        write: bool = True,
        sample_period_cycles: int | None = None,
        series_link_width_bits: int | None = None,
        series_flit_width_bits: int | None = None,
        series_store_dir: Path | str | None = None) -> ExecutionRecord:
    """Execute exactly the prepared bytes with an identified producer.

    Sampled series are strictly opt-in: every series argument left at
    None reproduces the unsampled path byte for byte (empty series key
    in the fork, no amendment, no publish, null series evidence). Pass
    sample_period_cycles plus both widths to sample; series_store_dir
    additionally publishes the validated series for the loom API.
    """
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
    from veritx_dse.backend.router_controls import base_profile_id
    execution_profile_id = base_profile_id(prepared.profile_id)
    validate_class_priority_config(prepared)
    class_vc_profile = (
        execution_profile_id in (MESH_DOR_CLASS_VC_PROFILE.profile_id,
                                 MESH_DOR_CLASS_PRIORITY_PROFILE.profile_id))
    # Every native family whose routing/VC proof is class-independent can
    # execute a class-bound trace. The mesh single-class profile stays out:
    # its audit pins classes = 1 and its execution gate must keep refusing a
    # multi-class trace. The promoted profiles below render ``classes`` from
    # the canonical map and must bind that map before execution.
    _multi_class_capable = {
        MESH_DOR_CLASS_VC_PROFILE.profile_id,
        MESH_DOR_CLASS_PRIORITY_PROFILE.profile_id,
        CMESH_DOR_PROFILE.profile_id,
        TORUS_DOR_PROFILE.profile_id,
        FLATFLY_MIN_PROFILE.profile_id,
        ANYNET_MC_PROFILE.profile_id,
        ANYNET_PROFILE.profile_id,
        GEC_MECS_PROFILE.profile_id,
        GEC_HYBRID_PROFILE.profile_id,
        QTREE_PROFILE.profile_id,
        TREE4_PROFILE.profile_id,
        RING_PROFILE.profile_id,
        FLY_PROFILE.profile_id,
    }
    _multi_class_only = {
        MESH_DOR_MC_PROFILE.profile_id,
        MESH_DOR_CLASS_VC_PROFILE.profile_id,
        MESH_DOR_CLASS_PRIORITY_PROFILE.profile_id,
    }
    _single_class_capable = {
        MESH_DOR_PROFILE.profile_id,
        CMESH_DOR_PROFILE.profile_id,
        TORUS_DOR_PROFILE.profile_id,
        FLATFLY_MIN_PROFILE.profile_id,
        ANYNET_PROFILE.profile_id,
        GEC_MECS_PROFILE.profile_id,
        GEC_HYBRID_PROFILE.profile_id,
        QTREE_PROFILE.profile_id,
        TREE4_PROFILE.profile_id,
        RING_PROFILE.profile_id,
        FLY_PROFILE.profile_id,
    }
    from veritx_dse.application.booksim_qualification_registry import qualification_of
    unqualified_profile = not qualification_of(prepared.profile_id).is_qualified
    if unqualified_profile and (require_pinned_producer or not allow_unqualified_profile):
        raise BookSimExecutionError("selected profile is not qualified; diagnostic execution requires explicit opt-in")
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
    if execution_profile_id == SROTA_ROW_FIRST_PROFILE.profile_id:
        # A bound class map is the SROTA multi-class signal: on a single
        # packet plane every class rides subnet 0; on a multi-plane fabric
        # each class rides its own subnet. An unbound input is the legacy
        # single-class path, and a multi-plane fabric without a map is
        # refused rather than sent to subnet 0.
        if prepared.trace_class_map:
            if not _trace_indices <= set(
                    range(len(prepared.trace_class_map))):
                raise BookSimExecutionError(
                    f"SROTA trace indices {sorted(_trace_indices)} "
                    f"exceed the bound class map "
                    f"{list(prepared.trace_class_map)}: refusing a "
                    "class-swapped or collapsed trace")
        elif parse_config_values(
                prepared.config_text).get("subnets") == "2":
            raise BookSimExecutionError(
                "multi-plane prepared input binds no class map: "
                "refusing an unbound multi-class execution")
        elif not _trace_indices <= {0}:
            raise BookSimExecutionError(
                f"single-class profile {prepared.profile_id!r} carries "
                f"trace class indices {sorted(_trace_indices)}: "
                f"refusing a multi-class trace on a single-class profile")
    elif execution_profile_id in _multi_class_only:
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
    elif (execution_profile_id in _multi_class_capable
          and prepared.trace_class_map):
        if not _trace_indices <= set(range(len(prepared.trace_class_map))):
            raise BookSimExecutionError(
                f"multi-class trace indices {sorted(_trace_indices)} "
                f"exceed the bound class map "
                f"{list(prepared.trace_class_map)}: refusing a "
                f"class-swapped or collapsed trace")
    elif execution_profile_id in _single_class_capable:
        if not _trace_indices <= {0}:
            raise BookSimExecutionError(
                f"single-class profile {prepared.profile_id!r} carries "
                f"trace class indices {sorted(_trace_indices)}: "
                f"refusing a multi-class trace on a single-class profile")
    else:
        raise BookSimExecutionError(
            f"profile {prepared.profile_id!r} has no trace class-domain "
            f"rule: refusing execution until the domain is declared")
    if execution_profile_id == QTREE_PROFILE.profile_id:
        required = {(router, terminal) for router in range(21) for terminal in range(64)}
        if (len(prepared.expected_route_rows) != 1344
                or {(r, d) for r, d, _ in prepared.expected_route_rows} != required
                or len(prepared.expected_route_ports) != 1344
                or {(r, d) for r, d, _ in prepared.expected_route_ports} != required):
            raise BookSimExecutionError("native QTree requires complete hop AND port obligations")
    tree4_vc_count = None
    if execution_profile_id == TREE4_PROFILE.profile_id:
        # Tree4's executed law is a legal-choice UNION (four roots, two
        # destination-group middles, two parents), so its obligations are the
        # union table plus the runtime dump, not a single-row table. A
        # prepared input carrying single rows would be a different, fictional
        # dialect; the model must also cover every router/terminal pair.
        if prepared.expected_route_rows or prepared.expected_route_ports:
            raise BookSimExecutionError(
                "native Tree4 prepared input must not carry single-row route "
                "obligations: the upward parent is a legal choice union")
        from .tree4_projection import expected_rows as _tree4_expected
        from .tree4_projection import model_topology, pinned_geometry
        from .tree4_projection import TERMINALS as _TREE4_TERMINALS
        _values = parse_config_values(prepared.config_text)
        pinned_geometry(_values)
        _model = model_topology()
        rows, ports, choices = _tree4_expected(_model)
        if len(rows) + len(choices) != _model.router_count * _TREE4_TERMINALS:
            raise BookSimExecutionError(
                "native Tree4 model law does not cover every "
                "router/terminal pair")
        tree4_vc_count = int(parse_config_values(
            prepared.config_text)["num_vcs"])
    ring_size = None
    if execution_profile_id == RING_PROFILE.profile_id:
        # The ring's obligations are the union dump and the runtime
        # route-compute dump, both total over the fabric; a prepared input
        # carrying single-row obligations would be a different (fictional)
        # dialect, so refuse rather than let one of them go unchecked.
        if prepared.expected_route_rows or prepared.expected_route_ports:
            raise BookSimExecutionError(
                "native ring prepared input must not carry single-row route "
                "obligations: the midpoint tie has no single first hop")
        from .ring_projection import expected_rows_for
        ring_size = int(parse_config_values(prepared.config_text)["k"])
        if ring_size < 4 or ring_size % 2:
            raise BookSimExecutionError(
                f"native ring requires even k >= 4, prepared k={ring_size}")
        rows, ports, ties = expected_rows_for(ring_size)
        if len(rows) + len(ties) != ring_size * (ring_size - 1):
            raise BookSimExecutionError(
                "native ring model law does not cover every "
                "router/destination pair")
    fly_vc_count = None
    if execution_profile_id == FLY_PROFILE.profile_id:
        # dest_tag_fly is deterministic, so BOTH obligations are available and
        # both are required: the single-row first-hop table (with ports) is
        # compared against the static dump, and the executed route-compute
        # stream is checked separately for stage advance and ejection point.
        from .fly_projection import QUALIFIED_HOP_OBLIGATIONS
        required = {(router, terminal)
                    for router in range(QUALIFIED_HOP_OBLIGATIONS[0])
                    for terminal in range(QUALIFIED_HOP_OBLIGATIONS[1])}
        if (len(prepared.expected_route_rows) != len(required)
                or {(r, d) for r, d, _ in prepared.expected_route_rows}
                != required
                or len(prepared.expected_route_ports) != len(required)
                or {(r, d) for r, d, _ in prepared.expected_route_ports}
                != required):
            raise BookSimExecutionError(
                "native fly requires complete hop AND port obligations over "
                f"every (router, terminal) pair (expected "
                f"{QUALIFIED_HOP_OBLIGATIONS[0]}x"
                f"{QUALIFIED_HOP_OBLIGATIONS[1]})")
        fly_vc_count = int(parse_config_values(
            prepared.config_text)["num_vcs"])
    if (execution_profile_id == GEC_HYBRID_PROFILE.profile_id
            and not prepared.expected_hybrid_candidates):
        raise BookSimExecutionError("hybrid prepared input binds no runtime candidate set")
    if type(timeout) is not int or timeout <= 0:
        raise BookSimExecutionError("timeout must be a positive int")

    # ---- Sampled series request validation (fail closed, before any
    # side effect). Widths or a store without a period are dangling
    # parameters, never silently ignored.
    sampling = sample_period_cycles is not None
    if sampling:
        if type(sample_period_cycles) is not int \
                or sample_period_cycles <= 0:
            raise BookSimExecutionError(
                "sample_period_cycles must be a positive int, got "
                f"{sample_period_cycles!r}")
        series_capacity = series_capacity_or_refuse(
            series_link_width_bits, series_flit_width_bits)
    else:
        if series_link_width_bits is not None \
                or series_flit_width_bits is not None \
                or series_store_dir is not None:
            raise BookSimExecutionError(
                "series sampling parameters without "
                "sample_period_cycles: pass a period or nothing")
        series_capacity = 0

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

    fidelity = ("DIAGNOSTIC_UNQUALIFIED_PROFILE" if unqualified_profile
                else FIDELITY_QUALIFIED if identity.pinned
                else FIDELITY_UNPINNED_PRODUCER)
    if transport == EXECUTION_TRANSPORT_TEST_INJECTED:
        fidelity = FIDELITY_TEST_INJECTED
    if require_pinned_producer:
        try:
            assert_pinned_producer(identity)
        except ProducerError as exc:
            raise BookSimExecutionError(str(exc)) from exc

    materialize_prepared(prepared, Path(run_dir))

    # ---- Series amendment (after the prepared bytes verified above).
    # The run_dir-local config gains the series keys; prepared_id and
    # config_sha256 keep referring to the prepared bytes, while
    # executed_config_sha256 below covers the amended bytes the binary
    # actually ran. A stale series file from a previous attempt refuses
    # in materialize (unexpected file), never silently re-served.
    run_hash: str | None = None
    executed_config_sha256: str | None = None
    if sampling:
        assert sample_period_cycles is not None  # narrowed above
        run_hash = series_run_hash(
            prepared_config_sha256=digests[CONFIG_FILE],
            trace_sha256=digests[TRACE_FILE],
            binary_sha256=identity.binary_sha256,
            seed=seed,
            sample_period_cycles=sample_period_cycles,
            link_capacity=series_capacity,
            link_width_bits=series_link_width_bits,
            flit_width_bits=series_flit_width_bits)
        watch_text = (Path(run_dir) / TRACE_FILE).read_text()
        watch_ids, watch_plan = observed_watch_plan(watch_text)
        amended = amend_config_for_series(
            prepared.config_text,
            sample_period_cycles=sample_period_cycles,
            run_hash=run_hash,
            binary_sha256=identity.binary_sha256,
            link_capacity=series_capacity,
            trace_sha256=digests[TRACE_FILE],
            config_sha256=digests[CONFIG_FILE],
            watch_packet_ids=watch_ids)
        config_path = Path(run_dir) / CONFIG_FILE
        if config_path.read_bytes() != prepared.config_text.encode():
            raise BookSimExecutionError(
                "prepared config changed under a sampled run between "
                "materialization and amendment — refusing to execute")
        config_path.write_bytes(amended.encode())
        executed_config_sha256 = hashlib.sha256(amended.encode()).hexdigest()

    command = (str(Path(binary)), CONFIG_FILE)
    run = runner or _supervised_runner
    started = time.monotonic()
    outcome = run(command, Path(run_dir), timeout)
    wall = time.monotonic() - started

    log_manifest_path = Path(run_dir) / "booksim-process-logs.json"
    log_hint = (f"; stdout/stderr logs: {log_manifest_path}"
                if log_manifest_path.is_file() else "")
    if outcome.timed_out:
        raise BookSimExecutionError(
            f"BookSim timed out after {timeout}s and was killed{log_hint}")
    if outcome.returncode != 0:
        raise BookSimExecutionError(
            f"BookSim exited {outcome.returncode}: "
            f"{(outcome.stderr or '')[-300:]}{log_hint}")

    stats = parse_booksim_stats(outcome.stdout, outcome.stderr)
    if prepared.priority_class_map:
        # The executed vector is a canonical design fact, not a parser
        # artifact: put the declared class->rank binding in the evidence so
        # a reader does not have to re-open the config to see the claim.
        stats['class_priority_plan'] = {
            cls: rank for cls, rank in prepared.priority_class_map}
    declared_by_class = (dict(prepared.expected_flits_by_class)
                         if prepared.expected_flits_by_class else {})
    expected_by_index = (
        {i: declared_by_class[cls]
         for i, cls in enumerate(prepared.trace_class_map)}
        if prepared.trace_class_map else None)
    if transport != EXECUTION_TRANSPORT_TEST_INJECTED:
        observations = validate_mesh_class_vc_observations(
            prepared.config_text, outcome.stdout + '\n' + outcome.stderr,
            expected_classes=_trace_indices)
        if observations:
            stats['mesh_class_vc_route_observations'] = observations
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
                adaptive=execution_profile_id
                in _ADAPTIVE_ROUTE_PROFILES)
        except RouteObservationError as exc:
            raise BookSimExecutionError(str(exc)) from exc
        if prepared.expected_route_ports:
            from veritx_dse.backend.route_observation import parse_route_dump_rows
            rows = parse_route_dump_rows(dump_text)
            for src, dest, port in prepared.expected_route_ports:
                if rows[(src, dest)].port != port:
                    raise BookSimExecutionError(
                        f"executed route port differs at router {src}, terminal {dest}: "
                        f"{rows[(src, dest)].port} != {port}")
        route_observation = ROUTE_OBSERVATION_OBSERVED
        route_dump_sha256 = hashlib.sha256(dump_text.encode()).hexdigest()

    if (transport != EXECUTION_TRANSPORT_TEST_INJECTED
            and execution_profile_id == GEC_HYBRID_PROFILE.profile_id):
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

    if (transport != EXECUTION_TRANSPORT_TEST_INJECTED
            and execution_profile_id == TREE4_PROFILE.profile_id):
        import hashlib as _hashlib
        from .route_observation import (
            RouteObservationError, parse_route_dump_union_rows,
        )
        from .tree4_projection import (
            OBSERVATION_FILE as TREE4_OBSERVATION_FILE, model_topology,
            verify_runtime as _tree4_runtime, verify_union_table,
        )
        union_path = Path(run_dir) / ROUTE_DUMP_FILE
        try:
            union_text = union_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BookSimExecutionError(
                f"Tree4 legal-choice union dump missing at {union_path} "
                f"({exc}); the upward parent choice is only certifiable "
                f"there") from exc
        try:
            union = parse_route_dump_union_rows(union_text)
        except RouteObservationError as exc:
            raise BookSimExecutionError(str(exc)) from exc
        assert tree4_vc_count is not None
        stats["tree4_route_union"] = verify_union_table(
            union=union, topology=model_topology())
        observed = Path(run_dir) / TREE4_OBSERVATION_FILE
        try:
            runtime_text = observed.read_text(encoding="utf-8")
        except OSError as exc:
            raise BookSimExecutionError(
                f"native Tree4 route-compute dump missing at {observed} "
                f"({exc}); the executed parent choice is only proven there"
            ) from exc
        stats["tree4_route_computations"] = _tree4_runtime(
            runtime_text, topology=model_topology(),
            vc_count=tree4_vc_count)
        route_observation = ROUTE_OBSERVATION_OBSERVED
        route_dump_sha256 = _hashlib.sha256(
            union_text.encode()).hexdigest()

    if (transport != EXECUTION_TRANSPORT_TEST_INJECTED
            and execution_profile_id == RING_PROFILE.profile_id):
        import hashlib as _hashlib
        from .ring_projection import (
            OBSERVATION_FILE as RING_OBSERVATION_FILE,
            verify_runtime_halves, verify_union_table,
        )
        from .route_observation import (
            RouteObservationError, parse_route_dump_union_rows,
        )
        union_path = Path(run_dir) / ROUTE_DUMP_FILE
        try:
            union_text = union_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BookSimExecutionError(
                f"ring legal-choice union dump missing at {union_path} "
                f"({exc}); the ring's first-hop law is only certifiable "
                f"there") from exc
        try:
            union = parse_route_dump_union_rows(union_text)
        except RouteObservationError as exc:
            raise BookSimExecutionError(str(exc)) from exc
        assert ring_size is not None
        stats["ring_route_union"] = verify_union_table(
            union=union, n=ring_size)
        observed = Path(run_dir) / RING_OBSERVATION_FILE
        try:
            runtime_text = observed.read_text(encoding="utf-8")
        except OSError as exc:
            raise BookSimExecutionError(
                f"native ring route-compute dump missing at {observed} "
                f"({exc}); the dateline halves are only proven there"
            ) from exc
        stats["ring_route_computations"] = verify_runtime_halves(
            runtime_text, endpoint_count=ring_size)
        route_observation = ROUTE_OBSERVATION_OBSERVED
        route_dump_sha256 = _hashlib.sha256(
            union_text.encode()).hexdigest()

    if (transport != EXECUTION_TRANSPORT_TEST_INJECTED
            and execution_profile_id == FLY_PROFILE.profile_id):
        from .fly_projection import (
            OBSERVATION_FILE as FLY_OBSERVATION_FILE,
            verify_runtime as _fly_runtime,
        )
        observed = Path(run_dir) / FLY_OBSERVATION_FILE
        try:
            runtime_text = observed.read_text(encoding="utf-8")
        except OSError as exc:
            raise BookSimExecutionError(
                f"native fly route-compute dump missing at {observed} "
                f"({exc}); stage advance and the ejection point are only "
                f"proven there") from exc
        assert fly_vc_count is not None
        stats["fly_route_computations"] = _fly_runtime(
            runtime_text, num_vcs=fly_vc_count)

    # ---- Series validation and publish. The emitted dump is read back
    # through the v3 reader (never trusted from the filename): a wrong
    # hash, a wrong period, a malformed document or zero windows fails
    # the run instead of recording an unservable series. An injected
    # (test) transport with no emitted file skips validation — the stub
    # stands in for the binary — but a stub-written file still validates.
    if sampling:
        assert run_hash is not None
        assert sample_period_cycles is not None
        series_path = Path(run_dir) / SERIES_OUTPUT_FILE
        if series_path.is_file():
            from veritx_dse.backend.channel_series import (
                SeriesRefusal, load_series,
            )
            try:
                series_artifact = load_series(str(series_path))
            except SeriesRefusal as exc:
                raise BookSimExecutionError(
                    f"sampled run emitted an unreadable series "
                    f"({exc.code}): refusing an unservable measurement"
                ) from exc
            if series_artifact.run_hash != run_hash:
                raise BookSimExecutionError(
                    "emitted series run_hash does not match the executed "
                    "run — refusing a transplanted series")
            if series_artifact.sample_period_cycles \
                    != sample_period_cycles:
                raise BookSimExecutionError(
                    "emitted series period does not match the requested "
                    "period — refusing a silently resampled series")
            if series_store_dir is not None:
                dest_dir = Path(series_store_dir) / run_hash
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / SERIES_OUTPUT_FILE
                data = series_path.read_bytes()
                if dest.is_file() and dest.read_bytes() != data:
                    raise BookSimExecutionError(
                        f"series store already holds different bytes for "
                        f"run {run_hash} — refusing to overwrite a "
                        f"published series")
                dest.write_bytes(data)
        elif transport != EXECUTION_TRANSPORT_TEST_INJECTED:
            raise BookSimExecutionError(
                "sampling was requested but the binary emitted no series "
                "file — refusing an unmeasured sampled run")

    observed_path = Path(run_dir) / "observed_hops.log"
    if sampling and observed_path.is_file():
        payload = observed_path.read_bytes()
        stats["observed_hop_capture"] = {
            "format": "booksim-watch/v1", "path": "observed_hops.log",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "packet_ids": watch_ids,
            "sample": watch_plan,
            "scope": ("bounded native watch events for the sampled packet "
                      "ids only — a stride sample of the run, never a full "
                      "hop trace"),
        }

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
        executed_config_sha256=executed_config_sha256,
        series_run_hash=run_hash,
        series_sample_period_cycles=sample_period_cycles if sampling
        else None,
        series_link_capacity_flits_per_cycle=series_capacity if sampling
        else None,
        series_link_width_bits=series_link_width_bits if sampling
        else None,
        series_flit_width_bits=series_flit_width_bits if sampling
        else None,
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
    "series_capacity_or_refuse", "series_run_hash",
    "validate_class_priority_config",
]
