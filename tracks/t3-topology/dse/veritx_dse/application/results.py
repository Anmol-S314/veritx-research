"""veritx_dse.application.results — verified result loading (Wave C.1).

Scientific consumers must NEVER use ``store.get("result", ...)``
directly: the persisted summary layer is evidence-bearing, so every
field is re-derived from its authorities on load:

    result -> experiment -> plan -> attempt -> EvidenceRef
           -> authenticated Wave-B evidence -> metric registry

Anything that cannot be re-derived refuses with EVIDENCE_INVALID.
``store.get()`` remains for inspection/internal storage access only.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .errors import ControlPlaneError, ErrorCode
from .resources import check_envelope


def loss_digest_of(loss: list[dict[str, Any]]) -> str:
    """Canonical digest over dimension-sorted semantic loss rows."""
    from veritx_dse.core.spec import canonical_json
    ordered = sorted((dict(r) for r in loss),
                     key=lambda r: r.get("dimension", ""))
    return hashlib.sha256(canonical_json(ordered).encode()).hexdigest()


def _linked(store: Any, kind: str, resource_id: Any) -> dict[str, Any]:
    if not isinstance(resource_id, str) or not resource_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result links to invalid {kind} id {resource_id!r}",
            operation="verify_result")
    try:
        return store.get(kind, resource_id)
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result links to missing {kind} {resource_id!r}: "
            f"{exc.message}",
            operation="verify_result",
            resource_id=resource_id) from exc


def _require_equal(what: str, actual: Any, expected: Any,
                   resource_id: str) -> None:
    if actual != expected:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result field {what!r} does not match its authority "
            f"({actual!r} != {expected!r})",
            operation="verify_result", resource_id=resource_id)


def load_verified_result(store: Any, result_id: str, *,
                         expected_experiment_id: str | None = None
                         ) -> dict[str, Any]:
    """Load a result only if its full chain re-derives consistently.

    Checks, in order: envelope; experiment link (and the expected
    experiment when reusing through a link); plan/attempt/design/
    workload links; attempt success + evidence-ref agreement; Wave-B
    evidence digest authentication; every scientific field against
    plan/experiment/evidence/registry derivations. Returns the stored
    mapping on success.
    """
    from veritx_dse.backend.evidence import EvidenceRef, read_verified_evidence
    result = store.get("result", result_id)
    check_envelope(result, "result")
    resource_id = result.get("resource_id", result_id)
    experiment = _linked(store, "experiment", result.get("experiment_id"))
    if expected_experiment_id is not None and \
            experiment.get("resource_id") != expected_experiment_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {resource_id} belongs to experiment "
            f"{experiment.get('resource_id')}, not the requested "
            f"{expected_experiment_id}: refusing transplanted reuse",
            operation="verify_result", resource_id=resource_id)
    plan = _linked(store, "plan", experiment.get("plan_id"))
    attempt = _linked(store, "attempt", result.get("attempt_id"))
    _require_equal("attempt.experiment_id",
                   attempt.get("experiment_id"),
                   experiment.get("resource_id"), resource_id)
    _require_equal("attempt.status", attempt.get("status"), "SUCCEEDED",
                   resource_id)
    _require_equal("attempt.evidence_ref", attempt.get("evidence_ref"),
                   result.get("evidence_ref"), resource_id)
    design = _linked(store, "design", plan.get("design_id"))
    workload = _linked(store, "workload", plan.get("workload_id"))
    for key in ("experiment_id", "attempt_id", "plan_id", "design_id",
                "workload_id"):
        _require_equal(key, result.get(key),
                       {"experiment_id": experiment.get("resource_id"),
                        "attempt_id": attempt.get("resource_id"),
                        "plan_id": plan.get("resource_id"),
                        "design_id": design.get("resource_id"),
                        "workload_id": workload.get("resource_id")}[key],
                       resource_id)
    for key in ("design_hash", "mapping_hash", "fabric_hash"):
        _require_equal(key, result.get(key), plan.get(key), resource_id)
        _require_equal(f"design.{key}", design.get(key), plan.get(key),
                       resource_id)
    _require_equal("workload_hash", result.get("workload_hash"),
                   plan.get("workload_hash"), resource_id)
    _require_equal("workload.trace_sha256", workload.get("trace_sha256"),
                   plan.get("workload_hash"), resource_id)
    for key in ("backend_target", "backend_profile",
                "backend_semantics_version", "execution_mode"):
        _require_equal(key, result.get(key), plan.get(key), resource_id)
    for key in ("backend_config_hash", "backend_input_hash"):
        _require_equal(f"result.{key}", result.get(key),
                       experiment.get(key), resource_id)
    ref_doc = result.get("evidence_ref") or {}
    try:
        ref = EvidenceRef(path=ref_doc["path"], sha256=ref_doc["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {resource_id} carries a malformed EvidenceRef: "
            f"{exc}",
            operation="verify_result", resource_id=resource_id) from exc
    try:
        evidence = read_verified_evidence(ref)
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {resource_id} evidence fails verification: {exc}",
            operation="verify_result", resource_id=resource_id,
            cause_type=type(exc).__name__) from exc
    if not isinstance(evidence, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {resource_id} evidence is not a mapping",
            operation="verify_result", resource_id=resource_id)
    for key in ("backend_config_hash", "backend_input_hash"):
        _require_equal(f"evidence.{key}", evidence.get(key),
                       experiment.get(key), resource_id)
    _require_equal("status", result.get("status"), "SUCCEEDED", resource_id)
    for key in ("qualification", "execution_transport", "seed",
                "seed_policy"):
        _require_equal(key, result.get(key), evidence.get(key), resource_id)
    _require_equal("semantic_loss",
                   sorted((dict(r) for r in result.get(
                       "semantic_loss", [])),
                          key=lambda r: r.get("dimension", "")),
                   sorted((dict(r) for r in evidence.get(
                       "semantic_loss", [])),
                          key=lambda r: r.get("dimension", "")),
                   resource_id)
    _require_equal("loss_digest", result.get("loss_digest"),
                   loss_digest_of(evidence.get("semantic_loss", [])),
                   resource_id)
    _verify_metrics(result, evidence, plan, resource_id)
    producer = result.get("producer") or {}
    for key, evidence_key in (
            ("binary_sha256", "booksim_binary_sha256"),
            ("source_revision", "producer_source_revision"),
            ("source_dirty", "producer_source_dirty"),
            ("source_dirty_digest", "producer_source_dirty_digest"),
            ("tool_identity", "producer_tool_identity")):
        _require_equal(f"producer.{key}", producer.get(key),
                       evidence.get(evidence_key), resource_id)
    return result


def _verify_metrics(result: dict[str, Any], evidence: dict[str, Any],
                    plan: dict[str, Any], resource_id: str) -> None:
    from .presets import METRIC_SCHEMA_VERSION, STATS_TO_METRIC, \
        get_metric_definition
    _require_equal("metric_schema_version",
                   result.get("metric_schema_version"),
                   METRIC_SCHEMA_VERSION, resource_id)
    rows = result.get("metrics")
    if not isinstance(rows, list):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            "result metrics must be a list", operation="verify_result",
            resource_id=resource_id)
    stats = evidence.get("stats") or {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"metric row must be an object, got {row!r}",
                operation="verify_result", resource_id=resource_id)
        metric_id = row.get("metric_id")
        try:
            definition = get_metric_definition(metric_id)
        except KeyError as exc:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"unknown metric {metric_id!r} in persisted result",
                operation="verify_result",
                resource_id=resource_id) from exc
        stats_key = next(
            (k for k, v in STATS_TO_METRIC.items() if v == metric_id), None)
        if stats_key is None or stats_key not in stats:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"metric {metric_id!r} is not derivable from evidence "
                f"stats",
                operation="verify_result", resource_id=resource_id)
        expected = stats[stats_key]
        if not isinstance(expected, (int, float)) or \
                float(row.get("value")) != float(expected):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"metric {metric_id!r} value {row.get('value')!r} does "
                f"not match evidence {expected!r}",
                operation="verify_result", resource_id=resource_id)
        _require_equal(f"metric {metric_id} unit", row.get("unit"),
                       definition.unit, resource_id)
        _require_equal(f"metric {metric_id} definition version",
                       row.get("definition_version"),
                       METRIC_SCHEMA_VERSION, resource_id)
        seen.add(metric_id)
    planned = set(plan.get("metric_ids", []))
    if seen != planned:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result metrics {sorted(seen)} do not cover the planned "
            f"metrics {sorted(planned)}",
            operation="verify_result", resource_id=resource_id)


__all__ = ["load_verified_result", "loss_digest_of"]
