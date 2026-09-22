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
Worker B's verifier authority re-proved the carried authenticated proof
for this request (A4: the verifier's derived claims are the authority;
the `certified-backend` label alone admits nothing) AND every requested
objective/constraint metric has a registered producer over those claims
AND its binding product requirements pass AND every requested objective
is measured and finite AND every hard constraint is SATISFIED. For a
certified candidate the evaluator's `objective_values` never score —
registered metrics are extracted from the proof and an unregistered
requested metric is UNMEASURABLE/ineligible. Ineligible candidates stay
visible with typed reasons and never reach pareto.py's indexing (never
a KeyError).

Emits OptimizationStudyView per the authoritative
contracts/srota/v2/optimization.study.view.schema.json
(contract_version 2 by default; contract_version=1 keeps the frozen
boolean-only v1 shape at contracts/srota/v1/ for pinned callers — that
projector is explicitly LOSSY and never claims to preserve three-state
semantics).

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

from veritx_dse.application.authenticated_evaluation import (
    verify_authenticated_backend_evaluation,
)
from veritx_dse.core.artifact import content_id
from veritx_dse.optimization.evaluators import (
    AUTHORITY_CERTIFIED_BACKEND,
)

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


def _verified_certified_claims(cand: Any, ev: Any):
    """Bind a certified evaluation to Worker B's verifier authority (A4).

    The ``evaluation_authority`` label is descriptive, never proof. The
    optimizer imports and calls
    ``verify_authenticated_backend_evaluation(request, proof)`` — it does
    NOT duck-type the proof — and uses the returned derived claims as the
    authoritative facts. The port's carried RequirementReport must be the
    one the proof derives, and its performance_result_id must be the
    verified result's resource_id; anything else is a forgery and
    refuses hard.
    """
    from veritx_dse.application.requirements import report_identity
    from veritx_dse.core.errors import EvidenceInvalid, InvalidInput

    proof = getattr(ev, "authenticated_proof", None)
    try:
        claims = verify_authenticated_backend_evaluation(cand.request, proof)
    except (InvalidInput, EvidenceInvalid) as exc:
        raise OptimizationResultError(
            f"candidate {cand.candidate_id!r} claims certified authority "
            f"but its authenticated proof was refused "
            f"({type(exc).__name__}: {exc}) — the 'certified-backend' "
            f"label is not proof; a verified performance result with an "
            f"authenticated evidence chain is required") from exc
    report = getattr(claims, "requirement_report", None)
    verified = getattr(claims, "verified_result", None)
    if not isinstance(report, Mapping) or verified is None:
        raise OptimizationResultError(
            f"Worker B's verifier returned claims for "
            f"{cand.candidate_id!r} without a RequirementReport and "
            f"verified result — refusing unverifiable derived claims")
    carried = ev.requirement_report
    if carried is None or report_identity(carried) != report_identity(report):
        raise OptimizationResultError(
            f"candidate {cand.candidate_id!r} carries a "
            f"RequirementReport that is not the one the authenticated "
            f"proof derives — refusing a fabricated or transplanted "
            f"report")
    result_id = getattr(claims, "performance_result_id", None)
    if not isinstance(result_id, str) or not result_id:
        raise OptimizationResultError(
            f"the authenticated proof for {cand.candidate_id!r} carries "
            f"a verified result with no resource_id — refusing an "
            f"unbindable proof")
    if ev.performance_result_id != result_id:
        raise OptimizationResultError(
            f"candidate {cand.candidate_id!r} carries "
            f"performance_result_id {ev.performance_result_id!r} but its "
            f"authenticated proof is {result_id!r} — refusing a made-up "
            f"result id")
    return claims, report


def _has_metric_authority(metric: str) -> bool:
    """Is there a registered producer for this metric? (A4 gate)."""
    from .metric_authority import registered_metric_authorities
    return metric in registered_metric_authorities()


