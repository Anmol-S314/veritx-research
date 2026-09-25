"""veritx_dse.gateway.errors — typed HTTP status mapping for the Studio API.

The gateway must never launder a programmer fault into a user error. Only
*typed semantic refusals* and *declared gateway conditions* map to 4xx/503;
anything else is a 500 and is logged. The canonical taxonomy is
``core/errors`` (``Refusal`` and subclasses) and ``application/errors``
(``ControlPlaneError``/``ErrorCode``); this module only assigns HTTP status,
it authors no semantics.
"""
from __future__ import annotations

from fastapi import HTTPException

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.core.errors import (
    BackendFailure, BackendTimeout, ConservationFailed, EvidenceInvalid,
    InvalidInput, MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
)


class BackendUnavailable(RuntimeError):
    """No qualified backend is configured for the requested operation."""


class Conflict(RuntimeError):
    """The request conflicts with durable state (e.g. an invalid bundle)."""


class NotFound(RuntimeError):
    """A named resource does not exist."""


_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INTENT: 400,
    ErrorCode.UNSUPPORTED_SEMANTICS: 422,
    ErrorCode.LOWERING_UNSUPPORTED: 422,
    ErrorCode.EXECUTION_FAILED: 503,
    ErrorCode.EXECUTION_TIMEOUT: 503,
    ErrorCode.EVIDENCE_INVALID: 422,
    ErrorCode.COMPARISON_INCOMPATIBLE: 409,
    ErrorCode.NO_FEASIBLE_DESIGN: 422,
    ErrorCode.POLICY_REJECTED: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INTERNAL_ERROR: 500,
}


def http_status_for(exc: BaseException) -> int | None:
    """The HTTP status for a *typed* failure, or ``None`` if unmapped.

    ``None`` means "this is not a declared failure" — the caller must treat
    it as a 500, never as a user error. A bare ``ValueError``/``TypeError``/
    ``RuntimeError``/``AttributeError`` is deliberately unmapped.
    """
    if isinstance(exc, HTTPException):
        return exc.status_code
    if isinstance(exc, BackendUnavailable):
        return 503
    if isinstance(exc, Conflict):
        return 409
    if isinstance(exc, NotFound):
        return 404
    # most-specific semantic refusals first
    if isinstance(exc, (BackendTimeout, BackendFailure)):
        return 503
    if isinstance(exc, UnsupportedSemantics):
        return 422
    if isinstance(exc, (UnsupportedSchedule, MappingInvalid,
                        ConservationFailed, EvidenceInvalid)):
        return 422
    if isinstance(exc, InvalidInput):
        return 400
    if isinstance(exc, ControlPlaneError):
        return _STATUS_BY_CODE.get(exc.code, 500)
    return None


def error_code_for(exc: BaseException) -> str:
    """A stable machine code for the response body (never a traceback)."""
    if isinstance(exc, HTTPException):
        return "HTTP_ERROR"
    if isinstance(exc, BackendUnavailable):
        return "BACKEND_UNAVAILABLE"
    if isinstance(exc, Conflict):
        return "CONFLICT"
    if isinstance(exc, NotFound):
        return "NOT_FOUND"
    if isinstance(exc, ControlPlaneError):
        return exc.code.value
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    status = http_status_for(exc)
    return {400: "INVALID_INPUT", 422: "UNSUPPORTED_SEMANTICS",
            404: "NOT_FOUND", 409: "CONFLICT",
            503: "BACKEND_UNAVAILABLE"}.get(status or 0, "INTERNAL_ERROR")


__all__ = [
    "BackendUnavailable", "Conflict", "NotFound",
    "error_code_for", "http_status_for",
]
