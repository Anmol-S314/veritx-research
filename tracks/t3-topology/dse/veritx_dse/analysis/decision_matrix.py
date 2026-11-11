"""Decision-accuracy matrix harness.

Fabric selection asks a question that absolute latency numbers cannot answer:
*does the ranking change when the model changes?*  This module records one
result per ``(topology, trace, config)`` case, ranks the evaluated topologies
inside each ``(trace, config)`` group, and reports whether the winner is stable
across traces.

The harness is deliberately pure: it never imports or runs a simulator.  A
caller supplies an ``evaluator(case) -> dict`` adapter around whichever
evaluation path it already trusts (legacy ``evaluate booksim`` /
``evaluate anynet`` or the canonical catalog).  The adapter is the only place
that knows about backends; this module only adjudicates the returned numbers.

Ordering contract
-----------------
``run_matrix`` returns results in **input case order**.  That keeps a run
traceable back to the case list a caller supplied, including the position of a
failure.  Ranking is a separate, sorted view: :func:`rankings` sorts groups by
``(trace, config)`` and topologies by ``(completion_cycles, topology)`` so two
runs over the same evidence produce byte-identical reports.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import SemanticError

__all__ = [
    "DecisionMatrixError",
    "MatrixCase",
    "MatrixResult",
    "Ranking",
    "SCHEMA_VERSION",
    "RESULT_STATUSES",
    "STATUS_EVALUATED",
    "STATUS_UNSUPPORTED",
    "STATUS_FAILED",
    "EVALUATED",
    "UNSUPPORTED",
    "FAILED",
    "run_matrix",
    "rankings",
    "stability",
    "to_dict",
    "from_dict",
    "main",
]

SCHEMA_VERSION = 1

STATUS_EVALUATED = "EVALUATED"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_FAILED = "FAILED"
RESULT_STATUSES = frozenset({
    STATUS_EVALUATED, STATUS_UNSUPPORTED, STATUS_FAILED,
})

# Conventional short aliases for callers that mirror the backend evaluator.
EVALUATED = STATUS_EVALUATED
UNSUPPORTED = STATUS_UNSUPPORTED
FAILED = STATUS_FAILED

CASE_FIELDS = frozenset({
    "case_id", "topology", "trace", "config", "metadata",
})
RESULT_FIELDS = frozenset({
    "case_id", "topology", "trace", "config", "status",
    "completion_cycles", "p50", "p95", "p99", "reason", "metadata",
})
EVALUATOR_RESULT_FIELDS = frozenset({
    "status", "completion_cycles", "p50", "p95", "p99", "reason",
    "metadata",
})
DOCUMENT_FIELDS = frozenset({"schema_version", "results"})
CLI_DOCUMENT_FIELDS = frozenset({"cases", "results"})

_CASE_REQUIRED = frozenset({"case_id", "topology", "trace"})
_RESULT_REQUIRED = frozenset({"case_id", "topology", "trace", "status"})


class DecisionMatrixError(ValueError, SemanticError):
    """A matrix input, evaluator result, or persisted document is invalid.

    Inherits both ``ValueError`` (ordinary Python argument error) and the
    repository's typed ``SemanticError`` refusal, so callers may catch either
    without this module leaking an untyped exception.
    """

    code = "DECISION_MATRIX_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _require_text(value: Any, field_name: str, *,
                  allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DecisionMatrixError(
            f"{field_name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise DecisionMatrixError(f"{field_name} must be a non-empty string")
    return value


def _require_metadata(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DecisionMatrixError(
            f"{field_name} must be a dict, got {type(value).__name__}")
    return _json_safe_copy(value, field_name)


def _json_safe_copy(value: Any, field_name: str,
                    _seen: set[int] | None = None) -> Any:
    """Validate the JSON data model and return an independent copy.

    Tuples are accepted as JSON arrays and normalized to lists.  Non-string
    object keys, non-finite floats, cycles, and non-JSON values are refused
    rather than coerced: a persisted matrix must round-trip exactly.
    """
    if _seen is None:
        _seen = set()
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DecisionMatrixError(
                f"{field_name} contains a non-finite float {value!r}")
        return value
    if isinstance(value, dict):
        identity = id(value)
        if identity in _seen:
            raise DecisionMatrixError(f"{field_name} contains a cycle")
        _seen.add(identity)
        try:
            out: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DecisionMatrixError(
                        f"{field_name} has a non-string key {key!r}")
                out[key] = _json_safe_copy(item, field_name, _seen)
            return out
        finally:
            _seen.discard(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in _seen:
            raise DecisionMatrixError(f"{field_name} contains a cycle")
        _seen.add(identity)
        try:
            return [_json_safe_copy(item, field_name, _seen)
                    for item in value]
        finally:
            _seen.discard(identity)
    raise DecisionMatrixError(
        f"{field_name} contains a non-JSON value of type "
        f"{type(value).__name__}")


def _optional_metric(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionMatrixError(
            f"{field_name} must be a number or None, got "
            f"{type(value).__name__}")
    try:
        number = float(value)
    except OverflowError:
        raise DecisionMatrixError(
            f"{field_name} is outside the finite float domain") from None
    if not math.isfinite(number):
        raise DecisionMatrixError(
            f"{field_name} must be finite, got {number!r}")
    if number < 0:
        raise DecisionMatrixError(
            f"{field_name} must be non-negative, got {number!r}")
    return number


def _tolerance(value: Any) -> float:
    """Validate the indifference band used when declaring a top-rank tie.

    A decision matrix must not turn a 10-cycle difference on an 8,000-cycle
    run into a "flip".  The tolerance is an absolute cycle count; callers
    that need a relative band can compute it before calling.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionMatrixError(
            f"tolerance must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise DecisionMatrixError(
            f"tolerance must be finite and non-negative, got {value!r}")
    return number


