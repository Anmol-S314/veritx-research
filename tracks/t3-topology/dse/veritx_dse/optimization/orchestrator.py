"""veritx_dse.optimization.orchestrator — run one optimization (§4/§147).

Pure sequencing over sealed authorities; no science lives here:

    build_candidates(defn)                    space.py   (§15–§20)
    -> budgeted canonical prefix              (§23/§24/§25)
    -> cp.evaluate(patched intent)            sealed control plane (§3)
    -> load_verified_result per scenario      (§65)
    -> extract objective/constraint values    metrics.py (§31)
    -> evaluate_constraint docs               constraints.py (§46)
    -> comparability gate + compute_frontier  pareto.py  (§41/§42)
    -> select() under the declared policy     pareto.py  (§57)
    -> OptimizationRun                        result.py  (§63)

Failures stay visible and typed (§30/§117): a candidate timeout remains
TIMED_OUT in the accounting and can never help prove infeasibility
(§50). No execution parallelism (§109); resume comes from control-plane
reuse (§26/§110).
"""
from __future__ import annotations

from typing import Any

from veritx_dse.application.errors import ControlPlaneError
from veritx_dse.application.results import load_verified_result
from veritx_dse.application.studies import study_status_for_error
from veritx_dse.optimization.constraints import (
    evaluate_constraint, feasibility, relaxation_evidence,
)
from veritx_dse.optimization.definition import (
    OptimizationDefinition, patched_scenario_template,
)
from veritx_dse.optimization.metrics import (
    extract_constraint_values, extract_objective_values,
)
from veritx_dse.optimization.pareto import (
    comparability_report, compute_frontier, dominance_explanations,
    frontier_is_complete, select,
)
from veritx_dse.optimization.result import (
    CandidateEvaluation, OptimizationRun, candidate_valid_ids,
    derive_budget, derive_feasible_ids, derive_search_complete,
)
from veritx_dse.optimization.space import (
    NOT_EVALUATED, budget_plan, build_candidates,
)


class OrchestratorError(ValueError):
    """Invalid orchestration state (fail-closed)."""


