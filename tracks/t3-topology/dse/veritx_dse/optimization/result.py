"""veritx_dse.optimization.result — OptimizationResult + Optimizer (P2).

Rationale: docs/decisions/modules/optimization.md
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.application.authenticated_evaluation import (
    verify_authenticated_backend_evaluation,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.core.artifact import content_id
from veritx_dse.optimization.evaluators import (
    AUTHORITY_CERTIFIED_BACKEND,
)
from veritx_dse.optimization.metric_registry import (
    CERTIFIED_METRIC_REGISTRY,
    CertifiedMetricRegistry,
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

Rationale: docs/decisions/modules/optimization.md
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


RESULT_CLASS_CERTIFIED = "CERTIFIED_PRODUCT"
RESULT_CLASS_ANALYTIC = "ANALYTIC_RESEARCH"


@dataclass(frozen=True)
class CertifiedBackendConfig:
    """Inputs for the optimizer-owned certified evaluator (R1/C3).

Rationale: docs/decisions/modules/optimization.md
    """

    binary: Any
    run_root: Any
    network_clock_hz: int | None = None
    timeout_s: int = 300
    repo_root: Any = None
    astra_binary: Any = None
    ramulator_vendor_dir: Any = None
    ramulator_python: str | None = None


def _make_real_certified_evaluator(config: CertifiedBackendConfig,
                                   definition: Any | None = None) -> Any:
    """Module-private, non-overridable certified evaluator factory (C1).

Rationale: docs/decisions/modules/optimization.md
    """
    from .real_evaluator import RealCandidateEvaluator
    return RealCandidateEvaluator(
        binary=config.binary,
        run_root=config.run_root,
        network_clock_hz=config.network_clock_hz,
        timeout_s=config.timeout_s,
        repo_root=config.repo_root,
        astra_binary=config.astra_binary,
        ramulator_vendor_dir=config.ramulator_vendor_dir,
        ramulator_python=config.ramulator_python,
        objectives=(None if definition is None
                    else tuple(definition.objectives)),
        require_quiescence=True)


def _verified_certified_claims(cand: Any, ev: Any):
    """Bind a certified evaluation to Worker B's verifier authority (A4).

Rationale: docs/decisions/modules/optimization.md
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


def _has_metric_authority(registry: Any, metric: str) -> bool:
    """Does the frozen certified registry carry this metric? (A4/R2)."""
    return isinstance(registry, CertifiedMetricRegistry) and \
        registry.has_metric(metric)


def _objective_question(objective: Any) -> EvaluationQuestion:
    """The federation question an objective reads (legacy default: network).

    Objectives constructed before the evaluation-policy extension carry
    no question attribute; they mean NETWORK_COMPLETION (the legacy
    BookSim-only objective) — never an unknown.
    """
    question = getattr(objective, "question", None)
    if question is None:
        return EvaluationQuestion.NETWORK_COMPLETION
    if isinstance(question, EvaluationQuestion):
        return question
    raise OptimizationResultError(
        f"objective {getattr(objective, 'metric', objective)!r} carries "
        f"a non-question evaluation policy {question!r} — refusing an "
        f"objective that names no federation question")


def _requirement_applicability(req: Any) -> str:
    """Closed applicability for one request requirement (V2 or V3).

    An explicit RequirementApplicability wins; legacy requirements
    without the field derive it: a declared bound applies, an empty
    one does not. Returns the canonical "APPLICABLE" /
    "NOT_APPLICABLE" / "NOT_EVALUATED" string.
    """
    from veritx_dse.model.compile_model import RequirementApplicability
    explicit = getattr(req, "applicability", None)
    if explicit is None:
        declares = (getattr(req, "latency_ceiling_cycles", None)
                    is not None
                    or getattr(req, "bandwidth_floor_gbps", None)
                    is not None)
        return "APPLICABLE" if declares else "NOT_APPLICABLE"
    if isinstance(explicit, RequirementApplicability):
        return explicit.value
    text = str(explicit)
    if text in ("APPLICABLE", "NOT_APPLICABLE", "NOT_EVALUATED"):
        return text
    raise OptimizationResultError(
        f"requirement carries unknown applicability {explicit!r} — "
        "refusing an applicability outside the closed vocabulary")