def _unknown_keys(doc: Mapping[str, Any], allowed: frozenset[str],
                  where: str) -> None:
    unknown = sorted(set(doc) - allowed, key=str)
    if unknown:
        raise DecisionMatrixError(f"{where} has unknown keys: {unknown!r}")


def _missing_keys(doc: Mapping[str, Any], required: frozenset[str],
                  where: str) -> None:
    missing = sorted(required - set(doc))
    if missing:
        raise DecisionMatrixError(f"{where} is missing keys: {missing!r}")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatrixCase:
    """One cell of the matrix: a topology evaluated on a trace under a config.

    ``case_id`` is non-empty and must be unique across a matrix; uniqueness is
    enforced by :func:`run_matrix` and :func:`from_dict`, which are the two
    entry points that see the whole set.  ``config`` is a free-form label used
    to keep matched-config comparisons together (it may be empty).
    ``metadata`` is validated as a JSON-safe object and defensively copied.
    """

    case_id: str
    topology: str
    trace: str
    config: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        case_id = _require_text(self.case_id, "case_id")
        topology = _require_text(self.topology, "topology")
        trace = _require_text(self.trace, "trace")
        config = _require_text(self.config, "config", allow_empty=True)
        metadata = _require_metadata(
            self.metadata, f"case {case_id!r} metadata")
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "topology", topology)
        object.__setattr__(self, "trace", trace)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "topology": self.topology,
            "trace": self.trace,
            "config": self.config,
            "metadata": _json_safe_copy(self.metadata, "metadata"),
        }

    @classmethod
    def from_dict(cls, doc: Any) -> MatrixCase:
        if not isinstance(doc, dict):
            raise DecisionMatrixError(
                f"matrix case must be an object, got {type(doc).__name__}")
        _unknown_keys(doc, CASE_FIELDS, "matrix case")
        _missing_keys(doc, _CASE_REQUIRED, "matrix case")
        return cls(
            case_id=doc["case_id"],
            topology=doc["topology"],
            trace=doc["trace"],
            config=doc.get("config", ""),
            metadata=doc.get("metadata", {}),
        )


