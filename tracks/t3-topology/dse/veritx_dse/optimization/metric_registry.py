"""veritx_dse.optimization.metric_registry — certified metric authorities.

Law (RT-final R2/C2): the certified metric authority is a FROZEN,
VERSIONED, identity-bearing product artifact. There is no public mutation
API on a frozen registry, and the certified entry point does not accept a
caller-supplied registry at all — certified optimization uses the
product-controlled ``CERTIFIED_METRIC_REGISTRY`` only. Extensibility goes
through an approved registry catalog (qualification -> registered producer
semantics -> approved registry ID -> certified execution), never runtime
selection. Plugins live in a separate
:class:`ExperimentalMetricRegistry` that can never yield
CERTIFIED_PRODUCT Pareto.

``registry_id()`` binds a declared semantic identity per metric —
``metric + producer_id + producer_semantics_version`` — not merely the
metric name, so ``{latency: ->1.0}`` and ``{latency: ->999999.0}`` can
never share an ID. (The callable itself need not be hashed; its declared
identity is the audit handle.) The resulting
``OptimizationResult`` binds ``metric_registry_id`` and
``metric_registry_version``.

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


@dataclass(frozen=True)
class MetricAuthority:
    """One metric's producer plus its DECLARED semantic identity.

    ``producer_id`` names the qualified producer (what the value means);
    ``semantics_version`` versions that meaning. Both are bound into the
    registry identity, so a semantics change is a new registry version
    even when the metric name and version string are unchanged.
    """

    metric: str
    producer: MetricProducer = field(repr=False)
    producer_id: str
    semantics_version: str = "1"

    def __post_init__(self):
        if not isinstance(self.metric, str) or not self.metric:
            raise MetricRegistryError(
                f"metric name must be a nonempty string, got "
                f"{self.metric!r}")
        if not callable(self.producer):
            raise MetricRegistryError(
                f"metric producer for {self.metric!r} must be callable, "
                f"got {type(self.producer).__name__}")
        if not isinstance(self.producer_id, str) or not self.producer_id:
            raise MetricRegistryError(
                f"producer_id for {self.metric!r} must be a nonempty "
                f"string, got {self.producer_id!r}")
        if not isinstance(self.semantics_version, str) or \
                not self.semantics_version:
            raise MetricRegistryError(
                f"semantics_version for {self.metric!r} must be a "
                f"nonempty string, got {self.semantics_version!r}")

    def identity(self) -> dict[str, str]:
        return {"metric": self.metric, "producer_id": self.producer_id,
                "semantics_version": self.semantics_version}


@dataclass(frozen=True)
class CertifiedMetricRegistry:
    """An immutable, versioned, identity-bearing metric authority.

    ``authorities`` is wrapped in a read-only mapping at construction; the
    dataclass is frozen and exposes no register/unregister method. The
    registry identity (``registry_id``) binds the version and the exact
    ``{metric, producer_id, semantics_version}`` set.
    """

    version: str
    authorities: Mapping[str, MetricAuthority] = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version:
            raise MetricRegistryError(
                f"registry version must be a nonempty string, got "
                f"{self.version!r}")
        if not isinstance(self.authorities, Mapping):
            raise MetricRegistryError(
                f"registry authorities must be a mapping, got "
                f"{type(self.authorities).__name__}")
        for metric, authority in self.authorities.items():
            if not isinstance(authority, MetricAuthority):
                raise MetricRegistryError(
                    f"authority for {metric!r} must be a MetricAuthority, "
                    f"got {type(authority).__name__}")
            if authority.metric != metric:
                raise MetricRegistryError(
                    f"authority key {metric!r} != authority metric "
                    f"{authority.metric!r}")
        object.__setattr__(
            self, "authorities",
            MappingProxyType(dict(self.authorities)))

    def registry_id(self) -> str:
        """Content identity of (version, declared producer semantics)."""
        return content_id(METRIC_REGISTRY_DOMAIN, {
            "version": self.version,
            "metrics": [self.authorities[m].identity()
                        for m in sorted(self.authorities)],
        })

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.authorities))

    def has_metric(self, metric: str) -> bool:
        return metric in self.authorities

    def extract(self, metric: str, verified: Any) -> float | None:
        """The authoritative finite value, or None (absent evidence)."""
        authority = self.authorities.get(metric)
        if authority is None:
            return None
        return _finite(authority.producer(verified))

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

    Starts from ``base`` authorities when supplied (a qualified registry),
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
        self._authorities: dict[str, MetricAuthority] = {}
        if base is not None:
            if not isinstance(base, CertifiedMetricRegistry):
                raise MetricRegistryError(
                    f"builder base must be a CertifiedMetricRegistry, "
                    f"got {type(base).__name__}")
            self._authorities.update(base.authorities)

    def register(self, metric: str, producer: MetricProducer, *,
                 producer_id: str,
                 semantics_version: str = "1",
                 ) -> "MetricRegistryBuilder":
        authority = MetricAuthority(
            metric=metric, producer=producer, producer_id=producer_id,
            semantics_version=semantics_version)
        if metric in self._authorities:
            raise MetricRegistryError(
                f"metric {metric!r} is already registered in this build "
                f"— one authority per metric; build a new version "
                f"instead of replacing a producer")
        self._authorities[metric] = authority
        return self

    def freeze(self) -> CertifiedMetricRegistry:
        return CertifiedMetricRegistry(version=self._version,
                                       authorities=dict(self._authorities))


class ExperimentalMetricRegistry:
    """Mutable plugin registry. NEVER certified.

    Plugin experiments register/replace producers here; this object is
    structurally distinct from :class:`CertifiedMetricRegistry` and the
    certified extraction path refuses it, so it can never yield
    CERTIFIED_PRODUCT Pareto.
    """

    certified = False

    def __init__(self, version: str = "experimental"):
        if not isinstance(version, str) or not version:
            raise MetricRegistryError(
                f"registry version must be a nonempty string, got "
                f"{version!r}")
        self.version = version
        self._authorities: dict[str, MetricAuthority] = {}

    def register(self, metric: str, producer: MetricProducer, *,
                 producer_id: str = "experimental",
                 semantics_version: str = "1") -> None:
        """Register/replace a plugin producer (experimental only)."""
        self._authorities[metric] = MetricAuthority(
            metric=metric, producer=producer, producer_id=producer_id,
            semantics_version=semantics_version)

    def unregister(self, metric: str) -> None:
        self._authorities.pop(metric, None)

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._authorities))

    def extract(self, metric: str, verified: Any) -> float | None:
        authority = self._authorities.get(metric)
        if authority is None:
            return None
        return _finite(authority.producer(verified))

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


#: The product-controlled certified registry (frozen at import). Only this
#: registry is used by ``Optimizer.optimize_certified``.
CERTIFIED_METRIC_REGISTRY = (
    MetricRegistryBuilder("certified-builtin-v1")
    .register("completion_cycles", _completion_cycles,
              producer_id="authenticated-network-window-cycles")
    .register("completion_time", _completion_cycles,
              producer_id="authenticated-network-window-cycles")
    .register("completion_ns", _completion_ns,
              producer_id="authenticated-network-window-wall-time-ns")
    .freeze()
)


__all__ = [
    "CERTIFIED_METRIC_REGISTRY",
    "METRIC_REGISTRY_DOMAIN",
    "CertifiedMetricRegistry",
    "ExperimentalMetricRegistry",
    "MetricAuthority",
    "MetricProducer",
    "MetricRegistryBuilder",
    "MetricRegistryError",
]