def _requirement_evidence_question(req: Any) -> Any | None:
    """The federation question whose evidence can answer a requirement.

Rationale: docs/decisions/modules/optimization.md
    """
    from veritx_dse.application.evaluation_question import (
        EvaluationQuestion,
    )
    if getattr(req, "latency_ceiling_cycles", None) is not None or \
            getattr(req, "bandwidth_floor_gbps", None) is not None:
        return EvaluationQuestion.NETWORK_COMPLETION
    return None


def _study_answerable_binding_requirements(
        request: Any, definition: Any) -> tuple[list[Any], list[Any]]:
    """Split applicable-binding requirements by study answerability.

Rationale: docs/decisions/modules/optimization.md
    """
    applicable, waived = _applicable_binding_requirements(request)
    try:
        study_questions = {_objective_question(o)
                           for o in definition.objectives}
    except Exception:
        return applicable, []
    if not study_questions:
        return applicable, []
    answerable: list[Any] = []
    out_of_scope: list[Any] = []
    for req in applicable:
        if _requirement_applicability(req) == "NOT_EVALUATED":
            answerable.append(req)
            continue
        needed = _requirement_evidence_question(req)
        if needed is None or needed in study_questions:
            answerable.append(req)
        else:
            out_of_scope.append(req)
    return answerable, out_of_scope


def _applicable_binding_requirements(
        request: Any) -> tuple[list[Any], list[Any]]:
    """Split request requirements into applicable-binding vs waived.

Rationale: docs/decisions/modules/optimization.md
    """
    applicable: list[Any] = []
    waived: list[Any] = []
    for req in getattr(request, "requirements", None) or ():
        if not getattr(req, "binding", False):
            continue
        applicability = _requirement_applicability(req)
        if applicability == "NOT_APPLICABLE":
            waived.append(req)
        else:
            applicable.append(req)
    return applicable, waived


def _federated_objective_metrics(ev: Any, definition: Any,
                                 port_measured: dict[str, float],
                                 port_invalid: dict[str, str],
                                 ) -> tuple[dict[str, float], set[str]]:
    """Re-derive federated values from carried analyses.

Rationale: docs/decisions/modules/optimization.md
    """
    measured: dict[str, float] = {}
    federated_keys: set[str] = set()
    analyses = getattr(ev, "federated_analyses", None) or ()
    if not analyses:
        return measured, federated_keys
    by_question: dict[Any, Any] = {}
    for row in analyses:
        by_question.setdefault(getattr(row, "question", None), row)

    def _check(metric: str, derived: float, where: str) -> None:
        if metric in port_invalid:
            raise OptimizationResultError(
                f"certified evaluation for {ev.candidate_id!r} reports "
                f"federated metric {metric!r} as "
                f"{port_invalid[metric]} while {where} evidences "
                f"{derived!r} — refusing a misreported metric")
        if metric in port_measured and port_measured[metric] != derived:
            raise OptimizationResultError(
                f"certified evaluation for {ev.candidate_id!r} reports "
                f"federated metric {metric!r}={port_measured[metric]!r} "
                f"but {where} evidences {derived!r} — refusing a "
                f"misreported metric")

    def _scalar(row: Any, metric: str) -> Any | None:
        envelope = getattr(row, "normalized_evidence", None)
        if getattr(row, "status", None) != "EVALUATED" or envelope is None:
            return None
        if not getattr(row, "qualification", None) or \
                not getattr(row, "native_evidence_id", None):
            return None
        found = [m for m in envelope.metrics
                 if m.key == metric and m.dimensions == ()]
        return found[0] if found else None

    for objective in definition.objectives:
        metric = getattr(objective, "metric", None)
        question = _objective_question(objective)
        if question is EvaluationQuestion.NETWORK_COMPLETION:
            continue
        row = by_question.get(question)
        if row is None:
            continue
        constraint = getattr(objective, "backend_id", None)
        if constraint is not None and \
                getattr(row, "backend_id", None) != constraint:
            continue
        found = _scalar(row, metric)
        if found is None:
            continue
        derived = float(found.value)
        _check(metric, derived, f"the {question.value} evidence")
        measured[metric] = derived
        federated_keys.add(metric)
    for constraint_def in (definition.constraints or []):
        metric = getattr(constraint_def, "metric", None)
        if metric in measured or not isinstance(metric, str):
            continue
        rows = [(q, row) for q, row in by_question.items()
                if q is not EvaluationQuestion.NETWORK_COMPLETION
                and _scalar(row, metric) is not None]
        # Zero — or several models evidencing the same key — binds
        # nothing: a constraint never guesses across models.
        if len(rows) != 1:
            continue
        question, row = rows[0]
        derived = float(_scalar(row, metric).value)
        _check(metric, derived, f"the {question.value} evidence")
        measured[metric] = derived
        federated_keys.add(metric)
    return measured, federated_keys


