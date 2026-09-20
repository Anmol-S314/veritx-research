"""veritx_dse.wavee.result — EventGraph + PerformanceResult (§65/§66/§74).

Identity DAG (direct parents, mechanically hashed):

    event_graph_id = H(temporal_workload_id, performance_model_id,
                       network window binding?, Wave-D chain?)

    performance_result_id = H(event_graph_id, performance_model_id,
                              canonical schedule, makespan, critical path)

Two rules from Waves C/D carry over verbatim:

- **Schema close**: a VERIFIED result refuses unknown fields — no
  ``{"estimated_speedup": "47%"}`` hitchhiking through verification (§75).
- **Summaries are re-derived**: makespan, utilization and the critical
  path are recomputed from the authenticated schedule on load; a
  persisted summary that disagrees with the schedule refuses (§74/§133).
"""
from __future__ import annotations

import hashlib
from typing import Any

from veritx_dse.wavee.metrics import (
    critical_path as compute_critical_path,
)
from veritx_dse.wavee.metrics import (
    latency_summary, request_latencies, resource_utilization,
)
from veritx_dse.wavee.network import NetworkWindowBinding
from veritx_dse.wavee.scheduler import Schedule
from veritx_dse.wavee.time import QTime
from veritx_dse.wavee.workload import (
    EVENT_NETWORK_OPERATION_REF, WaveETemporalWorkload,
)

RESULT_SCHEMA_VERSION = 1
_GRAPH_TAG = "srota/wavee/event-graph/v1"
_RESULT_TAG = "srota/wavee/performance-result/v1"

# The closed field set of a Wave-E performance result (§75).
RESULT_FIELDS = frozenset({
    "schema_version", "event_graph_id", "performance_model_id",
    "temporal_workload_id", "network_binding", "wave_d_chain",
    "schedule", "makespan", "critical_path", "critical_path_duration",
    "utilization", "request_latencies", "latency_summary",
    "sensitivity", "metrics_warning",
})


class ResultError(Exception):
    code = "INVALID_PERFORMANCE_RESULT"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _content_id(tag: str, body: dict[str, Any]) -> str:
    from veritx_dse.core.spec import canonical_json
    payload = tag + "\0" + canonical_json(body)
    return hashlib.sha256(payload.encode()).hexdigest()


class WaveEEventGraph:
    """Validated temporal workload + model + optional network binding."""

    __slots__ = ("workload", "network_binding", "wave_d_chain", "_id")

    def __init__(self, *, workload: WaveETemporalWorkload,
                 network_binding: NetworkWindowBinding | None = None,
                 wave_d_chain: dict[str, Any] | None = None) -> None:
        object.__setattr__(self, "workload", workload)
        object.__setattr__(self, "network_binding", network_binding)
        object.__setattr__(self, "wave_d_chain",
                           dict(wave_d_chain) if wave_d_chain else None)
        object.__setattr__(self, "_id", None)

    def event_graph_id(self) -> str:
        if self._id is None:
            body: dict[str, Any] = {
                "temporal_workload_id":
                    self.workload.temporal_workload_id(),
                "performance_model_id":
                    self.workload.performance_model.performance_model_id(),
            }
            if self.network_binding is not None:
                body["network_binding"] = self.network_binding.to_dict()
            if self.wave_d_chain is not None:
                body["wave_d_chain"] = self.wave_d_chain
            object.__setattr__(self, "_id",
                               _content_id(_GRAPH_TAG, body))
        return self._id

    def network_durations(self) -> dict[str, QTime] | None:
        """§37/§39: the BARRIER window as NETWORK_OPERATION_REF durations.

        The whole traffic window is ONE barrier event (§39): every
        NETWORK_OPERATION_REF in the workload receives the SAME window
        duration, bound to qualified evidence. Without a bound clock the
        duration stays None and cross-domain wall-time mixing refuses.
        """
        if self.network_binding is None:
            return None
        dur = self.network_binding.duration
        if dur is None:
            return None
        return {e.event_id: dur for e in self.workload.events
                if e.kind == EVENT_NETWORK_OPERATION_REF}


