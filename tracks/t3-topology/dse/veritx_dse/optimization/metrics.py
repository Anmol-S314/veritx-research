"""veritx_dse.optimization.metrics — verified metric extraction (§31–§36).

Every metric value in a Wave-F result comes from a VERIFIED parent
through this module — never from a stored summary typed by a producer,
never from a raw ``store.get``. Missing modeled behavior is NOT zero
(§33): a metric with no producer is UNMEASURABLE (value None) with an
exact reason, and unmeasurable constraints never pass (§47).

Sources:

    WAVE_E       the result's verified ``wave_e`` block (already
                 re-derived from the plan binding + authenticated
                 evidence by ``verify_wave_e_result_block``); request
                 latencies are RE-DERIVED by re-running the sealed
                 scheduler over the store-verified temporal workload
                 (§32: reuse sealed Wave-E functions).
    WAVE_D_CHAIN the result's verified ``wave_d`` execution block.
    STRUCTURAL   exact counts from the fabric authority (§34), labeled
                 EXACT_STRUCTURAL (§35). Proxies are not registered in
                 Wave-F v1 (§36: no fake area/power/energy).

All values are exact Fractions until reporting (§39).
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from veritx_dse.wavee.metrics import latency_summary, request_latencies
from veritx_dse.wavee.time import QTime
from veritx_dse.wavee.workload import EVENT_NETWORK_TRAFFIC_WINDOW

from .definition import METRIC_REGISTRY

#: Metric values are keyed by (metric_name, scenario_name | None) so
#: the same metric under two scenarios never silently collide (§44).
MetricKey = tuple[str, "str | None"]


class MetricError(ValueError):
    """Refusal to extract a metric from inadequate evidence."""


@dataclass(frozen=True)
class MetricValue:
    """One extracted value with full provenance (§93)."""
    name: str
    status: str                    # MEASURED | UNMEASURABLE | UNSUPPORTED
    value: Fraction | None         # exact; None unless MEASURED
    unit: str
    source_result_id: str | None
    fidelity: str                  # from the metric registry
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.name,
            "status": self.status,
            "value": ({"numerator": self.value.numerator,
                       "denominator": self.value.denominator}
                      if self.value is not None else None),
            "unit": self.unit,
            "source_result_id": self.source_result_id,
            "fidelity": self.fidelity,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, doc: Any) -> "MetricValue":
        if not isinstance(doc, dict) or set(doc) != {
                "metric", "status", "value", "unit", "source_result_id",
                "fidelity", "reason"}:
            raise MetricError(f"malformed metric value doc: {doc!r}")
        if doc["status"] not in ("MEASURED", "UNMEASURABLE",
                                 "UNSUPPORTED"):
            raise MetricError(f"bad metric status {doc['status']!r}")
        value = None
        if doc["value"] is not None:
            value = Fraction(doc["value"]["numerator"],
                             doc["value"]["denominator"])
        if doc["status"] == "MEASURED" and value is None:
            raise MetricError("MEASURED metric must carry a value")
        if doc["status"] != "MEASURED" and value is not None:
            raise MetricError(
                f"{doc['status']} metric must carry value=None, got "
                f"{doc['value']!r} (§33: never substitute zero)")
        return cls(name=doc["metric"], status=doc["status"], value=value,
                   unit=doc["unit"],
                   source_result_id=doc["source_result_id"],
                   fidelity=doc["fidelity"], reason=doc["reason"])


def _metric_def(name: str):
    try:
        return METRIC_REGISTRY[name]
    except KeyError:
        raise MetricError(
            f"metric {name!r} is not in the closed registry") from None


def _unmeasurable(name: str, rid: str | None, reason: str
                  ) -> MetricValue:
    mdef = _metric_def(name)
    return MetricValue(name=name, status="UNMEASURABLE", value=None,
                       unit=mdef.unit, source_result_id=rid,
                       fidelity=mdef.fidelity, reason=reason)


# ── extractors (pure; input = VERIFIED result document) ─────────────────

def _extract_wave_e_timing(result: dict[str, Any], name: str
                           ) -> MetricValue:
    """system.makespan_s / network.window_s from the verified wave_e block."""
    mdef = _metric_def(name)
    rid = result.get("resource_id")
    block = result.get("wave_e")
    if not isinstance(block, dict) or block.get("makespan") is None:
        return _unmeasurable(
            name, rid,
            "verified result carries no wave_e timing block")
    if name == "system.makespan_s":
        doc = block["makespan"]
    else:
        doc = block["network_window"]
        if doc is None:
            return _unmeasurable(
                name, rid,
                "no network window bound in the verified wave_e block "
                "(§33: absent producer, not zero)")
    try:
        value = Fraction(doc["numerator"], doc["denominator"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise MetricError(
            f"metric {name!r}: malformed rational document {doc!r}"
        ) from exc
    return MetricValue(
        name=name, status="MEASURED", value=value, unit=mdef.unit,
        source_result_id=rid, fidelity=mdef.fidelity)


def _extract_wave_d_delivered(result: dict[str, Any], name: str
                              ) -> MetricValue:
    """network.delivered_packets from the verified wave_d block."""
    mdef = _metric_def(name)
    rid = result.get("resource_id")
    block = result.get("wave_d")
    if not isinstance(block, dict) or \
            block.get("delivered_packets") is None:
        return _unmeasurable(
            name, rid,
            "verified result carries no wave_d execution block")
    value = block["delivered_packets"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MetricError(
            f"metric {name!r}: delivered_packets must be a "
            f"non-negative int, got {value!r}")
    return MetricValue(
        name=name, status="MEASURED", value=Fraction(value),
        unit=mdef.unit, source_result_id=rid, fidelity=mdef.fidelity)


def _network_durations_from_block(
        workload: Any, block: dict[str, Any]) -> dict[str, "QTime"] | None:
    """Evidence-bound window durations for the workload's NET event."""
    network_events = [e for e in workload.events
                      if e.kind == EVENT_NETWORK_TRAFFIC_WINDOW]
    if not network_events:
        return None
    binding_doc = block.get("network_binding")
    if not isinstance(binding_doc, dict):
        return None
    dur = binding_doc.get("duration")
    if not isinstance(dur, dict) or "numerator" not in dur:
        return None
    window = QTime(Fraction(dur["numerator"], dur["denominator"]))
    return {e.event_id: window for e in network_events}


