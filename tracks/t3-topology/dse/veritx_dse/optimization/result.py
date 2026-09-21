"""veritx_dse.optimization.result — OptimizationResult + verifier (§62–§82).

Identity (§116):

    optimization_result_id = H(
        optimization_definition_id,
        canonical candidate accounting (per raw assignment: identity,
        status, alias_of, verified scenario result ids),
        search scope (search_complete, frontier_complete))

Frontier, selection, verdicts and completeness are DERIVED SUMMARIES:
persisted for inspection, re-checked on load — the verifier recomputes
them from the verified definition and the verified candidate results
and refuses any disagreement (§65–§70, §113). Nothing important is
merely trusted:

    - every successful scenario result loads via load_verified_result
      (§65) and its plan intent_id must equal the RESOLVED intent
      identity of this candidate's scenario (§71/§72/§73: identity
      beats numeric coincidence);
    - objective values and constraint verdicts are re-extracted from
      verified parents (§66/§67); unmeasurable→zero and failure→
      violation forgeries refuse (§135/§136);
    - the Pareto frontier is recomputed over the feasible, measurable,
      comparable set (§68/§77);
    - selection is re-run under the declared policy; a persisted
      winner without a policy refuses (§69/§78/§137);
    - candidate accounting is regenerated from the definition, so an
      omitted candidate or alias refuses (§70/§74/§133/§134) and a
      forged search_complete/frontier_complete refuses (§75);
    - negative verdicts re-derive under the same asymmetric rules as
      production (§50/§76): a forged NO_FEASIBLE_DESIGN built from
      failures/timeouts refuses;
    - the outer result ID is recomputed (§116), so any edited field
      that survives the above still refuses on identity.
"""
from __future__ import annotations

import hashlib
from fractions import Fraction
from dataclasses import dataclass
from typing import Any

from veritx_dse.application.resources import check_envelope
from veritx_dse.application.results import load_verified_result
from veritx_dse.core.spec import canonical_json
from veritx_dse.optimization.constraints import (
    VerdictInput, evaluate_constraint, optimization_verdict,
)
from veritx_dse.optimization.definition import (
    OptimizationDefinition, OptimizationDefinitionError, frac_from_doc,
    patched_scenario_template,
)
from veritx_dse.optimization.metrics import (
    MetricValue, extract_constraint_values, extract_objective_values,
    value_map_doc, value_map_from_doc,
)
from veritx_dse.optimization.pareto import (
    comparability_report, compute_frontier, dominance_explanations,
    frontier_is_complete, select,
)
from veritx_dse.optimization.space import (
    NOT_EVALUATED, budget_plan, build_candidates, raw_cardinality,
)

RESULT_SCHEMA_VERSION = 1
_RESULT_TAG = "srota/optimization/result/v1"

#: Closed result envelope (§113).
RESULT_FIELDS = frozenset({
    "resource_type", "schema_version", "resource_id", "artifact",
})

#: Closed artifact schema (§113): unknown fields refuse on load.
ARTIFACT_FIELDS = frozenset({
    "schema_version", "optimization_definition_id",
    "candidate_records",        # every raw assignment, visible (§64)
    "search",                   # scope + budget accounting (§25/§54)
    "verdict",                  # feasibility verdict (§49–§53)
    "objectives",               # per-candidate exact values (§93)
    "constraints",              # per-candidate verdict docs (§46)
    "pareto",                   # scoped frontier summary (§41/§56)
    "selection",                # explicit policy outcome (§57)
    "dominance",                # dominator evidence (§142)
    "relaxation",               # information-only evidence (§98)
    "fidelity_warning",         # derived from verified parents (§138)
})

CANDIDATE_RECORD_FIELDS = frozenset({
    "index", "assignment", "candidate_id", "status", "alias_of",
    "scenario_intent_ids", "scenario_result_ids", "scenario_reused",
    "error",
})

SEARCH_FIELDS = frozenset({
    "search_policy", "search_complete", "frontier_complete", "budget",
})

