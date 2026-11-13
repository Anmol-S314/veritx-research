"""veritx_dse.gateway.errors — typed HTTP status mapping for the Studio API.

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

from fastapi import HTTPException

from veritx_dse.application.errors import (
    ControlPlaneError, EngineUnavailable, ErrorCode,
)
from veritx_dse.core.errors import (
    BackendFailure, BackendTimeout, ConservationFailed, EvidenceInvalid,
    InvalidInput, MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
)

_SERIES_REFUSAL_STATUS: dict[str, int] = {
    # docs/product/simulation-overlay-track.md §3 refusal vocabulary.
    "NO_RUN": 404,
    "NO_MEASURED": 422,
    "NO_TIME_AXIS": 400,
    "PERIOD_MISMATCH": 422,
    "STALE_FIXTURE": 409,
}


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
    ErrorCode.STALE_REVIEW: 409,
    ErrorCode.INTERNAL_ERROR: 500,
}

def http_status_for(exc: BaseException) -> int | None:
    """The HTTP status for a *typed* failure, or ``None`` if unmapped.

    ``None`` means "this is not a declared failure" — the caller must treat
    it as a 500, never as a user error. A bare ``ValueError``/``TypeError``/
    ``RuntimeError``/``AttributeError`` is deliberately unmapped. ``OSError``
    IS mapped (503): a filesystem fault is an environment failure with a
    detail worth showing, not a programmer bug with nothing to say.
    """
    if isinstance(exc, HTTPException):
        return exc.status_code
    if isinstance(exc, BackendUnavailable):
        return 503
    if isinstance(exc, EngineUnavailable):
        return 503
    if isinstance(exc, Conflict):
        return 409
    if isinstance(exc, NotFound):
        return 404
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
    # A filesystem failure is an environment fault, not a user error and not a
    # programmer bug: the request was well formed and nothing in it caused the
    # failure. It is typed so the detail (path + errno) reaches the UI instead
    # of collapsing into a bare "internal server error" that names nothing.
    if isinstance(exc, OSError):
        return 503
    # Series refusals (loom simulation API) carry a closed spec code.
    # Duck-typed so the gateway never imports the reader: any exception
    # with one of these codes maps the same way.
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        status = _SERIES_REFUSAL_STATUS.get(code)
        if status is not None:
            return status
    return None

def error_code_for(exc: BaseException) -> str:
    """A stable machine code for the response body (never a traceback)."""
    if isinstance(exc, HTTPException):
        return "HTTP_ERROR"
    if isinstance(exc, BackendUnavailable):
        return "BACKEND_UNAVAILABLE"
    if isinstance(exc, EngineUnavailable):
        return exc.code
    if isinstance(exc, Conflict):
        return "CONFLICT"
    if isinstance(exc, NotFound):
        return "NOT_FOUND"
    if isinstance(exc, ControlPlaneError):
        return exc.code.value
    if isinstance(exc, OSError):
        return "STORAGE_UNAVAILABLE"
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    status = http_status_for(exc)
    return {400: "INVALID_INPUT", 422: "UNSUPPORTED_SEMANTICS",
            404: "NOT_FOUND", 409: "CONFLICT",
            503: "BACKEND_UNAVAILABLE"}.get(status or 0, "INTERNAL_ERROR")

__all__ = [
    "BackendUnavailable", "Conflict", "EngineUnavailable", "NotFound",
    "error_code_for", "http_status_for",
]
