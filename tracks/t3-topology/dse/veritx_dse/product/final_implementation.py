"""The `final_implementation` verdict: computed from evidence, never asserted.

Why this module exists
----------------------
`final_implementation` is a claim about an artifact, and the acceptance
contract in `docs/product/FINAL-IMPLEMENTATION-TRUE.md` says exactly what
each scope's claim covers. Hard-coding the flag in a manifest made the flag
a mood: nothing checked it, and nothing could make it true. This module
turns the flag into a function of *named, hashed evidence*.

The rules it enforces
---------------------
* A row is CLOSED only when it was supplied with evidence that says so. An
  absent row is OPEN, and an OPEN row keeps the flag false. There is no way
  to pass a row by asserting it is closed.
* A row may be CLOSED by being **explicitly scoped out with a recorded
  decision** — that is how a physical row (STA, signoff) can be closed
  without a PDK: the decision is named, dated and attributed, and it is
  visible in the artifact.
* The verdict reports *every* row, closed or not, with the reason and the
  evidence's sha256, so a reader can check the claim instead of trusting it.
* A scope that the contract says can never carry the flag (a preview scope)
  never carries it, whatever the rows say.

The row identifiers are the contract's own (A1..A10 for the composed family
scope, C1..C6 for the selected-project scope). The rows and their evidence
requirements live here, next to the code that reads the evidence, so the two
cannot drift apart.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# The scopes that are structurally incapable of carrying the flag. The
# contract says a preview-scoped artifact can never be a final implementation,
# and the emitters say the same in their own words.
PREVIEW_SCOPES = frozenset({
    "TOPOLOGY_ONLY_PREVIEW",
    "CHIPYARD_TOPOLOGY_PREVIEW",
    "RESEARCH_VERILOG",
})

ROW_TEXT: dict[str, str] = {
    "A1": "The family composes from a real request (no harness substitute)",
    "A2": "Emitted RTL lints clean and simulates green with real scenarios",
    "A3": "The request->hardware binding is proven, not assumed",
    "A4": "Every compiled agent instance reaches hardware",
    "A5": "Multiple seats may share one router (concentrated fabrics)",
    "A6": "The decode contract is proven, not simulated",
    "A7": "Deadlock-freedom is proven",
    "A8": "BookSim<->RTL parity for the same traffic",
    "A9": "The AXI5 adapter's claimed feature surface is proven",
    "A10": "Multi-flit packets (HEAD/BODY/TAIL) are exercised",
    "A11": "Physical timing is closed",
    "A12": "Physical signoff (route/DRC/LVS)",
    "C1": "The compiler binds every instance to seats",
    "C2": "The shared emitter scales to the pinned shape",
    "C3": "Per-tap credit accounting",
    "C4": "Multi-flit framing + per-VC allocation + credit pipeline",
    "C5": "End-to-end run on RTL with conservation/credit/reset accounting",
    "C6": "Physical signoff of the selected contract",
}

# The rows that the composed-family scope requires, in the contract's order.
COMPOSED_FAMILY_ROWS: tuple[str, ...] = (
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10",
)

# The rows a scope may be closed on by an explicit, recorded decision rather
# than by evidence: the physical ones, whose closure is the operator's call
# (no PDK is available in the checkout).
SCOPEOUT_ELIGIBLE: frozenset({"A11", "A12", "C6"})


class EvidenceError(ValueError):
    """The evidence offered for a row is not usable."""


def _evidence_ref(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The parts of an evidence entry that a reader can check."""
    ref: dict[str, Any] = {}
    for key in ("status", "proof", "harness", "gate_test", "engine",
                "sha256", "decision", "decided_by", "decided_on", "scope",
                "measured", "residual"):
        if key in entry and entry[key] not in (None, ""):
            ref[key] = entry[key]
    if not ref:
        raise EvidenceError(
            "an evidence entry must name at least one checkable field "
            "(status, proof, gate_test, sha256, measured, or a decision)")
    return ref