BUDGET_FIELDS = frozenset({
    "raw_assignments", "unique_candidates", "planned_candidates",
    "planned_evaluations", "candidates_evaluated",
    "scenario_evaluations_attempted", "scenario_evaluations_reused",
})

#: Statuses a valid candidate may carry in a PERSISTED result.
#: NOT_EVALUATED is deliberately absent: it is not an evaluation
#: outcome, and counting it as terminal would fabricate
#: search_complete=True for budgeted runs (§23/§62/§75).
TERMINAL_EVALUATION_STATUSES = (
    "SUCCEEDED", "FAILED", "TIMED_OUT", "UNSUPPORTED", "BLOCKED",
    "UNMEASURABLE", "PRUNED_PROVEN",
)


class OptimizationResultError(ValueError):
    """Forged/malformed optimization result (refusal, §113)."""


def _order_json(value: Any) -> Any:
    """Canonical persisted-document form: dict keys sorted, and exact
    rationals rendered as {numerator, denominator} docs (§39) — the same
    shape value_map_doc/frac_from_doc use. Builder and verifier both
    pass derived blocks through this before comparing, so raw Fractions
    can neither break store serialization nor hide behind ad-hoc
    conversion asymmetry."""
    if isinstance(value, Fraction):
        return {"numerator": value.numerator,
                "denominator": value.denominator}
    if isinstance(value, dict):
        return {k: _order_json(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_order_json(v) for v in value]
    return value


def _content_id(tag: str, body: dict[str, Any]) -> str:
    payload = tag + "\0" + canonical_json(body)
    return hashlib.sha256(payload.encode()).hexdigest()


def _fidelity_warning(defn: OptimizationDefinition,
                      wave_e_models: list[dict[str, Any]]) -> str:
    """Derived warning (§138) from the verified parents' own text.

    Collects the metrics_warning of every Wave-E model actually used by
    verified candidate results; a producer cannot type marketing
    language here.
    """
    if not wave_e_models:
        return ("No Wave-E timing models were used by this "
                "optimization; conclusions rest on structural metrics "
                "only.")
    seen: list[str] = []
    for m in wave_e_models:
        w = m.get("metrics_warning")
        if w and w not in seen:
            seen.append(w)
    return ("Performance ranking is conditional on the verified "
            "Wave-E models: " + " | ".join(seen))


# ── shared derivations (builder and verifier use the SAME code) ─────────

def candidate_valid_ids(records: list[dict[str, Any]]) -> list[str]:
    """Valid unique candidate IDs from accounting (aliases excluded)."""
    return [r["candidate_id"] for r in records
            if r["status"] not in ("ALIAS", "INVALID")]


def derive_search_complete(records: list[dict[str, Any]]) -> bool:
    """§62: derived, never trusted. True when every valid unique
    candidate reached a terminal evaluation outcome."""
    valid = [r for r in records
             if r["status"] not in ("ALIAS", "INVALID")]
    if not valid:
        return False
    return all(r["status"] in TERMINAL_EVALUATION_STATUSES
               for r in valid)


def derive_budget(defn: OptimizationDefinition, unique_count: int,
                  records: list[dict[str, Any]]) -> dict[str, int]:
    """§25: requested vs actual accounting, all fields derived.

    ``scenario_evaluations_reused`` is derived per record (the count of
    scenario results the control plane served from verified reuse), so
    the verifier recomputes it from accounting instead of trusting the
    builder's tally (§62).
    """
    plan = budget_plan(defn, unique_count)
    evaluated = [r for r in records
                 if r["status"] in TERMINAL_EVALUATION_STATUSES
                 and r["status"] != NOT_EVALUATED]
    return {
        "raw_assignments": raw_cardinality(defn),
        "unique_candidates": unique_count,
        "planned_candidates": plan["planned_candidates"],
        "planned_evaluations": plan["planned_evaluations"],
        "candidates_evaluated": len(evaluated),
        "scenario_evaluations_attempted": sum(
            len(r.get("scenario_result_ids") or {}) for r in records),
        "scenario_evaluations_reused": sum(
            1 for r in records
            for v in (r.get("scenario_reused") or {}).values() if v),
    }


def derive_verdict(defn: OptimizationDefinition,
                   records: list[dict[str, Any]],
                   constraint_docs: dict[str, list[dict[str, Any]]]
                   ) -> dict[str, Any]:
    """The feasibility verdict from accounting + constraint docs (§49ff).

    A candidate is feasible only when EVERY declared constraint has a
    SATISFIED verdict; VIOLATED requires a measured value (enforced by
    evaluate_constraint); anything else is not conclusive.
    """
    valid_ids = candidate_valid_ids(records)
    n_declared = len(defn.hard_constraints)
    feasible = 0
    rejected = 0
    for cid in valid_ids:
        docs = constraint_docs.get(cid, [])
        if r_status(records, cid) != "SUCCEEDED":
            continue                # no evaluation evidence: never feasible
        if len(docs) == n_declared and \
                all(c["verdict"] == "SATISFIED" for c in docs):
            # NOTE: with zero declared constraints this is vacuously
            # true (§48) — an evaluated candidate with no binding
            # constraints is feasible.
            feasible += 1
        elif any(c["verdict"] == "VIOLATED" for c in docs):
            rejected += 1
    non_conclusive = len(valid_ids) - feasible - rejected
    any_measured = any(
        c.get("value") is not None
        for cid in valid_ids for c in constraint_docs.get(cid, []))
    return optimization_verdict(VerdictInput(
        search_complete=derive_search_complete(records),
        valid_total=len(valid_ids),
        feasible=feasible, rejected=rejected,
        non_conclusive=non_conclusive, any_measured=any_measured))


def derive_feasible_ids(defn: OptimizationDefinition,
                        records: list[dict[str, Any]],
                        constraint_docs: dict[str, list[dict[str, Any]]]
                        ) -> list[str]:
    """Candidates with every declared constraint SATISFIED (§48)."""
    n_declared = len(defn.hard_constraints)
    out = []
    for cid in candidate_valid_ids(records):
        if r_status(records, cid) != "SUCCEEDED":
            continue
        docs = constraint_docs.get(cid, [])
        if len(docs) == n_declared and \
                all(c["verdict"] == "SATISFIED" for c in docs):
            out.append(cid)
    return sorted(out)


def r_status(records: list[dict[str, Any]], cid: str) -> str | None:
    for r in records:
        if r["candidate_id"] == cid:
            return r["status"]
    return None


# ── builder side ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidateEvaluation:
    """Runner-side outcome for one raw assignment."""
    index: int
    assignment: dict[str, Any]
    candidate_id: str
    status: str                     # space.CANDIDATE_STATUS member
    alias_of: str | None
    scenario_intent_ids: dict[str, str | None]
    scenario_result_ids: dict[str, str | None]
    scenario_reused: dict[str, bool] | None = None
    error: str | None = None

    def to_doc(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "assignment": _order_json(self.assignment),
            "candidate_id": self.candidate_id,
            "status": self.status,
            "alias_of": self.alias_of,
            "scenario_intent_ids": _order_json(dict(sorted(
                self.scenario_intent_ids.items()))),
            "scenario_result_ids": _order_json(dict(sorted(
                (self.scenario_result_ids or {}).items()))),
            "scenario_reused": _order_json(dict(sorted(
                (self.scenario_reused or {}).items()))),
            "error": self.error,
        }


@dataclass(frozen=True)
class OptimizationRun:
    """Everything the runner produced, ready to persist (§63)."""
    definition: OptimizationDefinition
    records: list[CandidateEvaluation]
    search_complete: bool
    frontier_complete: bool
    objective_values: dict[str, dict[tuple[str, "str | None"],
                                     MetricValue]]
    constraint_docs: dict[str, list[dict[str, Any]]]
    pareto: dict[str, Any]
    selection: dict[str, Any]
    dominance: dict[str, Any]
    relaxation: list[dict[str, Any]]
    wave_e_models: list[dict[str, Any]]

    def build(self) -> dict[str, Any]:
        d = self.definition
        records = [r.to_doc() for r in
                   sorted(self.records, key=lambda r: r.index)]
        unique = len({r["candidate_id"] for r in records
                      if r["status"] not in ("ALIAS", "INVALID")})
        artifact = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "optimization_definition_id": d.definition_id(),
            "candidate_records": records,
            "search": {
                "search_policy": d.search_policy,
                "search_complete": self.search_complete,
                "frontier_complete": self.frontier_complete,
                "budget": derive_budget(d, unique, records),
            },
            "verdict": derive_verdict(d, records, self.constraint_docs),
            "objectives": {
                cid: value_map_doc(vals)
                for cid, vals in sorted(self.objective_values.items())},
            "constraints": {
                cid: [dict(c) for c in sorted(
                    self.constraint_docs.get(cid, []),
                    key=lambda c: (c.get("metric", ""),
                                   str(c.get("scenario"))))]
                for cid in sorted(self.constraint_docs)},
            "pareto": _order_json(self.pareto),
            "selection": _order_json(self.selection),
            "dominance": _order_json(self.dominance),
            "relaxation": _order_json(self.relaxation),
            "fidelity_warning": _fidelity_warning(d, self.wave_e_models),
        }
        if set(artifact) != ARTIFACT_FIELDS:
            raise OptimizationResultError(
                f"artifact fields {sorted(artifact)} != registry")
        result_id = _content_id(_RESULT_TAG, {
            "optimization_definition_id":
                artifact["optimization_definition_id"],
            "candidate_records": artifact["candidate_records"],
            "search_complete": self.search_complete,
            "frontier_complete": self.frontier_complete,
        })
        return {"resource_type": "optimizationresult",
                "schema_version": RESULT_SCHEMA_VERSION,
                "resource_id": result_id,
                "artifact": artifact}


