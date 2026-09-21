"""veritx_dse.optimization.result — OptimizationResult + Optimizer (P2).

OptimizationResult binds: base request identity, definition,
candidate/evaluation IDs, objective values, constraint verdicts, Pareto
membership, selection rationale. Execution order never changes
candidate identity (re-derived and refused on mismatch, never an
assert).

TWO AUTHORITIES, NEVER MERGED:

* the PRODUCT RequirementReport answers "did the design satisfy the
  customer's requirements?" — carried as requirement_report_id,
  product_requirements_satisfied and product_requirement_details;
* the optimizer's own hard constraints answer "did the candidate
  satisfy the study's constraints?" — carried as constraint_verdicts
  (SATISFIED/VIOLATED/UNMEASURABLE), constraint_details and
  constraints_satisfied.

Objectives are a third, measured-only namespace (objective_values).
A candidate is Pareto-eligible only when its evaluation succeeded AND
its binding product requirements pass AND every requested objective is
measured and finite AND every hard constraint is SATISFIED. Ineligible
candidates stay visible with typed reasons and never reach pareto.py's
indexing (never a KeyError).

Emits OptimizationStudyView per
contracts/srota/v1/optimization.study.view.v2.schema.json
(contract_version 2 by default; contract_version=1 keeps the frozen
boolean-only v1 shape for pinned callers — that projector is LOSSY and
never claims to preserve three-state semantics).

Provenance: result-identity and re-derivation discipline REPLAY
synthesis/compiler.py (request/budget/scope accounting, Pareto only over
the feasible set, relaxation as information) and the reference
result.py (content_id over definition + candidate rows + frontier);
Wave-F result.py's verified-loader machinery is SUPERSEDED (no control
plane / store in P2 — the fake evaluator carries no persisted evidence;
see CAPABILITY-LEDGER.md).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id

RESULT_DOMAIN = "veritx/optimization-result/v2"

OBJECTIVE_STATES = ("MEASURED", "UNMEASURABLE")


def _finite_number(value: Any) -> float | None:
    """float(value) iff value is a finite real number (bool excluded).

    Anything else -- missing, NaN, +/-inf, bool, string, object -- has no
    measured value and must become UNMEASURABLE, never a fabricated
    score.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    import math
    number = float(value)
    return number if math.isfinite(number) else None


def _requirement_report_id(report: dict[str, Any] | None) -> str | None:
    """Report identity (bare digest) or None when no report exists."""
    if report is None:
        return None
    from veritx_dse.application.requirements import report_identity
    return report_identity(report)


def _check_report_binding(ev: Any, report: Any, candidate_id: str) -> None:
    """Refuse a RequirementReport that does not belong to this evaluation.

    The report is the PRODUCT-requirement authority: its design_hash and
    every entry's performance_result_id must name this candidate's
    evaluation, and its carried identity must equal the re-derived
    canonical identity. A transplanted report can never be bound to
    another candidate's measurements (the only alternatives would be
    silently changing result identity or accepting foreign provenance —
    both forbidden).
    """
    if report is None:
        return
    from veritx_dse.application.requirements import report_identity
    if not isinstance(report, Mapping):
        raise OptimizationResultError(
            f"evaluator returned a non-mapping requirement_report "
            f"{type(report).__name__} for candidate {candidate_id!r}")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise OptimizationResultError(
            f"requirement_report for candidate {candidate_id!r} carries "
            f"no entries list — an empty stand-in is not a report")
    if ev.performance_result_id is None:
        raise OptimizationResultError(
            f"candidate {candidate_id!r} carries a requirement_report but "
            "no performance_result_id — the report cannot be bound to "
            "measurements")
    expected_design = ev.design_hash if ev.design_hash.startswith(
        "sha256:") else "sha256:" + ev.design_hash
    if report.get("design_hash") != expected_design:
        raise OptimizationResultError(
            f"requirement_report design_hash {report.get('design_hash')!r} "
            f"is not candidate {candidate_id!r}'s design "
            f"{expected_design!r} — refusing a transplanted report")
    if report.get("performance_result_id") != ev.performance_result_id:
        raise OptimizationResultError(
            f"requirement_report performance_result_id "
            f"{report.get('performance_result_id')!r} is not this "
            f"evaluation's {ev.performance_result_id!r} — refusing "
            "measurements transplanted from another candidate")
    for i, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or \
                entry.get("performance_result_id") != ev.performance_result_id:
            raise OptimizationResultError(
                f"requirement_report entries[{i}] does not bind this "
                f"evaluation's performance_result_id "
                f"{ev.performance_result_id!r} — refusing a report whose "
                "verdicts belong to another result")
    computed = report_identity(report)
    if ev.requirement_report_id is not None and \
            ev.requirement_report_id != computed:
        raise OptimizationResultError(
            f"evaluator-carried requirement_report_id "
            f"{ev.requirement_report_id!r} != re-derived report identity "
            f"{computed!r} for candidate {candidate_id!r} — refusing a "
            "forged report identity")