def _derive_request_latencies(result: dict[str, Any], name: str,
                              store: Any) -> MetricValue:
    """request.mean/p95_latency_s — RE-DERIVED from the verified workload.

    The persisted wave_e block carries only makespan/network_window
    summaries; request latencies are not among them. The store-verified
    temporal workload is the authority: re-run the sealed deterministic
    scheduler from the verified parents and re-derive through the
    sealed Wave-E latency functions (§32). A workload with no requests
    is UNSUPPORTED — an absent producer is never zero (§33).
    """
    rid = result.get("resource_id")
    block = result.get("wave_e")
    tw_id = block.get("temporal_workload_id")
    from veritx_dse.application.wave_e_resources import \
        load_verified_wave_e_workload
    try:
        workload = load_verified_wave_e_workload(store, tw_id)
    except Exception as exc:
        return _unmeasurable(
            name, rid,
            f"temporal workload {tw_id} fails verification: {exc}")
    if not workload.requests:
        mdef = _metric_def(name)
        return MetricValue(
            name=name, status="UNSUPPORTED", value=None, unit=mdef.unit,
            source_result_id=rid, fidelity=mdef.fidelity,
            reason="temporal workload declares no requests (§33: "
                   "absent producer, never zero)")
    from veritx_dse.wavee.scheduler import schedule_workload
    try:
        schedule = schedule_workload(
            workload,
            network_durations=_network_durations_from_block(
                workload, block))
        rows = request_latencies(workload, schedule)
    except Exception as exc:
        return _unmeasurable(
            name, rid, f"schedule re-derivation failed: {exc}")
    summary = latency_summary(rows) if rows else None
    if not summary:
        return _unmeasurable(
            name, rid,
            "no request completed within the derived schedule")
    key = "mean" if name == "request.mean_latency_s" else "p95"
    doc = summary[key]
    return MetricValue(
        name=name, status="MEASURED",
        value=Fraction(doc["numerator"], doc["denominator"]),
        unit=_metric_def(name).unit, source_result_id=rid,
        fidelity=_metric_def(name).fidelity)


def request_latency_summary(result: dict[str, Any],
                            store: Any) -> dict[str, Any] | None:
    """The full re-derived latency summary (verification aid, §66).

    Returns None when no summary can be derived; callers must treat
    that as "summary not available", never as zero.
    """
    block = result.get("wave_e") if isinstance(result, dict) else None
    if not isinstance(block, dict) or \
            block.get("temporal_workload_id") is None:
        return None
    from veritx_dse.application.wave_e_resources import \
        load_verified_wave_e_workload
    try:
        workload = load_verified_wave_e_workload(
            store, block["temporal_workload_id"])
        from veritx_dse.wavee.scheduler import schedule_workload
        schedule = schedule_workload(
            workload,
            network_durations=_network_durations_from_block(
                workload, block))
        rows = request_latencies(workload, schedule)
        return latency_summary(rows) if rows else None
    except Exception:
        return None


