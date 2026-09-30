"""veritx_dse.optimization.space_multiscenario — multi-scenario studies.

Rationale: docs/decisions/modules/optimization.md
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

from . import search as _search
from .candidate import (
    CandidateError,
    StudyCandidate,
    make_study_candidate,
    normalize_study_patch,
    study_candidate_id_for,
)
from .constraints import evaluate_constraint_value
from .definition import (
    SEARCH_METHODS,
    OptimizationDefinitionError,
    ScenarioConstraint,
    ScenarioObjective,
    StudyParam,
)

STUDY_DOMAIN = "veritx/multiscenario-study/v1"

VALID = "VALID"
ALIAS = "ALIAS"
INVALID = "INVALID"
NOT_EVALUATED = "NOT_EVALUATED"
EVAL_SUCCEEDED = "SUCCEEDED"
EVAL_FAILED = "FAILED"

BUILD_STATUSES = (VALID, ALIAS, INVALID, NOT_EVALUATED)
EVAL_STATUSES = (EVAL_SUCCEEDED, EVAL_FAILED)

class StudyError(ValueError):
    """Invalid multi-scenario study (typed, fail-closed)."""

def _normalized_workload_payload(value: Any) -> Any:
    """JSON-canonical projection of a workload intent (enums by value)."""
    import dataclasses
    from enum import Enum
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _normalized_workload_payload(getattr(value, f.name))
                for f in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return [_normalized_workload_payload(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalized_workload_payload(value[k])
                for k in sorted(value)}
    return value

def workload_fingerprint(workload: Any) -> str:
    """Content identity of a scenario workload intent.

    Only canonical workload dataclasses (Workload/WorkloadV3: frozen,
    int tp/pp/ep/dp) are scenario intents; anonymous dicts refuse.
    """
    import dataclasses
    if not dataclasses.is_dataclass(workload) \
            or isinstance(workload, type):
        raise StudyError(
            f"scenario workload must be a canonical workload artifact, "
            f"got {type(workload).__name__}: anonymous intents refuse")
    for attr in ("tp", "pp", "ep", "dp"):
        v = getattr(workload, attr, None)
        if type(v) is not int or v < 1:
            raise StudyError(
                f"scenario workload needs int {attr} >= 1, got {v!r}")
    try:
        payload = _normalized_workload_payload(workload)
        canonical_json(payload)
    except Exception as exc:
        raise StudyError(
            f"scenario workload not fingerprintable: {exc}") from exc
    return content_id("veritx/scenario-workload/v1", payload)

@dataclass(frozen=True)
class Scenario:
    """One evaluation scenario: an id + a canonical workload intent."""
    scenario_id: str
    workload: Any

    def __post_init__(self):
        if not isinstance(self.scenario_id, str) or not self.scenario_id:
            raise StudyError("scenario needs a non-empty string id")
        workload_fingerprint(self.workload)

    def fingerprint(self) -> str:
        return workload_fingerprint(self.workload)

@dataclass
class MultiScenarioStudy:
    """One study: base design + scenarios + scoped objectives/constraints."""
    base: Any
    scenarios: tuple[Scenario, ...]
    objectives: tuple[ScenarioObjective, ...] = ()
    constraints: tuple[ScenarioConstraint, ...] = ()
    domain: tuple[StudyParam, ...] = ()
    method: str = "grid"
    budget: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    selection: str = "min_first_objective"

    def __post_init__(self):
        if isinstance(self.scenarios, list):
            object.__setattr__(self, "scenarios", tuple(self.scenarios))
        if isinstance(self.objectives, list):
            object.__setattr__(self, "objectives", tuple(self.objectives))
        if isinstance(self.constraints, list):
            object.__setattr__(self, "constraints", tuple(self.constraints))
        if isinstance(self.domain, list):
            object.__setattr__(self, "domain", tuple(self.domain))
        if not self.scenarios:
            raise StudyError("a study needs at least one scenario")
        for s in self.scenarios:
            if not isinstance(s, Scenario):
                raise StudyError(
                    f"scenarios must contain Scenario, got {type(s).__name__}")
        ids = [s.scenario_id for s in self.scenarios]
        if len(ids) != len(set(ids)):
            raise StudyError(f"duplicate scenario ids: {sorted(ids)}")
        if not self.objectives:
            raise StudyError("a study needs at least one objective")
        for o in self.objectives:
            if not isinstance(o, ScenarioObjective):
                raise StudyError(
                    "objectives must contain ScenarioObjective, got "
                    f"{type(o).__name__}")
            if o.scenario is not None and o.scenario not in ids:
                raise StudyError(
                    f"objective {o.metric!r} scoped to unknown scenario "
                    f"{o.scenario!r}; study scenarios: {sorted(ids)}")
        obj_keys = [(o.metric, o.scenario) for o in self.objectives]
        dup = sorted({k for k in obj_keys if obj_keys.count(k) > 1})
        if dup:
            raise StudyError(
                f"duplicate (metric, scenario) objectives {dup}: exact "
                "nested closure — each objective declared exactly once")
        for c in self.constraints:
            if not isinstance(c, ScenarioConstraint):
                raise StudyError(
                    "constraints must contain ScenarioConstraint, got "
                    f"{type(c).__name__}")
            if c.scenario is not None and c.scenario not in ids:
                raise StudyError(
                    f"constraint {c.metric!r} scoped to unknown scenario "
                    f"{c.scenario!r}")
        con_keys = [(c.metric, c.scenario) for c in self.constraints]
        dup_c = sorted({k for k in con_keys if con_keys.count(k) > 1})
        if dup_c:
            raise StudyError(
                f"duplicate (metric, scenario) constraints {dup_c}")
        for p in self.domain:
            if not isinstance(p, StudyParam):
                raise StudyError(
                    f"domain must contain StudyParam, got {type(p).__name__}")
        names = [p.name for p in self.domain]
        if len(names) != len(set(names)):
            raise StudyError("duplicate study parameter names")
        if not self.domain:
            raise StudyError(
                "the study domain is empty: a study with no searchable "
                "dimension would only re-evaluate the base")
        if self.method not in SEARCH_METHODS:
            raise StudyError(
                f"unknown search method {self.method!r}; supported: "
                f"{list(SEARCH_METHODS)}")
        budget = dict(self.budget or {})
        for key in ("max_candidates", "max_evaluations"):
            if budget.get(key) is not None:
                v = budget[key]
                if type(v) is not int or v < 1:
                    raise StudyError(
                        f"budget {key} must be a positive int, got {v!r}")
        unknown = sorted(set(budget) - {"max_candidates", "max_evaluations"})
        if unknown:
            raise StudyError(f"budget has unknown fields {unknown}")
        object.__setattr__(self, "budget", budget)
        if self.seed is not None and type(self.seed) is not int:
            raise StudyError(f"seed must be an int or None, got {self.seed!r}")
        if self.method == "random" and self.seed is None:
            raise StudyError("'random' requires an explicit seed")

    def study_id(self) -> str:
        base_hash = self.base.design_hash()
        return content_id(STUDY_DOMAIN, {
            "base_design_hash": base_hash,
            "scenarios": sorted(s.fingerprint() for s in self.scenarios),
            "objectives": [
                {"metric": o.metric, "direction": o.direction,
                 "question": o.question.value, "backend_id": o.backend_id,
                 "scenario": o.scenario} for o in self.objectives],
            "constraints": [
                {"metric": c.metric, "op": c.op, "threshold": c.threshold,
                 "scenario": c.scenario} for c in self.constraints],
            "domain": [{"name": p.name, "namespace": p.namespace,
                        "values": list(p.values)}
                       for p in sorted(self.domain, key=lambda p: p.name)],
            "method": self.method,
            "budget": dict(sorted(self.budget.items())),
            "seed": self.seed,
            "selection": self.selection,
        })

@dataclass
class BuiltCandidate:
    """One build outcome: VALID carries a candidate; others carry reasons."""
    status: str
    patch: dict[str, Any]
    candidate: StudyCandidate | None = None
    reason: str | None = None
    canonical_of: str | None = None

@dataclass
class BuildLedger:
    """Full build accounting: every assignment lands in exactly one bin.

