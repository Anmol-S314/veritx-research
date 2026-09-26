"""veritx_dse.application.errors — one control-plane error taxonomy.

Every product surface (CLI/API/T3/Python) reports failures as typed
``ControlPlaneError`` values, never as raw tracebacks and never as a
generic "evaluation failed". The critical invariant: a simulator crash,
a timeout, bad evidence and an unsupported semantic are NEVER reported
as NO_FEASIBLE_DESIGN — that code is reserved for a legitimate
design/search process that evaluated its space and found nothing
feasible (Wave C has no such search yet, so it is never emitted here).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    INVALID_INTENT = "INVALID_INTENT"
    UNSUPPORTED_SEMANTICS = "UNSUPPORTED_SEMANTICS"
    LOWERING_UNSUPPORTED = "LOWERING_UNSUPPORTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    COMPARISON_INCOMPATIBLE = "COMPARISON_INCOMPATIBLE"
    NO_FEASIBLE_DESIGN = "NO_FEASIBLE_DESIGN"
    POLICY_REJECTED = "POLICY_REJECTED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    #: The reviewed draft snapshot is no longer the current draft. Compiling
    #: would certify content the user never reviewed (Gate 7 §4, REV-D2).
    STALE_REVIEW = "STALE_REVIEW"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass
class ControlPlaneError(Exception):
    """Typed control-plane failure (raised AND serialized).

    Deliberately NOT frozen: frozen dataclass exceptions cannot
    propagate through generator-based context managers (traceback
    assignment raises FrozenInstanceError). Value equality retained.
    """

    code: ErrorCode
    message: str
    operation: str = ""
    resource_id: str = ""
    cause_type: str = ""
    details: tuple[tuple[str, Any], ...] = ()

    def __str__(self) -> str:
        head = f"[{self.code.value}]"
        if self.operation:
            head += f" {self.operation}"
        return f"{head}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": True,
            "code": self.code.value,
            "message": self.message,
            "operation": self.operation,
            "resource_id": self.resource_id,
            "cause_type": self.cause_type,
            "details": {k: v for k, v in self.details},
        }


def intent_error(message: str, *, operation: str = "",
                 cause_type: str = "",
                 details: dict[str, Any] | None = None) -> ControlPlaneError:
    return ControlPlaneError(
        ErrorCode.INVALID_INTENT, message, operation=operation,
        cause_type=cause_type,
        details=tuple(sorted((details or {}).items())))


def internal_error(message: str, *, operation: str = "",
                   cause_type: str = "") -> ControlPlaneError:
    return ControlPlaneError(
        ErrorCode.INTERNAL_ERROR, message, operation=operation,
        cause_type=cause_type)


def map_lowering_error(exc: Exception, *, operation: str) -> ControlPlaneError:
    """Wave-B lowering/binding refusal -> LOWERING_UNSUPPORTED."""
    return ControlPlaneError(
        ErrorCode.LOWERING_UNSUPPORTED, str(exc), operation=operation,
        cause_type=type(exc).__name__)


def map_semantic_error(exc: Exception, *, operation: str) -> ControlPlaneError:
    """Infeasible/unsupported derivation -> UNSUPPORTED_SEMANTICS."""
    return ControlPlaneError(
        ErrorCode.UNSUPPORTED_SEMANTICS, str(exc), operation=operation,
        cause_type=type(exc).__name__)


def map_execution_error(exc: Exception, *, operation: str,
                        attempt_id: str = "") -> ControlPlaneError:
    """Execution-attempt failure -> typed code (never NO_FEASIBLE_DESIGN)."""
    from veritx_dse.core.errors import TimeoutError as CoreTimeout
    if isinstance(exc, CoreTimeout):
        code = ErrorCode.EXECUTION_TIMEOUT
    else:
        code = ErrorCode.EXECUTION_FAILED
    return ControlPlaneError(
        code, str(exc), operation=operation, resource_id=attempt_id,
        cause_type=type(exc).__name__)


__all__ = [
    "ControlPlaneError",
    "ErrorCode",
    "intent_error",
    "internal_error",
    "map_execution_error",
    "map_lowering_error",
    "map_semantic_error",
]
