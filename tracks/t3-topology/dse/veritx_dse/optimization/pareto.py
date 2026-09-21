"""veritx_dse.optimization.pareto — scoped Pareto + selection (§40, §54–§61).

Production dominance is the sealed ``core.comparison.pareto_with_scope``
— this module is a thin DIRECTION adapter (§40/§86), not a second
dominance implementation:

    MAXIMIZE x  ->  minimize (-x)   (exact Fraction negation)

The raw value and its declared direction are preserved in the result;
the negated projection is internal and never exposed as the user
metric (§40). Ties stay ties: equal objective vectors neither dominate
nor eliminate each other, and selection preserves ALL exact ties
(§58/§59/§119).

Completeness is two separate flags (§54/§55):

    search_complete    every valid candidate accounted for
    frontier_complete  search_complete AND every feasible candidate
                       objectively measurable AND all comparable
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from veritx_dse.core.comparison import ComparisonSpecError, pareto_with_scope


class ParetoError(ValueError):
    """Invalid Pareto/selection state (fail-closed)."""


@dataclass(frozen=True)
class ObjectiveDimension:
    """One canonical objective axis of the frontier."""
    metric: str
    scenario: str | None
    direction: str                    # MINIMIZE | MAXIMIZE

    @property
    def axis(self) -> str:
        """The internal (all-MINIMIZE) axis name handed to the adapter."""
        return f"{self.metric}@{self.scenario or '*'}"

    def project(self, value: Fraction) -> Fraction:
        return -value if self.direction == "MAXIMIZE" else value


def dimensions(defn: Any) -> list[ObjectiveDimension]:
    """Canonical objective axes: declared order, deduplicated."""
    out: list[ObjectiveDimension] = []
    seen: set[tuple[str, str | None]] = set()
    for obj in defn.objectives:
        key = (obj.metric, obj.scenario)
        if key in seen:
            continue
        seen.add(key)
        out.append(ObjectiveDimension(metric=obj.metric,
                                      scenario=obj.scenario,
                                      direction=obj.direction))
    return out


def _run_id(cand: Any) -> str:
    cid = getattr(cand, "candidate_id", None) or \
        (cand.get("candidate_id") if isinstance(cand, dict) else None)
    if not cid:
        raise ParetoError("candidate without a candidate_id")
    return cid


def comparability_report(
        defn: Any,
        scenario_results_by_candidate: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Set-level comparability gate (§42/§43/§131/§132).

    Search parameters are the DECLARED experimental variables;
    everything else relevant must remain controlled. Over the frontier
    set we require:

      - one Wave-E fidelity class (mixed-fidelity refusal; §94) —
        derived from each verified result's own ``metrics_warning``;
      - one performance model per scenario across candidates (§131:
        "optimizing" an assumption change is not optimization;
        §132: equal numbers with different models refuse);
      - scenario identity is structural: a candidate's scenario
        results are bound per scenario by the verified loader, so
        cross-scenario comparison cannot arise here (§44).
    """
    refusals: list[str] = []
    warnings: list[str] = []
    fidelity: set[str] = set()
    model_ids: dict[str, set[str]] = {}
    for cid, sres in sorted(scenario_results_by_candidate.items()):
        for sname in sorted(sres):
            vres = sres[sname]
            block = vres.get("wave_e") or {}
            if block.get("metrics_warning"):
                fidelity.add(str(block["metrics_warning"]))
            tw = block.get("performance_model_id")
            if tw:
                model_ids.setdefault(sname, set()).add(str(tw))
    if len(fidelity) > 1:
        refusals.append(
            "mixed Wave-E fidelity classes across frontier "
            "candidates: " + " | ".join(sorted(fidelity)) +
            " (declare an explicit cross-fidelity mode; §94)")
    for sname, ids in sorted(model_ids.items()):
        if len(ids) > 1:
            refusals.append(
                f"scenario {sname!r} runs under different performance "
                f"models across candidates: {sorted(ids)} (§131/§132: "
                f"a changed assumption is not a design improvement)")
    # Scenario-free multi-scenario mixing guard: when the definition
    # declares multiple scenarios, a scenario-free objective must not
    # silently straddle them — dimensions carry the scenario and the
    # frontier axes are (metric@scenario), so identity is preserved
    # structurally (§44).
    return {"comparable": not refusals, "refusals": refusals,
            "warnings": warnings,
            "fidelity_classes": sorted(fidelity),
            "performance_model_ids": {
                s: sorted(v) for s, v in sorted(model_ids.items())}}