@dataclass(frozen=True)
class MatrixResult:
    """One adjudicated matrix cell.

    ``EVALUATED`` requires ``completion_cycles`` and carries no reason.
    ``UNSUPPORTED`` and ``FAILED`` carry a non-empty reason and never
    participate in a ranking.  Metrics are validated as finite, non-negative
    numbers when present.
    """

    case_id: str
    topology: str
    trace: str
    config: str
    status: str
    completion_cycles: float | None = None
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        case_id = _require_text(self.case_id, "case_id")
        topology = _require_text(self.topology, "topology")
        trace = _require_text(self.trace, "trace")
        config = _require_text(self.config, "config", allow_empty=True)

        status = self.status
        if not isinstance(status, str) or status not in RESULT_STATUSES:
            raise DecisionMatrixError(
                f"status must be one of {sorted(RESULT_STATUSES)}, got "
                f"{status!r}")

        completion = _optional_metric(
            self.completion_cycles, "completion_cycles")
        p50 = _optional_metric(self.p50, "p50")
        p95 = _optional_metric(self.p95, "p95")
        p99 = _optional_metric(self.p99, "p99")

        reason = self.reason
        if reason is not None and not isinstance(reason, str):
            raise DecisionMatrixError(
                f"reason must be a string or None, got "
                f"{type(reason).__name__}")
        if isinstance(reason, str) and not reason.strip():
            reason = None

        if status == STATUS_EVALUATED:
            if completion is None:
                raise DecisionMatrixError(
                    "EVALUATED result requires completion_cycles")
            if reason is not None:
                raise DecisionMatrixError(
                    "EVALUATED result must not carry a reason")
        else:
            if reason is None:
                raise DecisionMatrixError(
                    f"{status} result requires a non-empty reason")

        metadata = _require_metadata(
            self.metadata, f"result {case_id!r} metadata")
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "topology", topology)
        object.__setattr__(self, "trace", trace)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "completion_cycles", completion)
        object.__setattr__(self, "p50", p50)
        object.__setattr__(self, "p95", p95)
        object.__setattr__(self, "p99", p99)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "topology": self.topology,
            "trace": self.trace,
            "config": self.config,
            "status": self.status,
            "completion_cycles": self.completion_cycles,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "reason": self.reason,
            "metadata": _json_safe_copy(self.metadata, "metadata"),
        }

    @classmethod
    def from_dict(cls, doc: Any) -> MatrixResult:
        if not isinstance(doc, dict):
            raise DecisionMatrixError(
                f"matrix result must be an object, got {type(doc).__name__}")
        _unknown_keys(doc, RESULT_FIELDS, "matrix result")
        _missing_keys(doc, _RESULT_REQUIRED, "matrix result")
        return cls(
            case_id=doc["case_id"],
            topology=doc["topology"],
            trace=doc["trace"],
            config=doc.get("config", ""),
            status=doc["status"],
            completion_cycles=doc.get("completion_cycles"),
            p50=doc.get("p50"),
            p95=doc.get("p95"),
            p99=doc.get("p99"),
            reason=doc.get("reason"),
            metadata=doc.get("metadata", {}),
        )


@dataclass(frozen=True)
class Ranking:
    """The ranked view of one ``(trace, config)`` group.

    ``order`` contains every evaluated topology, best first, with equal
    completion times ordered by topology name (standard competition ranking:
    two firsts are followed by a third, not a second).  ``winner`` is ``None``
    when the top rank is shared; ``tie`` records that top-rank tie.  Topologies
    that were ``UNSUPPORTED`` or ``FAILED`` are listed in ``missing`` and are
    never silently ranked.
    """

    trace: str
    config: str
    order: tuple[str, ...]
    winner: str | None
    tie: bool
    missing: tuple[str, ...]
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace": self.trace,
            "config": self.config,
            "order": list(self.order),
            "winner": self.winner,
            "tie": self.tie,
            "missing": list(self.missing),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _materialize_cases(cases: Iterable[MatrixCase]) -> tuple[MatrixCase, ...]:
    if isinstance(cases, MatrixCase):
        raise DecisionMatrixError(
            "cases must be an iterable of MatrixCase, not a single case")
    try:
        materialized = tuple(cases)
    except TypeError:
        raise DecisionMatrixError(
            "cases must be an iterable of MatrixCase") from None
    seen: set[str] = set()
    for index, case in enumerate(materialized):
        if not isinstance(case, MatrixCase):
            raise DecisionMatrixError(
                f"cases[{index}] must be a MatrixCase, got "
                f"{type(case).__name__}")
        if case.case_id in seen:
            raise DecisionMatrixError(
                f"duplicate case_id {case.case_id!r} in matrix")
        seen.add(case.case_id)
    return materialized


