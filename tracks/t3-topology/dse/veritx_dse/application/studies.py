"""veritx_dse.application.studies — typed study/batch resources (Wave C).

A study is a typed GROUPING of related experiments, not a scheduler:
sequential evaluation, no dependency graph, no workers. Multi-seed
evaluation = multiple candidate intents (seed is result-affecting, so
each seed is a distinct experiment). Replicates stay visible as
observation sets — Wave C computes no means and names no winners.

Compiler-verdict vocabulary (FEASIBLE / NO_FEASIBLE_DESIGN /
CONSTRAINT_UNMEASURABLE / INCONCLUSIVE) is encoded here with strict
rules for future search orchestration; Wave C emits verdicts only by
summarizing completed study records, never by searching.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .errors import ControlPlaneError, ErrorCode


@dataclass(frozen=True)
class StudyRequest:
    name: str
    candidates: tuple[dict[str, Any], ...]
    comparison: dict[str, Any] | None = None

    @classmethod
    def parse(cls, doc: Any) -> "StudyRequest":
        if not isinstance(doc, dict):
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                f"study request must be an object, got "
                f"{type(doc).__name__}",
                operation="run_study")
        unknown = sorted(set(doc) - {"name", "candidates", "comparison"})
        if unknown:
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                f"study request has unknown fields {unknown}",
                operation="run_study")
        name = doc.get("name")
        if not isinstance(name, str) or not name:
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                "study request needs a non-empty name",
                operation="run_study")
        candidates = doc.get("candidates")
        if not isinstance(candidates, list) or not candidates or any(
                not isinstance(c, dict) for c in candidates):
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                "study candidates must be a non-empty list of intent "
                "documents",
                operation="run_study")
        comparison = doc.get("comparison")
        if comparison is not None and not isinstance(comparison, dict):
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                "study comparison must be an object",
                operation="run_study")
        if comparison is not None:
            unknown_cmp = sorted(set(comparison) - {"contract", "pairs"})
            if unknown_cmp:
                raise ControlPlaneError(
                    ErrorCode.INVALID_INTENT,
                    f"study comparison has unknown fields {unknown_cmp}",
                    operation="run_study")
            pairs = comparison.get("pairs")
            if not isinstance(pairs, list) or not pairs:
                raise ControlPlaneError(
                    ErrorCode.INVALID_INTENT,
                    "study comparison needs a non-empty pairs list",
                    operation="run_study")
            seen: set[tuple[int, int]] = set()
            for pair in pairs:
                if not isinstance(pair, list) or len(pair) != 2 or any(
                        not isinstance(i, int) or isinstance(i, bool)
                        for i in pair):
                    raise ControlPlaneError(
                        ErrorCode.INVALID_INTENT,
                        f"comparison pair must be two candidate indices, "
                        f"got {pair!r}", operation="run_study")
                if any(i < 0 or i >= len(candidates) for i in pair):
                    raise ControlPlaneError(
                        ErrorCode.INVALID_INTENT,
                        f"comparison pair {pair!r} is out of range for "
                        f"{len(candidates)} candidates",
                        operation="run_study")
                key = (pair[0], pair[1])
                if key in seen:
                    raise ControlPlaneError(
                        ErrorCode.INVALID_INTENT,
                        f"comparison pair {pair!r} is requested twice; "
                        f"each requested pair must be unique",
                        operation="run_study")
                seen.add(key)
        return cls(name=name, candidates=tuple(candidates),
                   comparison=comparison)

    def candidate_identities(self) -> list[str]:
        """Ordered candidate identities (invalid markers preserved)."""
        from veritx_dse.core.spec import canonical_json
        from .errors import ControlPlaneError
        from .requests import resolve_intent
        import hashlib as _hashlib
        intents = []
        for candidate in self.candidates:
            try:
                resolved, _, _ = resolve_intent(candidate)
                intents.append(resolved.intent_id())
            except (ControlPlaneError, ValueError):
                intents.append("invalid:" + _hashlib.sha256(
                    canonical_json(candidate).encode()).hexdigest())
        return intents

    def study_id(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = "srota-study/v1\0" + canonical_json({
            "name": self.name,
            # Candidate order is semantically relevant (index-addressed
            # execution and comparison pairs): preserve it exactly.
            "candidate_intents": self.candidate_identities(),
            "comparison": self.comparison,
        })
        return hashlib.sha256(body.encode()).hexdigest()


STUDY_CANDIDATE_STATUSES = (
    "SUCCEEDED", "INVALID", "FAILED", "TIMED_OUT", "UNSUPPORTED",
    "BLOCKED")

#: Error codes that mean "this derivation is not supported", as opposed
#: to an execution failure. The capability registry decides whether the
#: candidate's backend is BLOCKED (serving) or merely UNSUPPORTED.
UNSUPPORTED_ERROR_CODES = (ErrorCode.UNSUPPORTED_SEMANTICS,
                           ErrorCode.LOWERING_UNSUPPORTED)


def capability_execution_state(backend_target: str) -> str:
    """Execution state for a known backend target (registry-derived)."""
    from .capabilities import capability_registry
    from .requests import KNOWN_BACKEND_TARGETS
    if backend_target not in KNOWN_BACKEND_TARGETS:
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            f"unknown backend_target {backend_target!r}",
            operation="run_study")
    entry = capability_registry()["backends"][backend_target]
    return str(entry.get("execution", "UNSUPPORTED"))


def study_status_for_code(code: ErrorCode, *,
                         backend_target: str | None = None) -> str:
    """The ONE authoritative evaluation-error -> study-status mapping.

    Typed control-plane reasons survive into study records: timeouts
    stay TIMED_OUT and unsupported derivations stay UNSUPPORTED (or
    BLOCKED when the capability registry says the target's execution is
    BLOCKED). Never derived from error message text.
    """
    if code == ErrorCode.EXECUTION_TIMEOUT:
        return "TIMED_OUT"
    if code in UNSUPPORTED_ERROR_CODES:
        if backend_target is not None and \
                capability_execution_state(backend_target) == "BLOCKED":
            return "BLOCKED"
        return "UNSUPPORTED"
    return "FAILED"


def study_status_for_error(error: ControlPlaneError, *,
                          backend_target: str | None = None) -> str:
    return study_status_for_code(error.code,
                                 backend_target=backend_target)


def summarize_study(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Strict compiler-verdict summary over completed candidate records.

    Each record: {status, measurable: bool, constraints_met: bool}.
    Rules: invalid input -> INVALID (never NO_FEASIBLE_DESIGN); backend
    unsupported -> UNSUPPORTED verdict family; nothing measurable ->
    CONSTRAINT_UNMEASURABLE; all crashed/timed out -> INCONCLUSIVE;
    every measured candidate violates -> NO_FEASIBLE_DESIGN; else
    FEASIBLE. Crashes and timeouts are NEVER feasibility evidence.
    """
    if not isinstance(records, list) or not records:
        raise ControlPlaneError(
            ErrorCode.INVALID_INTENT,
            "verdict summary needs a non-empty record list",
            operation="verdict")
    for record in records:
        if not isinstance(record, dict) or any(
                k not in record for k in
                ("status", "measurable", "constraints_met")):
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                f"verdict record must carry status/measurable/"
                f"constraints_met, got {record!r}",
                operation="verdict")
    if any(r["status"] in ("UNSUPPORTED", "BLOCKED") for r in records):
        return {"verdict": "UNSUPPORTED",
                "reason": "a candidate backend is not qualified"}
    measurable = [r for r in records if r["measurable"]]
    if not measurable:
        if all(r["status"] in ("FAILED", "TIMED_OUT") for r in records):
            return {"verdict": "INCONCLUSIVE",
                    "reason": "no candidate produced measurable evidence; "
                              "crashes and timeouts are not feasibility "
                              "evidence"}
        return {"verdict": "CONSTRAINT_UNMEASURABLE",
                "reason": "no candidate produced measurable constraint "
                          "evidence"}
    feasible = [r for r in measurable if r["constraints_met"]]
    if feasible:
        return {"verdict": "FEASIBLE",
                "feasible_count": len(feasible),
                "evaluated_count": len(measurable)}
    return {"verdict": "NO_FEASIBLE_DESIGN",
            "reason": "search completed; every measured candidate "
                      "violates a binding constraint",
            "evaluated_count": len(measurable)}


__all__ = ["STUDY_CANDIDATE_STATUSES", "StudyRequest",
           "capability_execution_state", "study_status_for_code",
           "study_status_for_error", "summarize_study"]