def _authoritative_metrics(ev: Any, definition: Any, claims: Any,
                           port_measured: dict[str, float],
                           port_invalid: dict[str, str],
                           ) -> dict[str, float]:
    """Registered metrics extracted from the verified claims (A4/R3).

    The verifier returns authenticated PRIMITIVES; optimization runs the
    registered producers over ``claims.verified_result`` afterwards
    (evidence truth never depends upward on optimization). There is NO
    fallback to the evaluator's ``objective_values``: a registered metric
    the evaluator carried with a different (or non-finite) value refuses;
    a registered metric the claims do not evidence is UNMEASURABLE and
    the evaluator's number is ignored.
    """
    from .metric_authority import (
        extract_authoritative_metrics,
        registered_metric_authorities,
    )

    verified = getattr(claims, "verified_result", None)
    if verified is None:
        raise OptimizationResultError(
            f"Worker B's verifier returned claims for "
            f"{ev.candidate_id!r} without a verified result — refusing "
            f"unverifiable derived claims")
    derived = extract_authoritative_metrics(verified)
    needed = {o.metric for o in definition.objectives} | \
        {c.metric for c in (definition.constraints or [])}
    measured_all: dict[str, float] = {}
    for metric in sorted(needed):
        value = _finite_number(derived.get(metric))
        if value is not None:
            measured_all[metric] = value
    for metric in registered_metric_authorities():
        if metric not in port_measured and metric not in port_invalid:
            continue
        authoritative = _finite_number(derived.get(metric))
        if authoritative is None:
            # The proof does not evidence a finite value for this
            # registered metric: it is UNMEASURABLE and the evaluator's
            # number is ignored, never used.
            continue
        if metric in port_invalid:
            raise OptimizationResultError(
                f"certified evaluation for {ev.candidate_id!r} reports "
                f"registered metric {metric!r} as "
                f"{port_invalid[metric]} while the authenticated proof "
                f"evidences {authoritative!r} — refusing a misreported "
                f"metric")
        if port_measured[metric] != authoritative:
            raise OptimizationResultError(
                f"certified evaluation for {ev.candidate_id!r} reports "
                f"registered metric {metric!r}={port_measured[metric]!r} "
                f"but the authenticated proof evidences "
                f"{authoritative!r} — refusing a misreported metric")
    return measured_all


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
    evaluation_authority: str | None = None
    evaluation_reason: str | None = None
    compilation_status: str = "COMPILED"
    product_requirement_details: tuple = ()
    constraint_details: tuple = ()
    objective_details: tuple = ()
    constraints_satisfied: bool | None = None
    eligibility_reason: str | None = None


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
            "evaluation_reason": r.evaluation_reason,
            "compilation_status": r.compilation_status,
            "performance_result_id": r.performance_result_id,
            "requirement_report_id": r.requirement_report_id,
            "product_requirements_satisfied":
                r.product_requirements_satisfied,
            "evaluation_authority": r.evaluation_authority,
            "eligibility_reason": r.eligibility_reason,
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

    def _definition_view_v1(self) -> dict[str, Any]:
        """LOSSY v1 definition projection (bare metric strings)."""
        defn = self.definition
        return {
            "objectives": [o.metric for o in defn.objectives],
            "constraints": [f"{c.metric}{c.op}{c.threshold:g}"
                            for c in defn.constraints],
            "method": defn.method,
            "budget": dict(defn.budget),
            "seed": defn.seed,
            "domain": {p.name: list(p.values) for p in defn.domain},
        }

    def _definition_view_v2(self) -> dict[str, Any]:
        """Lossless v2 definition projection.

        Identity (`definition_id`), objective direction (MIN/MAX),
        constraint operator and threshold, search method and selection
        policy are all explicit — a consumer never has to infer
        semantics from bare metric strings.
        """
        defn = self.definition
        return {
            "definition_id": defn.definition_id(),
            "objectives": [{"metric": o.metric, "direction": o.direction}
                           for o in defn.objectives],
            "constraints": [{"metric": c.metric, "op": c.op,
                             "threshold": c.threshold}
                            for c in defn.constraints],
            "method": defn.method,
            "selection": defn.selection,
            "budget": dict(defn.budget),
            "seed": defn.seed,
            "domain": {p.name: list(p.values) for p in defn.domain},
        }

    def _to_study_view_v2(self) -> dict[str, Any]:
        """Authoritative v2 projector (contract_version 2).

        Keeps the three authorities separate and lossless: product
        requirement identity/pass state, optimization constraint
        tri-state verdicts, and objective availability. ONE hash
        boundary (P1B rule): engine values are bare digests, product
        views are sha256:-prefixed, converted HERE only.
        """
        candidates = []
        for r in sorted(self.records, key=lambda r: r.candidate_id):
            candidates.append({
                "candidate_id": r.candidate_id,
                "guided_patch": dict(r.guided_patch),
                "locked_consequences": dict(r.locked_consequences),
                "evaluation_ids": {
                    "design_hash": _view_hash(r.design_hash),
                    "performance_result_id": r.performance_result_id,
                    "requirement_report_id": r.requirement_report_id,
                },
                "product_requirements": {
                    "satisfied": r.product_requirements_satisfied,
                    "verdicts": [dict(d)
                                 for d in r.product_requirement_details],
                },
                "objective_values": {k: float(v)
                                     for k, v in r.objective_values.items()},
                "objective_availability": dict(r.objective_availability),
                "constraint_verdicts": dict(r.constraint_verdicts),
                "evaluation_authority": r.evaluation_authority,
                "compilation_status": r.compilation_status,
                "evaluation_status": r.evaluation_status,
                "evaluation_reason": r.evaluation_reason,
                "eligibility_reason": r.eligibility_reason,
                "pareto_eligible": bool(r.pareto_eligible),
                "pareto_member": bool(r.pareto_member),
            })
        return {
            "contract_version": 2,
            "optimization_result_id": self.result_id(),
            "base_design_hash": _view_hash(self.base_design_hash),
            "definition": self._definition_view_v2(),
            "candidates": candidates,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "selection_rationale": self.selection_rationale,
        }

    def _to_study_view_v1(self) -> dict[str, Any]:
        """LOSSY v1 compatibility projector (contract_version 1).

        Frozen boolean-only shape for pinned callers. UNMEASURABLE
        collapses to false (fail-closed: unmeasurable is never
        satisfied) and the v2 availability/product provenance fields are
        absent — these booleans do NOT preserve three-state semantics;
        callers that need the distinction must consume v2.
        """
        candidates = []
        for r in sorted(self.records, key=lambda r: r.candidate_id):
            candidates.append({
                "candidate_id": r.candidate_id,
                "guided_patch": dict(r.guided_patch),
                "locked_consequences": dict(r.locked_consequences),
                "evaluation_ids": {
                    "design_hash": _view_hash(r.design_hash),
                    "performance_result_id": r.performance_result_id,
                },
                "objective_values": {k: float(v)
                                     for k, v in r.objective_values.items()},
                "constraint_verdicts": {
                    k: (v == "SATISFIED")
                    for k, v in r.constraint_verdicts.items()},
                "pareto_member": bool(r.pareto_member),
            })
        return {
            "contract_version": 1,
            "base_design_hash": _view_hash(self.base_design_hash),
            "definition": self._definition_view_v1(),
            "candidates": candidates,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "selection_rationale": self.selection_rationale,
        }

    def to_study_view(self, contract_version: int = 2) -> dict[str, Any]:
        """Emit the OptimizationStudyView.

        Contract v2 (default, authoritative) keeps the product /
        constraint / objective authorities separate and preserves
        SATISFIED/VIOLATED/UNMEASURABLE losslessly. Contract v1 is the
        explicitly-named LOSSY compatibility projector.
        """
        if contract_version == 2:
            return self._to_study_view_v2()
        if contract_version == 1:
            return self._to_study_view_v1()
        raise OptimizationResultError(
            f"unknown OptimizationStudyView contract_version "
            f"{contract_version!r}; supported: 1, 2")


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
        reasons = sorted({str(r.eligibility_reason) for r in records
                          if r.eligibility_reason})
        if reasons:
            return None, ("no feasible Pareto candidate — nothing "
                          "selected (ineligible: " + "; ".join(reasons) +
                          ")")
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
            authority = getattr(ev, "evaluation_authority", None)
            claims = None
            certified_claim = (
                authority == AUTHORITY_CERTIFIED_BACKEND
                and ev.status == "EVALUATED")
            if certified_claim:
                # A4: import and call Worker B's verifier authority; the
                # derived claims (and the report they derive) are the only
                # authoritative facts. Never duck-type the proof.
                claims, report = _verified_certified_claims(cand, ev)
            else:
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
            if claims is not None:
                # A4: certified metrics come ONLY from the registered
                # producers over the derived claims; the evaluator's
                # objective_values never score (a registered-metric
                # misreport refuses).
                measured_all = _authoritative_metrics(
                    ev, definition, claims, measured_all, invalid_values)
                invalid_values = {}
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
                elif claims is not None and not _has_metric_authority(
                        o.metric):
                    state = "UNMEASURABLE"
                    reason = (f"objective {o.metric} has no registered "
                              f"metric authority over the authenticated "
                              f"proof")
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
                              "the authenticated proof" if claims is not None
                              else f"objective {o.metric} not evidenced "
                                   "by evaluation")
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
            # Pareto input (authoritative): a CERTIFIED-BACKEND evaluation
            # succeeded AND its verified boundary was independently
            # re-derived (A3) AND a product RequirementReport is bound and
            # passing AND every objective measured+finite AND every hard
            # constraint SATISFIED. Anything else is visible and
            # ineligible with a typed reason, never a fabricated score —
            # analytic/fake doubles can never masquerade as authority.
            eligibility_reasons: list[str] = []
            if ev.status != "EVALUATED":
                eligibility_reasons.append(f"evaluation status {ev.status}")
            if authority != AUTHORITY_CERTIFIED_BACKEND:
                eligibility_reasons.append(
                    f"evaluation authority {authority!r} is not "
                    f"{AUTHORITY_CERTIFIED_BACKEND!r} — non-certified "
                    "(analytic/fake) evaluations are never "
                    "optimization-eligible")
            if report is None:
                eligibility_reasons.append(
                    "no product RequirementReport is bound — product "
                    "requirements cannot be shown to pass")
            if ev.performance_result_id is None:
                eligibility_reasons.append(
                    "no performance_result_id is bound")
            elif str(ev.performance_result_id).startswith("fake:"):
                eligibility_reasons.append(
                    "performance_result_id is a fake result, not "
                    "authenticated backend evidence")
            if report is not None and product_satisfied is not True:
                eligibility_reasons.append(
                    "binding product requirements are not satisfied")
            if not all_objectives_measured:
                missing = [o.metric for o in definition.objectives
                           if objective_availability[o.metric]
                           != "MEASURED"]
                eligibility_reasons.append(
                    f"requested objectives not measured: "
                    f"{', '.join(missing)}")
            if constraints_satisfied is not True:
                eligibility_reasons.append(
                    "hard constraints are not all SATISFIED")
            if claims is not None:
                # A4: every requested objective AND constraint metric must
                # have a registered producer over the derived claims.
                needed = sorted(
                    {o.metric for o in definition.objectives} |
                    {c.metric for c in (definition.constraints or [])})
                missing_authority = [m for m in needed
                                     if not _has_metric_authority(m)]
                if missing_authority:
                    eligibility_reasons.append(
                        "metric(s) without a registered metric authority "
                        "over the authenticated proof: "
                        + ", ".join(missing_authority))
            eligible = not eligibility_reasons
            eligibility_reason = ("; ".join(eligibility_reasons)
                                  if eligibility_reasons else None)
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
                evaluation_authority=authority,
                evaluation_reason=getattr(ev, "error", None),
                compilation_status=getattr(
                    ev, "compilation_status", "COMPILED"),
                product_requirement_details=product_details,
                constraint_details=constraint_details,
                objective_details=objective_details,
                constraints_satisfied=constraints_satisfied,
                eligibility_reason=eligibility_reason,
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
            evaluation_authority=r.evaluation_authority,
            evaluation_reason=r.evaluation_reason,
            compilation_status=r.compilation_status,
            product_requirement_details=r.product_requirement_details,
            constraint_details=r.constraint_details,
            objective_details=r.objective_details,
            constraints_satisfied=r.constraints_satisfied,
            eligibility_reason=r.eligibility_reason,
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
