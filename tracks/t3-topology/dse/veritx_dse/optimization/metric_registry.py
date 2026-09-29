"""veritx_dse.optimization.metric_registry — certified metric authorities.

Rationale: docs/decisions/modules/optimization.md
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

Rationale: docs/decisions/modules/optimization.md
    """

    metric: str
    producer: MetricProducer = field(repr=False)
    producer_id: str
    semantics_version: str = "1"
    measured: bool = True

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
        if not isinstance(self.measured, bool):
            raise MetricRegistryError(
                f"measured flag for {self.metric!r} must be a bool, "
                f"got {self.measured!r}")

    def identity(self) -> dict[str, str]:
        return {"metric": self.metric, "producer_id": self.producer_id,
                "semantics_version": self.semantics_version}


@dataclass(frozen=True)
class CertifiedMetricRegistry:
    """An immutable, versioned, identity-bearing metric authority.

Rationale: docs/decisions/modules/optimization.md
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

    def is_measured(self, metric: str) -> bool:
        """True iff the registered authority is a backend measurement.

        Unknown metrics return False (no authority, no measurement).
        Analytical authorities (Wave-E model outputs) return False: they
        extract honestly but never satisfy certified measurement."""
        authority = self.authorities.get(metric)
        return authority is not None and authority.measured is True

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

Rationale: docs/decisions/modules/optimization.md
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
                 measured: bool = True,
                 ) -> "MetricRegistryBuilder":
        authority = MetricAuthority(
            metric=metric, producer=producer, producer_id=producer_id,
            semantics_version=semantics_version, measured=measured)
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

Rationale: docs/decisions/modules/optimization.md
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


def _qtime_cycles(doc: Any) -> float | None:
    """Exact rational cycle count from a persisted QTime, or None.

    QTime.to_dict() is {numerator, denominator} and is cycle-valued, so the
    scalar is the exact ratio — never a rounded approximation.
    """
    if not isinstance(doc, Mapping):
        return None
    n, den = doc.get("numerator"), doc.get("denominator")
    if type(n) is not int or type(den) is not int or den == 0:
        return None
    return n / den


def _makespan(verified: Any) -> float | None:
    """Wave-E schedule makespan in cycles (ANALYTICAL, model-derived)."""
    if not isinstance(verified, Mapping):
        return None
    return _qtime_cycles(verified.get("makespan"))


def _critical_path(verified: Any) -> float | None:
    """Longest EXPLICIT dependency chain, in cycles.

    Named for exactly what it is: resource-serialization edges are NOT part
    of it, so it can be shorter than the makespan and must never be read as
    the realized schedule critical path (the performance result says so in
    its own comment).
    """
    if not isinstance(verified, Mapping):
        return None
    return _qtime_cycles(verified.get("dependency_critical_path_duration"))


def _request_latency_mean(verified: Any) -> float | None:
    """Mean per-request latency in cycles, from the latency summary."""
    if not isinstance(verified, Mapping):
        return None
    summary = verified.get("latency_summary")
    if not isinstance(summary, Mapping):
        return None
    return _qtime_cycles(summary.get("mean"))


def _resource_utilization_max(verified: Any) -> float | None:
    """Highest occupied fraction across resources.

    ``utilization`` is PER-RESOURCE. A single scalar requires a reduction
    and the reduction is a choice, so the metric NAME says which one: the
    binding (maximum) resource. None when no resource reports a fraction.
    """
    if not isinstance(verified, Mapping):
        return None
    util = verified.get("utilization")
    if not isinstance(util, Mapping):
        return None
    vals = [row.get("utilization") for row in util.values()
            if isinstance(row, Mapping)
            and isinstance(row.get("utilization"), (int, float))]
    return max(vals) if vals else None


#: Wave-E metric names actually derivable as scalars from the verified
#: performance result, with the producer that derives each.
WAVE_E_SCALAR_METRICS = (
    ("makespan", _makespan),
    ("critical_path", _critical_path),
    ("request_latency_mean", _request_latency_mean),
    ("resource_utilization_max", _resource_utilization_max),
)

#: Wave-E facts that are NOT registered as scalar metrics, with the reason.
#: Recorded so their absence is a DECISION, not an oversight.
WAVE_E_NOT_SCALAR = {
    "sensitivity": "present as a nested analysis document, not a scalar; "
                   "exposing a single number would invent a reduction",
    "ttft": "declared in the Wave-E capability set but NOT computed in the "
            "performance result; registering it would fabricate a metric",
    "decode_step_latency": "same as ttft — declared, not computed here",
    "request_latencies": "a per-request row set; request_latency_mean is "
                         "the registered scalar view",
    "latency_summary": "a summary document (count/mean/median/max); the "
                       "mean is registered as request_latency_mean",
}


def wave_e_honesty_metadata(verified: Any) -> dict[str, Any]:
    """The honesty facts that MUST travel with any Wave-E metric.

    These keep an analytical model output from being read as a backend
    measurement. predictive_validation is NOT_ESTABLISHED and stays
    explicit.
    """
    from veritx_dse.application.capabilities import capability_registry
    doc = capability_registry()
    wave_e = (doc.get("wave_e") or {}) if isinstance(doc, Mapping) else {}
    meta = {
        "authority": "ANALYTICAL_MODEL",
        "measured": False,
        "predictive_validation": wave_e.get(
            "predictive_validation", "NOT_ESTABLISHED"),
        "unsupported": list(wave_e.get("unsupported") or ()),
        "fidelity_warning": None,
    }
    if isinstance(verified, Mapping):
        meta["fidelity_warning"] = verified.get("metrics_warning")
    return meta


CERTIFIED_METRIC_REGISTRY_V1 = (
    MetricRegistryBuilder("certified-builtin-v1")
    .register("completion_cycles", _completion_cycles,
              producer_id="authenticated-network-window-cycles")
    .register("completion_time", _completion_cycles,
              producer_id="authenticated-network-window-cycles")
    .register("completion_ns", _completion_ns,
              producer_id="authenticated-network-window-wall-time-ns")
    .freeze()
)


def _build_v2() -> CertifiedMetricRegistry:
    b = MetricRegistryBuilder("certified-builtin-v2",
                              base=CERTIFIED_METRIC_REGISTRY_V1)
    for name, producer in WAVE_E_SCALAR_METRICS:
        b.register(name, producer, producer_id=f"wave-e-model/{name}",
                     measured=False)
    return b.freeze()


CERTIFIED_METRIC_REGISTRY = _build_v2()


@dataclass(frozen=True)
class FederatedMetricDescriptor:
    """One bindable-or-explicitly-ineligible optimization metric."""

    metric: str
    semantic_family: str
    question: str
    backends: tuple[str, ...]
    fidelity: str | None
    unit: str | None
    scalar_bindable: bool
    optimization_eligible: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "semantic_family": self.semantic_family,
            "question": self.question,
            "backends": list(self.backends),
            "fidelity": self.fidelity,
            "unit": self.unit,
            "scalar_bindable": self.scalar_bindable,
            "optimization_eligible": self.optimization_eligible,
            "reason": self.reason,
        }


def federated_semantic_family(question: Any, metric: str) -> str:
    """The semantic family of a (question, metric) objective axis.