def _federated_metric_sources(
        ev: Any) -> dict[str, list[tuple[Any, float]]]:
    """Per-metric evidencing sources across non-network analyses.

Rationale: docs/decisions/modules/optimization.md
    """
    sources: dict[str, list[tuple[Any, float]]] = {}
    for row in getattr(ev, "federated_analyses", None) or ():
        question = getattr(row, "question", None)
        if question is EvaluationQuestion.NETWORK_COMPLETION:
            continue
        if getattr(row, "status", None) != "EVALUATED":
            continue
        envelope = getattr(row, "normalized_evidence", None)
        if envelope is None:
            continue
        if not getattr(row, "qualification", None) or \
                not getattr(row, "native_evidence_id", None):
            continue
        seen: set[str] = set()
        for m in getattr(envelope, "metrics", None) or ():
            key = getattr(m, "key", None)
            if not key or key in seen:
                continue
            if getattr(m, "dimensions", None) != ():
                continue
            try:
                value = float(getattr(m, "value", None))
            except (TypeError, ValueError):
                continue
            import math
            if not math.isfinite(value):
                continue
            seen.add(key)
            sources.setdefault(key, []).append((question, value))
    return sources


def _resolve_constraint_values(
        definition: Any, measured_all: dict[str, float], registry: Any,
        claims: Any, sources: dict[str, list[tuple[Any, float]]],
        ) -> tuple[dict[str, float], dict[str, str]]:
    """Scope every hard constraint to exactly one semantic source.

Rationale: docs/decisions/modules/optimization.md
    """
    resolved: dict[str, float] = {}
    unresolved: dict[str, str] = {}
    proof_keys = set()
    if claims is not None:
        proof_keys = {m for m in measured_all
                      if registry.has_metric(m)
                      and registry.is_measured(m)}
    for con in definition.constraints or []:
        metric = con.metric if hasattr(con, "metric") else con["metric"]
        candidates: list[tuple[str, float]] = []
        if metric in proof_keys and metric in measured_all:
            candidates.append(("NETWORK_COMPLETION",
                               measured_all[metric]))
        for question, value in sources.get(metric, []):
            name = (question.value if isinstance(
                question, EvaluationQuestion) else str(question))
            candidates.append((name, value))
        if len(candidates) == 1:
            resolved[metric] = candidates[0][1]
        elif not candidates:
            unresolved[metric] = (
                f"constraint metric {metric!r} is not evidenced by "
                "any semantic source (verified proof or federated "
                "envelope) — unmeasured, never guessed")
        else:
            names = sorted({name for name, _ in candidates})
            unresolved[metric] = (
                f"constraint metric {metric!r} is evidenced by "
                f"{len(candidates)} semantic sources "
                f"({', '.join(names)}) — refusing to guess across "
                "models")
    return resolved, unresolved


