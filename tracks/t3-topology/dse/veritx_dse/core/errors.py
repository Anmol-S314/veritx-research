"""veritx_dse.errors — Structured error hierarchy.

Rationale: docs/decisions/modules/core.md
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

Rationale: docs/decisions/modules/core.md
    """
    pass

class TopologyError(VeritXError):
    """Topology-related errors."""
    pass

class SemanticError(VeritXError):
    """Base for a typed SEMANTIC refusal.

Rationale: docs/decisions/modules/core.md
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

class UnsupportedSemantics(Refusal):
    """The semantics exist as a concept but are outside the supported
    domain. Never approximated silently."""

    code = "UNSUPPORTED_SEMANTICS"


class MissingCapability(UnsupportedSemantics):
    """A design asked for a capability with no canonical artifact."""

    def __init__(self, capability: str, message: str, *,
                 stage: str | None = None) -> None:
        super().__init__(message)
        self.capability = capability
        self.kind = "NO_ARTIFACT"
        # Semantic stage token, intentionally independent of compiler enums.
        self.stage = stage


def require_capability(capability: str, message: str, *,
                       stage: str | None = None) -> None:
    """Raise a typed no-artifact refusal tagged with its stable capability id."""
    raise MissingCapability(capability, message, stage=stage)

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