def _materialize_results(
        results: Iterable[MatrixResult]) -> tuple[MatrixResult, ...]:
    if isinstance(results, MatrixResult):
        raise DecisionMatrixError(
            "results must be an iterable of MatrixResult, not a single "
            "result")
    try:
        materialized = tuple(results)
    except TypeError:
        raise DecisionMatrixError(
            "results must be an iterable of MatrixResult") from None
    seen: set[str] = set()
    for index, result in enumerate(materialized):
        if not isinstance(result, MatrixResult):
            raise DecisionMatrixError(
                f"results[{index}] must be a MatrixResult, got "
                f"{type(result).__name__}")
        if result.case_id in seen:
            raise DecisionMatrixError(
                f"duplicate case_id {result.case_id!r} in results")
        seen.add(result.case_id)
    return materialized


def _result_from_evaluator(case: MatrixCase,
                           raw: Any) -> MatrixResult:
    if not isinstance(raw, Mapping):
        raise DecisionMatrixError(
            f"evaluator result for case {case.case_id!r} must be a mapping, "
            f"got {type(raw).__name__}")
    data = dict(raw)
    _unknown_keys(data, EVALUATOR_RESULT_FIELDS,
                  f"evaluator result for case {case.case_id!r}")
    if "status" not in data:
        raise DecisionMatrixError(
            f"evaluator result for case {case.case_id!r} is missing "
            f"'status'")
    metadata = data.get("metadata", {})
    if metadata is None:
        metadata = {}
    try:
        return MatrixResult(
            case_id=case.case_id,
            topology=case.topology,
            trace=case.trace,
            config=case.config,
            status=data["status"],
            completion_cycles=data.get("completion_cycles"),
            p50=data.get("p50"),
            p95=data.get("p95"),
            p99=data.get("p99"),
            reason=data.get("reason"),
            metadata=metadata,
        )
    except DecisionMatrixError as exc:
        raise DecisionMatrixError(
            f"evaluator result for case {case.case_id!r} is invalid: "
            f"{exc}") from exc


def run_matrix(cases: Iterable[MatrixCase],
               evaluator: Callable[[MatrixCase], Mapping[str, Any]]
               ) -> tuple[MatrixResult, ...]:
    """Evaluate every case and return results in input case order.

    ``evaluator`` receives a :class:`MatrixCase` and returns a mapping with a
    ``status`` plus the status-appropriate fields.  Unknown keys are refused,
    and so are missing required fields.  If the evaluator itself raises, that
    case becomes ``FAILED`` with the exception type and message as its reason;
    one broken backend does not destroy the rest of the matrix.

    Deliberately, validation errors in the *returned mapping* are raised, not
    converted to ``FAILED``: a malformed adapter is a harness bug, while a
    backend exception is a legitimate per-case outcome.
    """
    if not callable(evaluator):
        raise DecisionMatrixError("evaluator must be callable")
    materialized = _materialize_cases(cases)
    results: list[MatrixResult] = []
    for case in materialized:
        try:
            raw = evaluator(case)
        except Exception as exc:  # noqa: BLE001 - per-case backend failure
            error_type = type(exc).__name__
            message = str(exc).strip()
            reason = f"{error_type}: {message}" if message else error_type
            results.append(MatrixResult(
                case_id=case.case_id,
                topology=case.topology,
                trace=case.trace,
                config=case.config,
                status=STATUS_FAILED,
                reason=reason,
                metadata={"error_type": error_type},
            ))
            continue
        results.append(_result_from_evaluator(case, raw))
    return tuple(results)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _evaluated_cycles(result: MatrixResult) -> float:
    cycles = result.completion_cycles
    if cycles is None:  # pragma: no cover - MatrixResult validation guards
        raise DecisionMatrixError(
            f"EVALUATED result {result.case_id!r} has no completion_cycles")
    return cycles


def _missing_reason(entries: Sequence[MatrixResult]) -> str:
    parts = []
    for result in sorted(entries, key=lambda item: item.topology):
        parts.append(
            f"{result.topology} ({result.status}: {result.reason})")
    return "missing: " + "; ".join(parts)