Rationale: docs/decisions/modules/optimization.md
    """
    from veritx_dse.application.evaluation_question import (
        EvaluationQuestion,
    )
    from veritx_dse.optimization.capabilities import (
        objective_semantic_family,
    )
    if question is EvaluationQuestion.NETWORK_COMPLETION:
        return objective_semantic_family(metric)
    name = getattr(question, "value", question)
    return f"{name}:{metric}"


def federated_metric_catalog(registry: Any | None = None
                             ) -> tuple[FederatedMetricDescriptor, ...]:
    """The federated optimization truth, derived from authority.

Rationale: docs/decisions/modules/optimization.md
    """
    from veritx_dse.application.evaluation_question import (
        EvaluationQuestion,
    )
    if registry is None:
        from veritx_dse.backend.registry import default_backend_registry
        registry = default_backend_registry()
    declared: dict[Any, dict[str, Any]] = {}
    for adapter in registry.adapters():
        backend_id = adapter.backend_id
        for capability in adapter.capabilities():
            from veritx_dse.backend.adapter import SupportLevel
            if capability.support is not SupportLevel.SUPPORTED:
                continue
            entry = declared.setdefault(
                capability.question,
                {"backends": [], "fidelity": None})
            if backend_id not in entry["backends"]:
                entry["backends"].append(backend_id)
            fidelity = capability.fidelity
            if entry["fidelity"] is None:
                entry["fidelity"] = fidelity
            elif entry["fidelity"] is not fidelity:
                raise MetricRegistryError(
                    f"question {capability.question.value!r} is claimed "
                    f"at two fidelities "
                    f"({entry['fidelity'].value!r} vs "
                    f"{fidelity.value!r}) — the catalog cannot name one "
                    f"model for it; refusing rather than merging models")

    rows: list[FederatedMetricDescriptor] = []

    def _family(question: Any, metric: str) -> str:
        return federated_semantic_family(question, metric)

    def _fidelity(question: Any) -> str | None:
        entry = declared.get(question)
        if entry is None or entry["fidelity"] is None:
            return None
        return entry["fidelity"].value

    def _backends(question: Any) -> tuple[str, ...]:
        entry = declared.get(question)
        if entry is None:
            return ()
        return tuple(sorted(entry["backends"]))

    network = EvaluationQuestion.NETWORK_COMPLETION
    for metric in CERTIFIED_METRIC_REGISTRY.metric_names():
        rows.append(FederatedMetricDescriptor(
            metric=metric, semantic_family=_family(network, metric),
            question=network.value, backends=_backends(network),
            fidelity=_fidelity(network), unit=None,
            scalar_bindable=True,
            optimization_eligible=bool(_backends(network)),
            reason=(None if _backends(network) else
                    "no registered backend answers NETWORK_COMPLETION")))

    # ASTRA questions: the adapter's single-source metric table
    # (ASTRA_NORMALIZED_METRICS mirrors normalize(); edit there).
    from veritx_dse.backend.astra_adapter import ASTRA_NORMALIZED_METRICS
    for question in (EvaluationQuestion.SYSTEM_MAKESPAN,
                     EvaluationQuestion.COMMUNICATION_EXPOSURE,
                     EvaluationQuestion.PER_RANK_COMPLETION):
        table = ASTRA_NORMALIZED_METRICS.get(question, ())
        if question not in ASTRA_NORMALIZED_METRICS:
            raise MetricRegistryError(
                f"the ASTRA metric table names no rows for "
                f"{question.value!r} — the catalog mirrors normalize(), "
                f"it never invents metrics")
        for key, unit, bindable in table:
            rows.append(FederatedMetricDescriptor(
                metric=key, semantic_family=_family(question, key),
                question=question.value, backends=_backends(question),
                fidelity=_fidelity(question), unit=unit,
                scalar_bindable=bool(bindable),
                optimization_eligible=(
                    bool(bindable) and bool(_backends(question))),
                reason=(None if (bindable and _backends(question))
                        else _ineligible_reason(
                            question, key, bindable,
                            _backends(question)))))

    from veritx_dse.backend.ramulator_adapter import (
        RAMULATOR_NORMALIZED_METRICS,
    )
    dram = EvaluationQuestion.DRAM_TIMING
    for key in RAMULATOR_NORMALIZED_METRICS:
        rows.append(FederatedMetricDescriptor(
            metric=key, semantic_family=_family(dram, key),
            question=dram.value, backends=_backends(dram),
            fidelity=_fidelity(dram), unit=None,
            scalar_bindable=True,
            optimization_eligible=bool(_backends(dram)),
            reason=(None if _backends(dram) else
                    "no registered backend answers DRAM_TIMING")))

    from veritx_dse.backend.serving_normalization import (
        SERVING_BACKEND_ID, SERVING_MODEL_FIDELITY,
    )
    for question, key in (
            (EvaluationQuestion.SERVING_TTFT, "ttft_cycles"),
            (EvaluationQuestion.SERVING_COMPLETION,
             "completion_cycles")):
        rows.append(FederatedMetricDescriptor(
            metric=key, semantic_family=_family(question, key),
            question=question.value, backends=(SERVING_BACKEND_ID,),
            fidelity=SERVING_MODEL_FIDELITY.value, unit="cycles",
            scalar_bindable=False, optimization_eligible=False,
            reason=(f"{key!r} from {question.value} is measured "
                    f"per-request (request_id dimensions) by "
                    f"{SERVING_BACKEND_ID}, never through the planner; "
                    f"a scalar objective cannot bind it")))
    return tuple(rows)


def _ineligible_reason(question: Any, metric: str, bindable: bool,
                       backends: tuple[str, ...]) -> str:
    if not backends:
        return (f"no registered backend answers {question.value!r}")
    if not bindable:
        return (f"{metric!r} from {question.value} is measured with "
                f"dimensions only; a scalar objective cannot bind it — "
                f"no invented key suffixes")
    return "not eligible"


__all__ = [
    "CERTIFIED_METRIC_REGISTRY",
    "CERTIFIED_METRIC_REGISTRY_V1",
    "WAVE_E_SCALAR_METRICS",
    "WAVE_E_NOT_SCALAR",
    "wave_e_honesty_metadata",
    "federated_metric_catalog",
    "federated_semantic_family",
    "FederatedMetricDescriptor",
    "METRIC_REGISTRY_DOMAIN",
    "CertifiedMetricRegistry",
    "ExperimentalMetricRegistry",
    "MetricAuthority",
    "MetricProducer",
    "MetricRegistryBuilder",
    "MetricRegistryError",
]