def _authentic_federated_source(ev: Any, metric: str,
                                question: Any) -> Any | None:
    """The native evidence id backing one non-network objective.

    Returns the native id iff an EVALUATED analysis for exactly this
    question carries an envelope, a qualification and a native evidence
    id evidencing the dimension-free metric — else None (values without
    evidence never reach Pareto, however finite).
    """
    for row in getattr(ev, "federated_analyses", None) or ():
        if getattr(row, "question", None) is not question:
            continue
        if getattr(row, "status", None) != "EVALUATED":
            continue
        envelope = getattr(row, "normalized_evidence", None)
        if envelope is None:
            continue
        if not getattr(row, "qualification", None):
            continue
        native = getattr(row, "native_evidence_id", None)
        if not native:
            continue
        for m in getattr(envelope, "metrics", None) or ():
            if getattr(m, "key", None) == metric and \
                    getattr(m, "dimensions", None) == ():
                return native
    return None


def _provenance_docs(ev: Any, measured: dict[str, float]
                     ) -> tuple[dict[str, Any], ...]:
    """Canonical per-objective provenance rows for a candidate record.

    Only bound (measured) metrics carry provenance, in metric order. A
    float without provenance never reaches the view as an objective.
    """
    carried = getattr(ev, "objective_provenance", None) or {}
    docs = []
    for metric in sorted(measured):
        row = carried.get(metric)
        if row is None:
            continue
        docs.append(row.to_dict() if hasattr(row, "to_dict") else dict(row))
    return tuple(docs)


def _enforce_federated_comparability(
        records: list["CandidateRecord"], definition: Any
        ) -> list["CandidateRecord"]:
    """Pareto comparability over model fidelity (Step 4).

Rationale: docs/decisions/modules/optimization.md
    """
    import dataclasses as _dc
    eligible = [r for r in records if r.pareto_eligible]
    if len(eligible) < 2:
        return records
    reference = {o.metric if hasattr(o, "metric") else o["metric"]:
                 _objective_question(o) for o in definition.objectives}
    prov_index = {}
    for record in eligible:
        per_metric: dict[str, dict[str, Any]] = {}
        for doc in record.objective_provenance:
            per_metric[doc.get("metric_key")] = doc
        prov_index[record.candidate_id] = per_metric
    demotions: dict[str, str] = {}
    for objective in definition.objectives:
        metric = objective.metric if hasattr(objective, "metric") \
            else objective["metric"]
        question = reference[metric]
        constraint = getattr(objective, "backend_id", None)
        first_signature: tuple | None = None
        first_id: str | None = None
        for record in eligible:
            if record.candidate_id in demotions:
                continue
            doc = prov_index[record.candidate_id].get(metric)
            if doc is None:
                continue
            if doc.get("question") != question.value:
                demotions[record.candidate_id] = (
                    f"objective {metric!r} answers "
                    f"{doc.get('question')!r}, not the definition's "
                    f"{question.value!r} — different semantic families "
                    f"never share an objective axis")
                continue
            if constraint is not None and \
                    doc.get("backend_id") != constraint:
                demotions[record.candidate_id] = (
                    f"objective {metric!r} was produced by "
                    f"{doc.get('backend_id')!r}, violating the "
                    f"definition backend constraint {constraint!r}")
                continue
            if not doc.get("native_evidence_id"):
                demotions[record.candidate_id] = (
                    f"objective {metric!r} carries no native evidence "
                    f"id — nothing comparable was measured")
                continue
            if not doc.get("qualification"):
                demotions[record.candidate_id] = (
                    f"objective {metric!r} carries no qualification — "
                    f"an unqualified measurement never compares")
                continue
            signature = (doc.get("unit"), doc.get("model_fidelity"),
                         doc.get("qualification"))
            if first_signature is None:
                first_signature, first_id = signature, \
                    record.candidate_id
            elif signature != first_signature:
                demotions[record.candidate_id] = (
                    f"objective {metric!r} is not comparable across the "
                    f"eligible set (unit/fidelity/qualification "
                    f"{signature!r} vs {first_id!r}'s "
                    f"{first_signature!r}) — MODEL DIFFERENCE, not a "
                    f"performance difference")
    if not demotions:
        return records
    out = []
    for record in records:
        reason = demotions.get(record.candidate_id)
        if reason is None or not record.pareto_eligible:
            out.append(record)
            continue
        prior = record.eligibility_reason
        out.append(_dc.replace(
            record, pareto_eligible=False,
            eligibility_reason=((prior + "; " if prior else "") + reason)))
    return out