def compute_frontier(defn: Any, feasible: list[Any],
                     objective_values: dict[str, dict[tuple[str, "str | None"], Any]],
                     *, comparability_ok: bool
                     ) -> dict[str, Any]:
    """Scoped Pareto over feasible, measurable, comparable candidates.

    ``feasible``: candidate objects/docs that are SUCCEEDED, feasible,
    and scientifically comparable. Every other candidate stays outside
    the frontier computation but remains visible in the caller's
    accounting (§41) — this function reports only the comparable scope.

    ``objective_values``: candidate_id -> {(metric, scenario): MetricValue}.
    """
    dims = dimensions(defn)
    if not dims:
        raise ParetoError("no objective dimensions")
    if not comparability_ok:
        raise ParetoError(
            "candidates are not scientifically comparable; refusing "
            "to compute a frontier over incompatible evidence (§42)")
    candidates: list[dict[str, Any]] = []
    for cand in feasible:
        cid = _run_id(cand)
        values = objective_values.get(cid)
        if values is None:
            raise ParetoError(f"candidate {cid} has no objective values")
        metrics: dict[str, Fraction] = {}
        missing: list[str] = []
        for d in dims:
            mv = values.get((d.metric, d.scenario))
            if mv is None or mv.status != "MEASURED" \
                    or mv.value is None:
                missing.append(d.axis)
                continue
            metrics[d.axis] = d.project(mv.value)
        if missing:
            candidates.append({
                "run_id": cid, "status": "MISSING_METRIC",
                "metrics": {},
                "reason": "objective(s) not measurable: "
                          + ", ".join(sorted(missing))})
            continue
        candidates.append({"run_id": cid, "status": "COMPARABLE",
                           "metrics": metrics})
    if not candidates:
        return {
            "comparison_kind": "OPTIMIZATION",
            "objectives": [d.axis for d in dims],
            "candidate_count": 0, "comparable_count": 0,
            "candidates": [], "excluded": [], "front": [],
            "dominated": [],
            "pareto_scope": {"candidate_count": 0,
                             "objectives": [d.axis for d in dims]},
        }
    try:
        scoped = pareto_with_scope(candidates, [d.axis for d in dims],
                                   kind="OPTIMIZATION")
    except ComparisonSpecError as exc:
        raise ParetoError(str(exc)) from exc
    return scoped


def frontier_is_complete(defn: Any, *, search_complete: bool,
                         feasible_ids: list[str],
                         objective_values: dict[str, dict],
                         comparable_count: int) -> bool:
    """§55: EXHAUSTIVE + all valid accounted + every feasible measurable
    + all comparable."""
    if not search_complete or defn.search_policy != "EXHAUSTIVE_GRID":
        return False
    if comparable_count != len(feasible_ids):
        return False
    for cid in feasible_ids:
        values = objective_values.get(cid) or {}
        for d in dimensions(defn):
            mv = values.get((d.metric, d.scenario))
            if mv is None or mv.status != "MEASURED":
                return False
    return True


# ── selection (§57–§61) ──────────────────────────────────────────────────

def _sel_key(defn: Any, order_entry: dict[str, Any]
             ) -> ObjectiveDimension:
    metric, scenario = order_entry["metric"], order_entry["scenario"]
    for obj in defn.objectives:
        if obj.metric == metric and obj.scenario == scenario:
            return ObjectiveDimension(metric=obj.metric,
                                      scenario=obj.scenario,
                                      direction=obj.direction)
    raise ParetoError(
        f"selection metric {metric}/{scenario} is not a declared "
        f"objective")


def select(defn: Any, frontier_ids: list[str],
           objective_values: dict[str, dict[tuple[str, "str | None"], Any]]
           ) -> dict[str, Any]:
    """Explicit-policy selection over the frontier (§57/§137).

    Returns {"selected": [...], "tied": True|False, "policy": ...}.
    Exact ties are ALL preserved (§58/§59/§119); no name-based tiebreak.
    """
    policy = defn.selection_policy
    if policy == "NONE":
        if len(frontier_ids) > 0:
            return {"selected": [], "tied": None, "policy": "NONE"}
        return {"selected": [], "tied": None, "policy": "NONE"}
    order = list(defn.selection_metric_order)
    if policy == "SINGLE_OBJECTIVE" and not order:
        dims = {(o.metric, o.scenario) for o in defn.objectives}
        if len(dims) != 1:
            raise ParetoError(
                "SINGLE_OBJECTIVE selection with multiple objective "
                "dimensions")
        metric, scenario = next(iter(dims))
        order = [{"metric": metric, "scenario": scenario}]
    keys = [_sel_key(defn, e) for e in order]
    remaining = list(frontier_ids)
    for depth, key in enumerate(keys):
        best_ids: list[str] = []
        best_val: Fraction | None = None
        for cid in remaining:
            values = objective_values.get(cid) or {}
            mv = values.get((key.metric, key.scenario))
            if mv is None or mv.status != "MEASURED" \
                    or mv.value is None:
                raise ParetoError(
                    f"selection candidate {cid} cannot measure "
                    f"{key.metric}@{key.scenario}; refusing to invent "
                    f"a value")
            v = key.project(mv.value)   # projected = minimized value
            if best_val is None or v < best_val:
                best_val = v
                best_ids = [cid]
            elif v == best_val:
                best_ids.append(cid)
        remaining = best_ids
        if len(best_ids) <= 1:
            break
    tied = len(remaining) > 1
    return {"selected": sorted(remaining), "tied": tied,
            "policy": policy}


def dominance_explanations(scoped: dict[str, Any]
                           ) -> dict[str, dict[str, Any]]:
    """Per-dominated-candidate: one dominator + the comparisons (§142).

    Derived from the same projected values the frontier used; frontier
    semantics are not changed by this.
    """
    comparable = {c["run_id"]: c for c in scoped.get("candidates", [])
                  if c.get("status") == "COMPARABLE"}
    axes = list(scoped.get("objectives", []))
    out: dict[str, dict[str, Any]] = {}
    dominated_ids = scoped.get("dominated", [])
    for did in dominated_ids:
        d = comparable.get(did)
        if d is None:
            continue
        for uid in scoped.get("front", []):
            u = comparable.get(uid)
            if u is None:
                continue
            if all(u["metrics"][a] <= d["metrics"][a] for a in axes) \
                    and any(u["metrics"][a] < d["metrics"][a]
                            for a in axes):
                out[did] = {
                    "dominated_by": uid,
                    "comparisons": {
                        a: {"dominator": u["metrics"][a],
                            "dominated": d["metrics"][a]}
                        for a in axes}}
                break
    return out