def _view_hash(bare: str) -> str:
    """Engine bare digest -> product-view ``sha256:`` identity.

    Idempotent: values that already carry the prefix pass through, so
    the boundary never double-prefixes.
    """
    if bare.startswith("sha256:"):
        return bare
    return "sha256:" + bare


class OptimizationResultError(ValueError):
    """Invalid optimization result state (fail-closed)."""


@dataclass(frozen=True)
class CandidateRecord:
    """One evaluated candidate with verdicts and Pareto membership.

    Binds the reason the candidate won or lost: compilation and
    evaluation status, performance_result_id, the product
    RequirementReport identity and pass state (product_* fields), the
    optimizer's own constraint verdicts/details (constraint_* fields),
    the measured objectives (objective_* fields) and the locked
    consequences. Engine hashes stay bare; views prefix at the boundary.
    """
    candidate_id: str
    guided_patch: dict[str, Any]
    design_hash: str  # bare engine digest, never prefixed here
    locked_consequences: dict[str, Any]
    evaluation_status: str
    objective_values: dict[str, float]
    objective_availability: dict[str, str]
    constraint_verdicts: dict[str, str]
    pareto_eligible: bool
    pareto_member: bool
    performance_result_id: str | None = None
    requirement_report_id: str | None = None
    product_requirements_satisfied: bool | None = None
    compilation_status: str = "COMPILED"
    product_requirement_details: tuple = ()
    constraint_details: tuple = ()
    objective_details: tuple = ()
    constraints_satisfied: bool | None = None


@dataclass(frozen=True)
class OptimizationResult:
    """Bound optimization outcome (in-memory proof carrier)."""
    base_design_hash: str
    definition: Any
    records: tuple[CandidateRecord, ...]
    pareto_ids: tuple[str, ...]
    selected_candidate_id: str | None
    selection_rationale: str | None

    def result_id(self) -> str:
        # Binds evaluation provenance, not just rounded objectives: two
        # authenticated evaluations with equal objective floats but
        # different performance_result_id, status, requirement bindings
        # or locked consequences hash differently. It must move when the
        # evaluation provenance moves.
        rows = [{
            "candidate_id": r.candidate_id,
            "guided_patch": {k: r.guided_patch[k]
                             for k in sorted(r.guided_patch)},
            "design_hash": r.design_hash,
            "evaluation_status": r.evaluation_status,
            "compilation_status": r.compilation_status,
            "performance_result_id": r.performance_result_id,
            "requirement_report_id": r.requirement_report_id,
            "product_requirements_satisfied":
                r.product_requirements_satisfied,
            "locked_consequences": {
                k: (sorted(v) if isinstance(v, list) else v)
                for k, v in sorted(r.locked_consequences.items())},
            "objective_values": {k: r.objective_values[k]
                                 for k in sorted(r.objective_values)},
            "objective_availability": {
                k: str(v)
                for k, v in sorted(r.objective_availability.items())},
            "constraint_verdicts": {
                k: str(v) for k, v in sorted(r.constraint_verdicts.items())},
            "product_requirement_details": [
                dict(d) for d in r.product_requirement_details],
            "constraint_details": [
                dict(d) for d in r.constraint_details],
            "objective_details": [dict(d) for d in r.objective_details],
            "constraints_satisfied": r.constraints_satisfied,
            "pareto_eligible": bool(r.pareto_eligible),
            "pareto_member": bool(r.pareto_member),
        } for r in sorted(self.records, key=lambda r: r.candidate_id)]
        return content_id(RESULT_DOMAIN, {
            "base_design_hash": self.base_design_hash,
            "definition_id": self.definition.definition_id(),
            "candidates": rows,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
        })

    def to_study_view(self, contract_version: int = 2) -> dict[str, Any]:
        """Emit the OptimizationStudyView.

        Contract v2 (default) keeps SATISFIED/VIOLATED/UNMEASURABLE
        distinct in ``constraint_verdicts``; contract v1 (opt-in, for
        callers pinning the frozen boolean-only shape) collapses
        UNMEASURABLE to false.
        """
        if contract_version not in (1, 2):
            raise OptimizationResultError(
                f"unknown OptimizationStudyView contract_version "
                f"{contract_version!r}; supported: 1, 2")
        defn = self.definition
        candidates = []
        for r in sorted(self.records, key=lambda r: r.candidate_id):
            evaluations: dict[str, Any] = {
                "design_hash": _view_hash(r.design_hash)}
            evaluations["performance_result_id"] = r.performance_result_id
            if contract_version == 2:
                # v2 preserves three-state semantics losslessly.
                verdicts: dict[str, Any] = dict(r.constraint_verdicts)
            else:
                # v1 is boolean-only: UNMEASURABLE collapses to false
                # (fail-closed means unmeasurable is never satisfied).
                # This projector is LOSSY BY DESIGN — the v1 booleans do
                # not preserve three-state semantics; the authoritative
                # v2 view does.
                verdicts = {
                    k: (v == "SATISFIED")
                    for k, v in r.constraint_verdicts.items()}
            candidates.append({
                "candidate_id": r.candidate_id,
                "guided_patch": dict(r.guided_patch),
                "locked_consequences": dict(r.locked_consequences),
                "evaluation_ids": evaluations,
                "objective_values": {k: float(v)
                                     for k, v in r.objective_values.items()},
                "constraint_verdicts": verdicts,
                "pareto_member": bool(r.pareto_member),
            })
        # ONE hash boundary (P1B rule): engine values are bare digests,
        # product views are sha256:-prefixed, converted HERE only.
        return {
            "contract_version": contract_version,
            "base_design_hash": _view_hash(self.base_design_hash),
            "definition": {
                "objectives": [o.metric for o in defn.objectives],
                "constraints": [f"{c.metric}{c.op}{c.threshold:g}"
                                for c in defn.constraints],
                "method": defn.method,
                "budget": dict(defn.budget),
                "seed": defn.seed,
                "domain": {p.name: list(p.values) for p in defn.domain},
            },
            "candidates": candidates,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "selection_rationale": self.selection_rationale,
        }


