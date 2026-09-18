"""compiler.py — requirements-driven fabric compiler (Phase 13, plan §17).

E2 requirements stop being inert data and actively gate synthesis:

  binding requirement   → hard constraint (per-constraint verdicts; every
                          feasible candidate must satisfy every constraint)
  non-binding           → recorded soft preference (never enforced silently)

Verdicts (exactly one):
  FEASIBLE              ≥1 candidate satisfied all constraints; Pareto
                        evidence over the feasible set via the Phase-8 gate
                        (pareto_with_scope — never re-implemented here)
  NO_FEASIBLE_DESIGN    every candidate failed some constraint; carries
                        violated-constraint evidence plus relaxation
                        information (tightest ceiling that would admit the
                        best measured candidate)
  (incoherent requests raise InvalidCompilerRequest before any evaluation)

Fail-closed semantics:
  - a constraint the candidate record cannot measure (bandwidth floors
    today: no measured GB/s exists anywhere in the stack) marks the
    candidate CONSTRAINT_UNMEASURABLE — never a silent pass
  - failed evaluations stay visible as EVALUATION_FAILED with their error
  - pruned candidates stay visible as PRUNED with their pruning reason and
    are never evaluated
  - sampling basis is stated: single-sample records never imply confidence
    intervals (seed policy is recorded, not pretended into statistics)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from veritx_dse.core.comparison import pareto_with_scope
from veritx_dse.model.compile_model import QoSClass, Requirement

# Candidate statuses (compiler-specific; distinct from Phase-8 comparison
# statuses on purpose — these describe constraint evaluation, not metric
# comparability across runs).
ST_FEASIBLE = "FEASIBLE"
ST_CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
ST_EVALUATION_FAILED = "EVALUATION_FAILED"
ST_CONSTRAINT_UNMEASURABLE = "CONSTRAINT_UNMEASURABLE"
ST_PRUNED = "PRUNED"

VERDICT_FEASIBLE = "FEASIBLE"
VERDICT_NO_FEASIBLE_DESIGN = "NO_FEASIBLE_DESIGN"

# The one constraint kind whose metric the stack cannot measure yet.
_UNMEASURABLE = {"bandwidth_floor": "bandwidth_floor_gbps"}


class InvalidCompilerRequest(ValueError):
    """Incoherent compiler request — fail closed before any evaluation."""


@dataclass
class CompilerRequest:
    """What to compile: requirements + candidate set + search policy.

    candidates: entries with at least ``name``; ``pruned: True`` entries
        must carry ``pruning_reason`` and are carried through unevaluated.
    search_budget: caller-declared budget (e.g. requested_evaluations);
        the result records requested vs executed.
    seed_policy: recorded verbatim; with replication 1 the result states
        ``single_sample_no_confidence_interval`` (n=1 honesty).
    """

    requirements: list[Requirement] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    search_budget: dict[str, Any] = field(default_factory=dict)
    seed_policy: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.requirements = [
            r if isinstance(r, Requirement) else self._coerce_requirement(r)
            for r in (self.requirements or [])
        ]
        self._validate()

    @staticmethod
    def _coerce_requirement(r: Any) -> Requirement:
        if not isinstance(r, dict):
            raise InvalidCompilerRequest(
                f"requirement must be Requirement or dict, got {type(r).__name__}")
        try:
            qos = QoSClass(r.get("qos_class"))
        except ValueError:
            raise InvalidCompilerRequest(
                f"unknown qos_class {r.get('qos_class')!r} — "
                f"known: {[c.value for c in QoSClass]}") from None
        return Requirement(
            qos_class=qos,
            latency_ceiling_cycles=r.get("latency_ceiling_cycles"),
            bandwidth_floor_gbps=r.get("bandwidth_floor_gbps"),
            binding=bool(r.get("binding", False)),
        )

    def _validate(self):
        for r in self.requirements:
            if r.binding and r.latency_ceiling_cycles is None \
                    and r.bandwidth_floor_gbps is None:
                raise InvalidCompilerRequest(
                    f"binding requirement {r.qos_class.value} carries no bound "
                    "(no latency ceiling, no bandwidth floor) — a constraint "
                    "with no number can never be evaluated; declare one or "
                    "mark the requirement non-binding")
            for kind, val in (("latency_ceiling_cycles", r.latency_ceiling_cycles),
                              ("bandwidth_floor_gbps", r.bandwidth_floor_gbps)):
                if val is not None and float(val) <= 0:
                    raise InvalidCompilerRequest(
                        f"{kind} must be positive, got {val}")
        for c in self.candidates or []:
            if not isinstance(c, dict) or not c.get("name"):
                raise InvalidCompilerRequest(
                    "every candidate needs a name — unnamed candidates "
                    "cannot appear in evidence")
            if c.get("pruned") and not c.get("pruning_reason"):
                raise InvalidCompilerRequest(
                    f"candidate {c['name']} is pruned without a "
                    "pruning_reason — invisible pruning is the failure mode "
                    "this compiler exists to prevent")
        if not self.candidates:
            raise InvalidCompilerRequest(
                "empty candidate set — an exhausted search is search "
                "evidence, not an empty request; supply the candidates "
                "actually generated (possibly PRUNED with reasons)")

    @classmethod
    def from_dict(cls, d: dict) -> "CompilerRequest":
        return cls(
            requirements=list(d.get("requirements", [])),
            candidates=list(d.get("candidates", [])),
            search_budget=dict(d.get("search_budget", {})),
            seed_policy=dict(d.get("seed_policy", {})),
        )


def _constraint_label(r: Requirement) -> dict[str, Any]:
    if r.latency_ceiling_cycles is not None:
        return {"kind": "latency_ceiling", "qos_class": r.qos_class.value,
                "bound": float(r.latency_ceiling_cycles),
                "unit": "cycles", "direction": "max"}
    return {"kind": "bandwidth_floor", "qos_class": r.qos_class.value,
            "bound": float(r.bandwidth_floor_gbps),
            "unit": "gbps", "direction": "min"}


def _evaluate_constraint(r: Requirement, measured_latency: float) -> dict[str, Any]:
    """One constraint verdict against a measured latency.

    Bandwidth floors never reach here (unmeasurable, handled by caller):
    the stack has no measured GB/s producer, so enforcing against an
    invented number would be silent fabrication.
    """
    label = _constraint_label(r)
    ok = measured_latency <= label["bound"]
    return {"constraint": label, "metric": "latency", "measured": measured_latency,
            "satisfied": ok,
            "margin": label["bound"] - measured_latency if ok else None,
            "excess": measured_latency - label["bound"] if not ok else None}


def compile_fabric(request: CompilerRequest,
                   evaluate: Callable[[dict], dict]) -> dict[str, Any]:
    """Run requirement-gated synthesis over the candidate set.

    ``evaluate`` maps a candidate entry to a SynthResult-shaped dict
    (status ok/error, latency). Exceptions from evaluate become
    EVALUATION_FAILED candidates — a crashing candidate must not crash
    the compiler or vanish from the record.
    """
    executed = 0
    records: list[dict[str, Any]] = []
    hard = [r for r in request.requirements if r.binding]
    soft = [r for r in request.requirements if not r.binding]

    for cand in request.candidates:
        rec: dict[str, Any] = {
            "candidate_id": cand["name"],
            "candidate": {k: v for k, v in cand.items()
                          if k not in ("pruned", "pruning_reason")},
        }
        if cand.get("pruned"):
            rec.update(status=ST_PRUNED, pruning_reason=cand["pruning_reason"],
                       constraint_verdicts=[], latency=None)
            records.append(rec)
            continue

        try:
            executed += 1
            result = evaluate(cand)
        except Exception as e:  # noqa: BLE001 — failed evals are evidence
            rec.update(status=ST_EVALUATION_FAILED, error=str(e),
                       constraint_verdicts=[], latency=None)
            records.append(rec)
            continue

        if result.get("status") != "ok" or result.get("latency") is None:
            rec.update(status=ST_EVALUATION_FAILED,
                       error=result.get("error") or "no latency parsed",
                       constraint_verdicts=[], latency=None)
            records.append(rec)
            continue

        latency = float(result["latency"])
        rec["latency"] = latency
        rec["seed"] = result.get("seed", cand.get("seed"))
        rec["fidelity"] = result.get("fidelity", cand.get("fidelity"))
        rec["metrics"] = {"latency": latency}
        rec["result"] = {k: v for k, v in result.items()
                         if k not in ("latency", "seed")}

        verdicts: list[dict[str, Any]] = []
        unmeasurable = [r for r in hard if _constraint_label(r)["kind"] in _UNMEASURABLE]
        for r in hard:
            if _constraint_label(r)["kind"] in _UNMEASURABLE:
                continue
            verdicts.append(_evaluate_constraint(r, latency))
        rec["constraint_verdicts"] = verdicts

        if unmeasurable:
            rec.update(
                status=ST_CONSTRAINT_UNMEASURABLE,
                unmeasurable=[_constraint_label(r) for r in unmeasurable],
                unmeasurable_reason=(
                    "no measured producer exists for this metric in the "
                    "stack today — enforcing would fabricate a number"))
        elif any(not v["satisfied"] for v in verdicts):
            rec.update(status=ST_CONSTRAINT_VIOLATION)
        else:
            rec.update(status=ST_FEASIBLE)
        records.append(rec)

    n_feasible = sum(1 for r in records if r["status"] == ST_FEASIBLE)
    n_violated = sum(1 for r in records if r["status"] == ST_CONSTRAINT_VIOLATION)
    n_failed = sum(1 for r in records if r["status"] == ST_EVALUATION_FAILED)
    n_unmeasurable = sum(1 for r in records if r["status"] == ST_CONSTRAINT_UNMEASURABLE)
    n_pruned = sum(1 for r in records if r["status"] == ST_PRUNED)

    out: dict[str, Any] = {
        "request": {
            "hard_constraints": [_constraint_label(r) for r in hard],
            "soft_requirements": [_constraint_label(r) for r in soft],
            "seed_policy": dict(request.seed_policy),
            "sampling_basis": (
                "single_sample_no_confidence_interval"
                if int(request.seed_policy.get("replication", 1)) <= 1
                else "replicated"),
        },
        "search_budget": {**request.search_budget, "executed": executed},
        "scope": {
            "candidates": len(records),
            "feasible": n_feasible,
            "constraint_violation": n_violated,
            "evaluation_failed": n_failed,
            "constraint_unmeasurable": n_unmeasurable,
            "pruned": n_pruned,
        },
        "candidates": records,
    }

    if n_feasible == 0:
        out["verdict"] = VERDICT_NO_FEASIBLE_DESIGN
        out["pareto"] = None
        out["violated_constraints"] = _violated_evidence(records, hard)
        out["relaxation_information"] = _relaxation(records, hard)
        return out

    out["verdict"] = VERDICT_FEASIBLE
    out["violated_constraints"] = _violated_evidence(records, hard)
    # Phase-8 gate over the feasible set: statuses + scope statement are
    # its contract; we never sort winners ourselves.
    pareto_in = [{"run_id": r["candidate_id"], "status": "COMPARABLE",
                  "fidelity": r.get("fidelity"),
                  "metrics": r["metrics"]} for r in records
                 if r["status"] == ST_FEASIBLE]
    out["pareto"] = pareto_with_scope(pareto_in, ["latency"])
    return out


def _violated_evidence(records: list[dict], hard: list[Requirement]) -> list[dict]:
    """Per-constraint violation evidence across all evaluated candidates."""
    ev: list[dict] = []
    for r in hard:
        if _constraint_label(r)["kind"] in _UNMEASURABLE:
            measured = [rec for rec in records
                        if rec["status"] == ST_CONSTRAINT_UNMEASURABLE]
            if measured:
                ev.append({"constraint": _constraint_label(r),
                           "status": ST_CONSTRAINT_UNMEASURABLE,
                           "candidates": [rec["candidate_id"] for rec in measured],
                           "reason": measured[0].get("unmeasurable_reason")})
            continue
        violating = [rec for rec in records
                     if any(not v["satisfied"] for v in rec["constraint_verdicts"]
                            if v["constraint"]["kind"] == _constraint_label(r)["kind"])]
        if not violating:
            continue
        lats = [rec["latency"] for rec in violating if rec.get("latency") is not None]
        ev.append({
            "constraint": _constraint_label(r),
            "candidates": [rec["candidate_id"] for rec in violating],
            "best_measured": min(lats) if lats else None,
            "margin_needed": (min(lats) - float(r.latency_ceiling_cycles))
            if lats else None,
        })
    return ev


def _relaxation(records: list[dict], hard: list[Requirement]) -> dict[str, Any]:
    """What the request would have to become to admit a real design.

    Only measured numbers inform relaxation — never defaults.
    """
    per: dict[str, Any] = {}
    best_overall: float | None = None
    for r in hard:
        label = _constraint_label(r)
        if label["kind"] in _UNMEASURABLE:
            per[f"{label['kind']}[{label['qos_class']}]"] = {
                "relaxable": False,
                "reason": "metric unmeasured anywhere in the stack; "
                          "relaxation is meaningless without a measurement"}
            continue
        lats = [rec["latency"] for rec in records
                if rec.get("latency") is not None]
        violations = sum(
            1 for rec in records
            if any(not v["satisfied"] for v in rec["constraint_verdicts"]
                   if v["constraint"]["kind"] == label["kind"]))
        per[f"{label['kind']}[{label['qos_class']}]"] = {
            "violations": violations,
            "relaxable": violations > 0,
        }
        if lats:
            best_overall = min(lats) if best_overall is None \
                else min(best_overall, min(lats))
    return {
        "minimal_ceiling_admitting_best": best_overall,
        "per_constraint": per,
        "note": "relaxation is information, not an action — hard "
                "requirements are never silently relaxed",
    }
