"""veritx_dse.optimization.pareto — Pareto frontier (P2).

Rationale: docs/decisions/modules/optimization.md
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from veritx_dse.optimization.definition import metric_axis_key

_MISSING = object()

def _objective_axis(objective: Any) -> str:
    """The candidate-value key one objective reads.

    ``Objective.key`` is the stable ``(metric, traffic_class)`` axis, so a
    class-scoped objective reads its composite key and never falls back to
    the bare metric. Items already projected to plain mappings by the
    optimizer carry the axis in ``metric``; a raw mapping that still carries
    ``traffic_class`` is projected onto the same composite key here.
    """
    declared = (objective.get("key", _MISSING)
                if isinstance(objective, Mapping)
                else getattr(objective, "key", _MISSING))
    if declared is not _MISSING:
        if not isinstance(declared, str) or not declared:
            raise ValueError(
                f"objective axis key must be a non-empty string, got "
                f"{declared!r}")
        return declared
    metric = (objective.get("metric") if isinstance(objective, Mapping)
              else getattr(objective, "metric", None))
    traffic_class = (objective.get("traffic_class")
                     if isinstance(objective, Mapping)
                     else getattr(objective, "traffic_class", None))
    if not isinstance(metric, str) or not metric:
        raise KeyError(
            f"objective carries no metric or axis key: {objective!r}")
    return metric_axis_key(metric, traffic_class)

def _objective_axes(objectives: Any) -> tuple[list[str], list[str]]:
    names = [_objective_axis(o) for o in objectives]
    directions = [o.direction if hasattr(o, "direction") else o["direction"]
                  for o in objectives]
    return names, directions

def pareto_front(values, directions):
    ids = sorted(values)

    def dominates(a, b):
        no_worse = True
        strict = False
        for x, y, d in zip(values[a], values[b], directions):
            if d == "MIN":
                no_worse &= x <= y
                strict |= x < y
            else:
                no_worse &= x >= y
                strict |= x > y
        return bool(no_worse and strict)
    return tuple(cid for cid in ids
                 if not any(dominates(other, cid)
                            for other in ids if other != cid))

def pareto_ids(objective_values: dict[str, dict[str, float]],
               objectives: Any) -> tuple[str, ...]:
    """Frontier over {candidate_id: {axis_key: value}} in objective order."""
    if not objective_values:
        return ()
    names, directions = _objective_axes(objectives)
    values = {cid: tuple(float(vals[m]) for m in names)
              for cid, vals in objective_values.items()}
    return pareto_front(values, directions)

def pareto_with_sealed_gate(objective_values: dict[str, dict[str, float]],
                            objectives: Any,
                            fidelities: dict[str, str]) -> dict[str, Any]:
    """Cross-check the moved frontier against the sealed Phase-8 gate.

    Fidelity rides per candidate — there is deliberately no default stamp.
    A candidate with no fidelity entry refuses here, and mixed fidelities
    refuse inside pareto_with_scope (same rule the synthesis compiler
    relies on). Returns the sealed scope doc plus the moved front for
    agreement assertion by callers/tests.
    """
    from veritx_dse.core.comparison import (
        ComparisonSpecError, pareto_with_scope,
    )
    missing = sorted(set(objective_values) - set(fidelities))
    if missing:
        raise ComparisonSpecError(
            f"pareto over candidates with no fidelity: {missing} — "
            "unstamped candidates cannot join a frontier")
    names, directions = _objective_axes(objectives)
    cands = [{"run_id": cid, "status": "COMPARABLE",
              "fidelity": fidelities[cid],
              "metrics": {m: float(vals[m]) for m in names}}
             for cid, vals in sorted(objective_values.items())]
    gated = []
    for c in cands:
        metrics = {}
        for m, d in zip(names, directions):
            metrics[m] = -c["metrics"][m] if d == "MAX" else c["metrics"][m]
        gated.append({**c, "metrics": metrics})
    scope = pareto_with_scope(gated, names)
    return {"scope": scope, "front": pareto_ids(objective_values, objectives)}

__all__ = ["pareto_front", "pareto_ids", "pareto_with_sealed_gate"]