def _select(records: list[CandidateRecord], definition: Any,
            pareto_ids: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Selection among Pareto members: min first objective (direction-aware).

    Ties break by smallest candidate_id (deterministic). "none" policy
    selects nothing. No feasible Pareto member -> (None, rationale).
    """
    if definition.selection == "none":
        return None, "selection policy is none — no candidate selected"
    feasible_pareto = [r for r in records
                       if r.pareto_eligible
                       and r.candidate_id in set(pareto_ids)]
    for r in feasible_pareto:
        missing = [o.metric for o in definition.objectives
                   if o.metric not in r.objective_values
                   or r.objective_availability.get(o.metric) != "MEASURED"]
        if missing:
            raise OptimizationResultError(
                f"Pareto member {r.candidate_id!r} carries no measured "
                f"value for objective(s) {missing} — refusing selection "
                "over incomplete measurements")
    if not feasible_pareto:
        unmeasured = sorted({
            str(d.get("metric")) for r in records
            for d in r.objective_details
            if d.get("state") == "UNMEASURABLE"})
        if unmeasured:
            return None, (
                "no feasible Pareto candidate — nothing selected "
                f"(objectives not evidenced by evaluation: "
                f"{', '.join(unmeasured)})")
        return None, ("no feasible Pareto candidate — nothing selected "
                      "(all candidates violated a constraint, failed to "
                      "evaluate, or were unmeasurable)")
    first = definition.objectives[0]
    reverse = (first.direction == "MAX")
    if definition.selection == "lexicographic" and len(definition.objectives) > 1:
        def key(r: CandidateRecord):
            return tuple(
                (-r.objective_values[o.metric] if o.direction == "MAX"
                 else r.objective_values[o.metric])
                for o in definition.objectives) + (r.candidate_id,)
        ordered = sorted(feasible_pareto, key=key)
    else:
        ordered = sorted(
            feasible_pareto,
            key=lambda r: ((-(r.objective_values[first.metric])
                            if reverse else r.objective_values[first.metric]),
                           r.candidate_id))
    winner = ordered[0]
    tied = [r.candidate_id for r in ordered
            if r.objective_values[first.metric] ==
            winner.objective_values[first.metric]]
    rationale = (
        f"selected {winner.candidate_id} minimizing {first.metric} "
        f"({first.direction}) over {len(feasible_pareto)} Pareto candidate(s); "
        f"policy={definition.selection}; "
        f"values={{{', '.join(f'{k}={v:g}' for k, v in sorted(winner.objective_values.items()))}}}"
        + (f"; tie among {sorted(tied)} broken by smallest id"
           if len(tied) > 1 else ""))
    return winner.candidate_id, rationale


def _constraint_details(verdict_docs: dict[str, Any]) -> tuple:
    """Per-optimization-constraint bindings in canonical metric order:
    {metric, operator, required, measured, verdict, margin_or_excess,
    reason}. This is the auditable reason a candidate satisfied or lost
    the STUDY's constraints — a different authority from the product
    RequirementReport — and part of result_id."""
    out = []
    for metric in sorted(verdict_docs):
        d = verdict_docs[metric] or {}
        out.append({
            "metric": metric,
            "operator": d.get("operator"),
            "required": d.get("bound"),
            "measured": d.get("value"),
            "verdict": d.get("verdict"),
            "margin_or_excess": d.get("margin_or_excess"),
            "reason": d.get("reason"),
        })
    return tuple(out)


class Optimizer:
    """Deterministic optimize: search -> evaluate -> verdicts -> Pareto."""

    def optimize(self, base_request: Any, definition: Any,
                 evaluator: Any) -> OptimizationResult:
        from veritx_dse.application.requirements import report_passes

        from .candidate import candidate_id_for
        from .constraints import evaluate_all
        from .pareto import pareto_ids as _pareto_ids
        from .search import search_candidates
        base_hash = base_request.design_hash()
        candidates = search_candidates(base_request, definition)
        if not candidates:
            raise OptimizationResultError("search produced no candidates")
        records: list[CandidateRecord] = []
        feasible_values: dict[str, dict[str, float]] = {}
        for cand in candidates:
            # Identity stability: order never changes candidate identity.
            # Explicit conditionals (not assert) so production gates do not
            # vanish under python -O.
            if cand.candidate_id != candidate_id_for(
                    base_hash, cand.guided_patch):
                raise OptimizationResultError(
                    f"candidate identity drifted for {cand.guided_patch!r}: "
                    f"{cand.candidate_id!r} != re-derived "
                    f"{candidate_id_for(base_hash, cand.guided_patch)!r}")
            if cand.base_design_hash != base_hash:
                raise OptimizationResultError(
                    f"candidate base_design_hash {cand.base_design_hash!r} "
                    f"!= search base {base_hash!r} — execution order must "
                    "never change candidate identity")
            ev = evaluator.evaluate(cand)
            if ev.candidate_id != cand.candidate_id:
                raise OptimizationResultError(
                    f"evaluator returned {ev.candidate_id!r} for candidate "
                    f"{cand.candidate_id!r} — refusing transplanted evaluation")
            if ev.design_hash != cand.request.design_hash():
                raise OptimizationResultError(
                    f"evaluator design_hash {ev.design_hash!r} != candidate "
                    "request hash — refusing transplanted evaluation")
            # Product-requirement authority (separate from the optimizer's
            # constraint authority): a report is accepted only when it is
            # THIS candidate's report, and a binding failure makes the
            # candidate optimization-ineligible even though the backend
            # returned EVALUATED.
            report = ev.requirement_report
            _check_report_binding(ev, report, cand.candidate_id)
            product_satisfied: bool | None = None
            if report is not None:
                product_satisfied = report_passes(report)
            raw_values = ev.objective_values
            if not isinstance(raw_values, Mapping):
                raise OptimizationResultError(
                    f"evaluator returned non-mapping objective_values "
                    f"{type(raw_values).__name__} for candidate "
                    f"{cand.candidate_id!r}")
            # Measured values are real finite numbers only; a declared
            # objective without one is UNMEASURABLE (never 0, never
            # infinity, never a backend failure masquerading as a score).
            measured_all: dict[str, float] = {}
            invalid_values: dict[str, str] = {}
            for key, raw in raw_values.items():
                number = _finite_number(raw)
                if number is None:
                    invalid_values[str(key)] = repr(raw)
                else:
                    measured_all[str(key)] = number
            if ev.status == "EVALUATED":
                verdicts = evaluate_all(definition.constraints,
                                        measured_all)
            else:
                # No measured values: every declared binding is
                # UNMEASURABLE (never a pass), with its required bound
                # still recorded so the refusal is auditable.
                unmeasured = {}
                for c in (definition.constraints or []):
                    metric = c.metric if hasattr(c, "metric") else c["metric"]
                    op = c.op if hasattr(c, "op") else c["op"]
                    bound = (c.threshold if hasattr(c, "threshold")
                             else c["threshold"])
                    unmeasured[metric] = {
                        "metric": metric, "operator": op,
                        "bound": float(bound), "verdict": "UNMEASURABLE",
                        "value": None,
                        "reason": f"evaluation status {ev.status} — "
                                  "no measured value"}
                verdicts = {
                    "verdicts": unmeasured,
                    "feasible": (None if definition.constraints else False)}
                if not definition.constraints:
                    verdicts["feasible"] = False
            # Optimization-constraint authority (a DIFFERENT namespace
            # from the product RequirementReport above): pure tri-state
            # verdicts over this candidate's measured values.
            constraints_satisfied = verdicts["feasible"]
            constraint_verdicts = {
                k: str(v.get("verdict"))
                for k, v in verdicts["verdicts"].items()}
            constraint_details = _constraint_details(verdicts["verdicts"])
            # Every REQUESTED objective gets an explicit state. A missing,
            # non-finite or non-real value is UNMEASURABLE with its typed
            # reason; only MEASURED objectives may score or reach Pareto.
            objective_availability: dict[str, str] = {}
            objective_entries: list[dict[str, Any]] = []
            for o in definition.objectives:
                if ev.status != "EVALUATED":
                    state = "UNMEASURABLE"
                    reason = (f"evaluation status {ev.status} — "
                              "no measured value")
                elif o.metric in invalid_values:
                    state = "UNMEASURABLE"
                    reason = (f"objective {o.metric} value "
                              f"{invalid_values[o.metric]} is not a "
                              "finite real number")
                elif o.metric in measured_all:
                    state = "MEASURED"
                    reason = None
                else:
                    state = "UNMEASURABLE"
                    reason = (f"objective {o.metric} not evidenced by "
                              "evaluation")
                objective_availability[o.metric] = state
                if state != "MEASURED":
                    objective_entries.append({
                        "metric": o.metric,
                        "state": state,
                        "measured": None,
                        "reason": reason,
                    })
            for key in sorted(measured_all):
                objective_availability.setdefault(key, "MEASURED")
            objective_details = tuple(objective_entries)
            all_objectives_measured = all(
                objective_availability[o.metric] == "MEASURED"
                for o in definition.objectives)
            # Pareto input: backend success AND product binding
            # requirements pass AND every objective measured+finite AND
            # every hard constraint SATISFIED. Anything else is visible
            # and ineligible, never a fabricated score.
            eligible = (ev.status == "EVALUATED"
                        and constraints_satisfied is True
                        and product_satisfied is not False
                        and all_objectives_measured)
            pareto_member = False  # assigned after the frontier computes
            product_details = tuple(
                dict(e) for e in report.get("entries", [])) \
                if report is not None else ()
            record = CandidateRecord(
                candidate_id=cand.candidate_id,
                guided_patch=dict(cand.guided_patch),
                design_hash=ev.design_hash,
                locked_consequences=dict(ev.locked_consequences),
                evaluation_status=ev.status,
                objective_values=measured_all,
                objective_availability=objective_availability,
                constraint_verdicts=constraint_verdicts,
                pareto_eligible=eligible,
                pareto_member=pareto_member,
                performance_result_id=ev.performance_result_id,
                requirement_report_id=_requirement_report_id(report),
                product_requirements_satisfied=product_satisfied,
                compilation_status=getattr(
                    ev, "compilation_status", "COMPILED"),
                product_requirement_details=product_details,
                constraint_details=constraint_details,
                objective_details=objective_details,
                constraints_satisfied=constraints_satisfied,
            )
            records.append(record)
            if eligible:
                feasible_values[cand.candidate_id] = {
                    o.metric: measured_all[o.metric]
                    for o in definition.objectives}
        front = _pareto_ids(feasible_values, definition.objectives)
        front_set = set(front)
        records = [CandidateRecord(
            candidate_id=r.candidate_id, guided_patch=r.guided_patch,
            design_hash=r.design_hash,
            locked_consequences=r.locked_consequences,
            evaluation_status=r.evaluation_status,
            objective_values=r.objective_values,
            objective_availability=r.objective_availability,
            constraint_verdicts=r.constraint_verdicts,
            pareto_eligible=r.pareto_eligible,
            pareto_member=(r.candidate_id in front_set),
            performance_result_id=r.performance_result_id,
            requirement_report_id=r.requirement_report_id,
            product_requirements_satisfied=
                r.product_requirements_satisfied,
            compilation_status=r.compilation_status,
            product_requirement_details=r.product_requirement_details,
            constraint_details=r.constraint_details,
            objective_details=r.objective_details,
            constraints_satisfied=r.constraints_satisfied,
        ) for r in records]
        selected, rationale = _select(records, definition, front)
        return OptimizationResult(
            base_design_hash=base_hash,
            definition=definition,
            records=tuple(records),
            pareto_ids=tuple(front),
            selected_candidate_id=selected,
            selection_rationale=rationale,
        )


__all__ = [
    "RESULT_DOMAIN", "CandidateRecord", "OptimizationResult",
    "OptimizationResultError", "Optimizer",
]
