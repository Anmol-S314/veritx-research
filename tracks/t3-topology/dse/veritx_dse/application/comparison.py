"""veritx_dse.application.comparison — one comparison authority (Wave C).

No product path may compare naked result dictionaries. Comparison goes
through an explicit ``ComparisonContract`` (allowed variations +
metrics), a compatibility gate over typed ``EvaluationResult`` records,
and observed-language output (``lower observed latency`` — never
WINNER/BEST/OPTIMAL from single samples).

Conservative defaults for DESIGN_COMPARISON: the fabric may vary; the
experiment context (workload, mapping, backend profile/semantics,
execution mode, seed policy, metric schema) must match. Binary producer
identity must match unless the contract explicitly varies it. Semantic
loss digests must match unless the contract varies loss with an explicit
acknowledgement covering the differing dimensions.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .errors import ControlPlaneError, ErrorCode

COMPARISON_KINDS = ("DESIGN_COMPARISON", "EXACT_REPLAY", "CONTROLLED_STUDY")

KNOWN_DIMENSIONS = (
    "fabric_hash",
    "workload_hash",
    "mapping_hash",
    "backend_target",
    "backend_profile",
    "backend_semantics",
    "execution_mode",
    "seed_policy",
    "seed",
    "metric_schema",
    "producer_binary",
    "semantic_loss",
    # Wave E: two latency numbers are not automatically comparable. A
    # result produced under a different performance model (different
    # clocks, resources, compute source, arbitration or calibration
    # context) measures something else, so the model is a required
    # compatibility dimension. A contract may explicitly allow it, but
    # silence never may.
    "timing_model",
)

_DEFAULT_ALLOWED: dict[str, frozenset[str]] = {
    "DESIGN_COMPARISON": frozenset({"fabric_hash"}),
    "EXACT_REPLAY": frozenset(),
    "CONTROLLED_STUDY": frozenset(),
}


@dataclass(frozen=True)
class ComparisonContract:
    comparison_kind: str
    allowed_variations: tuple[str, ...]
    metric_ids: tuple[str, ...]
    acknowledged_differences: tuple[str, ...] = ()

    def identity_dict(self) -> dict[str, Any]:
        return {
            "comparison_kind": self.comparison_kind,
            "allowed_variations": list(self.allowed_variations),
            "metric_ids": list(self.metric_ids),
            "acknowledged_differences": list(
                self.acknowledged_differences),
        }

    def contract_id(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = "srota-comparison-contract/v1\0" + canonical_json(
            self.identity_dict())
        return hashlib.sha256(body.encode()).hexdigest()


def parse_contract(doc: Any) -> ComparisonContract:
    """Strict comparison-contract parsing (unknown fields refuse)."""
    if not isinstance(doc, dict):
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            f"comparison contract must be an object, got "
            f"{type(doc).__name__}",
            operation="compare")
    allowed_keys = frozenset({
        "comparison_kind", "allowed_variations", "metric_ids",
        "acknowledged_differences"})
    extra = sorted(set(doc) - allowed_keys)
    if extra:
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            f"comparison contract has unknown fields {extra}",
            operation="compare")
    kind = doc.get("comparison_kind", "DESIGN_COMPARISON")
    if kind not in COMPARISON_KINDS:
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            f"unknown comparison_kind {kind!r} "
            f"(known: {list(COMPARISON_KINDS)})",
            operation="compare")
    raw_allowed = doc.get("allowed_variations")
    if raw_allowed is None:
        allowed = _DEFAULT_ALLOWED[kind]
    else:
        if not isinstance(raw_allowed, list) or any(
                not isinstance(v, str) for v in raw_allowed):
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                "allowed_variations must be a list of dimension names",
                operation="compare")
        unknown = sorted(set(raw_allowed) - set(KNOWN_DIMENSIONS))
        if unknown:
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                f"unknown comparison dimensions {unknown} "
                f"(known: {list(KNOWN_DIMENSIONS)})",
                operation="compare")
        allowed = frozenset(raw_allowed)
    raw_metrics = doc.get("metric_ids")
    if not isinstance(raw_metrics, list) or not raw_metrics or any(
            not isinstance(m, str) for m in raw_metrics):
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            "metric_ids must be a non-empty list of metric ids",
            operation="compare")
    from .presets import get_metric_definition
    for metric_id in raw_metrics:
        try:
            get_metric_definition(metric_id)
        except KeyError as exc:
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT, str(exc),
                operation="compare") from exc
    raw_ack = doc.get("acknowledged_differences", [])
    if not isinstance(raw_ack, list) or any(
            not isinstance(v, str) for v in raw_ack):
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            "acknowledged_differences must be a list of strings",
            operation="compare")
    return ComparisonContract(
        comparison_kind=kind, allowed_variations=tuple(sorted(allowed)),
        metric_ids=tuple(raw_metrics),
        acknowledged_differences=tuple(raw_ack))


def _dimension_values(result: dict[str, Any]) -> dict[str, Any]:
    producer = result.get("producer") or {}
    wave_e = result.get("wave_e")
    timing_model = "NO_TIMING_MODEL"
    if isinstance(wave_e, dict) and wave_e.get("performance_model_id"):
        # The performance model IS the timing semantics (clocks,
        # resources, compute source, arbitration); the fidelity warning
        # is a function of it. Wave-D-only results have no timing model.
        timing_model = wave_e["performance_model_id"]
    return {
        "fabric_hash": result.get("fabric_hash"),
        "workload_hash": result.get("workload_hash"),
        "mapping_hash": result.get("mapping_hash"),
        "backend_target": result.get("backend_target"),
        "backend_profile": result.get("backend_profile"),
        "backend_semantics": result.get("backend_semantics_version"),
        "execution_mode": result.get("execution_mode"),
        "seed_policy": result.get("seed_policy"),
        "seed": result.get("seed"),
        "metric_schema": result.get("metric_schema_version"),
        "producer_binary": producer.get("binary_sha256")
        if isinstance(producer, dict) else None,
        "semantic_loss": result.get("loss_digest"),
        "timing_model": timing_model,
    }


def check_compatibility(a: dict[str, Any], b: dict[str, Any],
                        contract: ComparisonContract) -> dict[str, Any]:
    """Gate two result records; returns the compatibility report.

    Raises ControlPlaneError(COMPARISON_INCOMPATIBLE) with explicit
    reasons on the first violated required dimension. Never returns a
    verdict for failed, tampered, test-transport or fidelity-mismatched
    results.
    """
    for label, result in (("a", a), ("b", b)):
        if result.get("resource_type") != "result":
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {label} is not an evaluation result "
                f"(got {result.get('resource_type')!r})",
                operation="compare")
        if result.get("status") != "SUCCEEDED":
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {label} is not a successful result "
                f"(status {result.get('status')!r}); comparison consumes "
                f"successful typed results only",
                operation="compare")
        if result.get("execution_transport") != "SUPERVISED_PROCESS":
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {label} has non-production execution "
                f"transport {result.get('execution_transport')!r}",
                operation="compare")
    dimensions = []
    values_a = _dimension_values(a)
    values_b = _dimension_values(b)
    for dimension in KNOWN_DIMENSIONS:
        va, vb = values_a[dimension], values_b[dimension]
        if va == vb:
            dimensions.append({"dimension": dimension, "outcome": "match"})
            continue
        if dimension in contract.allowed_variations:
            if dimension == "semantic_loss":
                _check_acknowledged(a, b, contract)
            dimensions.append({"dimension": dimension,
                               "outcome": "varied-allowed"})
            continue
        raise ControlPlaneError(
            ErrorCode.COMPARISON_INCOMPATIBLE,
            f"dimension {dimension!r} differs and is not an allowed "
            f"variation (a={va!r} b={vb!r})",
            operation="compare")
    return {"verdict": "COMPATIBLE", "dimensions": dimensions}


def _check_acknowledged(a: dict[str, Any], b: dict[str, Any],
                        contract: ComparisonContract) -> None:
    dims_a = {row.get("dimension") for row in a.get("semantic_loss", [])
              if isinstance(row, dict)}
    dims_b = {row.get("dimension") for row in b.get("semantic_loss", [])
              if isinstance(row, dict)}
    differing = sorted(dims_a ^ dims_b)
    missing = [d for d in differing
               if d not in contract.acknowledged_differences]
    if missing:
        raise ControlPlaneError(
            ErrorCode.COMPARISON_INCOMPATIBLE,
            f"semantic-loss dimensions differ {differing} but are not "
            f"acknowledged (acknowledged: "
            f"{list(contract.acknowledged_differences)})",
            operation="compare")


def metric_value(result: dict[str, Any], metric_id: str) -> float:
    for row in result.get("metrics", []):
        if isinstance(row, dict) and row.get("metric_id") == metric_id:
            value = row.get("value")
            if not isinstance(value, (int, float)):
                raise ControlPlaneError(
                    ErrorCode.COMPARISON_INCOMPATIBLE,
                    f"metric {metric_id!r} has non-numeric value "
                    f"{value!r}",
                    operation="compare")
            return float(value)
    raise ControlPlaneError(
        ErrorCode.COMPARISON_INCOMPATIBLE,
        f"metric {metric_id!r} is not present in candidate "
        f"{result.get('resource_id')!r}",
        operation="compare")


def compare_metrics(a: dict[str, Any], b: dict[str, Any],
                    metric_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    """Observed-language deltas (never WINNER/BEST/OPTIMAL)."""
    rows = []
    for metric_id in metric_ids:
        va = metric_value(a, metric_id)
        vb = metric_value(b, metric_id)
        delta = vb - va
        if delta < 0:
            lower = b.get("resource_id")
        elif delta > 0:
            lower = a.get("resource_id")
        else:
            lower = None
        rows.append({
            "metric_id": metric_id,
            "a_value": va,
            "b_value": vb,
            "delta_b_minus_a": delta,
            "lower_observed": lower,
        })
    return rows


__all__ = [
    "COMPARISON_KINDS",
    "KNOWN_DIMENSIONS",
    "ComparisonContract",
    "check_compatibility",
    "compare_metrics",
    "metric_value",
    "parse_contract",
]
