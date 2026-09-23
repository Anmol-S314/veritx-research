"""veritx_dse.optimization.search — deterministic search first (P2).

Enumeration, grid, and bounded seeded random as the correctness oracle.
Bayes/MILP refuse until deterministic correctness is established.

Canonical order (REPLAYED from reference search.canonical_assignments
and wave-f space.iter_raw_assignments §24/§83/§84): parameters sorted
by name, domain values sorted by canonical JSON; the first parameter
in canonical order varies slowest (lexicographic product). Declaration
order never changes the searched set; budget truncation keeps the
canonical prefix, never a sample (wave-f §23 rule, REPLAYED).

No blind Wave-F merge: BO/RHO/GRPO/SA/MILP loops are NOT imported here
(REJECTED/HISTORICAL per CAPABILITY-LEDGER.md).
"""
from __future__ import annotations

import random
from itertools import product
from typing import Any, Iterator

from veritx_dse.core.spec import canonical_json


class SearchError(ValueError):
    """Invalid search request (fail-closed)."""


def canonical_assignments(defn: Any) -> Iterator[dict[str, Any]]:
    """Yield every domain assignment in canonical order."""
    params = sorted(defn.domain, key=lambda p: p.name)
    domains = [tuple(sorted(p.values, key=canonical_json)) for p in params]
    names = [p.name for p in params]
    if not params:
        yield {}
        return
    for vals in product(*domains):
        yield dict(zip(names, vals))


def raw_cardinality(defn: Any) -> int:
    """|Cartesian product| before budget."""
    n = 1
    for p in defn.domain:
        n *= len(p.values)
    return n


def _budget_limit(defn: Any) -> int | None:
    budget = dict(getattr(defn, "budget", None) or {})
    mc = budget.get("max_candidates")
    me = budget.get("max_evaluations")
    limits = [v for v in (mc, me) if v is not None]
    if not limits:
        return None
    return min(limits)


def enumerate_candidates(base: Any, defn: Any) -> list[Any]:
    """Exhaustive grid: every assignment -> Candidate, canonical order."""
    from .candidate import make_candidate
    return [make_candidate(base, patch)
            for patch in canonical_assignments(defn)]


def bounded_random_candidates(base: Any, defn: Any) -> list[Any]:
    """Bounded seeded random subsample (deterministic oracle).

    Shuffles the canonical enumeration with seed(defn.seed) and keeps
    the budget prefix. Budget defaults to the full cardinality when
    unset. Requires defn.seed (checked at definition construction).
    """
    from .candidate import make_candidate
    if defn.seed is None:
        raise SearchError("random search requires definition seed")
    all_patches = list(canonical_assignments(defn))
    limit = _budget_limit(defn)
    if limit is None:
        limit = len(all_patches)
    if limit > len(all_patches):
        raise SearchError(
            f"budget max {limit} exceeds raw cardinality {len(all_patches)}")
    rng = random.Random(int(defn.seed))
    order = list(all_patches)
    rng.shuffle(order)
    # Deterministic presentation: keep selection sorted canonically so
    # the evaluated SET is seed-dependent but the ORDER is canonical.
    chosen = order[:limit]
    chosen.sort(key=canonical_json)
    return [make_candidate(base, patch) for patch in chosen]


def search_candidates(base: Any, defn: Any) -> list[Any]:
    """Dispatch by definition method; enforce budget on grid as prefix."""
    method = getattr(defn, "method", "grid")
    if method in ("grid", "enumeration"):
        cands = enumerate_candidates(base, defn)
        limit = _budget_limit(defn)
        if limit is not None:
            cands = cands[:limit]
        return cands
    if method == "random":
        return bounded_random_candidates(base, defn)
    raise SearchError(
        f"search method {method!r} refused: Bayes/MILP only after "
        "deterministic correctness is established — use grid/enumeration/random")


__all__ = [
    "SearchError", "bounded_random_candidates", "canonical_assignments",
    "enumerate_candidates", "raw_cardinality", "search_candidates",
]
