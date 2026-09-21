"""veritx_dse.errors — Structured error hierarchy.

All errors should inherit from VeritXError so callers can catch
specific error types instead of bare Exception.
"""
from __future__ import annotations


class VeritXError(Exception):
    """Base exception for all veritx errors."""
    pass


class ConfigError(VeritXError):
    """Configuration validation errors."""
    pass


class TraceError(VeritXError):
    """Trace file errors."""
    pass


class BookSimError(VeritXError):
    """BookSim simulation errors."""
    def __init__(self, message: str, returncode: int = -1, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TimeoutError(BookSimError):
    """Raised when BookSim exceeds the time limit.

    Subclasses BookSimError so existing ``except BookSimError`` handlers
    keep catching timeouts, while carrying returncode/stdout/stderr like
    its parent for debuggability.
    """
    pass


class TopologyError(VeritXError):
    """Topology-related errors."""
    pass


class CertificationError(VeritXError):
    """Certification failures."""
    pass


class Refusal(VeritXError):
    """A typed, machine-coded refusal (fail closed, never silent).

    Domain refusals carry a stable ``code`` so callers distinguish refusal
    classes without string matching. Every refusal type in the repository
    derives from this one base.
    """

    code = "REFUSAL"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ArtifactError(Refusal):
    """Artifact contract failure: bad shape, unknown field, forged ID.

    ONE definition for the whole repository (``core.artifact`` derives its
    ``InvalidInput``/``EvidenceInvalid`` from this class).
    """

    code = "ARTIFACT_ERROR"


class InvalidInput(ArtifactError):
    """Malformed input to an artifact: bad types, out-of-range values,
    out-of-range ranks, missing fields."""

    code = "INVALID_INPUT"


class EvidenceInvalid(ArtifactError):
    """Persisted artifact identity failed verification, or backend
    evidence does not bind the artifacts it claims."""

    code = "EVIDENCE_INVALID"


# ── domain refusals (formerly waved.errors) ─────────────────────────────
class UnsupportedSemantics(Refusal):
    """The semantics exist as a concept but are outside the supported v1
    domain. Never approximated silently."""

    code = "UNSUPPORTED_SEMANTICS"


class UnsupportedSchedule(Refusal):
    """A collective/multicast algorithm outside the pinned set, or a
    payload violating the schedule's divisibility law."""

    code = "UNSUPPORTED_SCHEDULE"


class MappingInvalid(Refusal):
    """Rank space / mapping / endpoint binding seam failure."""

    code = "MAPPING_INVALID"


class ConservationFailed(Refusal):
    """A conservation law did not hold. Hard failure, never a warning."""

    code = "CONSERVATION_FAILED"


class BackendFailure(Refusal):
    """Qualified backend execution failed: nonzero exit, missing evidence,
    route divergence."""

    code = "BACKEND_FAILURE"


class BackendTimeout(BackendFailure):
    """Qualified backend execution exceeded its time limit."""

    code = "TIMEOUT"


class ServingPreflightError(VeritXError):
    """A serving execution refused before LLMServingSim was spawned.

    Carries a machine-readable ``reason`` (closed vocabulary, see
    core.serving.preflight_serve) plus a human block with the concrete
    values. Downstream safety checks stay in place; this fails earlier.
    """
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class ServingResultError(VeritXError):
    """A serving execution finished but its result is not valid science.

    Returncode 0 with missing/partial results (e.g. fewer retired
    requests than requested) lands here — never reported as success.
    """
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