def _structural_counts(template: dict[str, Any]) -> tuple[int, int, int]:
    """Exact (routers, channels, endpoints) from the Wave-B authority.

    The scenario template (patched with the candidate's assignment) is
    lowered through the SAME sealed derivation the backend consumes
    (``derive_request`` -> ``CompileRequest`` -> ``compile_bundle``);
    counts are read off the materialized topology/attachment. No
    formula, no proxy, no guessing (§34/§35).
    """
    from veritx_dse.application.compile import compile_bundle
    from veritx_dse.application.presets import derive_request
    from veritx_dse.model.compile_model import CompileRequest
    req = CompileRequest.from_dict(derive_request(
        template["fabric_preset"],
        dict(template.get("fabric_overrides") or {})))
    bundle = compile_bundle(req)
    topo = bundle.topology
    att = bundle.attachment
    return (int(topo.router_count), int(topo.channel_count),
            int(att.endpoint_count))


def _extract_structural(result: dict[str, Any], name: str
                        ) -> MetricValue:
    """fabric.router_count / endpoint_count / channel_count (§34/§35).

    EXACT counts derived from the sealed Wave-B fabric chain for the
    CANDIDATE-PATCHED scenario template. Classification is always
    EXACT_STRUCTURAL (§35). Unknown presets and failing derivations
    yield UNMEASURABLE, never zero.
    """
    template = result.get("_scenario_template")
    mdef = _metric_def(name)
    rid = result.get("resource_id")
    if not isinstance(template, dict) or \
            not isinstance(template.get("fabric_preset"), str):
        return _unmeasurable(
            name, rid,
            "no patched scenario template available for structural "
            "extraction")
    try:
        routers, channels, endpoints = _structural_counts(template)
    except Exception as exc:
        return _unmeasurable(
            name, rid,
            f"structural derivation failed through the Wave-B chain: "
            f"{type(exc).__name__}: {exc}")
    value = {"fabric.router_count": routers,
             "fabric.channel_count": channels,
             "fabric.endpoint_count": endpoints}.get(name)
    if value is None:
        raise MetricError(f"unknown structural metric {name!r}")
    return MetricValue(
        name=name, status="MEASURED", value=Fraction(value),
        unit=mdef.unit, source_result_id=rid, fidelity=mdef.fidelity)


# ── dispatch ─────────────────────────────────────────────────────────────

def extract_metric(name: str, result: dict[str, Any], *,
                   store: Any = None, scenario_template: dict | None = None
                   ) -> MetricValue:
    """Extract one registry metric from a VERIFIED result (§31).

    ``store`` is required for request-latency re-derivation;
    ``scenario_template`` for structural metrics. Unknown metrics refuse.
    """
    if name not in METRIC_REGISTRY:
        raise MetricError(
            f"metric {name!r} is not in the closed registry")
    payload = dict(result) if isinstance(result, dict) else {}
    if scenario_template is not None:
        payload["_scenario_template"] = scenario_template
    if name in ("system.makespan_s", "network.window_s"):
        return _extract_wave_e_timing(payload, name)
    if name == "network.delivered_packets":
        return _extract_wave_d_delivered(payload, name)
    if name in ("request.mean_latency_s", "request.p95_latency_s"):
        if store is None:
            raise MetricError(
                f"metric {name!r} requires a store for verified "
                f"workload re-derivation")
        block = payload.get("wave_e")
        if not isinstance(block, dict) or \
                block.get("temporal_workload_id") is None:
            return _unmeasurable(
                name, payload.get("resource_id"),
                "verified result carries no wave_e timing block")
        return _derive_request_latencies(payload, name, store)
    if name in ("fabric.router_count", "fabric.endpoint_count",
                "fabric.channel_count"):
        return _extract_structural(payload, name)
    raise MetricError(f"metric {name!r} has no extractor")


# ── per-candidate objective/constraint extraction ────────────────────────