def _authoritative_metrics(ev: Any, definition: Any, claims: Any,
                           port_measured: dict[str, float],
                           port_invalid: dict[str, str],
                           registry: Any,
                           ) -> dict[str, float]:
    """Registered metrics extracted from the verified claims (A4/R2/R3).

Rationale: docs/decisions/modules/optimization.md
    """
    if not isinstance(registry, CertifiedMetricRegistry):
        raise OptimizationResultError(
            f"certified extraction requires a frozen "
            f"CertifiedMetricRegistry, got {type(registry).__name__} — "
            f"experimental/plugin registries can never yield "
            f"CERTIFIED_PRODUCT results")
    verified = getattr(claims, "verified_result", None)
    if verified is None:
        raise OptimizationResultError(
            f"Worker B's verifier returned claims for "
            f"{ev.candidate_id!r} without a verified result — refusing "
            f"unverifiable derived claims")
    derived = registry.extract_all(verified)
    needed = {o.metric for o in definition.objectives} | \
        {c.metric for c in (definition.constraints or [])}
    measured_all: dict[str, float] = {}
    for metric in sorted(needed):
        value = _finite_number(derived.get(metric))
        if value is not None:
            measured_all[metric] = value
    for metric in registry.metric_names():
        if metric not in port_measured and metric not in port_invalid:
            continue
        authoritative = _finite_number(derived.get(metric))
        if authoritative is None:
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

