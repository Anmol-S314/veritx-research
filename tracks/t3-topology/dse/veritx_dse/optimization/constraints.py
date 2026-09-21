"""veritx_dse.optimization.constraints — hard-constraint verdicts (P2).

Truth table over exact comparisons (floats compared directly; the fake
evaluator emits short decimals, so no Fraction machinery is needed):

    measured value, op satisfied  -> SATISFIED (with margin)
    measured value, op violated   -> VIOLATED  (with excess)
    missing/None value            -> UNMEASURABLE (NEVER a pass)

Feasibility: every declared constraint SATISFIED. One VIOLATED rejects;
one UNMEASURABLE leaves feasibility unproven (fail-closed, never a
silent pass).

Provenance: REPLAYS the North-Star reference constraints module
(Constraint.evaluate for <=/>=) extended with the
UNMEASURABLE fail-closed arm from synthesis/compiler.py
(_UNMEASURABLE bandwidth floors) and wave-f constraints.py §47
(unmeasurable never passes). No expression parsing: operators are
exactly <= / >= (wave-f §45 rule, REPLAYED).
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
                 objective_values: dict[str, Any]) -> dict[str, Any]:
    """Verdicts for every declared constraint + feasibility summary.

    Returns {"verdicts": {metric: doc}, "feasible": True/False/None}.
    None = not proven (some UNMEASURABLE, none VIOLATED).
    """
    verdicts: dict[str, dict[str, Any]] = {}
    for con in constraints or []:
        metric = con.metric if hasattr(con, "metric") else con["metric"]
        op = con.op if hasattr(con, "op") else con["op"]
        threshold = (con.threshold if hasattr(con, "threshold")
                     else con["threshold"])
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
