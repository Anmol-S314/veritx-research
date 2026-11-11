"""Diagnostic raw-trace evaluation over a legacy BookSim mesh-DOR config.

This module is a deliberately narrow BRIDGE, not a certified backend path.
The certified raw-trace seam (``backend/trace_evaluation.py``) lowers the
compiled fabric to the standalone ANYNET profile, which realizes only
``ANYNET_MIN_HOPS`` and therefore refuses a typed ``MeshIntent`` whose route
class is ``DOR_XY``.  The legacy ``veritx evaluate booksim --topo mesh``
path executes DOR, but it is neither request-driven nor evidence-bound.

This seam connects the two without over-claiming:

* it accepts exactly one schema-v4 request and compiles it with
  :class:`~veritx_dse.application.fabric_compiler.FabricCompiler`;
* it requires a typed :class:`~veritx_dse.model.topology_intent.MeshIntent`
  and derives ``k`` from ``side_length``;
* it validates the raw single-class trace and writes it into a fresh run
  directory;
* it builds a LEGACY ``Topology(backend="mesh", routing="dim_order",
  params={"k": k, "n": 2})`` and a BookSim config through
  :func:`veritx_dse.simulation.booksim.build_config`;
* it runs the legacy BookSim runner (or an injected test runner) and
  persists one JSON document labelled ``DIAGNOSTIC_MESH_DOR`` with
  ``exact_fabric_eligible=False``.

What it never claims: route equivalence, certified config identity, exact
fabric eligibility, ASTRA execution, or that the legacy config is the
compiled bundle's backend projection.  The compiled bundle's ``vc_count``
and flit width are reported for context only; the legacy mesh config does
not bind the bundle's VC assignment or route artifact.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.errors import BookSimError, SemanticError, TraceError
from veritx_dse.core.logging import Ctx
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.presets import Topology
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.simulation.booksim import (
    build_config,
    detect_trace_stats,
    run_booksim,
)

#: The one qualification label this seam may emit.
QUALIFICATION = "DIAGNOSTIC_MESH_DOR"

#: The raw standalone trace grammar is ``cyc src cl dst sz``.
TRACE_COLUMNS = 5
TRACE_DIALECT = "whitespace"

#: The legacy trace config binds exactly one traffic class.
SINGLE_TRACE_CLASS = 0

#: Attempt-local artifact names.  A run directory is a fresh attempt: this
#: seam refuses to overwrite any of these.
TRACE_FILENAME = "workload.trace"
CONFIG_FILENAME = "booksim.cfg"
EVIDENCE_FILENAME = "mesh-trace-evaluation.json"

#: The exact limitations carried in every persisted document.  These are
#: claims the bridge does NOT make, stated once so a reader cannot mistake
#: diagnostic output for certified evidence.
LIMITATIONS: tuple[str, ...] = (
    "legacy mesh config: topology=mesh, routing=dim_order, n=2; it is not "
    "the compiled bundle's backend projection",
    "not the compiled bundle's VC assignment or route artifact; vc_count "
    "and link width are reported for context only",
    "no route dump comparison: executed routes are not compared with the "
    "compiled route artifact",
    "no ASTRA execution or ASTRA evidence",
    "diagnostic only: exact_fabric_eligible is False and no certified "
    "config identity is claimed",
)


class MeshTraceEvaluationError(ValueError, SemanticError):
    """A request or trace cannot be evaluated by the diagnostic mesh bridge."""


@dataclass(frozen=True)
class MeshTraceEvaluation:
    """One diagnostic mesh-DOR raw-trace evaluation.

    ``stats`` is the normalized runner result as data.  The bridge requires
    at least one of ``completion_time`` or ``latency`` but never invents a
    missing metric.
    """

    request_design_hash: str
    topology: str
    k: int
    vc_count: int | None
    trace_sha256: str
    trace_summary: dict[str, Any]
    qualification: str = QUALIFICATION
    exact_fabric_eligible: bool = False
    stats: dict[str, Any] = field(default_factory=dict)
    config_sha256: str = ""
    output_dir: str = ""
    link_width_bits: int | None = None
    seed: int = 0
    sample_period: int = 0
    limitations: tuple[str, ...] = LIMITATIONS

    def to_dict(self) -> dict[str, Any]:
        """The persisted, JSON-native document for this evaluation."""
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
    """Recursively convert backend results into JSON-native values."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _json_safe(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    # Unknown objects must not leak into the JSON document.
    return str(value)


