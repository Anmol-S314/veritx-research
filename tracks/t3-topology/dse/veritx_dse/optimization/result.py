"""veritx_dse.optimization.result — OptimizationResult + Optimizer (P2).

OptimizationResult binds: base request identity, definition,
candidate/evaluation IDs, objective values, constraint verdicts, Pareto
membership, selection rationale. Execution order never changes
candidate identity (asserted by re-derivation).

Emits OptimizationStudyView per
contracts/srota/v1/optimization.study.view.schema.json (contract_version 1).

Provenance: result-identity and re-derivation discipline REPLAY
synthesis/compiler.py (request/budget/scope accounting, Pareto only over
the feasible set, relaxation as information) and the reference
result.py (content_id over definition + candidate rows + frontier);
Wave-F result.py's verified-loader machinery is SUPERSEDED (no control
plane / store in P2 — the fake evaluator carries no persisted evidence;
see CAPABILITY-LEDGER.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id

RESULT_DOMAIN = "veritx/optimization-result/v2"


class OptimizationResultError(ValueError):
    """Invalid optimization result state (fail-closed)."""


@dataclass(frozen=True)
class CandidateRecord:
    """One evaluated candidate with verdicts and Pareto membership."""
    candidate_id: str
    guided_patch: dict[str, Any]
    design_hash: str
    locked_consequences: dict[str, Any]
    evaluation_status: str
    objective_values: dict[str, float]
    constraint_verdicts: dict[str, bool | None]
    pareto_member: bool
    performance_result_id: str | None = None


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
        rows = [{
            "candidate_id": r.candidate_id,
            "guided_patch": {k: r.guided_patch[k]
                             for k in sorted(r.guided_patch)},
            "design_hash": r.design_hash,
            "objective_values": {k: r.objective_values[k]
                                 for k in sorted(r.objective_values)},
            "constraint_verdicts": {
                k: (None if v is None else bool(v))
                for k, v in sorted(r.constraint_verdicts.items())},
            "pareto_member": bool(r.pareto_member),
        } for r in sorted(self.records, key=lambda r: r.candidate_id)]
        return content_id(RESULT_DOMAIN, {
            "base_design_hash": self.base_design_hash,
            "definition_id": self.definition.definition_id(),
            "candidates": rows,
            "pareto_ids": list(self.pareto_ids),
            "selected_candidate_id": self.selected_candidate_id,
        })

    def to_study_view(self) -> dict[str, Any]:
        """Emit the frozen OptimizationStudyView (contract v1)."""
        defn = self.definition
        candidates = []
        for r in sorted(self.records, key=lambda r: r.candidate_id):
            evaluations: dict[str, Any] = {"design_hash": r.design_hash}
            evaluations["performance_result_id"] = r.performance_result_id
            candidates.append({
                "candidate_id": r.candidate_id,
                "guided_patch": dict(r.guided_patch),
                "locked_consequences": dict(r.locked_consequences),
                "evaluation_ids": evaluations,
                "objective_values": {k: float(v)
                                     for k, v in r.objective_values.items()},
                "constraint_verdicts": {
                    k: (False if v is None else bool(v))
                    for k, v in r.constraint_verdicts.items()},
                "pareto_member": bool(r.pareto_member),
            })
        # Frozen view requires sha256:-prefixed identities; the
        # in-memory result carries the bare CompileRequest design hash.
        # UNMEASURABLE verdicts (None) collapse to false here: the
        # view's constraint_verdicts is boolean-only (frozen schema),
        # and fail-closed means unmeasurable is never satisfied. The
        # full OptimizationResult retains the None distinction.
        return {
            "contract_version": 1,
            "base_design_hash": "sha256:" + self.base_design_hash,
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


class Optimizer:
    """Deterministic optimize: search -> evaluate -> verdicts -> Pareto."""

    def optimize(self, base_request: Any, definition: Any,
                 evaluator: Any) -> OptimizationResult:
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
            if ev.status == "EVALUATED":
                verdicts = evaluate_all(definition.constraints,
                                        ev.objective_values)
            else:
                verdicts = {"verdicts": {
                    c.metric if hasattr(c, "metric") else c["metric"]:
                    {"verdict": "UNMEASURABLE", "value": None}
                    for c in (definition.constraints or [])},
                    "feasible": (None if definition.constraints else False)}
                if not definition.constraints:
                    verdicts["feasible"] = False
            feasible = verdicts["feasible"]
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
