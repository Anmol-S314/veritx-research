"""veritx_dse.performance.result — EventGraph + PerformanceResult (§65/§66/§74).

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

from typing import Any

from veritx_dse.performance.metrics import (
    dependency_critical_path as compute_critical_path,
)
from veritx_dse.performance.metrics import (
    latency_summary, request_latencies, resource_utilization,
)
from veritx_dse.performance.model import fidelity_warning
from veritx_dse.performance.network import NetworkWindowBinding
from veritx_dse.performance.scheduler import (
    Schedule, ScheduledEvent, schedule_workload,
)
from veritx_dse.core.time import QTime
# The immutability layer is shared with Wave D: one implementation of
# "frozen canonical value tree", not a second copy (AGENTS.md rule).
from veritx_dse.core.artifact import (
    ImmutableError, content_id, freeze, thaw,
)


def _freeze(self, name, value):  # noqa: ANN001
    raise AttributeError(
        f"{type(self).__name__} is immutable (Wave-E §11); construct a "
        f"new instance instead")
from veritx_dse.performance.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW, TemporalWorkload,
)

RESULT_SCHEMA_VERSION = 1
_GRAPH_TAG = "srota/wavee/event-graph/v1"
_RESULT_TAG = "srota/wavee/performance-result/v1"

# The closed field set of a Wave-E performance result (§75).
RESULT_FIELDS = frozenset({
    "schema_version", "event_graph_id", "performance_model_id",
    "temporal_workload_id", "network_binding", "wave_d_chain",
    "schedule", "makespan", "dependency_critical_path",
    "dependency_critical_path_duration", "utilization",
    "request_latencies", "latency_summary", "sensitivity",
    "metrics_warning",
})

# The closed key set of one persisted schedule row.
SCHEDULE_ROW_FIELDS = frozenset({
    "event_id", "start", "end", "resource", "bandwidth_allocated_bps",
    "bytes_moved",
})


class ResultError(Exception):
    code = "INVALID_PERFORMANCE_RESULT"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _content_id(tag: str, body: dict[str, Any]) -> str:
    """Wave-E tags ARE the whole domain, so the id is the bare digest."""
    return content_id(tag, body)


class PerformanceEventGraph:
    """Validated temporal workload + model + optional network binding.

    Transitively immutable, like every other Wave-E/D artifact: the
    Wave-D chain block is copied into a frozen canonical map, so mutating
    the caller's dict (or any nested value) cannot change the graph after
    ``event_graph_id()`` has been observed. A cached identity over
    mutable content is the exact bug class Waves B and D exterminated.
    """

    __slots__ = ("workload", "network_binding", "wave_d_chain", "_id")

    __setattr__ = _freeze

    def __init__(self, *, workload: TemporalWorkload,
                 network_binding: NetworkWindowBinding | None = None,
                 wave_d_chain: dict[str, Any] | None = None) -> None:
        object.__setattr__(self, "workload", workload)
        object.__setattr__(self, "network_binding", network_binding)
        if wave_d_chain:
            try:
                chain = freeze(wave_d_chain)
            except ImmutableError as exc:
                raise ResultError(
                    f"wave_d_chain is not a canonical immutable value: "
                    f"{exc}") from None
        else:
            chain = None
        object.__setattr__(self, "wave_d_chain", chain)
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
                body["wave_d_chain"] = thaw(self.wave_d_chain)
            object.__setattr__(self, "_id",
                               _content_id(_GRAPH_TAG, body))
        return self._id

    def network_durations(self) -> dict[str, QTime] | None:
        """§37/§39: the ONE aggregate window event's duration.

        BookSim exposes a global completion window, so the workload
        declares exactly one NETWORK_TRAFFIC_WINDOW event and it receives
        that window verbatim. Handing the same global duration to several
        network events would multiply or fake-overlap the network
        contribution with no evidence behind it. Without a bound clock the
        duration stays None and cross-domain wall-time mixing refuses.
        """
        if self.network_binding is None:
            return None
        dur = self.network_binding.duration
        if dur is None:
            return None
        return {e.event_id: dur for e in self.workload.events
                if e.kind == EVENT_NETWORK_TRAFFIC_WINDOW}


def build_performance_result(*, graph: PerformanceEventGraph,
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
    # The fidelity classification is DERIVED from the model, never
    # supplied: a producer cannot leave it null (hiding the claim) or
    # forge it (the verifier re-derives the same function).
    metrics_warning = fidelity_warning(workload.performance_model)
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
        "dependency_critical_path": list(path),
    })
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "event_graph_id": graph.event_graph_id(),
        "performance_model_id":
            workload.performance_model.performance_model_id(),
        "temporal_workload_id": workload.temporal_workload_id(),
        "network_binding": network_binding_doc,
        # canonical JSON data, not a frozen container: thaw at the
        # serialization boundary
        "wave_d_chain": (thaw(graph.wave_d_chain)
                         if graph.wave_d_chain is not None else None),
        "schedule": schedule.to_dict(),
        "makespan": makespan.to_dict(),
        # The name says exactly what it is: the longest EXPLICIT
        # dependency chain. Resource-serialization edges (two independent
        # events sharing a capacity-1 resource) are not part of it, so
        # this can be shorter than the makespan and must not be read as
        # the realized schedule critical path.
        "dependency_critical_path": list(path),
        "dependency_critical_path_duration": path_len.to_dict(),
        "utilization": util,
        "request_latencies": rows,
        "latency_summary": summary,
        "sensitivity": sensitivity,
        "metrics_warning": metrics_warning,
        "resource_id": result_id,
    }


def reverify_result(result_doc: dict[str, Any], *,
                    workload: TemporalWorkload) -> dict[str, Any]:
    """§74/§133: re-derive EVERY exposed field and re-check identity.

    The verified workload + model + network binding are the authority:
    the deterministic scheduler is RE-RUN from them, the persisted
    schedule must equal that expected schedule exactly, and only then are
    the summaries re-derived (from the expected schedule). Proving that
    summaries follow *a* schedule is not the same as proving the schedule
    follows the verified parents — a self-consistent re-signed schedule
    must not verify. There is deliberately no caller-supplied schedule
    seam: one schedule for summaries and another for identity is exactly
    the confusion this closes.
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
    # ── the schedule envelope is closed ────────────────────────────
    schedule_doc = result_doc["schedule"]
    if not isinstance(schedule_doc, dict) or \
            set(schedule_doc) != {"events"}:
        raise ResultError(
            "schedule must be an object with exactly the 'events' field")
    # ── parent binding: ids must be the workload's, and the event graph
    #    must reconstruct to the same identity ───────────────────────
    if result_doc["temporal_workload_id"] != workload.temporal_workload_id():
        raise ResultError(
            "temporal_workload_id is not the supplied workload's id")
    model = workload.performance_model
    if result_doc["performance_model_id"] != \
            model.performance_model_id():
        raise ResultError(
            "performance_model_id is not the workload's model id")
    binding_doc = result_doc["network_binding"]
    binding = None
    if binding_doc is not None:
        if not isinstance(binding_doc, dict):
            raise ResultError("network_binding must be an object or null")
        binding = NetworkWindowBinding.from_dict(binding_doc)
    chain_doc = result_doc["wave_d_chain"]
    if chain_doc is not None and not isinstance(chain_doc, dict):
        raise ResultError("wave_d_chain must be an object or null")
    graph = PerformanceEventGraph(workload=workload, network_binding=binding,
                            wave_d_chain=chain_doc)
    if result_doc["event_graph_id"] != graph.event_graph_id():
        raise ResultError(
            "event_graph_id does not reconstruct from the workload, "
            "network binding and Wave-D chain; refusing transplanted "
            "graph provenance")
    window_events = [e.event_id for e in workload.events
                     if e.kind == EVENT_NETWORK_TRAFFIC_WINDOW]
    if binding is not None and not window_events:
        raise ResultError(
            "network_binding present but the workload declares no "
            "NETWORK_TRAFFIC_WINDOW event")
    if binding is None and window_events:
        raise ResultError(
            "workload declares a NETWORK_TRAFFIC_WINDOW event but the "
            "result carries no network binding")
    from veritx_dse.performance.scheduler import (
    Schedule, ScheduledEvent, schedule_workload,
)
    events = []
    for row in schedule_doc["events"]:
        if not isinstance(row, dict) or \
                not {"event_id", "start", "end"} <= set(row):
            raise ResultError(f"malformed schedule row {row!r}")
        unknown = sorted(set(row) - SCHEDULE_ROW_FIELDS)
        if unknown:
            raise ResultError(
                f"schedule row {row.get('event_id')!r} has unknown "
                f"fields {unknown}; the schedule schema is closed")
        bw = row.get("bandwidth_allocated_bps")
        events.append(ScheduledEvent(
            row["event_id"],
            QTime.from_dict(row["start"]),
            QTime.from_dict(row["end"]),
            row.get("resource"),
            bandwidth_allocated_bps=(Fraction(bw["num"], bw["den"])
                                     if bw else None),
            # bytes_moved is identity-bearing for bandwidth utilization;
            # dropping it on load made the re-derived utilization wrong.
            bytes_moved=int(row.get("bytes_moved", 0))))
    persisted_schedule = Schedule(tuple(events))
    # ── the schedule must be what the deterministic scheduler derives
    #    from the VERIFIED parents, not merely self-consistent ───────
    expected_schedule = schedule_workload(
        workload, network_durations=graph.network_durations())
    if persisted_schedule.to_dict() != expected_schedule.to_dict():
        raise ResultError(
            "persisted schedule does not derive from the verified "
            "workload/model/network parents; refusing a schedule that is "
            "internally consistent but not the deterministic one")
    schedule = expected_schedule
    # re-derive every summary from the schedule (§74)
    path, path_len = compute_critical_path(workload, schedule)
    makespan = schedule.makespan()
    checks = (
        ("makespan", result_doc["makespan"], makespan.to_dict()),
        ("dependency_critical_path",
         result_doc["dependency_critical_path"], list(path)),
        ("dependency_critical_path_duration",
         result_doc["dependency_critical_path_duration"],
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
    # ── every remaining exposed field is re-derived too ─────────────
    rows = request_latencies(workload, schedule)
    if result_doc["request_latencies"] != rows:
        raise ResultError(
            "persisted request_latencies disagree with the schedule (§74)")
    summary = latency_summary(rows) if rows else None
    if result_doc["latency_summary"] != summary:
        raise ResultError(
            "persisted latency_summary disagrees with the schedule (§74)")
    if result_doc["metrics_warning"] != fidelity_warning(model):
        raise ResultError(
            "persisted metrics_warning is not the model's fidelity "
            "classification (§64)")
    expected_sensitivity = None
    if result_doc["sensitivity"] is not None:
        from veritx_dse.performance.sensitivity import sensitivity_analysis
        expected_sensitivity = sensitivity_analysis(
            workload, schedule, network_durations=graph.network_durations())
        if result_doc["sensitivity"] != expected_sensitivity:
            raise ResultError(
                "persisted sensitivity does not re-derive from the "
                "verified workload and schedule (§48)")
    # identity re-derivation: the document must hash to its own id
    rebuild = dict(result_doc)
    rid = rebuild.pop("resource_id")
    body = {
        "event_graph_id": rebuild["event_graph_id"],
        "performance_model_id": rebuild["performance_model_id"],
        "schedule": rebuild["schedule"],
        "makespan": rebuild["makespan"],
        "dependency_critical_path": rebuild["dependency_critical_path"],
    }
    if _content_id(_RESULT_TAG, body) != rid:
        raise ResultError(
            "performance_result_id does not match canonical content; "
            "refusing transplanted or tampered results (§73)")
    return result_doc


# Fraction is needed inside reverify_result for bandwidth deserialization
from fractions import Fraction  # noqa: E402
