"""veritx_dse.optimization.metric_authority — registered metric producers.

Law (RT-final A3): for an authoritative (certified-backend) evaluation,
an objective measurement is not whatever the port says it is. Every
metric that has a registered authority is re-extracted from the carried
``VerifiedPerformanceResult`` (B's boundary) by the registered producer
and the port's own value must agree exactly. A metric with no registered
producer has no independent extraction authority; its value is taken
from the authenticated evaluation itself (never from a self-declared
label) and a certified port may not misreport a registered metric.

One authority per metric, exactly like ``validate_requirement_scopes``:
the cycle-recovery rule lives in
``requirements.authenticated_network_cycles`` and is not mirrored here.

Built-in producers:

* ``completion_cycles`` / ``completion_time`` — the bound network
  window's authenticated completion_time (the backend's own name for the
  same integral cycle count);
* ``completion_ns`` — the bound network window's authenticated wall
  duration in nanoseconds (cycles-only results evidence neither).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from veritx_dse.application.requirements import (
    authenticated_network_cycles,
)


class MetricAuthorityError(ValueError):
    """Metric-authority registration/refusal (fail-closed)."""


MetricExtractor = Callable[[Any], float | None]

_METRIC_AUTHORITIES: dict[str, MetricExtractor] = {}


def register_metric_authority(metric: str, extractor: MetricExtractor
                              ) -> None:
    """Register the ONE producer that extracts ``metric`` from a verified
    performance result. Re-registering replaces the producer (tests do
    this explicitly; production registers at import)."""
    if not isinstance(metric, str) or not metric:
        raise MetricAuthorityError(
            f"metric name must be a nonempty string, got {metric!r}")
    if not callable(extractor):
        raise MetricAuthorityError(
            f"metric authority for {metric!r} must be callable, got "
            f"{type(extractor).__name__}")
    _METRIC_AUTHORITIES[metric] = extractor


def unregister_metric_authority(metric: str) -> None:
    """Remove a producer (no-op when absent)."""
    _METRIC_AUTHORITIES.pop(metric, None)


def registered_metric_authorities() -> tuple[str, ...]:
    """The registered metric names, sorted (deterministic iteration)."""
    return tuple(sorted(_METRIC_AUTHORITIES))


def extract_metric(metric: str, verified: Any) -> float | None:
    """The authoritative finite value for ``metric``, or None.

    None means "this verified result does not evidence the metric
    through any registered authority" — absent, never zero, never a
    fabricated number. Non-finite or non-real producer output is refused
    as no evidence.
    """
    extractor = _METRIC_AUTHORITIES.get(metric)
    if extractor is None:
        return None
    value = extractor(verified)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def extract_authoritative_metrics(verified: Any) -> dict[str, float]:
    """Every registered metric this verified result evidences (sorted)."""
    out: dict[str, float] = {}
    for metric in registered_metric_authorities():
        value = extract_metric(metric, verified)
        if value is not None:
            out[metric] = value
    return out


def _completion_cycles(verified: Any) -> float | None:
    """The authenticated completion_time cycles, or None (cycles-only)."""
    cycles, _ = authenticated_network_cycles(verified)
    return None if cycles is None else float(cycles)


def _completion_ns(verified: Any) -> float | None:
    """The authenticated wall window in nanoseconds, or None."""
    from veritx_dse.core.time import QTime
    binding = verified.get("network_binding") \
        if isinstance(verified, Mapping) else None
    if not isinstance(binding, Mapping) or binding.get("duration") is None:
        return None
    duration = QTime.from_dict(binding["duration"])
    return duration.to_float() * 1e9


register_metric_authority("completion_cycles", _completion_cycles)
register_metric_authority("completion_time", _completion_cycles)
register_metric_authority("completion_ns", _completion_ns)


__all__ = [
    "MetricAuthorityError",
    "MetricExtractor",
    "extract_authoritative_metrics",
    "extract_metric",
    "register_metric_authority",
    "registered_metric_authorities",
    "unregister_metric_authority",
]
