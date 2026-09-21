"""veritx_dse.optimization.pareto — Pareto frontier (P2).

MOVED from the North-Star reference optimization pareto module
(pareto_front: exact dominance, MIN/MAX directions, sorted-id
order — reused verbatim, no style rewrites) plus a thin objective-space
adapter and a sealed-gate cross-check against
core.comparison.pareto_with_scope (the Phase-8 authority REPLAYED from
synthesis/compiler.py's Pareto stage).

Ties stay ties: equal objective vectors neither dominate nor eliminate
each other.
"""
from __future__ import annotations

from typing import Any


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
    """Frontier over {candidate_id: {metric: value}} in objective order."""
    if not objective_values:
        return ()
    names = [o.metric if hasattr(o, "metric") else o["metric"]
             for o in objectives]
    directions = [o.direction if hasattr(o, "direction") else o["direction"]
                  for o in objectives]
    values = {cid: tuple(float(vals[m]) for m in names)
              for cid, vals in objective_values.items()}
    return pareto_front(values, directions)


def pareto_with_sealed_gate(objective_values: dict[str, dict[str, float]],
                            objectives: Any,
                            fidelity: str = "FAKE_DETERMINISTIC") -> dict[str, Any]:
    """Cross-check the moved frontier against the sealed Phase-8 gate.

    Every candidate enters as COMPARABLE with its objective metrics;
    mixed fidelities refuse inside pareto_with_scope (same rule the
    synthesis compiler relies on). Returns the sealed scope doc plus
    the moved front for agreement assertion by callers/tests.
    """
    from veritx_dse.core.comparison import pareto_with_scope
    names = [o.metric if hasattr(o, "metric") else o["metric"]
             for o in objectives]
    cands = [{"run_id": cid, "status": "COMPARABLE",
              "fidelity": fidelity,
              "metrics": {m: float(vals[m]) for m in names}}
             for cid, vals in sorted(objective_values.items())]
    # pareto_with_scope minimizes every axis; MAX objectives are
    # projected by negation for the gate check only.
    directions = [o.direction if hasattr(o, "direction") else o["direction"]
                  for o in objectives]
    gated = []
    for c in cands:
        metrics = {}
        for m, d in zip(names, directions):
            metrics[m] = -c["metrics"][m] if d == "MAX" else c["metrics"][m]
        gated.append({**c, "metrics": metrics})
    scope = pareto_with_scope(gated, names)
    return {"scope": scope, "front": pareto_ids(objective_values, objectives)}


__all__ = ["pareto_front", "pareto_ids", "pareto_with_sealed_gate"]