def rankings(results: Iterable[MatrixResult], *,
             tolerance: float = 0.0,
             relative_tolerance: float = 0.0) -> tuple[Ranking, ...]:
    """Rank evaluated topologies inside each ``(trace, config)`` group.

    Only ``EVALUATED`` results participate.  ``UNSUPPORTED``/``FAILED``
    topologies are excluded from ``order`` and reported in ``missing``.  Groups
    are returned sorted by ``(trace, config)``; within a group, order is
    ``(completion_cycles, topology)``.  A topology may appear at most once per
    group: two results for the same cell are ambiguous evidence and are
    refused.

    ``tolerance`` is an absolute cycle band and ``relative_tolerance`` is a
    fraction of the best result (``0.015`` = 1.5%).  The effective band for a
    group is ``max(tolerance, relative_tolerance * best)``.  A topology within
    that band shares rank 1 and makes the top a tie; this is how a 10-cycle
    difference on an 8,000-cycle run, or a 1% difference on a 32,000-cycle
    run, stays a tie instead of becoming a fabricated winner.  The defaults
    are strict equality.
    """
    absolute = _tolerance(tolerance)
    relative = _tolerance(relative_tolerance)
    materialized = _materialize_results(results)
    groups: dict[tuple[str, str], list[MatrixResult]] = {}
    for result in materialized:
        groups.setdefault((result.trace, result.config), []).append(result)

    ranked: list[Ranking] = []
    for trace, config in sorted(groups):
        group = groups[(trace, config)]
        by_topology: dict[str, MatrixResult] = {}
        for result in group:
            if result.topology in by_topology:
                raise DecisionMatrixError(
                    f"duplicate topology {result.topology!r} in ranking "
                    f"group (trace={trace!r}, config={config!r})")
            by_topology[result.topology] = result

        evaluated = [result for result in group
                     if result.status == STATUS_EVALUATED]
        missing_results = [result for result in group
                           if result.status != STATUS_EVALUATED]
        missing = tuple(sorted(result.topology for result in missing_results))

        if evaluated:
            ordered = sorted(
                evaluated,
                key=lambda result: (_evaluated_cycles(result),
                                    result.topology))
            order = tuple(result.topology for result in ordered)
            best = _evaluated_cycles(ordered[0])
            group_band = max(absolute, relative * best)
            top = tuple(result.topology for result in ordered
                        if _evaluated_cycles(result) <= best + group_band)
            tie = len(top) > 1
            winner = None if tie else top[0]
        else:
            order = ()
            top = ()
            tie = False
            winner = None

        reason_parts: list[str] = []
        if not evaluated:
            reason_parts.append("no evaluated results")
        elif tie:
            band_note = (f" within {group_band:g} cycles"
                         if group_band > 0 else "")
            reason_parts.append(
                f"tie at rank 1{band_note}: {', '.join(top)}")
        if missing_results:
            reason_parts.append(_missing_reason(missing_results))
        reason = "; ".join(reason_parts) if reason_parts else None

        ranked.append(Ranking(
            trace=trace,
            config=config,
            order=order,
            winner=winner,
            tie=tie,
            missing=missing,
            reason=reason,
        ))
    return tuple(ranked)


def _top_tied_topologies(group: Sequence[MatrixResult], *,
                         tolerance: float = 0.0,
                         relative_tolerance: float = 0.0) -> list[str]:
    absolute = _tolerance(tolerance)
    relative = _tolerance(relative_tolerance)
    evaluated = [result for result in group
                 if result.status == STATUS_EVALUATED]
    if not evaluated:
        return []
    best = min(_evaluated_cycles(result) for result in evaluated)
    band = max(absolute, relative * best)
    return sorted(result.topology for result in evaluated
                  if _evaluated_cycles(result) <= best + band)


