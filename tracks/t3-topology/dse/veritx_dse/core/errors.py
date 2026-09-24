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


class SemanticError(VeritXError):
    """Base for a typed SEMANTIC refusal.

    The input is understood and outside the supported domain, or two
    semantic facts contradict. Trust boundaries (certificate obligations,
    compiler orchestration) catch this base — never Python's built-in
    ``ValueError`` — so a programmer fault (including a bare ``ValueError``
    from an invariant that exploded) propagates and aborts certification
    instead of being laundered into a design verdict.

    Artifact/model error classes that are already ``ValueError`` subclasses
    also inherit this, so existing ``except ValueError`` call sites keep
    working while boundaries get a precise handle.
    """
    code = "SEMANTIC_ERROR"


class Refusal(VeritXError):
    """A semantic refusal: the input is understood and outside the
    supported domain. Never approximated silently."""

    code = "REFUSAL"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ArtifactError(Refusal):
    """Artifact signing/manifest errors."""

    code = "ARTIFACT_ERROR"


class InvalidInput(ArtifactError):
    """Malformed persisted artifact input."""

    code = "INVALID_INPUT"


class EvidenceInvalid(ArtifactError):
    """Persisted artifact identity failed verification."""

    code = "EVIDENCE_INVALID"


# ── domain refusals (workload semantics) ────────────────────────────────
class UnsupportedSemantics(Refusal):
    """The semantics exist as a concept but are outside the supported
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