def _parse_request(request_doc: Any) -> CompileRequestV4:
    """Accept exactly one schema-v4 request document; never migrate."""
    if not isinstance(request_doc, Mapping):
        raise MeshTraceEvaluationError(
            "request_doc must be a JSON object, got "
            f"{type(request_doc).__name__}")
    version = request_doc.get("schema_version")
    if version != 4:
        raise MeshTraceEvaluationError(
            "mesh-DOR trace evaluation requires a schema v4 request, got "
            f"schema_version={version!r}. v3 and v5 documents must be "
            "migrated or down-projected explicitly; this diagnostic seam "
            "never upgrades or downgrades a request implicitly.")
    try:
        return CompileRequestV4.from_dict(dict(request_doc))
    except (TypeError, ValueError) as exc:
        raise MeshTraceEvaluationError(
            f"request_doc is not a valid v4 CompileRequest: {exc}") from exc


def _parse_trace(trace: bytes) -> list[_Packet]:
    """Strictly validate the raw single-class whitespace trace grammar.

    Blank lines and lines beginning with ``#`` or ``%`` are comments.  Every
    other line must have exactly five whitespace columns, integer fields, a
    non-negative timestamp, a positive packet size, and class column ``0``.
    Endpoint bounds are checked later, once the compiled fabric is known.
    """
    if not trace:
        raise MeshTraceEvaluationError("trace is empty")
    try:
        text = trace.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MeshTraceEvaluationError(f"trace is not UTF-8: {exc}") from exc

    packets: list[_Packet] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in ("#", "%"):
            continue
        fields = line.split()
        if len(fields) != TRACE_COLUMNS:
            raise MeshTraceEvaluationError(
                f"trace line {line_no}: expected exactly {TRACE_COLUMNS} "
                f"whitespace columns (cyc src cl dst sz) in the raw "
                f"single-class dialect, got {len(fields)}: {line!r}")
        try:
            timestamp, src, cls, dst, size = (int(item) for item in fields)
        except ValueError as exc:
            raise MeshTraceEvaluationError(
                f"trace line {line_no}: non-integer field: {exc}") from exc
        if cls != SINGLE_TRACE_CLASS:
            raise MeshTraceEvaluationError(
                f"trace line {line_no}: single-class raw traces require "
                f"class column {SINGLE_TRACE_CLASS}, got {cls}; the legacy "
                "mesh config binds one traffic class and cannot execute "
                "multi-class traffic")
        if timestamp < 0:
            raise MeshTraceEvaluationError(
                f"trace line {line_no}: negative timestamp {timestamp}")
        if src < 0 or dst < 0:
            raise MeshTraceEvaluationError(
                f"trace line {line_no}: negative endpoint src={src} dst={dst}")
        if size < 1:
            raise MeshTraceEvaluationError(
                f"trace line {line_no}: non-positive packet size {size}")
        packets.append(_Packet(line_no=line_no, timestamp=timestamp,
                               src=src, cls=cls, dst=dst, size=size))

    if not packets:
        raise MeshTraceEvaluationError(
            "trace has no non-comment data lines (it is empty)")
    return packets


