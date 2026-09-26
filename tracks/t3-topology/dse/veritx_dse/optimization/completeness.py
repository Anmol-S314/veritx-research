"""veritx_dse.optimization.completeness — search completeness accounting.

THE DEFECT THIS REPAIRS
-----------------------

``search.py::search_candidates`` applies the budget as a silent prefix
truncation::

    cands = enumerate_candidates(base, defn)
    limit = _budget_limit(defn)
    if limit is not None:
        cands = cands[:limit]        # <- no completeness fact survives
    return cands

A consumer therefore cannot distinguish an exhaustive search from a
truncated one. The historical vocabulary existed and was removed
(``EXHAUSTIVE_GRID`` in 2 commits, ``BUDGETED_GRID`` in 3,
``NOT_EVALUATED`` in 4); ``optimization/CAPABILITY-LEDGER.md`` row W11
records the loss as ``HISTORICAL`` with the reason *"no
ALIAS/INVALID/NOT_EVALUATED states in P2"*.

Silent truncation is the exact failure mode that vocabulary existed to
prevent: a budgeted search that looks exhaustive will be read as an
optimality claim.

THE LAW
-------

Seven mechanical invariants (each is a test, not prose):

1. Truncation is identity/evidence-visible.
2. ``EXHAUSTIVE`` is never inferred — only claimed when
   ``universe_known`` and ``evaluated_count == universe_size``.
3. Non-evaluated candidates remain represented; absence must not look
   like nonexistence.
4. Pareto uses only eligible, evaluated candidates (unchanged).
5. Requirement violation stays separate from Pareto eligibility
   (unchanged).
6. Generated objective != evaluated metric (unchanged).
7. A synthesis engine cannot manufacture a certificate or evidence
   (unchanged; synthesis is a candidate producer, not an authority).

PRODUCT LANGUAGE
----------------

* exhaustive finite enumeration, all resolved:
  "complete over this declared finite design space"
* budgeted / synthesized:
  "best observed among evaluated candidates"
* otherwise: no optimality claim at all.

Never "optimal NoC" without a fully qualified scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOMAIN = "veritx/search-completeness/v1"
SCHEMA_VERSION = 1

#: Completeness verdicts. EXHAUSTIVE is the only one that may support a
#: completeness claim.
COMPLETENESS_VALUES = ("EXHAUSTIVE", "BUDGETED", "UNBOUNDED")

#: Product-facing claim text. Keyed by completeness value.
CLAIM_TEXT = {
    "EXHAUSTIVE": "complete over this declared finite design space",
    "BUDGETED": "best observed among evaluated candidates",
    "UNBOUNDED": "best observed among evaluated candidates",
}


class CompletenessError(ValueError):
    """Invalid completeness accounting (typed, fail-closed)."""


@dataclass(frozen=True)
class SearchCompleteness:
    """What was searched, what was not, and whether the search was complete.

    ``universe_known`` is the honesty switch: when the search method cannot
    bound its own space (a seeded random subsample), the universe size is
    NOT knowable and must not be fabricated.
    """

    method: str
    universe_size: int | None
    universe_known: bool
    budget: int | None
    evaluated_count: int
    not_evaluated_count: int | None
    completeness: str
    not_evaluated_identities: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.completeness not in COMPLETENESS_VALUES:
            raise CompletenessError(
                f"unknown completeness {self.completeness!r}; "
                f"supported: {list(COMPLETENESS_VALUES)}")
        if self.evaluated_count < 0:
            raise CompletenessError("evaluated_count must be >= 0")
        if self.universe_known:
            if self.universe_size is None:
                raise CompletenessError(
                    "universe_known=True requires a universe_size")
            if self.universe_size < self.evaluated_count:
                raise CompletenessError(
                    f"universe_size {self.universe_size} < evaluated_count "
                    f"{self.evaluated_count} — a search cannot evaluate more "
                    "candidates than its universe contains")
            expected_tail = self.universe_size - self.evaluated_count
            if self.not_evaluated_count != expected_tail:
                raise CompletenessError(
                    f"not_evaluated_count {self.not_evaluated_count} != "
                    f"universe_size - evaluated_count = {expected_tail}")
        else:
            if self.universe_size is not None:
                raise CompletenessError(
                    "universe_known=False requires universe_size=None "
                    "(an unbounded space must not carry a size)")
            if self.not_evaluated_count is not None:
                raise CompletenessError(
                    "universe_known=False requires not_evaluated_count=None")
        # INVARIANT 2: EXHAUSTIVE is never inferred.
        if self.completeness == "EXHAUSTIVE":
            if not self.universe_known:
                raise CompletenessError(
                    "EXHAUSTIVE cannot be claimed for an unbounded space")
            if self.evaluated_count != self.universe_size:
                raise CompletenessError(
                    f"EXHAUSTIVE requires evaluated_count == universe_size, "
                    f"got {self.evaluated_count} != {self.universe_size}")

    # ── claims ──────────────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        return self.completeness == "EXHAUSTIVE"

    def claim(self) -> str:
        """The ONLY permitted product claim for this search."""
        return CLAIM_TEXT[self.completeness]

    def may_claim_optimality(self) -> bool:
        """Optimality over the declared space is claimable ONLY when the
        search was exhaustive. A budgeted search may never imply it."""
        return self.is_complete

    def to_dict(self) -> dict[str, Any]:
        d = {
            "schema_version": self.schema_version,
            "method": self.method,
            "universe_size": self.universe_size,
            "universe_known": self.universe_known,
            "budget": self.budget,
            "evaluated_count": self.evaluated_count,
            "not_evaluated_count": self.not_evaluated_count,
            "completeness": self.completeness,
            "claim": self.claim(),
            "may_claim_optimality": self.may_claim_optimality(),
        }
        if self.not_evaluated_identities:
            d["not_evaluated_identities"] = list(self.not_evaluated_identities)
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "SearchCompleteness":
        if not isinstance(d, dict):
            raise CompletenessError(
                f"completeness must be an object, got {type(d).__name__}")
        allowed = {
            "schema_version", "method", "universe_size", "universe_known",
            "budget", "evaluated_count", "not_evaluated_count",
            "completeness", "not_evaluated_identities", "claim",
            "may_claim_optimality",
        }
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise CompletenessError(f"unknown completeness fields {unknown}")
        return cls(
            method=d["method"],
            universe_size=d["universe_size"],
            universe_known=d["universe_known"],
            budget=d["budget"],
            evaluated_count=d["evaluated_count"],
            not_evaluated_count=d["not_evaluated_count"],
            completeness=d["completeness"],
            not_evaluated_identities=tuple(
                d.get("not_evaluated_identities") or ()),
        )


def derive(definition: Any, evaluated_count: int,
           not_evaluated_identities: tuple[str, ...] = ()
           ) -> SearchCompleteness:
    """Derive completeness from the definition and what was evaluated.

    ``grid``/``enumeration`` have a knowable finite universe (the Cartesian
    product before budget). ``random`` subsamples and cannot bound its own
    space, so its universe is reported as UNKNOWN rather than fabricated.
    """
    from .search import raw_cardinality, _budget_limit

    method = getattr(definition, "method", "grid")
    budget = _budget_limit(definition)

    if method == "random":
        return SearchCompleteness(
            method=method, universe_size=None, universe_known=False,
            budget=budget, evaluated_count=evaluated_count,
            not_evaluated_count=None, completeness="UNBOUNDED",
            not_evaluated_identities=())

    universe = raw_cardinality(definition)
    tail = universe - evaluated_count
    if tail < 0:
        raise CompletenessError(
            f"evaluated {evaluated_count} candidates from a universe of "
            f"{universe} — the search over-produced")
    value = "EXHAUSTIVE" if tail == 0 else "BUDGETED"
    return SearchCompleteness(
        method=method, universe_size=universe, universe_known=True,
        budget=budget, evaluated_count=evaluated_count,
        not_evaluated_count=tail, completeness=value,
        not_evaluated_identities=tuple(not_evaluated_identities))


def not_evaluated_identities(definition: Any,
                             evaluated_ids: set[str]) -> tuple[str, ...]:
    """Identities of valid candidates excluded by the budget.

    INVARIANT 3: absence must not look like nonexistence. We can name them
    exactly for a grid/enumeration search because the enumeration is a pure
    function of the definition — so we do, rather than reporting a bare
    count.
    """
    from .candidate import candidate_id_for
    from .search import canonical_assignments
    from .search import _budget_limit

    method = getattr(definition, "method", "grid")
    if method == "random":
        return ()
    base_hash = getattr(definition, "_base_design_hash", None)
    if base_hash is None:
        return ()
    limit = _budget_limit(definition)
    out: list[str] = []
    for i, patch in enumerate(canonical_assignments(definition)):
        if limit is not None and i >= limit:
            cid = candidate_id_for(base_hash, patch)
            if cid not in evaluated_ids:
                out.append(cid)
    return tuple(out)


__all__ = [
    "DOMAIN", "SCHEMA_VERSION", "COMPLETENESS_VALUES", "CLAIM_TEXT",
    "CompletenessError", "SearchCompleteness", "derive",
    "not_evaluated_identities",
]
