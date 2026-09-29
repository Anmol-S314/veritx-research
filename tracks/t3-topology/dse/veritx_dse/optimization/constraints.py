"""veritx_dse.optimization.constraints — hard-constraint verdicts (P2).

Rationale: docs/decisions/modules/optimization.md
"""
from __future__ import annotations

from typing import Any

CONSTRAINT_VERDICTS = ("SATISFIED", "VIOLATED", "UNMEASURABLE")


class ConstraintError(ValueError):
    """Invalid constraint evaluation state (fail-closed)."""


def evaluate_constraint_value(metric: str, op: str, threshold: float,
                              value: Any) -> dict[str, Any]:
    """One constraint verdict against a measured value (or None)."""
    if op not in ("<=", ">="):
        raise ConstraintError(f"unsupported operator {op!r}")
    base: dict[str, Any] = {"metric": metric, "operator": op,
                            "bound": float(threshold)}
    if value is None:
        return {**base, "verdict": "UNMEASURABLE", "value": None,
                "margin_or_excess": None,
                "reason": f"no measured value for metric {metric!r} — "
                          "unmeasurable never passes"}
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConstraintError(
            f"metric {metric!r} value must be a real number or None, "
            f"got {value!r}")
    import math
    if not math.isfinite(float(value)):
        raise ConstraintError(f"metric {metric!r} value must be finite")
    v = float(value)
    margin = (float(threshold) - v) if op == "<=" else (v - float(threshold))
    verdict = "SATISFIED" if margin >= 0 else "VIOLATED"
    return {**base, "verdict": verdict, "value": v,
            "margin_or_excess": margin}


def evaluate_all(constraints: Any,
                 objective_values: dict[str, Any],
                 unresolved: dict[str, str] | None = None) -> dict[str, Any]:
    """Verdicts for every declared constraint + feasibility summary.

Rationale: docs/decisions/modules/optimization.md
    """
    unresolved = unresolved or {}
    verdicts: dict[str, dict[str, Any]] = {}
    for con in constraints or []:
        metric = con.metric if hasattr(con, "metric") else con["metric"]
        op = con.op if hasattr(con, "op") else con["op"]
        threshold = (con.threshold if hasattr(con, "threshold")
                     else con["threshold"])
        if metric in verdicts:
            raise ConstraintError(
                f"duplicate constraint for metric {metric!r} — a "
                "metric-indexed verdict map has one slot per metric; "
                "refusing to overwrite the earlier verdict")
        if metric in unresolved:
            verdicts[metric] = {
                "metric": metric, "operator": op,
                "bound": float(threshold), "verdict": "UNMEASURABLE",
                "value": None, "margin_or_excess": None,
                "reason": unresolved[metric],
            }
            continue
        value = (objective_values or {}).get(metric)
        verdicts[metric] = evaluate_constraint_value(
            metric, op, float(threshold), value)
    if any(v["verdict"] == "VIOLATED" for v in verdicts.values()):
        feasible: bool | None = False
    elif any(v["verdict"] == "UNMEASURABLE" for v in verdicts.values()):
        feasible = None
    else:
        feasible = True
    return {"verdicts": verdicts, "feasible": feasible}


__all__ = [
    "CONSTRAINT_VERDICTS", "ConstraintError", "evaluate_all",
    "evaluate_constraint_value",
]