def _validate_endpoint_range(packets: list[_Packet],
                             endpoint_count: int) -> None:
    """Refuse any endpoint outside the compiled attachment universe."""
    for packet in packets:
        if not (0 <= packet.src < endpoint_count) or \
                not (0 <= packet.dst < endpoint_count):
            raise MeshTraceEvaluationError(
                f"trace line {packet.line_no}: endpoint outside "
                f"[0, {endpoint_count}): src={packet.src} dst={packet.dst}; "
                "the compiled attachment defines the valid endpoint range")


def _trace_summary(packets: list[_Packet],
                   endpoint_count: int) -> dict[str, Any]:
    return {
        "packets": len(packets),
        "max_timestamp": max(packet.timestamp for packet in packets),
        "endpoints": endpoint_count,
    }


def _refuse_existing_attempt(run_dir: Path) -> None:
    """A run directory is one attempt; never overwrite its inputs."""
    if run_dir.exists() and not run_dir.is_dir():
        raise MeshTraceEvaluationError(
            f"run_dir {str(run_dir)!r} exists and is not a directory")
    if not run_dir.exists():
        return
    for name in (TRACE_FILENAME, EVIDENCE_FILENAME):
        path = run_dir / name
        if path.exists():
            raise MeshTraceEvaluationError(
                f"run_dir already contains {name!r}; mesh-DOR trace "
                "evaluation requires a fresh attempt directory and will "
                "not overwrite a previous trace or evidence file")
    for path in run_dir.iterdir():
        if path.suffix == ".cfg":
            raise MeshTraceEvaluationError(
                f"run_dir already contains config {path.name!r}; mesh-DOR "
                "trace evaluation requires a fresh attempt directory and "
                "will not overwrite a previous config file")


