"""Product metric contracts used by comparison gates.

A metric key is not a definition. Two runs that both report
``completion_cycles`` may have measured different populations, so a delta
is only offered when both sides name the same product-level definition.
The product evaluation surface reports a small, closed set of network
metrics; unknown keys deliberately receive no definition and are therefore
not comparable.

Rationale: docs/decisions/modules/product.md
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

VERSION = 1

@dataclass(frozen=True)
class ProductMetricDefinition:
    metric_id: str
    unit: str
    aggregation: str
    direction: str
    scope: str
    description: str
    authority: str

    @property
    def definition_id(self) -> str:
        return f"product.metric.{self.metric_id}.v{VERSION}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "definition_id": self.definition_id,
            "version": VERSION,
            "unit": self.unit,
            "aggregation": self.aggregation,
            "direction": self.direction,
            "scope": self.scope,
            "description": self.description,
            "authority": self.authority,
        }


def _metric(metric_id: str, unit: str, aggregation: str, direction: str,
            scope: str, description: str, authority: str
            ) -> ProductMetricDefinition:
    return ProductMetricDefinition(
        metric_id=metric_id, unit=unit, aggregation=aggregation,
        direction=direction, scope=scope, description=description,
        authority=authority)


PRODUCT_METRIC_DEFINITIONS: dict[str, ProductMetricDefinition] = {
    definition.metric_id: definition
    for definition in (
        _metric(
            "completion_cycles", "cycles", "total", "LOWER_IS_BETTER",
            "network completion window",
            "Cycles from the authenticated network completion window; this "
            "is a network duration, not transaction or application latency.",
            "performance_result.network_binding.duration x network clock"),
        _metric(
            "sample_window_cycles", "cycles", "window", "NONE",
            "backend sample window",
            "The backend's reported sampling window in cycles. It bounds "
            "the observation; it is not a completion time.",
            "backend statistics"),
        _metric(
            "completion_time", "cycles", "total", "LOWER_IS_BETTER",
            "network completion window",
            "Legacy alias for the network completion duration.",
            "authenticated network window"),
        _metric(
            "packet_latency_avg", "cycles", "mean", "LOWER_IS_BETTER",
            "stock BookSim packet latency population",
            "Mean packet latency from the stock qtime/ctime population. "
            "It is not the trace-request latency population.",
            "BookSim packet statistics"),
        _metric(
            "flit_latency_avg", "cycles", "mean", "LOWER_IS_BETTER",
            "BookSim flit latency population",
            "Mean flit latency from the backend's flit statistics.",
            "BookSim flit statistics"),
        _metric(
            "delivered_packets", "packets", "count", "NONE",
            "trace replay delivery",
            "Packets delivered by the trace replay.",
            "BookSim trace replay"),
        _metric(
            "injected_trace_packets", "packets", "count", "NONE",
            "injected trace traffic",
            "Trace packets injected by the workload binding.",
            "authenticated trace binding"),
        _metric(
            "loaded_trace_packets", "packets", "count", "NONE",
            "loaded trace traffic",
            "Trace packets loaded from the canonical trace.",
            "authenticated trace binding"),
        _metric(
            "flits_injected", "flits", "count", "NONE",
            "network flit injection",
            "Flits injected into the network.",
            "BookSim flit statistics"),
        _metric(
            "flits_accepted", "flits", "count", "NONE",
            "network flit acceptance",
            "Flits accepted by the network.",
            "BookSim flit statistics"),
        _metric(
            "hops", "hops", "mean", "LOWER_IS_BETTER",
            "BookSim hop count",
            "Mean hops per packet reported by the backend.",
            "BookSim statistics"),
        _metric(
            "throughput", "packets/cycle", "mean", "HIGHER_IS_BETTER",
            "accepted packet rate",
            "Mean accepted packet rate. It is not application throughput.",
            "BookSim statistics"),
    )
}

UNKNOWN_DEFINITION: dict[str, Any] = {
    "metric_id": None,
    "definition_id": None,
    "version": None,
    "unit": None,
    "aggregation": None,
    "direction": "UNKNOWN",
    "scope": None,
    "description": "No product-level metric definition is registered.",
    "authority": None,
}


def product_metric_definition(metric_id: str) -> dict[str, Any] | None:
    definition = PRODUCT_METRIC_DEFINITIONS.get(metric_id)
    return None if definition is None else definition.to_dict()


def metric_definitions_for(metrics: dict[str, Any]) -> dict[str, Any]:
    """Return one definition (or an explicit unknown marker) per key."""
    return {key: (product_metric_definition(key) or
                  {**UNKNOWN_DEFINITION, "metric_id": key})
            for key in sorted(metrics)}


def definition_mismatch(a: dict[str, Any] | None,
                        b: dict[str, Any] | None) -> str | None:
    """Return the identity field that differs, or None when identical."""
    if a is None or b is None:
        return "definition"
    for field in ("definition_id", "version", "unit", "direction",
                  "aggregation", "scope"):
        if a.get(field) != b.get(field):
            return field
    return None


__all__ = [
    "PRODUCT_METRIC_DEFINITIONS",
    "ProductMetricDefinition",
    "definition_mismatch",
    "metric_definitions_for",
    "product_metric_definition",
]