Rationale: docs/decisions/modules/optimization.md
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
    objective_provenance: tuple = ()
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
    result_class: str = RESULT_CLASS_ANALYTIC
    metric_registry_id: str | None = None
    metric_registry_version: str | None = None
    completeness: Any = None

    def result_id(self) -> str:
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
            "objective_provenance": [dict(d)
                                     for d in r.objective_provenance],
            "constraints_satisfied": r.constraints_satisfied,
            "pareto_eligible": bool(r.pareto_eligible),
            "pareto_member": bool(r.pareto_member),
        } for r in sorted(self.records, key=lambda r: r.candidate_id)]
        return content_id(RESULT_DOMAIN, {
            "base_design_hash": self.base_design_hash,
            "definition_id": self.definition.definition_id(),
            "result_class": self.result_class,
            "metric_registry_id": self.metric_registry_id,
            "metric_registry_version": self.metric_registry_version,
            "candidates": rows,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "completeness": (self.completeness.to_dict()
                             if self.completeness is not None else None),
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

Rationale: docs/decisions/modules/optimization.md
        """
        defn = self.definition
        return {
            "definition_id": defn.definition_id(),
            "objectives": [{"metric": o.metric, "direction": o.direction,
                            "question": _objective_question(o).value,
                            "backend_id": getattr(o, "backend_id", None)}
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

Rationale: docs/decisions/modules/optimization.md
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
                "objective_provenance": [dict(d)
                                         for d in r.objective_provenance],
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
            "result_class": self.result_class,
            "metric_registry_id": self.metric_registry_id,
            "metric_registry_version": self.metric_registry_version,
            "optimization_result_id": self.result_id(),
            "base_design_hash": _view_hash(self.base_design_hash),
            "definition": self._definition_view_v2(),
            "candidates": candidates,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "selection_rationale": self.selection_rationale,
            "completeness": (self.completeness.to_dict()
                             if self.completeness is not None else None),
        }

    def _to_study_view_v1(self) -> dict[str, Any]:
        """LOSSY v1 compatibility projector (contract_version 1).

Rationale: docs/decisions/modules/optimization.md
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


def _derive_completeness(definition: Any, evaluated: int) -> Any:
    """Derive the search-completeness fact (AMEND-4).

    Never infers EXHAUSTIVE: `completeness.derive` claims it only when the
    universe is known AND every candidate was evaluated.
    """
    from .completeness import derive
    return derive(definition, evaluated)


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
    """Deterministic optimize: search -> evaluate -> verdicts -> Pareto.

Rationale: docs/decisions/modules/optimization.md
    """

    def optimize_with_port(self, base_request: Any, definition: Any,
                           port: Any) -> OptimizationResult:
        """Analytic/test/research mode. Never yields certified results."""
        return self._optimize_core(base_request, definition, port,
                                   accept_certified_claims=False)

    def optimize(self, base_request: Any, definition: Any,
                 evaluator: Any) -> OptimizationResult:
        """Backward-compatible alias for :meth:`optimize_with_port`.

        Analytic-only: a certified claim from a caller-supplied evaluator
        is a typed refusal (certified results come only from
        :meth:`optimize_certified`).
        """
        return self.optimize_with_port(base_request, definition, evaluator)

    def optimize_certified(self, base_request: Any, definition: Any, *,
                           backend_config: Any,
                           ) -> OptimizationResult:
        """The ONLY certified entry point (R1/C1/C2/C3).

Rationale: docs/decisions/modules/optimization.md
        """
        if not isinstance(backend_config, CertifiedBackendConfig):
            raise OptimizationResultError(
                f"optimize_certified requires a CertifiedBackendConfig, "
                f"got {type(backend_config).__name__}")
        evaluator = _make_real_certified_evaluator(backend_config,
                                                   definition)
        core = self._optimize_core(
            base_request, definition, evaluator,
            accept_certified_claims=True,
            metric_registry=CERTIFIED_METRIC_REGISTRY)
        import dataclasses as _dc
        return _dc.replace(
            core,
            result_class=RESULT_CLASS_CERTIFIED,
            metric_registry_id=CERTIFIED_METRIC_REGISTRY.registry_id(),
            metric_registry_version=CERTIFIED_METRIC_REGISTRY.version)

    def _optimize_core(self, base_request: Any, definition: Any,
                       evaluator: Any, *,
                       accept_certified_claims: bool,
                       metric_registry: Any = None) -> OptimizationResult:
        from veritx_dse.application.requirements import report_passes

        from .candidate import candidate_id_for
        from .constraints import evaluate_all
        from .pareto import pareto_ids as _pareto_ids
        from .search import search_candidates
        registry = metric_registry if metric_registry is not None \
            else CERTIFIED_METRIC_REGISTRY
        if not isinstance(registry, CertifiedMetricRegistry):
            raise OptimizationResultError(
                f"certified metric extraction requires a frozen "
                f"CertifiedMetricRegistry, got {type(registry).__name__} "
                f"— experimental/plugin registries can never yield "
                f"certified claims")
        base_hash = base_request.design_hash()
        candidates = search_candidates(base_request, definition)
        if not candidates:
            raise OptimizationResultError("search produced no candidates")
        records: list[CandidateRecord] = []
        feasible_values: dict[str, dict[str, float]] = {}
        for cand in candidates:
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
            authority = getattr(ev, "evaluation_authority", None)
            claims = None
            certified_claim = (
                authority == AUTHORITY_CERTIFIED_BACKEND
                and ev.status == "EVALUATED"
                and (getattr(ev, "authenticated_proof", None)
                     is not None
                     or ev.performance_result_id is not None))
            if certified_claim:
                if not accept_certified_claims:
                    raise OptimizationResultError(
                        f"candidate {cand.candidate_id!r} claims certified "
                        f"authority through optimize_with_port — that "
                        f"entry point is ANALYTIC/TEST/RESEARCH only. A "
                        f"certified result requires a verified performance "
                        f"result produced by the optimizer-owned "
                        f"evaluator: use Optimizer.optimize_certified, "
                        f"which owns the real backend path")
                claims, report = _verified_certified_claims(cand, ev)
            else:
                if not accept_certified_claims and getattr(
                        ev, "authenticated_proof", None) is not None:
                    raise OptimizationResultError(
                        f"candidate {cand.candidate_id!r} carries an "
                        f"authenticated proof through optimize_with_port "
                        f"— the analytic entry point refuses certified "
                        f"evidence; use Optimizer.optimize_certified")
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
            measured_all: dict[str, float] = {}
            invalid_values: dict[str, str] = {}
            for key, raw in raw_values.items():
                number = _finite_number(raw)
                if number is None:
                    invalid_values[str(key)] = repr(raw)
                else:
                    measured_all[str(key)] = number
            if claims is not None:
                measured_all = _authoritative_metrics(
                    ev, definition, claims, measured_all, invalid_values,
                    registry)
                invalid_values = {}
                federated_measured, federated_keys = \
                    _federated_objective_metrics(
                        ev, definition, measured_all, invalid_values)
                for key, value in federated_measured.items():
                    if key in measured_all and \
                            measured_all[key] != value:
                        raise OptimizationResultError(
                            f"certified evaluation for "
                            f"{ev.candidate_id!r} evidences metric "
                            f"{key!r} as {measured_all[key]!r} from the "
                            f"network proof and as {value!r} from "
                            f"federated evidence — two models, one "
                            f"metric: refusing rather than merging")
                    measured_all[key] = value
            else:
                federated_keys = set()
            if ev.status == "EVALUATED":
                constraint_sources = _federated_metric_sources(ev)
                if claims is None and not constraint_sources:
                    verdicts = evaluate_all(definition.constraints,
                                            measured_all)
                else:
                    constraint_values, unresolved = \
                        _resolve_constraint_values(
                            definition, measured_all, registry, claims,
                            constraint_sources)
                    verdicts = evaluate_all(definition.constraints,
                                            constraint_values,
                                            unresolved)
            else:
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
            constraints_satisfied = verdicts["feasible"]
            constraint_verdicts = {
                k: str(v.get("verdict"))
                for k, v in verdicts["verdicts"].items()}
            constraint_details = _constraint_details(verdicts["verdicts"])
            objective_availability: dict[str, str] = {}
            objective_entries: list[dict[str, Any]] = []
            for o in definition.objectives:
                if ev.status != "EVALUATED":
                    state = "UNMEASURABLE"
                    reason = (f"evaluation status {ev.status} — "
                              "no measured value")
                elif (claims is not None
                        and _objective_question(o) is
                        EvaluationQuestion.NETWORK_COMPLETION
                        and not _has_metric_authority(
                            registry, o.metric)):
                    state = "UNMEASURABLE"
                    reason = (f"objective {o.metric} has no registered "
                              f"metric authority over the authenticated "
                              f"proof")
                elif (claims is not None
                        and _objective_question(o) is
                        EvaluationQuestion.NETWORK_COMPLETION
                        and not registry.is_measured(o.metric)):
                    state = "UNMEASURABLE"
                    reason = (f"objective {o.metric} is an analytical "
                              f"model output, not a backend measurement "
                              f"— certified Pareto measures backends, "
                              f"never models")
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
                    miss = getattr(
                        ev, "objective_unmeasured_reasons", None) or {}
                    reason = miss.get(o.metric) or (
                        f"objective {o.metric} not evidenced by "
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
            eligibility_reasons: list[str] = []
            if ev.status != "EVALUATED":
                eligibility_reasons.append(f"evaluation status {ev.status}")
            if authority != AUTHORITY_CERTIFIED_BACKEND:
                eligibility_reasons.append(
                    f"evaluation authority {authority!r} is not "
                    f"{AUTHORITY_CERTIFIED_BACKEND!r} — non-certified "
                    "(analytic/fake) evaluations are never "
                    "optimization-eligible")
            applicable_binding, _out_of_scope = \
                _study_answerable_binding_requirements(
                    cand.request, definition)
            explicitly_unevaluated = [
                r for r in applicable_binding
                if _requirement_applicability(r) == "NOT_EVALUATED"]
            if explicitly_unevaluated:
                eligibility_reasons.append(
                    "binding product requirements are explicitly "
                    f"marked NOT_EVALUATED "
                    f"({len(explicitly_unevaluated)}) — never passing "
                    "until evaluated")
            elif applicable_binding:
                if report is None:
                    eligibility_reasons.append(
                        "binding product requirements are unevaluated "
                        f"({len(applicable_binding)} applicable) — no "
                        "RequirementReport is bound")
                elif product_satisfied is not True:
                    eligibility_reasons.append(
                        "binding product requirements are not satisfied")
            elif report is not None and product_satisfied is not True:
                eligibility_reasons.append(
                    "binding product requirements are not satisfied")
            network_leg = (ev.performance_result_id is not None or any(
                _objective_question(o) is
                EvaluationQuestion.NETWORK_COMPLETION
                for o in definition.objectives))
            if network_leg:
                if ev.performance_result_id is None:
                    eligibility_reasons.append(
                        "no performance_result_id is bound")
                elif str(ev.performance_result_id).startswith("fake:"):
                    eligibility_reasons.append(
                        "performance_result_id is a fake result, not "
                        "authenticated backend evidence")
            if authority == AUTHORITY_CERTIFIED_BACKEND:
                for o in definition.objectives:
                    question = _objective_question(o)
                    if question is \
                            EvaluationQuestion.NETWORK_COMPLETION:
                        continue
                    native = _authentic_federated_source(
                        ev, o.metric, question)
                    if native is None:
                        eligibility_reasons.append(
                            f"objective {o.metric} has no authentic "
                            f"{question.value} evidence binding "
                            "(EVALUATED analysis with envelope, "
                            "qualification and native evidence id) — "
                            "values without evidence never reach Pareto")
                    elif str(native).startswith("fake:"):
                        eligibility_reasons.append(
                            f"objective {o.metric} binds fake native "
                            "evidence, not authenticated backend "
                            "evidence")
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
                needed = sorted(
                    {o.metric for o in definition.objectives
                     if _objective_question(o) is
                     EvaluationQuestion.NETWORK_COMPLETION} |
                    {c.metric if hasattr(c, "metric") else c["metric"]
                     for c in (definition.constraints or [])})
                missing_authority = [m for m in needed
                                     if not _has_metric_authority(registry,
                                                                  m)
                                     and m not in federated_keys]
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
                objective_provenance=_provenance_docs(ev, measured_all),
                constraints_satisfied=constraints_satisfied,
                eligibility_reason=eligibility_reason,
            )
            records.append(record)
            if eligible:
                feasible_values[cand.candidate_id] = {
                    o.metric: measured_all[o.metric]
                    for o in definition.objectives}
        records = _enforce_federated_comparability(records, definition)
        feasible_values = {
            r.candidate_id: {o.metric: r.objective_values[o.metric]
                             for o in definition.objectives}
            for r in records if r.pareto_eligible}
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
            objective_provenance=r.objective_provenance,
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
            result_class=RESULT_CLASS_ANALYTIC,
            metric_registry_id=None,
            metric_registry_version=None,
            completeness=_derive_completeness(definition, len(records)),
        )


__all__ = [
    "RESULT_CLASS_ANALYTIC", "RESULT_CLASS_CERTIFIED", "RESULT_DOMAIN",
    "CandidateRecord", "CertifiedBackendConfig", "OptimizationResult",
    "OptimizationResultError", "Optimizer",
]