Rationale: docs/decisions/modules/optimization.md
    """
    valid: list[StudyCandidate]
    aliases: list[BuiltCandidate]
    invalid: list[BuiltCandidate]
    not_evaluated: list[str]

def _budget_limit(study: MultiScenarioStudy) -> int | None:
    limits = [v for v in (study.budget.get("max_candidates"),
                          study.budget.get("max_evaluations"))
              if v is not None]
    return min(limits) if limits else None

def _ordered_patches(study: MultiScenarioStudy) -> list[dict[str, Any]]:
    shim = SimpleNamespace(domain=tuple(study.domain))
    patches = list(_search.canonical_assignments(shim))
    if study.method == "random":
        rng = random.Random(int(study.seed))
        order = list(patches)
        rng.shuffle(order)
        limit = _budget_limit(study)
        if limit is None:
            limit = len(order)
        return sorted(order[:limit], key=canonical_json)
    return patches

def build_study_candidates(study: MultiScenarioStudy,
                           known_ids: frozenset[str] = frozenset()
                           ) -> BuildLedger:
    """Enumerate, deduplicate (ALIAS), refuse (INVALID), cut tail.

    known_ids are already-evaluated identities (earlier builds, earlier
    studies on the same base): repeats surface as ALIAS with canonical_of
    set, so no candidate is ever evaluated twice.
    """
    valid: list[StudyCandidate] = []
    aliases: list[BuiltCandidate] = []
    invalid: list[BuiltCandidate] = []
    seen: dict[str, StudyCandidate] = {}
    patches = _ordered_patches(study)
    for patch in patches:
        try:
            norm = normalize_study_patch(patch)
        except CandidateError as exc:
            invalid.append(BuiltCandidate(
                status=INVALID, patch=dict(patch), reason=str(exc)))
            continue
        cid = study_candidate_id_for(study.base.design_hash(), norm)
        if cid in known_ids and cid not in seen:
            aliases.append(BuiltCandidate(
                status=ALIAS, patch=dict(patch), reason=(
                    f"already evaluated as {cid}: alias, never "
                    "double-counted"),
                canonical_of=cid))
            continue
        if cid in seen:
            aliases.append(BuiltCandidate(
                status=ALIAS, patch=dict(patch), reason=(
                    f"duplicate of canonical first {cid}: evaluated once, "
                    "never double-counted"),
                canonical_of=cid))
            continue
        try:
            cand = make_study_candidate(study.base, norm)
        except CandidateError as exc:
            invalid.append(BuiltCandidate(
                status=INVALID, patch=dict(patch), reason=str(exc)))
            continue
        seen[cid] = cand
        valid.append(cand)
    limit = _budget_limit(study)
    not_evaluated: list[str] = []
    if limit is not None and len(valid) > limit:
        not_evaluated = [c.candidate_id for c in valid[limit:]]
    return BuildLedger(valid=valid, aliases=aliases, invalid=invalid,
                       not_evaluated=not_evaluated)

def eligible_ids(ledger: BuildLedger) -> list[str]:
    """Valid identities evaluation may attempt (valid minus the tail)."""
    tail = set(ledger.not_evaluated)
    return [c.candidate_id for c in ledger.valid if c.candidate_id not in tail]

def scenario_request_for(candidate: StudyCandidate,
                         scenario: Scenario) -> Any:
    """Candidate hardware + scenario workload, binding asserted."""
    request = dataclasses.replace(candidate.request,
                                  workload=scenario.workload)
    assert_scenario_binding(request, candidate, scenario)
    return request

def assert_scenario_binding(request: Any, candidate: StudyCandidate,
                            scenario: Scenario) -> None:
    """Prove a request is this candidate under this scenario intent."""
    if workload_fingerprint(request.workload) != scenario.fingerprint():
        raise StudyError(
            f"request workload is not scenario {scenario.scenario_id!r}: "
            "a candidate is evaluated against exactly the scenario intent "
            "in its identity — refusing transplant")
    fabric_now = dataclasses.replace(request, workload=candidate.request.workload)
    if fabric_now != candidate.request:
        raise StudyError(
            "request hardware differs from the candidate hardware: "
            "scenario evaluation must not mutate fabric — refusing transplant")

def check_hardware_consistent(requests: list[Any]) -> None:
    """Prove scenario requests differ ONLY in workload (pairwise)."""
    if len(requests) < 2:
        return
    first = requests[0]
    for other in requests[1:]:
        if dataclasses.replace(first, workload=other.workload) != other:
            raise StudyError(
                "hardware inconsistency across scenarios: scenario "
                "requests must share identical fabric/agents and differ "
                "only in workload")

def verify_tail_agreement(valid_ids: list[str], evaluated_ids: list[str],
                          not_evaluated_ids: list[str]) -> None:
    """Tail/evaluation agreement: subsets, disjoint, no doubles, no tail runs.

    The tail is the canonical-prefix cut: evaluated identities must come
    from the eligible prefix, never from the tail (re-budget first), and
    no identity may be evaluated twice (alias double-counting).
    """
    if len(set(evaluated_ids)) != len(evaluated_ids):
        raise StudyError("evaluated identities contain duplicates: an "
                         "alias evaluated twice is double-counting")
    if len(set(not_evaluated_ids)) != len(not_evaluated_ids):
        raise StudyError("NOT_EVALUATED identities contain duplicates")
    valid, tail, evaluated = (set(valid_ids), set(not_evaluated_ids),
                              set(evaluated_ids))
    if not tail <= valid:
        raise StudyError(
            "budget-tail disagreement: NOT_EVALUATED identities must be "
            "valid candidates (the canonical-prefix cut)")
    if not evaluated <= valid:
        raise StudyError(
            "budget-tail disagreement: evaluated identities must be "
            "built valid candidates")
    if evaluated & tail:
        raise StudyError(
            "budget-tail disagreement: tail identities were evaluated "
            "without re-budgeting — re-budget first")

@dataclass(frozen=True)
class EvaluationRow:
    """One per-(candidate, scenario) evaluation outcome (evaluator-owned)."""
    candidate_id: str
    scenario_id: str
    status: str
    reason: str | None = None

    def __post_init__(self):
        if self.status not in EVAL_STATUSES:
            raise StudyError(
                f"evaluation status must be {list(EVAL_STATUSES)}, got "
                f"{self.status!r}")

def accounting_summary(ledger: BuildLedger,
                       eval_rows: list[EvaluationRow]) -> dict[str, Any]:
    """Full accounting: build bins + per-scenario evaluation outcomes."""
    by_candidate: dict[str, list[EvaluationRow]] = {}
    for row in eval_rows:
        by_candidate.setdefault(row.candidate_id, []).append(row)
    alias_ids = {a.canonical_of for a in ledger.aliases
                 if a.canonical_of is not None}
    for row in eval_rows:
        if row.candidate_id not in {c.candidate_id for c in ledger.valid} \
                and row.candidate_id not in alias_ids:
            raise StudyError(
                f"evaluation row for unknown candidate {row.candidate_id!r}: "
                "evaluations bind to built identities only")
    evaluated_ids = sorted({r.candidate_id for r in eval_rows})
    verify_tail_agreement([c.candidate_id for c in ledger.valid],
                          evaluated_ids, ledger.not_evaluated)
    failed = [r for r in eval_rows if r.status == EVAL_FAILED]
    return {
        "valid": len(ledger.valid),
        "aliases": len(ledger.aliases),
        "invalid": len(ledger.invalid),
        "not_evaluated": len(ledger.not_evaluated),
        "evaluated_candidates": len(evaluated_ids),
        "succeeded_rows": sum(1 for r in eval_rows
                              if r.status == EVAL_SUCCEEDED),
        "failed_rows": len(failed),
        "failed": [(r.candidate_id, r.scenario_id, r.reason) for r in failed],
    }

def evaluate_constraints_per_scenario(
        study: MultiScenarioStudy,
        values_by_scenario: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Constraint verdicts per scenario (relaxation as information).

    Requirement/constraint status is an orthogonal annotation, never a
    frontier predicate: violating scenarios are reported, not hidden.
    """
    report: dict[str, Any] = {}
    for scenario in study.scenarios:
        sid = scenario.scenario_id
        values = values_by_scenario.get(sid, {})
        applicable = [c for c in study.constraints
                      if c.scenario is None or c.scenario == sid]
        verdicts = {}
        for c in applicable:
            doc = evaluate_constraint_value(c.metric, c.op, c.threshold,
                                            values.get(c.metric))
            verdicts[c.metric] = doc
        violated = sorted(m for m, d in verdicts.items()
                          if d["verdict"] == "VIOLATED")
        report[sid] = {"verdicts": verdicts, "violated": violated}
    return report