def stability(results: Iterable[MatrixResult], *,
              tolerance: float = 0.0,
              relative_tolerance: float = 0.0) -> dict[str, Any]:
    """Compare winners across traces for each config.

    ``winner_by_trace`` is nested by config: ``{config: {trace: winner}}``.
    Nesting is required because one trace may legitimately be evaluated under
    several configs; a flat ``trace -> winner`` map would silently overwrite
    one of them.

    ``flips`` compares consecutive *decisive* traces (unique winner present)
    in trace-name order within a config, so a tie between two decisive traces
    is reported in ``ties`` instead of manufacturing a flip.  ``ties`` reports
    every top-rank tie, and ``incomplete`` reports every trace with at least
    one ``UNSUPPORTED``/``FAILED`` topology.  ``stable`` is true only when no
    config has a flip, a tie, or incomplete evidence: a missing topology means
    the ranking cannot be certified, even if the observed winner did not
    change.

    ``tolerance`` and ``relative_tolerance`` are the same bands as
    :func:`rankings`; use them when a difference below the model's resolution
    should be a tie.
    """
    band = _tolerance(tolerance)
    relative = _tolerance(relative_tolerance)
    materialized = _materialize_results(results)
    if not materialized:
        return {
            "stable": False,
            "winner_by_trace": {},
            "flips": (),
            "ties": (),
            "incomplete": (),
            "tolerance": band,
            "relative_tolerance": relative,
        }

    rank_rows = rankings(materialized, tolerance=tolerance,
                         relative_tolerance=relative_tolerance)
    by_config: dict[str, dict[str, Ranking]] = {}
    for row in rank_rows:
        by_config.setdefault(row.config, {})[row.trace] = row

    evaluated_by_group: dict[tuple[str, str], list[MatrixResult]] = {}
    for result in materialized:
        if result.status == STATUS_EVALUATED:
            evaluated_by_group.setdefault(
                (result.trace, result.config), []).append(result)

    winner_by_trace: dict[str, dict[str, str | None]] = {}
    flips: list[dict[str, Any]] = []
    ties: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    config_stable: dict[str, bool] = {}

    for config in sorted(by_config):
        trace_rows = by_config[config]
        traces = sorted(trace_rows)
        winner_by_trace[config] = {
            trace: trace_rows[trace].winner for trace in traces
        }

        previous_trace: str | None = None
        previous_winner: str | None = None
        for trace in traces:
            row = trace_rows[trace]
            if row.winner is not None:
                if (previous_winner is not None
                        and previous_winner != row.winner):
                    flips.append({
                        "config": config,
                        "from_trace": previous_trace,
                        "to_trace": trace,
                        "from_winner": previous_winner,
                        "to_winner": row.winner,
                    })
                previous_trace = trace
                previous_winner = row.winner

            if row.tie:
                ties.append({
                    "config": config,
                    "trace": trace,
                    "topologies": _top_tied_topologies(
                        evaluated_by_group.get((trace, config), []),
                        tolerance=tolerance,
                        relative_tolerance=relative_tolerance),
                    "reason": row.reason,
                })
            if row.missing:
                incomplete.append({
                    "config": config,
                    "trace": trace,
                    "missing": list(row.missing),
                    "reason": row.reason,
                })

        config_stable[config] = not any(
            entry["config"] == config for entry in flips) and not any(
            entry["config"] == config for entry in ties) and not any(
            entry["config"] == config for entry in incomplete)

    return {
        "stable": bool(config_stable) and all(config_stable.values()),
        "winner_by_trace": winner_by_trace,
        "flips": tuple(flips),
        "ties": tuple(ties),
        "incomplete": tuple(incomplete),
        "tolerance": band,
        "relative_tolerance": relative,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def to_dict(results: Iterable[MatrixResult]) -> dict[str, Any]:
    """Serialize results as ``{"schema_version": 1, "results": [...]}``.

    Result order is preserved.  ``from_dict`` refuses unknown keys at both the
    document and result level, so a persisted matrix cannot acquire fields that
    this version did not adjudicate.
    """
    materialized = _materialize_results(results)
    return {
        "schema_version": SCHEMA_VERSION,
        "results": [result.to_dict() for result in materialized],
    }


def from_dict(doc: Any) -> tuple[MatrixResult, ...]:
    """Parse a document produced by :func:`to_dict` (strict closed shape)."""
    if not isinstance(doc, dict):
        raise DecisionMatrixError(
            f"matrix document must be an object, got {type(doc).__name__}")
    _unknown_keys(doc, DOCUMENT_FIELDS, "matrix document")
    _missing_keys(doc, DOCUMENT_FIELDS, "matrix document")
    version = doc["schema_version"]
    if (not isinstance(version, int) or isinstance(version, bool)
            or version != SCHEMA_VERSION):
        raise DecisionMatrixError(
            f"matrix document schema_version {version!r} is not the "
            f"supported v{SCHEMA_VERSION}")
    raw_results = doc["results"]
    if not isinstance(raw_results, list):
        raise DecisionMatrixError(
            f"matrix document results must be a list, got "
            f"{type(raw_results).__name__}")

    results: list[MatrixResult] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_results):
        try:
            result = MatrixResult.from_dict(raw)
        except DecisionMatrixError as exc:
            raise DecisionMatrixError(
                f"results[{index}] is invalid: {exc}") from exc
        if result.case_id in seen:
            raise DecisionMatrixError(
                f"duplicate case_id {result.case_id!r} in matrix document")
        seen.add(result.case_id)
        results.append(result)
    return tuple(results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cli_cases(raw: Any) -> tuple[MatrixCase, ...]:
    if not isinstance(raw, list):
        raise DecisionMatrixError(
            f"'cases' must be a list, got {type(raw).__name__}")
    cases: list[MatrixCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        try:
            case = MatrixCase.from_dict(item)
        except DecisionMatrixError as exc:
            raise DecisionMatrixError(
                f"cases[{index}] is invalid: {exc}") from exc
        if case.case_id in seen:
            raise DecisionMatrixError(
                f"duplicate case_id {case.case_id!r} in 'cases'")
        seen.add(case.case_id)
        cases.append(case)
    return tuple(cases)


def _parse_cli_results(raw: Any) -> tuple[MatrixResult, ...]:
    if not isinstance(raw, list):
        raise DecisionMatrixError(
            f"'results' must be a list, got {type(raw).__name__}")
    results: list[MatrixResult] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        try:
            result = MatrixResult.from_dict(item)
        except DecisionMatrixError as exc:
            raise DecisionMatrixError(
                f"results[{index}] is invalid: {exc}") from exc
        if result.case_id in seen:
            raise DecisionMatrixError(
                f"duplicate case_id {result.case_id!r} in 'results'")
        seen.add(result.case_id)
        results.append(result)
    return tuple(results)


def main(argv: Sequence[str] | None = None) -> int:
    """Offline report CLI over precomputed results.

    The document is ``{"cases": [...], "results": [...]}``.  This command never
    invokes a simulator; it validates that every case has exactly one result,
    then prints ``{"rankings": [...], "stability": {...}}``.  Use ``-`` (the
    default) to read stdin.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="veritx-decision-matrix",
        description=(
            "Rank precomputed decision-matrix results and report winner "
            "stability. This command does not run simulators."),
    )
    parser.add_argument(
        "document", nargs="?", default="-",
        help="JSON document with 'cases' and precomputed 'results' "
             "('-' reads stdin)")
    parser.add_argument(
        "--tolerance", type=float, default=0.0,
        help="Absolute cycle band within which the top rank is a tie "
             "(default: 0, strict equality)")
    parser.add_argument(
        "--relative-tolerance", type=float, default=0.0,
        help="Relative band as a fraction of the best result, e.g. 0.015 "
             "for 1.5%% (default: 0)")
    args = parser.parse_args(argv)
    try:
        band = _tolerance(args.tolerance)
        relative = _tolerance(args.relative_tolerance)
    except DecisionMatrixError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True),
              file=sys.stderr)
        return 2

    try:
        if args.document == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.document).read_text(encoding="utf-8")
        doc = json.loads(text)
        if not isinstance(doc, dict):
            raise DecisionMatrixError(
                f"CLI document must be an object, got "
                f"{type(doc).__name__}")
        _unknown_keys(doc, CLI_DOCUMENT_FIELDS, "CLI document")
        _missing_keys(doc, CLI_DOCUMENT_FIELDS, "CLI document")

        cases = _parse_cli_cases(doc["cases"])
        results = _parse_cli_results(doc["results"])

        case_ids = {case.case_id for case in cases}
        result_ids = {result.case_id for result in results}
        unknown = sorted(result_ids - case_ids)
        if unknown:
            raise DecisionMatrixError(
                f"results contain unknown case_ids: {unknown!r}")
        missing = sorted(case_ids - result_ids)
        if missing:
            raise DecisionMatrixError(
                f"cases have no result: {missing!r}")

        cases_by_id = {case.case_id: case for case in cases}
        for result in results:
            case = cases_by_id[result.case_id]
            identity = (result.topology, result.trace, result.config)
            expected = (case.topology, case.trace, case.config)
            if identity != expected:
                raise DecisionMatrixError(
                    f"result {result.case_id!r} identity {identity!r} does "
                    f"not match case identity {expected!r}")

        payload = {
            "rankings": [
                row.to_dict() for row in rankings(
                    results, tolerance=band, relative_tolerance=relative)
            ],
            "stability": stability(
                results, tolerance=band, relative_tolerance=relative),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (DecisionMatrixError, OSError, UnicodeError,
            json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True),
              file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