def _write_new_bytes(path: Path, data: bytes) -> None:
    """Create a new attempt file, refusing to overwrite an existing one."""
    try:
        with open(path, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise MeshTraceEvaluationError(
            f"refusing to overwrite existing attempt file {str(path)!r}; "
            "mesh-DOR trace evaluation requires a fresh run directory") from exc


def _write_new_text(path: Path, text: str) -> None:
    _write_new_bytes(path, text.encode("utf-8"))


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


def _result_mapping(result: Any) -> dict[str, Any]:
    """Normalize a runner result (mapping/dataclass/object) to a mapping."""
    if isinstance(result, Mapping):
        raw = dict(result)
    elif dataclasses.is_dataclass(result) and not isinstance(result, type):
        raw = dataclasses.asdict(result)
    elif callable(getattr(result, "to_dict", None)):
        converted = result.to_dict()
        if not isinstance(converted, Mapping):
            raise MeshTraceEvaluationError(
                "mesh-DOR runner result.to_dict() did not return a mapping")
        raw = dict(converted)
    elif hasattr(result, "stats"):
        raw = {"stats": getattr(result, "stats")}
        for name in ("stderr", "stdout", "reason", "error", "returncode",
                     "exit_status"):
            value = getattr(result, name, None)
            if value is not None:
                raw[name] = value
    else:
        raise MeshTraceEvaluationError(
            "mesh-DOR runner returned an unsupported result type "
            f"{type(result).__name__}; expected a mapping, dataclass, or "
            "object with to_dict()/stats")

    normalized = _json_safe(raw)
    if not isinstance(normalized, dict):
        raise MeshTraceEvaluationError(
            "mesh-DOR runner result did not normalize to an object")
    return normalized


def _select_stats(normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Pick the metric object from a flat or ``{"stats": {...}}`` result."""
    if normalized.get("completion_time") is not None or \
            normalized.get("latency") is not None:
        return dict(normalized)
    nested = normalized.get("stats")
    if isinstance(nested, Mapping) and (
            nested.get("completion_time") is not None
            or nested.get("latency") is not None):
        return dict(nested)
    return dict(normalized)


def _require_metrics(stats: Mapping[str, Any],
                     normalized: Mapping[str, Any]) -> None:
    """Require a completion metric; surface runner diagnostics on refusal."""
    if stats.get("completion_time") is not None or \
            stats.get("latency") is not None:
        return
    details: list[str] = []
    for key in ("stderr", "reason", "error"):
        value = normalized.get(key)
        if value:
            details.append(f"{key}: {value}")
    suffix = ("; " + "; ".join(details)) if details else ""
    raise MeshTraceEvaluationError(
        "BookSim mesh-DOR diagnostic result has neither completion_time nor "
        f"latency{suffix}")


def _require_mesh_intent(request: CompileRequestV4) -> MeshIntent:
    """Require the typed mesh authority before compiling anything."""
    intent = request.topology
    if not isinstance(intent, MeshIntent) or intent.kind != "mesh":
        kind = getattr(intent, "kind", type(intent).__name__)
        raise MeshTraceEvaluationError(
            "mesh-DOR trace evaluation requires a typed mesh topology "
            f"(MeshIntent, kind='mesh'), got kind={kind!r}. The legacy "
            "BookSim mesh-DOR config only represents a k x k nearest-"
            "neighbour mesh.")
    return intent


def _derive_mesh_shape(bundle: Any, request: CompileRequestV4) -> tuple[int, int]:
    """Derive/verify the legacy k x k shape from a typed mesh request."""
    intent = _require_mesh_intent(request)
    k = intent.side_length
    router_count = bundle.topology.router_count
    if k * k != router_count:
        raise MeshTraceEvaluationError(
            f"MeshIntent(side_length={k}) implies a {k}x{k} mesh with "
            f"{k * k} routers, but the compiled bundle has {router_count}; "
            "the diagnostic bridge only supports a square k x k mesh")

    # The legacy trace dialect addresses BookSim router ids directly.  The
    # compiled attachment must therefore use the same ids for every endpoint
    # it seats; otherwise the trace would silently address the wrong node.
    for endpoint in bundle.attachment.endpoints:
        if endpoint.endpoint_id != endpoint.router_id:
            raise MeshTraceEvaluationError(
                "the compiled attachment does not map endpoint ids to the "
                f"same mesh router ids (endpoint {endpoint.endpoint_id} -> "
                f"router {endpoint.router_id}); the legacy trace dialect "
                "addresses router ids directly, so this diagnostic bridge "
                "cannot bind the trace honestly")
    return k, router_count


def evaluate_mesh_dor_trace(
    request_doc: dict,
    trace: bytes,
    *,
    repo_root: Path,
    run_dir: Path,
    booksim_bin: Path | None = None,
    seed: int = 0,
    timeout: int = 600,
    runner=None,
) -> MeshTraceEvaluation:
    """Compile, execute, and persist one diagnostic mesh-DOR trace run.

    ``runner`` is an explicit test seam.  When omitted, the legacy
    :func:`veritx_dse.simulation.booksim.run_booksim` is used with a silent
    :class:`~veritx_dse.core.logging.Ctx`.  An injected runner is called as::

        runner(Ctx(verbosity=0), config, repo_root=repo_root, timeout=timeout)

    ``booksim_bin`` is accepted for call-site symmetry with the certified
    raw-trace seam.  The legacy ``run_booksim`` resolves its own binary from
    ``repo_root``; callers that need a specific binary inject ``runner``.
    """
    if not isinstance(trace, (bytes, bytearray)):
        raise MeshTraceEvaluationError(
            f"trace must be bytes, got {type(trace).__name__}")
    trace = bytes(trace)
    repo_root = Path(repo_root)
    run_dir = Path(run_dir)

    request = _parse_request(request_doc)
    _require_mesh_intent(request)
    packets = _parse_trace(trace)
    _refuse_existing_attempt(run_dir)

    try:
        compilation = FabricCompiler().compile(request)
    except Exception as exc:                       # noqa: BLE001
        raise MeshTraceEvaluationError(
            f"fabric compilation failed before a verdict: {exc}") from exc

    if compilation.status != "COMPILED" or compilation.bundle is None:
        raise MeshTraceEvaluationError(
            "fabric compilation did not produce a bundle: "
            f"status={compilation.status}, error={compilation.error!r}")

    bundle = compilation.bundle
    k, router_count = _derive_mesh_shape(bundle, request)
    endpoint_count = bundle.attachment.endpoint_count
    _validate_endpoint_range(packets, endpoint_count)
    if endpoint_count > router_count:
        raise MeshTraceEvaluationError(
            f"compiled attachment has {endpoint_count} endpoints but the "
            f"{k}x{k} mesh has only {router_count} routers; the legacy trace "
            "dialect cannot address more endpoints than mesh nodes")

    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / TRACE_FILENAME
    _write_new_bytes(trace_path, trace)

    try:
        trace_stats = detect_trace_stats(str(trace_path))
    except TraceError as exc:
        raise MeshTraceEvaluationError(
            f"cannot inspect the persisted workload trace: {exc}") from exc
    sample_period = max(200, trace_stats.max_cycle + 1000)

    topo = Topology(
        name=f"mesh_{k}x{k}",
        backend="mesh",
        routing="dim_order",
        params={"k": k, "n": 2},
    )
    config = build_config(
        topo,
        str(trace_path),
        sample_period=sample_period,
        seed=seed,
    )
    config_sha256 = hashlib.sha256(config.encode("utf-8")).hexdigest()
    _write_new_text(run_dir / CONFIG_FILENAME, config)

    if runner is None:
        try:
            result = run_booksim(
                Ctx(verbosity=0), config,
                repo_root=repo_root, timeout=timeout)
        except Exception as exc:                   # noqa: BLE001
            detail = getattr(exc, "stderr", "") or ""
            reason = getattr(exc, "message", "") or str(exc)
            suffix = f"; stderr: {detail}" if detail else ""
            raise MeshTraceEvaluationError(
                f"BookSim mesh-DOR diagnostic run failed: {reason}{suffix}"
            ) from exc
    else:
        try:
            result = runner(
                Ctx(verbosity=0), config,
                repo_root=repo_root, timeout=timeout)
        except BookSimError as exc:
            detail = getattr(exc, "stderr", "") or ""
            reason = getattr(exc, "message", "") or str(exc)
            suffix = f"; stderr: {detail}" if detail else ""
            raise MeshTraceEvaluationError(
                f"BookSim mesh-DOR diagnostic runner failed: {reason}{suffix}"
            ) from exc

    if result is None:
        raise MeshTraceEvaluationError(
            "mesh-DOR runner returned no evidence")

    normalized = _result_mapping(result)
    stats = _select_stats(normalized)
    _require_metrics(stats, normalized)

    evaluation = MeshTraceEvaluation(
        request_design_hash=request.design_hash(),
        topology=topo.name,
        k=k,
        vc_count=getattr(bundle.vc_assignment, "vc_count", None),
        trace_sha256=hashlib.sha256(trace).hexdigest(),
        trace_summary=_trace_summary(packets, endpoint_count),
        qualification=QUALIFICATION,
        exact_fabric_eligible=False,
        stats=stats,
        config_sha256=config_sha256,
        output_dir=str(run_dir),
        link_width_bits=getattr(bundle.packet_format, "flit_width_bits", None),
        seed=seed,
        sample_period=sample_period,
        limitations=LIMITATIONS,
    )
    _write_json_atomic(run_dir / EVIDENCE_FILENAME, evaluation.to_dict())
    return evaluation


__all__ = [
    "CONFIG_FILENAME",
    "EVIDENCE_FILENAME",
    "LIMITATIONS",
    "MeshTraceEvaluation",
    "MeshTraceEvaluationError",
    "QUALIFICATION",
    "SINGLE_TRACE_CLASS",
    "TRACE_COLUMNS",
    "TRACE_DIALECT",
    "TRACE_FILENAME",
    "evaluate_mesh_dor_trace",
]
