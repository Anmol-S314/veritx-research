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


class TopologyError(VeritXError):
    """Topology-related errors."""
    pass


class CertificationError(VeritXError):
    """Certification failures."""
    pass


class ArtifactError(VeritXError):
    """Artifact signing/manifest errors."""
    pass


class InvalidInput(ArtifactError):
    """Malformed persisted artifact input."""
    pass


class EvidenceInvalid(ArtifactError):
    """Persisted artifact identity failed verification."""
    pass