# ── verified load side ───────────────────────────────────────────────────

def load_verified_optimization_definition(store: Any, defn_id: Any
                                          ) -> OptimizationDefinition:
    """§114: verified definition load — schema, ID agreement, closure."""
    if not isinstance(defn_id, str) or not defn_id:
        raise OptimizationResultError(
            f"invalid optimizationdef link {defn_id!r}")
    try:
        record = store.get("optimizationdef", defn_id)
        check_envelope(record, "optimizationdef")
    except Exception as exc:
        raise OptimizationResultError(
            f"optimizationdef {defn_id} fails envelope: {exc}") from exc
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise OptimizationResultError(
            f"optimizationdef {defn_id} artifact is not a mapping")
    try:
        defn = OptimizationDefinition.parse(artifact)
    except OptimizationDefinitionError as exc:
        raise OptimizationResultError(
            f"optimizationdef {defn_id} does not re-validate: "
            f"{exc}") from exc
    recomputed = defn.definition_id()
    if recomputed != defn_id:
        raise OptimizationResultError(
            f"optimizationdef {defn_id} recomputes to {recomputed}: "
            f"content does not match its identity")
    return defn


def _require(cond: Any, message: str) -> None:
    if not cond:
        raise OptimizationResultError(message)


def load_verified_optimization_result(store: Any, result_id: str
                                      ) -> dict[str, Any]:
    """§115: full re-derivation. Returns the verification report.

    Every persisted summary is recomputed from the verified definition
    and verified candidate results; any disagreement refuses. The
    returned report carries the verified definition, the verified
    scenario results per candidate, and the recomputed summaries.
    """
    result = store.get("optimizationresult", result_id)
    _require(isinstance(result, dict) and
             set(result) == set(RESULT_FIELDS),
             f"optimizationresult {result_id} envelope is not closed")
    _require(result["resource_type"] == "optimizationresult",
             "resource_type mismatch")
    _require(result["schema_version"] == RESULT_SCHEMA_VERSION,
             "schema_version mismatch")
    _require(result["resource_id"] == result_id,
              "filename/id mismatch")
    artifact = result["artifact"]
    _require(isinstance(artifact, dict) and
             set(artifact) == set(ARTIFACT_FIELDS),
             f"artifact field set is not closed: "
             f"{sorted(artifact) if isinstance(artifact, dict) else artifact}")
    _require(artifact["schema_version"] == RESULT_SCHEMA_VERSION,
             "artifact schema_version mismatch")

    # 1) verified definition (§114)
    defn = load_verified_optimization_definition(
        store, artifact["optimization_definition_id"])

    # 2) regenerate the space and compare accounting (§62/§70/§74/§134)
    records = artifact["candidate_records"]
    _require(isinstance(records, list) and bool(records),
             "candidate_records must be a non-empty list")
    for r in records:
        _require(isinstance(r, dict) and
                 set(r) == set(CANDIDATE_RECORD_FIELDS),
                 f"candidate record field set is not closed: {sorted(r)}")
    _require([r["index"] for r in records] == list(range(len(records))),
             "candidate record indices are not 0..n-1")
    candidates, expected_records = build_candidates(defn)
    expected_by_index = {r["index"]: r for r in expected_records}
    _require(len(records) == len(expected_records),
             "regenerated design-space membership disagrees with the "
             "persisted candidate records: omission or fabrication "
             "(§74/§133)")
    for r in records:
        exp = expected_by_index[r["index"]]
        _require(r["assignment"] == exp["assignment"],
                 f"candidate {r['index']} assignment disagrees with "
                 f"the regenerated space")
        _require(r["candidate_id"] == exp["candidate_id"],
                 f"candidate {r['index']} identity disagrees with the "
                 f"regenerated space (§72)")
        _require(r["scenario_intent_ids"] == exp["scenario_intent_ids"],
                 f"candidate {r['index']} scenario intent ids disagree "
                 f"with the regenerated space (§71)")
        if exp["status"] == "ALIAS":
            _require(r["status"] == "ALIAS" and
                     r["alias_of"] == exp["alias_of"],
                     f"candidate {r['index']} must remain a visible "
                     f"ALIAS of {exp['alias_of']} (§19/§134)")
        elif exp["status"] == "INVALID":
            _require(r["status"] == "INVALID",
                     f"candidate {r['index']} is INVALID in the "
                     f"regenerated space; persisted status "
                     f"{r['status']!r} fabricates evidence")
        else:
            _require(r["status"] in TERMINAL_EVALUATION_STATUSES or
                     r["status"] == NOT_EVALUATED,
                     f"candidate {r['index']} has non-terminal status "
                     f"{r['status']!r}")

    # 2b) budget-tail agreement (§23/§62/§70/§75): the NOT_EVALUATED set
    #     must be EXACTLY the canonical budget cut — never a hand-picked
    #     subset, and empty for an exhaustive search.
    plan = budget_plan(defn, len(candidates))
    if defn.search_policy == "BUDGETED_GRID":
        tail = candidates[plan["planned_candidates"]:]
    else:
        tail = []
    expected_tail = {c.candidate_id for c in tail}
    actual_tail = {r["candidate_id"] for r in records
                   if r["status"] == NOT_EVALUATED}
    _require(actual_tail == expected_tail,
             "NOT_EVALUATED accounting disagrees with the canonical "
             "budget cut: an evaluated candidate was marked unevaluated "
             "or unevaluated candidates were hidden (§23/§75)")

    # 3) load every successful scenario result through the verified
    #    loader and bind it to THIS candidate's scenario intent (§65/§71)
    results_by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
    for r in records:
        if r["status"] != "SUCCEEDED":
            continue
        per_scenario: dict[str, dict[str, Any]] = {}
        for sname in defn.scenario_names():
            rid = (r["scenario_result_ids"] or {}).get(sname)
            _require(isinstance(rid, str) and rid,
                     f"candidate {r['index']} scenario {sname} has no "
                     f"result id despite SUCCEEDED status")
            vres = load_verified_result(store, rid)
            _require(vres.get("status") == "SUCCEEDED",
                     f"result {rid} is not SUCCEEDED")
            plan = store.get("plan", vres["plan_id"])
            _require(plan.get("intent_id") ==
                     r["scenario_intent_ids"].get(sname),
                     f"result {rid} was produced from intent "
                     f"{plan.get('intent_id')!r}, not this candidate's "
                     f"scenario {sname} intent "
                     f"{r['scenario_intent_ids'].get(sname)!r}: "
                     f"refusing transplanted evidence (§72/§73)")
            per_scenario[sname] = vres
        results_by_candidate[r["candidate_id"]] = per_scenario

    # 4) re-extract objectives + constraints from verified parents
    #    (§66/§67) — SAME scope and SAME template patching as the
    #    builder: only SUCCEEDED candidates have evidence, and
    #    structural metrics must see the candidate-patched template
    #    (§34/§35), not the base one. Failed/NOT_EVALUATED candidates
    #    have no evidence; fabricating UNMEASURABLE "values" for them
    #    would erase the §30 status distinction.
    base_templates = {s.name: s.intent for s in defn.scenarios}
    objective_values: dict[str, dict] = {}
    constraint_values: dict[str, dict] = {}
    constraint_docs: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r["status"] != "SUCCEEDED":
            continue
        cid = r["candidate_id"]
        sres = results_by_candidate[cid]
        assignment = dict(r["assignment"])
        templates = {name: patched_scenario_template(base_templates[name],
                                                     assignment)
                     for name in base_templates}
        objective_values[cid] = extract_objective_values(
            defn, sres, store=store, templates=templates)
        constraint_values[cid] = extract_constraint_values(
            defn, sres, store=store, templates=templates)
        docs = []
        for con in defn.hard_constraints:
            mv = constraint_values[cid][(con.metric, con.scenario)]
            docs.append(evaluate_constraint(
                mv, con.operator, con.bound, scenario=con.scenario))
        constraint_docs[cid] = sorted(
            docs, key=lambda c: (c["metric"], str(c["scenario"])))

    # 5) compare re-extracted objective values with persisted (§66)
    persisted_objectives = artifact["objectives"]
    _require(isinstance(persisted_objectives, dict),
             "objectives must be an object")
    for cid, vals in objective_values.items():
        persisted = persisted_objectives.get(cid)
        _require(persisted is not None,
                 f"candidate {cid} objective values missing from the "
                 f"persisted result (§64)")
        _require(canonical_json(value_map_doc(vals)) ==
                 canonical_json(value_map_doc(
                     value_map_from_doc(persisted))),
                 f"candidate {cid} persisted objective values disagree "
                 f"with re-extraction from verified parents (§66)")

    # 6) compare re-derived constraint verdicts with persisted (§67)
    persisted_constraints = artifact["constraints"]
    for cid, docs in constraint_docs.items():
        persisted = persisted_constraints.get(cid)
        _require(persisted is not None,
                 f"candidate {cid} constraint verdicts missing (§64)")
        _require(canonical_json(docs) == canonical_json(persisted),
                 f"candidate {cid} persisted constraint verdicts "
                 f"disagree with re-derivation (§67)")

    # 7) feasible set + comparability + Pareto recomputation (§68/§77)
    feasible_ids = derive_feasible_ids(defn, records, constraint_docs)
    comparability = comparability_report(
        defn, {cid: results_by_candidate[cid]
               for cid in feasible_ids})
    _require(comparability["comparable"],
             "frontier candidates are not scientifically comparable: "
             + "; ".join(comparability["refusals"]) +
             " (§42/§131)")
    scoped = compute_frontier(
        defn, [{"candidate_id": cid} for cid in feasible_ids],
        objective_values, comparability_ok=True)
    _require(canonical_json(_order_json(scoped)) ==
             canonical_json(artifact["pareto"]),
             "persisted Pareto frontier disagrees with recomputation "
             "(§68/§77)")

    # 8) completeness: search derived from accounting, frontier from
    #    the recomputed scope (§54/§55/§70/§75)
    search = artifact["search"]
    _require(isinstance(search, dict) and
             set(search) == set(SEARCH_FIELDS),
             "search block field set is not closed")
    search_complete = derive_search_complete(records)
    _require(search["search_policy"] == defn.search_policy,
             "persisted search policy disagrees with the definition")
    _require(search["search_complete"] == search_complete,
             "persisted search_complete disagrees with the derived "
             "value (§62/§75)")
    frontier_complete = frontier_is_complete(
        defn, search_complete=search_complete,
        feasible_ids=feasible_ids, objective_values=objective_values,
        comparable_count=scoped.get("comparable_count", 0))
    _require(search["frontier_complete"] == frontier_complete,
             "persisted frontier_complete disagrees with the derived "
             "value (§55)")
    unique = len({r["candidate_id"] for r in records
                  if r["status"] not in ("ALIAS", "INVALID")})
    _require(canonical_json(derive_budget(defn, unique, records)) ==
             canonical_json(search["budget"]),
             "persisted budget accounting disagrees with the derived "
             "accounting (§25)")

    # 9) selection re-derivation (§69/§78/§137)
    selection = select(defn, list(scoped.get("front", [])),
                       objective_values)
    _require(canonical_json(_order_json(selection)) ==
             canonical_json(artifact["selection"]),
             "persisted selection disagrees with recomputation "
             "(§69/§78)")

    # 10) verdict re-derivation with the asymmetric rules (§76)
    verdict = derive_verdict(defn, records, constraint_docs)
    _require(canonical_json(_order_json(verdict)) ==
             canonical_json(artifact["verdict"]),
             "persisted verdict disagrees with recomputation under "
             "the asymmetric negative-claim rules (§76)")

    # 11) informational blocks re-derived (§142/§98)
    dominance = dominance_explanations(scoped)
    _require(canonical_json(_order_json(dominance)) ==
             canonical_json(artifact["dominance"]),
             "persisted dominance evidence disagrees with "
             "recomputation")
    from veritx_dse.optimization.constraints import relaxation_evidence
    relaxation = relaxation_evidence(
        list(constraint_values.values()), list(defn.hard_constraints))
    _require(canonical_json(_order_json(relaxation)) ==
             canonical_json(artifact["relaxation"]),
             "persisted relaxation evidence disagrees with "
             "recomputation")

    # 12) fidelity warning re-derived from verified parents (§138)
    wave_e_models = []
    for sres in results_by_candidate.values():
        for vres in sres.values():
            block = vres.get("wave_e") or {}
            if isinstance(block, dict) and \
                    block.get("metrics_warning"):
                wave_e_models.append(
                    {"metrics_warning": block["metrics_warning"]})
    _require(_fidelity_warning(defn, wave_e_models) ==
             artifact["fidelity_warning"],
             "persisted fidelity warning is not the derived one (§138)")

    # 13) identity: the outer ID binds definition + accounting + scope
    #     (§116); any surviving tamper refuses here (§74/§75)
    recomputed_id = _content_id(_RESULT_TAG, {
        "optimization_definition_id":
            artifact["optimization_definition_id"],
        "candidate_records": artifact["candidate_records"],
        "search_complete": artifact["search"]["search_complete"],
        "frontier_complete": artifact["search"]["frontier_complete"],
    })
    _require(recomputed_id == result_id,
             f"optimizationresult {result_id} recomputes to "
             f"{recomputed_id}: forged")

    return {
        "definition": defn,
        "record": result,
        "artifact": artifact,
        "results_by_candidate": results_by_candidate,
        "objective_values": objective_values,
        "constraint_docs": constraint_docs,
        "feasible_ids": feasible_ids,
        "pareto": scoped,
        "selection": selection,
        "verdict": verdict,
        "search_complete": search_complete,
        "frontier_complete": frontier_complete,
        "budget": derive_budget(defn, unique, records),
    }