def build_performance_result(*, graph: WaveEEventGraph,
                             schedule: Schedule,
                             sensitivity: dict[str, Any] | None = None,
                             metrics_warning: str | None = None,
                             ) -> dict[str, Any]:
    """Run the scheduler output through metric re-derivation + identity.

    Returns the result document. Summaries are computed HERE from the
    schedule and re-checked on load (§74) — they are never trusted
    input.
    """
    workload = graph.workload
    if len(schedule) != len(workload.events):
        raise ResultError(
            f"schedule covers {len(schedule)} of {len(workload.events)} "
            f"events; refusing to certify an incomplete schedule (§34)")
    path, path_len = compute_critical_path(workload, schedule)
    util = resource_utilization(workload, schedule)
    rows = request_latencies(workload, schedule)
    summary = latency_summary(rows) if rows else None
    makespan = schedule.makespan()
    network_binding_doc = (graph.network_binding.to_dict()
                           if graph.network_binding is not None else None)
    result_id = _content_id(_RESULT_TAG, {
        "event_graph_id": graph.event_graph_id(),
        "performance_model_id":
            workload.performance_model.performance_model_id(),
        "schedule": schedule.to_dict(),
        "makespan": makespan.to_dict(),
        "critical_path": list(path),
    })
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "event_graph_id": graph.event_graph_id(),
        "performance_model_id":
            workload.performance_model.performance_model_id(),
        "temporal_workload_id": workload.temporal_workload_id(),
        "network_binding": network_binding_doc,
        "wave_d_chain": graph.wave_d_chain,
        "schedule": schedule.to_dict(),
        "makespan": makespan.to_dict(),
        "critical_path": list(path),
        "critical_path_duration": path_len.to_dict(),
        "utilization": util,
        "request_latencies": rows,
        "latency_summary": summary,
        "sensitivity": sensitivity,
        "metrics_warning": metrics_warning,
        "resource_id": result_id,
    }


def reverify_result(result_doc: dict[str, Any], *,
                    workload: WaveETemporalWorkload,
                    schedule: Schedule | None = None) -> dict[str, Any]:
    """§74/§133: re-derive summaries and re-check identity on load.

    Rebuilds a Schedule from the persisted rows (or accepts a freshly
    computed one), recomputes makespan / critical path / utilization,
    and refuses ANY mismatch. Also enforces the closed field set.
    """
    unknown = set(result_doc) - RESULT_FIELDS - {"resource_id"}
    if unknown:
        raise ResultError(
            f"unknown performance-result fields {sorted(unknown)}; "
            f"results are schema close (§75)")
    allowed = RESULT_FIELDS | {"resource_id"}
    missing = allowed - set(result_doc)
    if missing:
        raise ResultError(
            f"performance result missing fields {sorted(missing)}")
    if result_doc["schema_version"] != RESULT_SCHEMA_VERSION:
        raise ResultError("schema_version mismatch")
    if schedule is None:
        from veritx_dse.wavee.scheduler import ScheduledEvent
        events = []
        for row in result_doc["schedule"]["events"]:
            bw = row.get("bandwidth_allocated_bps")
            events.append(ScheduledEvent(
                row["event_id"],
                QTime.from_dict(row["start"]),
                QTime.from_dict(row["end"]),
                row.get("resource"),
                bandwidth_allocated_bps=(Fraction(bw["num"], bw["den"])
                                         if bw else None)))
        schedule = Schedule(tuple(events))
    # re-derive every summary from the schedule (§74)
    path, path_len = compute_critical_path(workload, schedule)
    makespan = schedule.makespan()
    checks = (
        ("makespan", result_doc["makespan"], makespan.to_dict()),
        ("critical_path", result_doc["critical_path"], list(path)),
        ("critical_path_duration", result_doc["critical_path_duration"],
         path_len.to_dict()),
    )
    for what, stored, derived in checks:
        if stored != derived:
            raise ResultError(
                f"persisted {what} disagrees with the schedule "
                f"({stored!r} vs {derived!r}); refusing (§74/§133)")
    util = resource_utilization(workload, schedule)
    if result_doc["utilization"] != util:
        raise ResultError(
            "persisted utilization disagrees with the schedule (§74)")
    # identity re-derivation: the document must hash to its own id
    rebuild = dict(result_doc)
    rid = rebuild.pop("resource_id")
    body = {
        "event_graph_id": rebuild["event_graph_id"],
        "performance_model_id": rebuild["performance_model_id"],
        "schedule": rebuild["schedule"],
        "makespan": rebuild["makespan"],
        "critical_path": rebuild["critical_path"],
    }
    if _content_id(_RESULT_TAG, body) != rid:
        raise ResultError(
            "performance_result_id does not match canonical content; "
            "refusing transplanted or tampered results (§73)")
    return result_doc


# Fraction is needed inside reverify_result for bandwidth deserialization
from fractions import Fraction  # noqa: E402
