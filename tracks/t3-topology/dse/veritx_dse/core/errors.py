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


class ArtifactError(VeritXError):
    """Artifact signing/manifest errors."""
    pass


class ServingPreflightError(VeritXError):
    """A serving execution refused before LLMServingSim was spawned.

    Carries a machine-readable ``reason`` (closed vocabulary, see
    core.serving.preflight_serve) plus a human block with the concrete
    values. Downstream safety checks stay in place; this fails earlier.
    """
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
