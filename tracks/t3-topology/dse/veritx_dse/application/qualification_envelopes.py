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

# Profiles a backend labels DIAGNOSTIC_ are model contracts (e.g. the
# multi-pool Ramulator dispatcher), not qualified envelopes. A certified
# single-pool envelope is never inherited by such a row.
DIAGNOSTIC_PROFILE_PREFIX = "DIAGNOSTIC_"

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

def qualification_envelope(backend_id: str | None, *,
                            qualification_profile: str | None = None,
                            ) -> dict[str, Any] | None:
    """The honest qualification dimensions for a backend, or None when the
    backend is not certified (never a fabricated envelope).

    ``qualification_profile`` is the profile the plan row actually
    selected. When it is a diagnostic model contract the backend's
    certified envelope is NOT inherited: that row answers LIMITED /
    NOT_ESTABLISHED with the non-inheritance stated in its basis.
    """
    if backend_id is None:
        return None
    envelope = _ENVELOPES.get(backend_id)
    if envelope is None:
        return None
    numerical, calibration, basis = envelope
    if qualification_profile and \
            qualification_profile.startswith(DIAGNOSTIC_PROFILE_PREFIX):
        return {
            "numerical_qualification": LIMITED,
            "calibration": NOT_ESTABLISHED,
            "basis": (
                f"{basis}; this row's qualification profile "
                f"{qualification_profile} is a DIAGNOSTIC model contract, so "
                "the certified envelope above is NOT inherited by it"),
        }
    return {
        "numerical_qualification": numerical,
        "calibration": calibration,
        "basis": basis,
    }

__all__ = [
    "DIAGNOSTIC_PROFILE_PREFIX", "ESTABLISHED", "LIMITED", "NOT_ESTABLISHED",
    "PARTIAL", "qualification_envelope",
]