def _pick_scenario_free(scenario_results: dict[str, dict[str, Any] | None]
                        ) -> tuple[str, dict[str, Any]] | None:
    """Deterministic (scenario_name, result) for a scenario-free spec:
    lexicographically first scenario that has a verified result."""
    for sname in sorted(scenario_results):
        if scenario_results[sname] is not None:
            return (sname, scenario_results[sname])
    return None


def extract_spec_values(
        defn: Any, specs: list[Any], *,
        scenario_results: dict[str, dict[str, Any] | None],
        store: Any = None,
        templates: dict[str, dict] | None = None
        ) -> dict[MetricKey, MetricValue]:
    """Extract every spec's metric, keyed by (metric, scenario).

    Shared by objectives and hard constraints — one concept, one
    implementation. Unknown scenario names and missing scenario results
    yield UNMEASURABLE with reasons (§47), never zero.
    """
    values: dict[MetricKey, MetricValue] = {}
    templates = templates or {}
    known_scenarios = set(defn.scenario_names())
    for spec in specs:
        key: MetricKey = (spec.metric, spec.scenario)
        if key in values:
            continue
        if spec.scenario is not None and \
                spec.scenario not in known_scenarios:
            values[key] = _unmeasurable(
                spec.metric, None,
                f"names unknown scenario {spec.scenario!r}")
            continue
        if spec.scenario is not None:
            result = scenario_results.get(spec.scenario)
            tname: str | None = spec.scenario
        else:
            picked = _pick_scenario_free(scenario_results)
            if picked is None:
                result = None
            else:
                tname, result = picked
        if result is None:
            values[key] = _unmeasurable(
                spec.metric, None,
                f"scenario {spec.scenario!r} has no verified result"
                if spec.scenario is not None else
                "no scenario produced a verified result")
            continue
        # scenario-free structural metrics take the template of the
        # scenario whose verified result was picked — never a None-key
        # lookup (which would silently drop the candidate patch).
        template = templates.get(tname) if tname is not None else None
        values[key] = extract_metric(
            spec.metric, result, store=store,
            scenario_template=template)
    return values


def extract_objective_values(
        defn: Any, scenario_results: dict[str, dict[str, Any] | None], *,
        store: Any = None,
        templates: dict[str, dict] | None = None
        ) -> dict[MetricKey, MetricValue]:
    """All declared objective metrics for one candidate (§38/§93)."""
    return extract_spec_values(
        defn, list(defn.objectives), scenario_results=scenario_results,
        store=store, templates=templates)


def extract_constraint_values(
        defn: Any, scenario_results: dict[str, dict[str, Any] | None], *,
        store: Any = None,
        templates: dict[str, dict] | None = None
        ) -> dict[MetricKey, MetricValue]:
    """All declared hard-constraint metrics for one candidate (§46)."""
    return extract_spec_values(
        defn, list(defn.hard_constraints),
        scenario_results=scenario_results, store=store,
        templates=templates)


def metric_key_doc(key: MetricKey) -> dict[str, Any]:
    """Canonical JSON document for a metric key."""
    return {"metric": key[0], "scenario": key[1]}


def metric_key_from_doc(doc: Any) -> MetricKey:
    if not isinstance(doc, dict) or set(doc) != {"metric", "scenario"}:
        raise MetricError(f"malformed metric key doc: {doc!r}")
    if not isinstance(doc["metric"], str):
        raise MetricError("metric key metric must be a string")
    if doc["scenario"] is not None and \
            not isinstance(doc["scenario"], str):
        raise MetricError("metric key scenario must be a string or null")
    return (doc["metric"], doc["scenario"])


def value_map_doc(values: dict[MetricKey, MetricValue]) -> list[dict]:
    """Canonical serialization of a keyed metric-value map (sorted)."""
    out = []
    for key in sorted(values, key=lambda k: (k[0], k[1] or "")):
        doc = metric_key_doc(key)
        doc["value"] = values[key].to_dict()
        out.append(doc)
    return out


def value_map_from_doc(docs: Any) -> dict[MetricKey, MetricValue]:
    """Rebuild a keyed metric-value map; malformed entries refuse."""
    if not isinstance(docs, list):
        raise MetricError("metric value map must be a list")
    out: dict[MetricKey, MetricValue] = {}
    for doc in docs:
        if not isinstance(doc, dict) or set(doc) != {"metric", "scenario",
                                                     "value"}:
            raise MetricError(f"malformed metric map entry: {doc!r}")
        key = metric_key_from_doc(
            {"metric": doc["metric"], "scenario": doc["scenario"]})
        out[key] = MetricValue.from_dict(doc["value"])
    return out