def evaluate_row(row: str, entry: Mapping[str, Any] | None,
                 text: str | None = None) -> dict[str, Any]:
    """One row's verdict: closed or open, with the reason and the evidence.

    A row is closed when the evidence says ``status`` is one of the closed
    spellings, or when it carries an explicit scope-out decision. Anything
    else leaves the row open, and the reason says which.

    ``text`` lets a scope supply its own requirement wording (the shared-wire
    scopes claim criteria that are not the A rows), so the verdict can say
    what the row asks instead of repeating an identifier.
    """
    text = text or ROW_TEXT.get(row, row)
    if not entry:
        return {"row": row, "requirement": text, "status": "OPEN",
                "reason": "no evidence supplied for this row"}
    status = str(entry.get("status", "")).upper()
    decision = entry.get("decision")
    if decision:
        if row not in SCOPEOUT_ELIGIBLE:
            return {"row": row, "requirement": text, "status": "OPEN",
                    "reason": "this row cannot be closed by a scope-out "
                              "decision; it needs evidence",
                    "evidence": _evidence_ref(entry)}
        missing = [k for k in ("decided_by", "decided_on") if not entry.get(k)]
        if missing:
            return {"row": row, "requirement": text, "status": "OPEN",
                    "reason": "a scope-out decision must record " +
                              ", ".join(missing),
                    "evidence": _evidence_ref(entry)}
        return {"row": row, "requirement": text, "status": "SCOPED_OUT",
                "reason": "closed by an explicit recorded decision: " +
                          str(decision),
                "evidence": _evidence_ref(entry)}
    if status in ("CLOSED", "PASS", "PROVEN", "COMPLETE"):
        try:
            ref = _evidence_ref(entry)
        except EvidenceError as exc:
            return {"row": row, "requirement": text, "status": "OPEN",
                    "reason": str(exc)}
        return {"row": row, "requirement": text, "status": "CLOSED",
                "reason": str(entry.get("reason", "evidence supplied")),
                "evidence": ref}
    if status in ("OPEN", "PARTIAL", "NOT_RUN", "FAIL", "UNSUPPORTED"):
        return {"row": row, "requirement": text, "status": "OPEN",
                "reason": str(entry.get("reason", "evidence says " + status)),
                "evidence": _evidence_ref(entry) if entry.get("status") else {}}
    return {"row": row, "requirement": text, "status": "OPEN",
            "reason": "unrecognised evidence status " + repr(status) +
                      "; a row needs a closed spelling or a decision",
            "evidence": _evidence_ref(entry)}


def evaluate(*, scope: str, rows: Iterable[str],
             evidence: Mapping[str, Mapping[str, Any]] | None = None,
             residual: Iterable[str] = (),
             row_text: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The verdict for one artifact: the flag, the scope, and every row."""
    evidence = dict(evidence or {})
    text = dict(row_text or {})
    verdicts = [evaluate_row(row, evidence.get(row), text.get(row))
                for row in rows]
    open_rows = [v["row"] for v in verdicts if v["status"] == "OPEN"]
    scoped_out = [v["row"] for v in verdicts if v["status"] == "SCOPED_OUT"]
    preview = scope in PREVIEW_SCOPES
    flag = (not open_rows) and (not preview)
    reasons: list[str] = []
    if preview:
        reasons.append(
            "scope " + scope + " is a preview scope, which the contract says "
            "can never carry final_implementation")
    if open_rows:
        reasons.append("open rows: " + ", ".join(open_rows))
    return {
        "scope": scope,
        "final_implementation": flag,
        "rows": verdicts,
        "open_rows": open_rows,
        "scoped_out_rows": scoped_out,
        "residual": list(residual),
        "reason": "; ".join(reasons) if reasons else
                  "every required row is closed or explicitly scoped out",
    }


def composed_family_verdict(*, family: str,
                             evidence: Mapping[str, Mapping[str, Any]] | None = None,
                             residual: Iterable[str] = ()) -> dict[str, Any]:
    """The composed-family scope's verdict for one family."""
    return evaluate(scope="COMPOSED_FAMILY", rows=COMPOSED_FAMILY_ROWS,
                    evidence=evidence, residual=residual)


__all__ = [
    "COMPOSED_FAMILY_ROWS",
    "EvidenceError",
    "PREVIEW_SCOPES",
    "ROW_TEXT",
    "SCOPEOUT_ELIGIBLE",
    "composed_family_verdict",
    "evaluate",
    "evaluate_row",
]
