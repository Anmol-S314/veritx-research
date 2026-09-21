"""veritx_dse.optimization.space — finite design space (§15–§28).

The declared Cartesian product is semantic: canonical enumeration means
parameter declarations (§83) and domain values (§84) can be permuted
without changing the mathematical space, while the BUDGETED evaluated
subset stays identical for identical definitions (§24).

Candidates resolve BEFORE execution (§18): an assignment patches every
scenario intent through the verified ``fabric_overrides`` seam and must
``resolve_intent`` cleanly, or it is recorded INVALID and never spawns
a backend. Duplicate assignments that resolve to identical per-scenario
intent identities are evaluated once; the duplicates stay visible as
ALIAS (§19) — duplicates do not enlarge the searched space.

Multi-scenario candidates carry a hardware-consistency proof (§10): a
candidate is valid only if the hardware-defining projection of its
scenario intents agrees across scenarios. Different workloads per
scenario are the point; hardware that differs between PREFILL and
DECODE is not one architecture and refuses.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from veritx_dse.application.requests import resolve_intent
from veritx_dse.core.spec import canonical_json

from .definition import PARAM_REGISTRY, OptimizationDefinition, \
    registered_param

CANDIDATE_STATUS = (
    "SUCCEEDED", "INVALID", "PRUNED_PROVEN", "FAILED", "TIMED_OUT",
    "UNSUPPORTED", "BLOCKED", "UNMEASURABLE", "ALIAS", "NOT_EVALUATED")

#: A valid unique candidate that the budget did not reach. It stays
#: visible in accounting (§64) and keeps search_complete False (§23).
NOT_EVALUATED = "NOT_EVALUATED"


class SpaceError(ValueError):
    """Invalid design-space state (fail-closed)."""


# ── raw enumeration ──────────────────────────────────────────────────────

def iter_raw_assignments(defn: OptimizationDefinition
                         ) -> list[dict[str, Any]]:
    """All assignments of the declared Cartesian product, canonical order.

    Parameters are processed in sorted-name order (§83/§24); domain
    values are already canonically sorted (§84). The first parameter in
    canonical order varies slowest — plain lexicographic enumeration.
    """
    params = sorted(defn.parameters, key=lambda p: p.name)
    out: list[dict[str, Any]] = []

    def rec(i: int, acc: dict[str, Any]) -> None:
        if i == len(params):
            out.append(dict(acc))
            return
        for v in params[i].values:
            acc[params[i].name] = v
            rec(i + 1, acc)

    rec(0, {})
    return out


def raw_cardinality(defn: OptimizationDefinition) -> int:
    """|Cartesian product| before dedupe/invalidity (§20)."""
    n = 1
    for p in defn.parameters:
        n *= len(p.values)
    return n


# ── candidate construction ───────────────────────────────────────────────

@dataclass(frozen=True)
class ScenarioOutcome:
    """One scenario's pre-execution outcome for one assignment."""
    scenario: str
    status: str                    # RESOLVED | INVALID
    intent_id: str | None
    resolved_intent: Any = None
    error: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One candidate: assignment -> per-scenario resolution -> identity."""
    index: int
    assignment: dict[str, Any]
    assignment_id: str
    scenario_outcomes: tuple[ScenarioOutcome, ...]
    candidate_id: str | None       # None when INVALID
    hardware_signature: str | None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.candidate_id is not None

    def intent_ids(self) -> dict[str, str]:
        return {o.scenario: o.intent_id for o in self.scenario_outcomes
                if o.intent_id is not None}


def _patched_overrides(template: dict[str, Any],
                       assignment: dict[str, Any]) -> dict[str, Any]:
    """The patched ``fabric_overrides`` mapping (§12/§107).

    Only registered parameters patch the intent, through the sealed
    ``fabric_overrides`` field — the same seam the verified intent
    system already accepts. The optimizer never touches backend
    configuration (§106/§107).
    """
    overrides = dict(template.get("fabric_overrides") or {})
    for pname, value in assignment.items():
        pdef = registered_param(pname)
        if pdef.scenario_key != "fabric_overrides":
            raise SpaceError(
                f"parameter {pname!r} has unsupported seam "
                f"{pdef.scenario_key!r}")
        overrides[pdef.intent_key] = value
    return overrides


def _merge_intent(template: dict[str, Any],
                  assignment: dict[str, Any]) -> dict[str, Any]:
    """Patched overrides + the untouched scenario template body."""
    merged = dict(template)
    merged["fabric_overrides"] = _patched_overrides(template, assignment)
    return merged


def _hardware_dict(template: dict[str, Any],
                   assignment: dict[str, Any]) -> dict[str, Any]:
    """The hardware-defining projection of one patched scenario (§10).

    Exactly: every registered HARDWARE parameter's assigned value, plus
    the scenario template's fabric-defining fields (fabric_preset and
    the full fabric_overrides mapping, so template-pinned hardware that
    no declared parameter varies still counts). Everything else in the
    template — wave_d/wave_e blocks (which carry the PHASE: PREFILL vs
    DECODE), trace, mapping — deliberately does NOT enter: a signature
    that changes because PREFILL became DECODE is not a hardware
    signature (§10).
    """
    hw: dict[str, Any] = {}
    for pname in sorted(PARAM_REGISTRY):
        pdef = PARAM_REGISTRY[pname]
        if pdef.kind == "HARDWARE":
            hw[pname] = assignment.get(pname)
    hw["template.fabric_preset"] = template.get("fabric_preset")
    hw["template.fabric_overrides"] = _order_json(dict(
        sorted((template.get("fabric_overrides") or {}).items())))
    return hw


def hardware_signature(template: dict[str, Any],
                       assignment: dict[str, Any]) -> str:
    """Content address of the hardware-defining projection (§10)."""
    body = "srota/optimization/hardware/v1\0" + canonical_json(
        _order_json(_hardware_dict(template, assignment)))
    return hashlib.sha256(body.encode()).hexdigest()


def candidate_identity(defn_id: str, assignment: dict[str, Any],
                       scenario_intent_ids: dict[str, str | None]) -> str:
    """candidate_assignment_id = H(design_space_id, canonical assignment,
    resolved scenario intent ids) (§17).

    The evaluated evidence is bound separately through the verified
    result chain (result -> plan -> intent_id), so a result from another
    candidate or another scenario cannot be transplanted (§71–§73).
    """
    body = {
        "design_space_id": defn_id,
        "assignment": _order_json(assignment),
        "scenario_intents": _order_json(
            dict(sorted(scenario_intent_ids.items()))),
    }
    payload = "srota/optimization/candidate/v1\0" + canonical_json(body)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_candidates(
        defn: OptimizationDefinition
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """Enumerate, resolve, dedupe.

    Returns (canonical valid candidates in canonical order, records).
    Every raw assignment appears in ``records`` exactly once (§30/§64:
    no disappearing candidates) with status VALID, ALIAS, or INVALID;
    the runner finalizes VALID records with evaluation outcomes and the
    verifier recomputes them (§70).
    """
    defn_id = defn.definition_id()
    resolved: list[Candidate] = []
    records: list[dict[str, Any]] = []

    for index, assignment in enumerate(iter_raw_assignments(defn)):
        outcomes: list[ScenarioOutcome] = []
        for spec in defn.scenarios:
            merged = _merge_intent(spec.intent, assignment)
            try:
                intent, _, _ = resolve_intent(merged)
                outcomes.append(ScenarioOutcome(
                    scenario=spec.name, status="RESOLVED",
                    intent_id=intent.intent_id(), resolved_intent=intent))
            except Exception as exc:  # resolve_intent is the authority
                outcomes.append(ScenarioOutcome(
                    scenario=spec.name, status="INVALID", intent_id=None,
                    error=f"{type(exc).__name__}: {exc}"))
        ids = {o.scenario: o.intent_id for o in outcomes}
        cid = candidate_identity(defn_id, assignment, ids)
        base_record = {
            "index": index,
            "assignment": _order_json(assignment),
            "candidate_id": cid,
            "status": "VALID",
            "alias_of": None,
            "scenario_intent_ids": _order_json(dict(sorted(
                ids.items()))),
            "error": None,
        }
        invalid_reason: str | None = next(
            (o.error for o in outcomes if o.error), None)
        # §10: multi-scenario hardware consistency must be PROVEN.
        if invalid_reason is None and len(outcomes) > 1:
            sigs = {
                spec.name: hardware_signature(spec.intent, assignment)
                for spec in defn.scenarios}
            if len(set(sigs.values())) != 1:
                invalid_reason = "hardware signature differs across " \
                    "scenarios: " + "; ".join(
                        f"{k}={v[:12]}"
                        for k, v in sorted(sigs.items()))
        if invalid_reason is not None:
            base_record["status"] = "INVALID"
            base_record["error"] = invalid_reason
            resolved.append(Candidate(
                index=index, assignment=assignment, assignment_id=cid,
                scenario_outcomes=tuple(outcomes), candidate_id=None,
                hardware_signature=None, error=invalid_reason))
        else:
            sig = (hardware_signature(defn.scenarios[0].intent, assignment)
                   if len(outcomes) > 1 else None)
            resolved.append(Candidate(
                index=index, assignment=assignment, assignment_id=cid,
                scenario_outcomes=tuple(outcomes), candidate_id=cid,
                hardware_signature=sig, error=None))
        records.append(base_record)

    # §19: dedupe on the per-scenario intent identity SET. First in
    # canonical order is the evaluated canonical candidate; later
    # duplicates stay visible as ALIAS.
    by_key: dict[str, int] = {}
    canonical: list[Candidate] = []
    for cand in resolved:
        if not cand.valid:
            continue
        key = canonical_json(dict(sorted(cand.intent_ids().items())))
        first = by_key.get(key)
        if first is not None:
            records[cand.index]["status"] = "ALIAS"
            records[cand.index]["alias_of"] = \
                records[first]["candidate_id"]
            continue
        by_key[key] = cand.index
        canonical.append(cand)
    return canonical, records


# ── budget accounting (§20/§25) ──────────────────────────────────────────

def budget_plan(defn: OptimizationDefinition,
                unique_count: int) -> dict[str, int]:
    """Pre-execution plan: how much will actually run (§20).

    A candidate is evaluated on ALL its scenarios (partial evaluation
    cannot enter a per-scenario Pareto), so max_scenario_evaluations
    admits floor(max_e / n_scenarios) whole candidates.
    """
    n_scen = len(defn.scenarios)
    planned = unique_count
    if defn.budget.get("max_design_candidates") is not None:
        planned = min(planned, defn.budget["max_design_candidates"])
    if defn.budget.get("max_scenario_evaluations") is not None:
        planned = min(planned,
                      defn.budget["max_scenario_evaluations"] // n_scen)
    return {
        "raw_assignments": raw_cardinality(defn),
        "unique_candidates": unique_count,
        "planned_candidates": planned,
        "planned_evaluations": planned * n_scen,
    }


def budget_accounting(raw: int, unique: int, evaluated_c: int,
                      evaluated_e: int, reused: int) -> dict[str, int]:
    """Final budget report (§25): requested vs actual vs reused."""
    return {
        "raw_assignments": raw,
        "unique_candidates": unique,
        "candidates_evaluated": evaluated_c,
        "scenario_evaluations_attempted": evaluated_e,
        "evaluations_reused": reused,
    }


def _order_json(value: Any) -> Any:
    """Recursively sort dict keys for canonical embedding."""
    if isinstance(value, dict):
        return {k: _order_json(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_order_json(v) for v in value]
    return value
