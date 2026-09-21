"""veritx_dse.optimization.constraints — hard constraints + verdicts (§45–§53).

Truth table (§87) for operators ``<=`` / ``>=`` over exact rationals:

    MEASURED value, op satisfied  -> SATISFIED (with margin)
    MEASURED value, op violated   -> VIOLATED  (with excess)
    UNMEASURABLE / UNSUPPORTED    -> UNMEASURABLE (NEVER a pass, §47)
    wrong unit                    -> hard error (definition-stage guard)

Feasibility (§48): every binding constraint SATISFIED. One VIOLATED
rejects; one UNMEASURABLE means feasibility is not proven.

Negative-claim asymmetry (§49–§52): FEASIBLE is existential and cheap;
NO_FEASIBLE_DESIGN requires search_complete AND every valid candidate
conclusively rejected by MEASURED constraint evidence. Timeouts,
failures, unsupported backends and unmeasurable constraints never
prove infeasibility — they force INCONCLUSIVE.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .metrics import MetricValue

CONSTRAINT_VERDICTS = ("SATISFIED", "VIOLATED", "UNMEASURABLE")

OPTIMIZATION_VERDICTS = (
    "FEASIBLE", "NO_FEASIBLE_DESIGN", "INCONCLUSIVE",
    "CONSTRAINT_UNMEASURABLE", "NO_VALID_CANDIDATES")

#: Candidate statuses that can never prove infeasibility (§50).
NON_PROVING_STATUSES = ("FAILED", "TIMED_OUT", "UNSUPPORTED", "BLOCKED",
                        "UNMEASURABLE", "INVALID", "ALIAS")


class ConstraintError(ValueError):
    """Invalid constraint evaluation state (fail-closed)."""


def evaluate_constraint(metric: MetricValue, operator: str,
                        bound: Fraction, *,
                        scenario: str | None = None) -> dict[str, Any]:
    """One constraint verdict with margin/excess (§46).

    The metric's unit is the registry's unit (the definition parser
    checks the declared unit against the registry at parse time; the
    verifier re-derives both from the registry).
    """
    if operator not in ("<=", ">="):
        raise ConstraintError(
            f"unsupported operator {operator!r} (§45: no expression "
            f"parsing)")
    base = {"metric": metric.name, "scenario": scenario,
            "operator": operator,
            "bound": {"numerator": bound.numerator,
                      "denominator": bound.denominator},
            "unit": metric.unit}
    if metric.status == "MEASURED":
        assert metric.value is not None  # registry invariant
        value = metric.value
        margin = (bound - value) if operator == "<=" \
            else (value - bound)
        verdict = "SATISFIED" if margin >= 0 else "VIOLATED"
        return {**base,
                "verdict": verdict,
                "value": {"numerator": value.numerator,
                          "denominator": value.denominator},
                "margin_or_excess": {
                    "numerator": margin.numerator,
                    "denominator": margin.denominator},
                "source_result_id": metric.source_result_id,
                "fidelity": metric.fidelity}
    # UNMEASURABLE / UNSUPPORTED: never a pass (§47), never zero.
    if metric.value is not None:
        raise ConstraintError(
            f"non-measured metric {metric.name} carries a value; "
            f"refusing to constrain it")
    return {**base,
            "verdict": "UNMEASURABLE",
            "value": None,
            "margin_or_excess": None,
            "reason": metric.reason or f"metric status {metric.status}",
            "source_result_id": metric.source_result_id,
            "fidelity": metric.fidelity}


def feasibility(
        metric_values: dict[tuple[str, "str | None"], MetricValue],
        constraints: list[Any]) -> bool | None:
    """Per-candidate feasibility: True / False / None (not proven).

    One VIOLATED rejects; any UNMEASURABLE leaves feasibility unproven
    (§48); otherwise all SATISFIED is feasible.
    """
    unmeasurable = False
    for con in constraints:
        mv = metric_values.get((con.metric, con.scenario))
        if mv is None:
            raise ConstraintError(
                f"constraint {con.metric}/{con.scenario} has no "
                f"extracted metric value")
        if mv.status != "MEASURED":
            unmeasurable = True
            continue
        assert mv.value is not None
        if con.operator == "<=":
            ok = mv.value <= con.bound
        else:
            ok = mv.value >= con.bound
        if not ok:
            return False
    if unmeasurable:
        return None
    return True


@dataclass(frozen=True)
class VerdictInput:
    """Everything the verdict needs, derived (never asserted).

    ``valid_total``  all VALID unique candidates (aliases excluded).
    ``rejected``     candidates conclusively rejected by a MEASURED
                     constraint violation.
    ``feasible``     candidates with every binding constraint SATISFIED.
    ``non_conclusive`` valid candidates that are neither feasible nor
                     conclusively rejected (failed/timed out/
                     unmeasurable constraints/still unevaluated).
    ``all_measured_unmeasurable`` True when no valid candidate could
                     produce constraint evidence at all.
    """
    search_complete: bool
    valid_total: int
    feasible: int
    rejected: int
    non_conclusive: int
    any_measured: bool


def optimization_verdict(inp: VerdictInput) -> dict[str, Any]:
    """The strict verdict ladder (§49–§53).

    FEASIBLE is existential and needs exactly one conclusive feasible
    candidate. NO_FEASIBLE_DESIGN needs COMPLETE search over the valid
    space and every valid candidate conclusively rejected by measured
    evidence. Anything else that could still change the conclusion is
    INCONCLUSIVE. A valid space with no measurable constraint evidence
    anywhere is CONSTRAINT_UNMEASURABLE.
    """
    if inp.valid_total == 0:
        return {"verdict": "NO_VALID_CANDIDATES",
                "reason": "every declared assignment was invalid before "
                          "evaluation (§53: not a feasibility claim)"}
    if inp.feasible > 0:
        return {"verdict": "FEASIBLE",
                "feasible_count": inp.feasible,
                "evaluated_count": inp.rejected + inp.feasible
                                   + inp.non_conclusive}
    if not inp.any_measured:
        return {"verdict": "CONSTRAINT_UNMEASURABLE",
                "reason": "no valid candidate produced measurable "
                          "constraint evidence",
                "non_conclusive_count": inp.non_conclusive}
    if inp.search_complete and inp.non_conclusive == 0 \
            and inp.rejected == inp.valid_total:
        return {"verdict": "NO_FEASIBLE_DESIGN",
                "reason": "search complete; every valid candidate is "
                          "conclusively rejected by measured hard-"
                          "constraint evidence",
                "evaluated_count": inp.rejected}
    return {"verdict": "INCONCLUSIVE",
            "reason": "no feasible candidate found and the negative "
                      "claim is not proven (incomplete search, "
                      "failures, timeouts, or unmeasurable "
                      "constraints)",
            "non_conclusive_count": inp.non_conclusive}


def relaxation_evidence(
        metric_values_by_candidate: list[dict[
            tuple[str, "str | None"], MetricValue]],
        constraints: list[Any]) -> list[dict[str, Any]]:
    """How far would the bound need to move? (§98/§99 — information only)

    Only MEASURED values contribute; unmeasurable candidates contribute
    nothing (no invented numbers). Completeness language is the
    caller's responsibility (best observed vs minimal over the space).
    """
    out: list[dict[str, Any]] = []
    for con in constraints:
        best: MetricValue | None = None
        best_violates = False
        for values in metric_values_by_candidate:
            mv = values.get((con.metric, con.scenario))
            if mv is None or mv.status != "MEASURED" \
                    or mv.value is None:
                continue
            violates = not _satisfies(mv.value, con.operator, con.bound)
            d_cur = abs(mv.value - con.bound)
            if best is None:
                best, best_violates = mv, violates
                continue
            assert best.value is not None
            # Prefer violating (relaxation-relevant) values; among
            # equals, prefer the value closest to the bound.
            d_best = abs(best.value - con.bound)
            if violates != best_violates:
                if violates:
                    best, best_violates = mv, violates
                continue
            if d_cur < d_best:
                best, best_violates = mv, violates
        if best is None or best.value is None or not best_violates:
            continue  # some candidate satisfies; no relaxation needed
        # |value - bound| : how far the bound must move to admit the
        # best observed value (sign-free, exact).
        diff = abs(best.value - con.bound)
        out.append({
            "metric": con.metric, "scenario": con.scenario,
            "operator": con.operator,
            "bound": {"numerator": con.bound.numerator,
                      "denominator": con.bound.denominator},
            "unit": best.unit,
            "best_observed": {"numerator": best.value.numerator,
                              "denominator": best.value.denominator},
            "required_relaxation": {
                "numerator": diff.numerator,
                "denominator": diff.denominator},
            "information_only": True,
        })
    return out


def _satisfies(value: Fraction, operator: str, bound: Fraction) -> bool:
    return value <= bound if operator == "<=" else value >= bound