def eligible_summary(ledger: BuildLedger) -> dict[str, Any]:
    """Eligible (prefix) vs tail counts for launch planning."""
    eligible = eligible_ids(ledger)
    return {"eligible": len(eligible), "tail": len(ledger.not_evaluated),
            "eligible_ids": eligible,
            "tail_ids": list(ledger.not_evaluated)}

def study_structure(study: MultiScenarioStudy,
                    ledger: BuildLedger) -> dict[str, Any]:
    """Structural (backend-free) facts about a built study."""
    shim = SimpleNamespace(domain=tuple(study.domain))
    return {
        "study_id": study.study_id(),
        "scenarios": [s.scenario_id for s in study.scenarios],
        "raw_cardinality": _search.raw_cardinality(shim),
        "method": study.method,
        "valid": len(ledger.valid),
        "aliases": len(ledger.aliases),
        "invalid": [(b.patch, b.reason) for b in ledger.invalid],
        "not_evaluated": list(ledger.not_evaluated),
        **eligible_summary(ledger),
    }

__all__ = [
    "STUDY_DOMAIN", "VALID", "ALIAS", "INVALID", "NOT_EVALUATED",
    "EVAL_SUCCEEDED", "EVAL_FAILED", "StudyError", "Scenario",
    "MultiScenarioStudy", "BuiltCandidate", "BuildLedger",
    "EvaluationRow", "workload_fingerprint", "build_study_candidates",
    "scenario_request_for", "assert_scenario_binding",
    "check_hardware_consistent", "verify_tail_agreement",
    "eligible_ids", "eligible_summary",
    "accounting_summary", "evaluate_constraints_per_scenario",
    "study_structure",
]
