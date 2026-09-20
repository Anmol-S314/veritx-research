"""veritx_dse.waved.errors — Wave-D typed refusals (§31).

Semantic refusals are typed, never ``False``/``None``/silent. Each error
carries a machine-readable ``code`` from a closed vocabulary so callers can
distinguish refusal classes without string matching. Existing error codes
are reused where a suitable one exists; Wave-D-specific classes only name
boundaries Wave B/C do not have.
"""
from __future__ import annotations


class WaveDError(Exception):
    """Base class for every Wave-D refusal (fail closed, never silent)."""

    code = "WAVED_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInput(WaveDError):
    """Malformed request: bad types, out-of-range ranks, missing fields."""

    code = "INVALID_INPUT"


class UnsupportedSemantics(WaveDError):
    """The requested semantics exist as a concept but are outside the
    supported Wave-D v1 domain (§31). Never approximated silently."""

    code = "UNSUPPORTED_SEMANTICS"


class UnsupportedSchedule(WaveDError):
    """A collective/multicast algorithm outside the pinned v1 set, or a
    payload that violates the schedule's divisibility law (§10.2)."""

    code = "UNSUPPORTED_SCHEDULE"


class MappingInvalid(WaveDError):
    """Rank space / mapping / endpoint binding seam failure."""

    code = "MAPPING_INVALID"


class ConservationFailed(WaveDError):
    """A per-class conservation law (§24) did not hold. Hard failure,
    never a warning (§24)."""

    code = "CONSERVATION_FAILED"


class EvidenceInvalid(WaveDError):
    """Persisted artifact identity failed verification, or backend
    evidence does not bind the artifacts it claims."""

    code = "EVIDENCE_INVALID"


class BackendFailure(WaveDError):
    """The qualified backend execution failed (nonzero exit, missing
    evidence, route divergence)."""

    code = "BACKEND_FAILURE"


class WavedTimeout(BackendFailure):
    """The qualified backend execution exceeded its time limit."""

    code = "TIMEOUT"


__all__ = [
    "BackendFailure",
    "ConservationFailed",
    "EvidenceInvalid",
    "InvalidInput",
    "MappingInvalid",
    "UnsupportedSchedule",
    "UnsupportedSemantics",
    "WavedTimeout",
    "WaveDError",
]
