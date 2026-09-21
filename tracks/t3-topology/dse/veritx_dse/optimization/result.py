"""veritx_dse.optimization.result — OptimizationResult + Optimizer (P2).

OptimizationResult binds: base request identity, definition,
candidate/evaluation IDs, objective values, constraint verdicts, Pareto
membership, selection rationale. Execution order never changes
candidate identity (asserted by re-derivation).

Emits OptimizationStudyView per
contracts/srota/v1/optimization.study.view.v2.schema.json
(contract_version 2 by default; contract_version=1 keeps the frozen
boolean-only v1 shape for pinned callers).

Candidates whose evaluation evidences none of a declared objective's
metric are ineligible: they stay visible with a typed UNMEASURABLE
requirement_details entry, out of feasible_values and out of the Pareto
frontier (never a pareto.py KeyError).

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
    evaluation status, performance_result_id, per-requirement bindings
    ({metric, operator, required, measured, verdict}), the
    all-binding-satisfied flag, and the locked consequences. Engine
    hashes stay bare; views prefix at the boundary.
    """
    candidate_id: str
    guided_patch: dict[str, Any]
    design_hash: str  # bare engine digest, never prefixed here
    locked_consequences: dict[str, Any]
    evaluation_status: str
    objective_values: dict[str, float]
    constraint_verdicts: dict[str, bool | None]
    pareto_member: bool
    performance_result_id: str | None = None
    requirement_report_id: str | None = None
    product_requirements_satisfied: bool | None = None
    compilation_status: str = "COMPILED"
    requirement_details: tuple = ()
    all_binding_satisfied: bool | None = None


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
            "constraint_verdicts": {
                k: (None if v is None else bool(v))
                for k, v in sorted(r.constraint_verdicts.items())},
            "requirement_details": [{
                "metric": d.get("metric"),
                "operator": d.get("operator"),
                "required": d.get("required"),
                "measured": d.get("measured"),
                "verdict": d.get("verdict"),
            } for d in sorted(r.requirement_details,
                               key=lambda d: str(d.get("metric")))],
            "all_binding_satisfied": r.all_binding_satisfied,
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
                verdicts: dict[str, Any] = {
                    k: ("UNMEASURABLE" if v is None
                        else "SATISFIED" if v else "VIOLATED")
                    for k, v in r.constraint_verdicts.items()}
            else:
                # v1 is boolean-only: UNMEASURABLE collapses to false
                # (fail-closed means unmeasurable is never satisfied).
                # The full OptimizationResult retains the None
                # distinction; v2 projects it without loss.
                verdicts = {
                    k: (False if v is None else bool(v))
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
    feasible_pareto = [r for r in records if r.candidate_id in set(pareto_ids)]
    if not feasible_pareto:
        unmeasured = sorted({
            str(d.get("metric")) for r in records
            for d in r.requirement_details
            if d.get("verdict") == "UNMEASURABLE"
            and str(d.get("reason", "")).startswith("objective ")})
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


def _requirement_details(verdict_docs: dict[str, Any]) -> tuple:
    """Per-requirement bindings: {metric, operator, required, measured,
    verdict}, canonical metric order. This is the auditable reason a
    candidate passed or failed its bindings — and part of result_id."""
    out = []
    for metric in sorted(verdict_docs):
        d = verdict_docs[metric] or {}
        out.append({
            "metric": metric,
            "operator": d.get("operator"),
            "required": d.get("bound"),
            "measured": d.get("value"),
            "verdict": d.get("verdict"),
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
            assert cand.candidate_id == candidate_id_for(
                base_hash, cand.guided_patch), \
                f"candidate identity drifted for {cand.guided_patch!r}"
            assert cand.base_design_hash == base_hash
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
            if ev.status == "EVALUATED":
                verdicts = evaluate_all(definition.constraints,
                                        ev.objective_values)
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
            feasible = verdicts["feasible"]
            if product_satisfied is False:
                # Backend success alone is never optimization-eligible:
                # binding product requirements must pass.
                feasible = False
            details = _requirement_details(verdicts["verdicts"])
            unmeasured_objectives = tuple(
                o.metric for o in definition.objectives
                if o.metric not in ev.objective_values)
            if unmeasured_objectives:
                # An objective with no evidenced value cannot be scored:
                # the candidate is ineligible (visible, with a typed
                # UNMEASURABLE reason) and never reaches feasible_values
                # -- so pareto.py never indexes a missing metric.
                details = details + tuple({
                    "metric": metric,
                    "operator": None,
                    "required": None,
                    "measured": None,
                    "verdict": "UNMEASURABLE",
                    "reason": f"objective {metric} not evidenced by "
                              "evaluation",
                } for metric in unmeasured_objectives)
                feasible = False
            binding = feasible if isinstance(feasible, bool) else None
            pareto_member = False  # assigned after the frontier computes
            record = CandidateRecord(
                candidate_id=cand.candidate_id,
                guided_patch=dict(cand.guided_patch),
                design_hash=ev.design_hash,
                locked_consequences=dict(ev.locked_consequences),
                evaluation_status=ev.status,
                objective_values=dict(ev.objective_values),
                constraint_verdicts={
                    k: (None if v.get("verdict") == "UNMEASURABLE"
                        else bool(v.get("verdict") == "SATISFIED"))
                    for k, v in verdicts["verdicts"].items()},
                pareto_member=pareto_member,
                performance_result_id=ev.performance_result_id,
                requirement_report_id=_requirement_report_id(report),
                product_requirements_satisfied=product_satisfied,
                compilation_status=getattr(
                    ev, "compilation_status", "COMPILED"),
                requirement_details=details,
                all_binding_satisfied=binding,
            )
            records.append(record)
            if ev.status == "EVALUATED" and feasible is True:
                feasible_values[cand.candidate_id] = dict(ev.objective_values)
        front = _pareto_ids(feasible_values, definition.objectives)
        front_set = set(front)
        records = [CandidateRecord(
            candidate_id=r.candidate_id, guided_patch=r.guided_patch,
            design_hash=r.design_hash,
            locked_consequences=r.locked_consequences,
            evaluation_status=r.evaluation_status,
            objective_values=r.objective_values,
            constraint_verdicts=r.constraint_verdicts,
            pareto_member=(r.candidate_id in front_set),
            performance_result_id=r.performance_result_id,
            requirement_report_id=r.requirement_report_id,
            product_requirements_satisfied=
                r.product_requirements_satisfied,
            compilation_status=r.compilation_status,
            requirement_details=r.requirement_details,
            all_binding_satisfied=r.all_binding_satisfied,
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