def run_optimization(cp: Any, defn: OptimizationDefinition) -> OptimizationRun:
    """One deterministic optimization pass over the control plane."""
    # 1) enumerate + resolve + dedupe BEFORE any execution (§18/§19)
    candidates, records = build_candidates(defn)
    n_scen = len(defn.scenarios)
    plan = budget_plan(defn, len(candidates))
    planned = plan["planned_candidates"]

    evaluated: list[CandidateEvaluation] = []
    objective_values: dict[str, dict] = {}
    constraint_values: dict[str, dict] = {}
    constraint_docs: dict[str, list[dict[str, Any]]] = {}
    result_docs: dict[str, dict[str, dict[str, Any]]] = {}
    n_reused = 0

    # 2) canonical budgeted prefix (§24): candidates are already in
    #    canonical order; the budget cuts the prefix, never a sample.
    ordered = candidates[:planned]
    for cand in ordered:
        per_scenario_results: dict[str, dict[str, Any] | None] = {}
        result_ids: dict[str, str | None] = {}
        statuses: list[str] = []
        for spec in defn.scenarios:
            outcome = cand.scenario_outcomes[
                defn.scenario_names().index(spec.name)]
            patched = patched_scenario_template(spec.intent, cand.assignment)
            try:
                ev = cp.evaluate(patched)
            except ControlPlaneError as exc:
                statuses.append(study_status_for_error(
                    exc, backend_target=spec.intent.get(
                        "backend_target")))
                per_scenario_results[spec.name] = None
                result_ids[spec.name] = None
                continue
            n_reused += 1 if ev.get("reused") else 0
            try:
                vres = load_verified_result(
                    cp.store, ev["resource_id"],
                    expected_experiment_id=ev["experiment_id"])
            except ControlPlaneError as exc:
                raise OrchestratorError(
                    f"candidate {cand.candidate_id[:12]} scenario "
                    f"{spec.name!r}: fresh evaluation failed "
                    f"verification: {exc.message}") from exc
            statuses.append("SUCCEEDED")
            per_scenario_results[spec.name] = vres
            result_ids[spec.name] = ev["resource_id"]
        if all(s == "SUCCEEDED" for s in statuses):
            status = "SUCCEEDED"
        elif any(s == "TIMED_OUT" for s in statuses):
            status = "TIMED_OUT"
        elif any(s in ("UNSUPPORTED", "BLOCKED") for s in statuses):
            status = next(s for s in statuses
                          if s in ("UNSUPPORTED", "BLOCKED"))
        elif any(s == "FAILED" for s in statuses):
            status = "FAILED"
        else:
            raise OrchestratorError(
                f"candidate produced non-terminal scenario outcomes: "
                f"{statuses}")
        evaluated.append(CandidateEvaluation(
            index=cand.index, assignment=cand.assignment,
            candidate_id=cand.candidate_id, status=status,
            alias_of=None,
            scenario_intent_ids=cand.intent_ids(),
            scenario_result_ids=result_ids,
            error=None))
        result_docs[cand.candidate_id] = per_scenario_results  # type: ignore[assignment]

    # 3) the budget tail stays visible as NOT_EVALUATED (§23/§64)
    evaluated_set = {c.index for c in ordered}
    for cand in candidates:
        if cand.index in evaluated_set:
            continue
        evaluated.append(CandidateEvaluation(
            index=cand.index, assignment=cand.assignment,
            candidate_id=cand.candidate_id, status=NOT_EVALUATED,
            alias_of=None, scenario_intent_ids=cand.intent_ids(),
            scenario_result_ids={}, error=None))

    # INVALID/ALIAS records from the space pass through unchanged
    space_rows = []
    valid_indexes = {c.index for c in candidates}
    for row in records:
        if row["status"] == "VALID":
            ev = next((e for e in evaluated
                       if e.index == row["index"]), None)
            if ev is None:
                raise OrchestratorError(
                    f"valid candidate {row['index']} vanished from "
                    f"accounting (§64)")
            space_rows.append({
                "index": ev.index,
                "assignment": ev.assignment,
                "candidate_id": ev.candidate_id,
                "status": ev.status,
                "alias_of": ev.alias_of,
                "scenario_intent_ids": ev.scenario_intent_ids,
                "scenario_result_ids": ev.scenario_result_ids,
                "error": ev.error,
            })
        else:
            space_rows.append({
                "index": row["index"],
                "assignment": row["assignment"],
                "candidate_id": row["candidate_id"],
                "status": row["status"],
                "alias_of": row["alias_of"],
                "scenario_intent_ids": row["scenario_intent_ids"],
                "scenario_result_ids": {},
                "error": row["error"],
            })
    space_rows.sort(key=lambda r: r["index"])

    # 4) verified metric extraction + constraint docs (§31/§46/§66/§67)
    #    Structural metrics see the CANDIDATE-PATCHED template so counts
    #    track the assignment through the Wave-B authority (§34/§35).
    base_templates = {s.name: s.intent for s in defn.scenarios}
    for ev in evaluated:
        if ev.status != "SUCCEEDED":
            continue
        sres = result_docs[ev.candidate_id]
        templates = {
            name: patched_scenario_template(base_templates[name],
                                            ev.assignment)
            for name in base_templates}
        objective_values[ev.candidate_id] = extract_objective_values(
            defn, sres, store=cp.store, templates=templates)
        cvals = extract_constraint_values(
            defn, sres, store=cp.store, templates=templates)
        constraint_values[ev.candidate_id] = cvals
        docs = [
            evaluate_constraint(
                cvals[(con.metric, con.scenario)], con.operator,
                con.bound, scenario=con.scenario)
            for con in defn.hard_constraints]
        constraint_docs[ev.candidate_id] = sorted(
            docs, key=lambda c: (c["metric"], str(c["scenario"])))

    # 5) feasible set, comparability, Pareto, selection (§41/§42/§48)
    all_records = space_rows
    feasible_ids = derive_feasible_ids(
        defn, all_records, constraint_docs)
    comparability = comparability_report(
        defn, {cid: result_docs[cid] for cid in feasible_ids
               if cid in result_docs})
    if not comparability["comparable"]:
        raise OrchestratorError(
            "frontier candidates are not scientifically comparable: "
            + "; ".join(comparability["refusals"]))
    scoped = compute_frontier(
        defn, [{"candidate_id": cid} for cid in feasible_ids],
        objective_values, comparability_ok=True)
    selection = select(defn, list(scoped.get("front", [])),
                       objective_values)
    dominance = dominance_explanations(scoped)

    # 6) relaxation evidence over MEASURED constraint values (§98)
    relaxation = relaxation_evidence(
        list(constraint_values.values()), list(defn.hard_constraints))

    # 7) completeness (§54/§55/§62)
    search_complete = derive_search_complete(all_records)
    frontier_complete = frontier_is_complete(
        defn, search_complete=search_complete, feasible_ids=feasible_ids,
        objective_values=objective_values,
        comparable_count=scoped.get("comparable_count", 0))

    # 8) Wave-E models actually used (for the derived warning, §138)
    wave_e_models = []
    for sres in result_docs.values():
        for vres in sres.values():
            if vres is None:
                continue
            block = vres.get("wave_e") or {}
            if isinstance(block, dict) and block.get("metrics_warning"):
                wave_e_models.append(
                    {"metrics_warning": block["metrics_warning"]})

    return OptimizationRun(
        definition=defn,
        records=[CandidateEvaluation(
            index=r["index"], assignment=r["assignment"],
            candidate_id=r["candidate_id"], status=r["status"],
            alias_of=r["alias_of"],
            scenario_intent_ids=r["scenario_intent_ids"],
            scenario_result_ids=r["scenario_result_ids"],
            error=r["error"]) for r in space_rows],
        search_complete=search_complete,
        frontier_complete=frontier_complete,
        objective_values=objective_values,
        constraint_docs=constraint_docs,
        pareto=scoped,
        selection=selection,
        dominance=dominance,
        relaxation=relaxation,
        wave_e_models=wave_e_models,
    )
