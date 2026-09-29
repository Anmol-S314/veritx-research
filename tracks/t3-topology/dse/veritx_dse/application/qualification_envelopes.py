"""Per-backend scientific qualification envelopes (independent dimensions).

A successful backend process is NOT a scientifically qualified number.
This module separates, for every certified backend, the dimensions that
must never imply one another:

  numerical_qualification  has the metric been independently validated?
  calibration              is the model calibrated to real hardware?

The other dimensions are per-run and live elsewhere: representability
(``support``) and execution readiness (``readiness``) come from the plan;
evidence integrity comes from the executed run's own authentication.

These values are transcribed from docs/production/ENGINE-QUALIFICATION.md
and docs/validation/{ASTRA,SERVING}-QUALIFICATION.md. They are the
product's honest claim surface; the qualification_profile id remains the
backend's own native verdict word.
"""
from __future__ import annotations

from typing import Any

NOT_ESTABLISHED = "NOT_ESTABLISHED"
ESTABLISHED = "ESTABLISHED"
LIMITED = "LIMITED"
PARTIAL = "PARTIAL"

#: backend_id -> (numerical_qualification, calibration, basis)
_ENVELOPES: dict[str, tuple[str, str, str]] = {
    "BOOKSIM_STANDALONE": (
        ESTABLISHED, NOT_ESTABLISHED,
        "certified mesh-DOR-xy envelope (conservation + route proof); "
        "within the certified profile only"),
    "ASTRA2_EMBEDDED_BOOKSIM": (
        LIMITED, NOT_ESTABLISHED,
        "internally qualified under model M; ABSOLUTE LATENCY "
        "NOT_ESTABLISHED — cycles are the projected machine's "
        "schedule/exposure window, never end-to-end runtime"),
    "RAMULATOR2_HBM3_V1": (
        ESTABLISHED, NOT_ESTABLISHED,
        "audited HBM3 v1 single-channel envelope; row/queue timing "
        "simulated, request stream assumed"),
    "CANONICAL_SERVING": (
        PARTIAL, NOT_ESTABLISHED,
        "scheduling/TP/DP/EP qualified; absolute latency PARTIAL "
        "(exact only under the declared linear profile, not calibrated)"),
}


def qualification_envelope(backend_id: str | None) -> dict[str, Any] | None:
    """The honest qualification dimensions for a backend, or None when the
    backend is not certified (never a fabricated envelope)."""
    if backend_id is None:
        return None
    envelope = _ENVELOPES.get(backend_id)
    if envelope is None:
        return None
    numerical, calibration, basis = envelope
    return {
        "numerical_qualification": numerical,
        "calibration": calibration,
        "basis": basis,
    }


__all__ = [
    "ESTABLISHED", "LIMITED", "NOT_ESTABLISHED", "PARTIAL",
    "qualification_envelope",
]
