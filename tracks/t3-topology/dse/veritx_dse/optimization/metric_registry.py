"""veritx_dse.optimization.metric_registry — certified metric authorities.

Law (RT-final R2): the certified metric authority is a FROZEN, VERSIONED,
identity-bearing product artifact. There is no public mutation API on a
frozen registry: external code cannot register ``magic_score -> 1e-6`` or
replace ``completion_cycles`` at runtime while a study runs. Extensibility
is an explicit qualification phase — ``MetricRegistryBuilder(...)
.register(...).freeze()`` produces a NEW registry version — and plugins
live in a separate :class:`ExperimentalMetricRegistry` that can never
yield CERTIFIED_PRODUCT Pareto.

The optimizer consumes ONLY a frozen ``CertifiedMetricRegistry`` for the
certified entry point; producers run over the authenticated proof's
``verified_result`` (R3: evidence truth is upstream, metric extraction is
optimization's job afterwards). A metric with no producer is
UNMEASURABLE; a producer that returns no finite value is UNMEASURABLE;
only a finite extracted value scores.

One authority per metric: the cycle-recovery rule lives in
``requirements.authenticated_network_cycles`` and is not mirrored here.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from veritx_dse.application.requirements import (
    authenticated_network_cycles,
)
from veritx_dse.core.artifact import content_id

METRIC_REGISTRY_DOMAIN = "veritx/certified-metric-registry/v1"


class MetricRegistryError(ValueError):
    """Registry construction/refusal (fail-closed)."""


MetricProducer = Callable[[Any], float | None]


def _finite(value: Any) -> float | None:
    """float(value) iff a finite real number (bool excluded)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validate_producer(metric: str, producer: MetricProducer) -> None:
    if not isinstance(metric, str) or not metric:
        raise MetricRegistryError(
            f"metric name must be a nonempty string, got {metric!r}")
    if not callable(producer):
        raise MetricRegistryError(
            f"metric producer for {metric!r} must be callable, got "
            f"{type(producer).__name__}")


@dataclass(frozen=True)
class CertifiedMetricRegistry:
    """An immutable, versioned, identity-bearing metric authority.

    ``producers`` is wrapped in a read-only mapping at construction; the
    dataclass is frozen and exposes no register/unregister method. The
    registry identity (``registry_id``) binds the version and the exact
    metric set, so two differently-qualified registries can never be
    confused in an audit trail.
    """

    version: str
    producers: Mapping[str, MetricProducer] = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version:
            raise MetricRegistryError(
                f"registry version must be a nonempty string, got "
                f"{self.version!r}")
        if not isinstance(self.producers, Mapping):
            raise MetricRegistryError(
                f"registry producers must be a mapping, got "
                f"{type(self.producers).__name__}")
        for metric, producer in self.producers.items():
            _validate_producer(metric, producer)
        object.__setattr__(
            self, "producers",
            MappingProxyType(dict(self.producers)))

    def registry_id(self) -> str:
        """Content identity of (version, metric set)."""
        return content_id(METRIC_REGISTRY_DOMAIN, {
            "version": self.version,
            "metrics": sorted(self.producers),
        })

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.producers))

    def has_metric(self, metric: str) -> bool:
        return metric in self.producers

    def extract(self, metric: str, verified: Any) -> float | None:
        """The authoritative finite value, or None (absent evidence)."""
        producer = self.producers.get(metric)
        if producer is None:
            return None
        return _finite(producer(verified))

    def extract_all(self, verified: Any) -> dict[str, float]:
        """Every metric this registry evidences (deterministic order)."""
        out: dict[str, float] = {}
        for metric in self.metric_names():
            value = self.extract(metric, verified)
            if value is not None:
                out[metric] = value
        return out


class MetricRegistryBuilder:
    """Explicit qualification phase: build a NEW frozen registry version.

    Starts from ``base`` producers when supplied (a qualified registry),
    refuses duplicate metric names within one build, and ``freeze()``
    returns an immutable :class:`CertifiedMetricRegistry`. The builder
    itself is never used while a study runs.
    """

    def __init__(self, version: str,
                 base: CertifiedMetricRegistry | None = None):
        if not isinstance(version, str) or not version:
            raise MetricRegistryError(
                f"registry version must be a nonempty string, got "
                f"{version!r}")
        self._version = version
        self._producers: dict[str, MetricProducer] = {}
        if base is not None:
            if not isinstance(base, CertifiedMetricRegistry):
                raise MetricRegistryError(
                    f"builder base must be a CertifiedMetricRegistry, "
                    f"got {type(base).__name__}")
            self._producers.update(base.producers)

    def register(self, metric: str, producer: MetricProducer
                 ) -> "MetricRegistryBuilder":
        _validate_producer(metric, producer)
        if metric in self._producers:
            raise MetricRegistryError(
                f"metric {metric!r} is already registered in this build "
                f"— one authority per metric; build a new version "
                f"instead of replacing a producer")
        self._producers[metric] = producer
        return self

    def freeze(self) -> CertifiedMetricRegistry:
        return CertifiedMetricRegistry(version=self._version,
                                       producers=dict(self._producers))


class ExperimentalMetricRegistry:
    """Mutable plugin registry. NEVER certified.

    Plugin experiments register/replace producers here; this object is
    structurally distinct from :class:`CertifiedMetricRegistry` and the
    certified entry point refuses it, so it can never yield
    CERTIFIED_PRODUCT Pareto.
    """

    certified = False

    def __init__(self, version: str = "experimental"):
        if not isinstance(version, str) or not version:
            raise MetricRegistryError(
                f"registry version must be a nonempty string, got "
                f"{version!r}")
        self.version = version
        self._producers: dict[str, MetricProducer] = {}

    def register(self, metric: str, producer: MetricProducer) -> None:
        """Register/replace a plugin producer (experimental only)."""
        _validate_producer(metric, producer)
        self._producers[metric] = producer

    def unregister(self, metric: str) -> None:
        self._producers.pop(metric, None)

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._producers))

    def extract(self, metric: str, verified: Any) -> float | None:
        producer = self._producers.get(metric)
        if producer is None:
            return None
        return _finite(producer(verified))

    def extract_all(self, verified: Any) -> dict[str, float]:
        out: dict[str, float] = {}
        for metric in self.metric_names():
            value = self.extract(metric, verified)
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


#: The product-controlled certified registry (frozen at import).
CERTIFIED_METRIC_REGISTRY = (
    MetricRegistryBuilder("certified-builtin-v1")
    .register("completion_cycles", _completion_cycles)
    .register("completion_time", _completion_cycles)
    .register("completion_ns", _completion_ns)
    .freeze()
)


__all__ = [
    "CERTIFIED_METRIC_REGISTRY",
    "METRIC_REGISTRY_DOMAIN",
    "CertifiedMetricRegistry",
    "ExperimentalMetricRegistry",
    "MetricProducer",
    "MetricRegistryBuilder",
    "MetricRegistryError",
]
