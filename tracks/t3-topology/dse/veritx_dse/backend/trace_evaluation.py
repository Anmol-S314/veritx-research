"""Raw-trace evaluation seam for the certified standalone BookSim backend.

This module is intentionally self-contained.  It turns one schema-v4 request
plus one raw single-class trace into a compiled fabric, binds the trace to the
canonical standalone BookSim inputs, executes through the certified runner (or
an injected test runner), and persists one JSON evidence document.

The seam is deliberately narrow:

* only a schema-v4 request is accepted; v3/v5 documents are refused rather
  than migrated implicitly;
* only the raw whitespace trace dialect with exactly five columns
  ``cyc src cl dst sz`` is accepted;
* the standalone backend binds ``classes=1``, so every packet must carry
  class ``0``;
* the trace is validated against the compiled attachment's endpoint universe
  before any runner is invoked.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.backend.booksim import (
    PreparedBackend,
    prepare_booksim_standalone,
    run_qualified_booksim,
)
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compile_request_v4 import CompileRequestV4

#: The exact evidence summary this seam persists.  Missing optional fields
#: are represented by ``None``; they are never fabricated.
EVIDENCE_FIELDS: tuple[str, ...] = (
    "backend_config_hash",
    "backend_input_hash",
    "resolved_fabric_hash",
    "fabric_hash",
    "qualification",
    "exact_fabric_eligible",
    "stats",
    "exit_status",
    "workload_hash",
    "seed",
    "seed_policy",
    "route_equivalence",
    "route_pairs_compared",
)

#: The raw standalone trace grammar is ``cyc src cl dst sz``.
TRACE_COLUMNS = 5
TRACE_DIALECT = "whitespace"

#: The certified standalone backend binds exactly one traffic class.
SINGLE_TRACE_CLASS = 0


class TraceEvaluationError(ValueError, SemanticError):
    """A raw trace cannot be evaluated as a certified standalone run."""


@dataclass(frozen=True)
class TraceEvaluation:
    """One raw-trace evaluation bound to its compiled fabric and evidence."""

    request_design_hash: str
    fabric_hash: str
    trace_sha256: str
    trace_summary: dict[str, Any]
    evidence: dict[str, Any]
    output_dir: str

    def to_dict(self) -> dict[str, Any]:
        """The persisted, JSON-safe document for this evaluation."""
        return _json_safe(dataclasses.asdict(self))


@dataclass(frozen=True)
class _Packet:
    """One validated raw trace packet (line numbers aid refusal messages)."""

    line_no: int
    timestamp: int
    src: int
    cls: int
    dst: int
    size: int


def _json_safe(value: Any) -> Any:
    """Recursively convert backend evidence into JSON-native values.

    ``stats`` is carried as data, not reinterpreted: mappings and sequences
    keep their shape, dataclasses become mappings, and paths become strings.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_safe(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    # Unknown objects must not leak into the JSON document.  Keep a readable
    # representation rather than inventing scientific content.
    return str(value)


def _summary_of(evidence: Any) -> dict[str, Any]:
    """Normalize a runner result (dataclass or mapping) to the evidence summary.

    Optional fields absent from the result become ``None``.  ``stats`` is
    preserved as the runner returned it (after JSON-safe conversion).
    """
    if evidence is None:
        return {field: None for field in EVIDENCE_FIELDS}

    if dataclasses.is_dataclass(evidence) and not isinstance(evidence, type):
        def read(name: str) -> Any:
            return getattr(evidence, name, None)
    elif isinstance(evidence, Mapping):
        def read(name: str) -> Any:
            return evidence.get(name)
    else:
        def read(name: str) -> Any:
            return getattr(evidence, name, None)

    return {field: _json_safe(read(field)) for field in EVIDENCE_FIELDS}


def _parse_request(request_doc: Any) -> CompileRequestV4:
    """Accept exactly one schema-v4 request document; never migrate."""
    if not isinstance(request_doc, Mapping):
        raise TraceEvaluationError(
            "request_doc must be a JSON object, got "
            f"{type(request_doc).__name__}")
    version = request_doc.get("schema_version")
    if version != 4:
        raise TraceEvaluationError(
            "trace evaluation requires a schema v4 request, got "
            f"schema_version={version!r}. v3 and v5 documents must be "
            "migrated or down-projected explicitly; this seam never upgrades "
            "or downgrades a request implicitly.")
    try:
        return CompileRequestV4.from_dict(dict(request_doc))
    except (TypeError, ValueError) as exc:
        raise TraceEvaluationError(
            f"request_doc is not a valid v4 CompileRequest: {exc}") from exc


def _parse_trace(trace: bytes) -> list[_Packet]:
    """Strictly validate the raw single-class whitespace trace grammar.

    Blank lines and lines beginning with ``#`` or ``%`` are comments.  Every
    other line must have exactly five whitespace columns, integer fields, a
    non-negative timestamp, a positive packet size, and class column ``0``.
    Endpoint bounds are checked later, once the compiled fabric is known.
    """
    if not trace:
        raise TraceEvaluationError("trace is empty")
    try:
        text = trace.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TraceEvaluationError(f"trace is not UTF-8: {exc}") from exc

    packets: list[_Packet] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in ("#", "%"):
            continue
        fields = line.split()
        if len(fields) != TRACE_COLUMNS:
            raise TraceEvaluationError(
                f"trace line {line_no}: expected exactly {TRACE_COLUMNS} "
                f"whitespace columns (cyc src cl dst sz) in the raw "
                f"single-class dialect, got {len(fields)}: {line!r}")
        try:
            timestamp, src, cls, dst, size = (int(field) for field in fields)
        except ValueError as exc:
            raise TraceEvaluationError(
                f"trace line {line_no}: non-integer field: {exc}") from exc
        if cls != SINGLE_TRACE_CLASS:
            raise TraceEvaluationError(
                f"trace line {line_no}: single-class raw traces require "
                f"class column {SINGLE_TRACE_CLASS}, got {cls}; the "
                "standalone backend binds classes=1 and cannot execute "
                "multi-class traffic")
        if timestamp < 0:
            raise TraceEvaluationError(
                f"trace line {line_no}: negative timestamp {timestamp}")
        if src < 0 or dst < 0:
            raise TraceEvaluationError(
                f"trace line {line_no}: negative endpoint src={src} dst={dst}")
        if size < 1:
            raise TraceEvaluationError(
                f"trace line {line_no}: non-positive packet size {size}")
        packets.append(_Packet(line_no=line_no, timestamp=timestamp, src=src,
                               cls=cls, dst=dst, size=size))

    if not packets:
        raise TraceEvaluationError(
            "trace has no non-comment data lines (it is empty)")
    return packets


def _validate_endpoint_range(packets: list[_Packet], endpoint_count: int) -> None:
    """Refuse any endpoint outside the compiled attachment universe."""
    for packet in packets:
        if not (0 <= packet.src < endpoint_count) or \
                not (0 <= packet.dst < endpoint_count):
            raise TraceEvaluationError(
                f"trace line {packet.line_no}: endpoint outside "
                f"[0, {endpoint_count}): src={packet.src} dst={packet.dst}; "
                "the compiled attachment defines the valid endpoint range")


def _trace_summary(packets: list[_Packet], endpoint_count: int) -> dict[str, Any]:
    return {
        "dialect": TRACE_DIALECT,
        "num_packets": len(packets),
        "max_timestamp": max(packet.timestamp for packet in packets),
        "endpoint_count": endpoint_count,
    }


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Write one JSON document with a temp file followed by ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, sort_keys=True, indent=2,
                      ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def evaluate_trace(
    request_doc: dict,
    trace: bytes,
    *,
    repo_root: Path,
    run_dir: Path,
    booksim_bin: Path | None = None,
    seed: int = 0,
    timeout: int = 600,
    runner=None,
) -> TraceEvaluation:
    """Compile, execute, and persist one raw single-class trace evaluation.

    ``runner`` is an explicit test seam.  When omitted, the certified
    :func:`run_qualified_booksim` is used.  The runner is called as::

        runner(prepared, run_dir=run_dir, repo_root=repo_root,
               timeout=timeout, binary=booksim_bin)

    and may return either a dataclass or a mapping.  Only the fields listed in
    :data:`EVIDENCE_FIELDS` are persisted.
    """
    if not isinstance(trace, (bytes, bytearray)):
        raise TraceEvaluationError(
            f"trace must be bytes, got {type(trace).__name__}")
    trace = bytes(trace)
    run_dir = Path(run_dir)
    repo_root = Path(repo_root)

    request = _parse_request(request_doc)
    packets = _parse_trace(trace)

    try:
        compilation = FabricCompiler().compile(request)
    except Exception as exc:                       # noqa: BLE001
        raise TraceEvaluationError(
            f"fabric compilation failed before a verdict: {exc}") from exc

    if compilation.status != "COMPILED" or compilation.bundle is None:
        raise TraceEvaluationError(
            "fabric compilation did not produce a bundle: "
            f"status={compilation.status}, error={compilation.error!r}")

    bundle = compilation.bundle
    endpoint_count = bundle.attachment.endpoint_count
    _validate_endpoint_range(packets, endpoint_count)

    try:
        prepared: PreparedBackend = prepare_booksim_standalone(
            bundle, workload_trace=trace, seed=seed)
    except ValueError as exc:
        raise TraceEvaluationError(
            f"cannot prepare the standalone BookSim run: {exc}") from exc

    execute = run_qualified_booksim if runner is None else runner
    result = execute(
        prepared,
        run_dir=run_dir,
        repo_root=repo_root,
        timeout=timeout,
        binary=booksim_bin,
    )
    if result is None:
        raise TraceEvaluationError("backend runner returned no evidence")

    evaluation = TraceEvaluation(
        request_design_hash=request.design_hash(),
        fabric_hash=bundle.fabric.fabric_hash,
        trace_sha256=hashlib.sha256(trace).hexdigest(),
        trace_summary=_trace_summary(packets, endpoint_count),
        evidence=_summary_of(result),
        output_dir=str(run_dir),
    )
    _write_json_atomic(run_dir / "trace-evaluation.json",
                       evaluation.to_dict())
    return evaluation


__all__ = [
    "EVIDENCE_FIELDS",
    "SINGLE_TRACE_CLASS",
    "TRACE_COLUMNS",
    "TRACE_DIALECT",
    "TraceEvaluation",
    "TraceEvaluationError",
    "evaluate_trace",
]
