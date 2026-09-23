"""veritx_dse.performance.workload — temporal overlay + event graph (§14–§17).

Wave E does **not** add COMPUTE/KV timing to sealed Wave-D semantics
(§8). The overlay *references* Wave-D operations by id and declares
local compute/memory events with explicit provenance. The event graph
is the causal object the scheduler consumes:

    temporal_workload_id = H(performance_model_id, canonical events,
                             dependencies, resources, requests)

Event kinds (small vocabulary, §14): COMPUTE, MEMORY_READ, MEMORY_WRITE,
MEMORY_COPY, NETWORK_TRAFFIC_WINDOW, BARRIER.

DAG laws (§17): every dependency references an existing event; no self
edges; acyclic; referenced resources exist in the model; Wave-D
operation references resolve; durations are exact and non-negative.
Repeated steps use explicit ``step`` identities — never graph cycles.
"""
from __future__ import annotations


def _freeze(self, name: str, value: object) -> None:
    raise AttributeError(
        f"{type(self).__name__} is immutable (Wave-E §11); construct a new instance instead")

from fractions import Fraction
from typing import Any

from veritx_dse.performance.model import (
    RESOURCE_KIND_BANDWIDTH, RESOURCE_KIND_EXCLUSIVE,
    PerformanceModel,
)
from veritx_dse.core.time import QTime

SCHEMA_VERSION = 1
_TAG = "srota/wavee/temporal-workload/v1"

EVENT_COMPUTE = "COMPUTE"
EVENT_MEMORY_READ = "MEMORY_READ"
EVENT_MEMORY_WRITE = "MEMORY_WRITE"
EVENT_MEMORY_COPY = "MEMORY_COPY"
# ONE aggregate network event covering the WHOLE Wave-D traffic artifact.
# BookSim exposes a global completion window and no per-message completion
# cycles, so a per-operation network event would be a lie: assigning the
# global window to each of N operations multiplies the network
# contribution N-fold (or invents overlap) with no evidence behind it.
EVENT_NETWORK_TRAFFIC_WINDOW = "NETWORK_TRAFFIC_WINDOW"
EVENT_BARRIER = "BARRIER"
EVENT_KINDS = (EVENT_COMPUTE, EVENT_MEMORY_READ, EVENT_MEMORY_WRITE,
               EVENT_MEMORY_COPY, EVENT_NETWORK_TRAFFIC_WINDOW,
               EVENT_BARRIER)

MEMORY_KINDS = (EVENT_MEMORY_READ, EVENT_MEMORY_WRITE, EVENT_MEMORY_COPY)
# Retained as a NAME ONLY so a persisted v1 document refuses with a clear
# message instead of "unknown kind".
EVENT_NETWORK_OPERATION_REF = "NETWORK_OPERATION_REF"


class WorkloadError(Exception):
    """Typed refusal for invalid temporal workloads (§17/§127)."""

    code = "INVALID_TEMPORAL_WORKLOAD"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PerformanceRequest:
    """Explicit request grouping (§52). Never inferred from packets.

    ``request_id`` is the identity the scheduler keys release times by, so
    it must be unique within a workload. Root/completion/first-token
    events must be owned by this request or unowned — one ownership
    policy for all three.
    """

    __slots__ = ("request_id", "arrival", "root_event_ids",
                 "completion_event_ids", "first_token_event_id")

    __setattr__ = _freeze

    def __init__(self, request_id: str, arrival: QTime, *,
                 root_event_ids: tuple[str, ...] = (),
                 completion_event_ids: tuple[str, ...] = (),
                 first_token_event_id: str | None = None) -> None:
        if not isinstance(request_id, str) or not request_id:
            raise WorkloadError("request_id must be a non-empty string")
        if not isinstance(arrival, QTime):
            raise WorkloadError("arrival must be QTime")
        for fld, v in (("root_event_ids", root_event_ids),
                       ("completion_event_ids", completion_event_ids)):
            if not isinstance(v, tuple) or \
                    not all(isinstance(x, str) and x for x in v):
                raise WorkloadError(f"{fld} must be tuple of non-empty strs")
        if first_token_event_id is not None and \
                (not isinstance(first_token_event_id, str) or
                 not first_token_event_id):
            raise WorkloadError("first_token_event_id must be None or str")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "arrival", arrival)
        object.__setattr__(self, "root_event_ids", tuple(root_event_ids))
        object.__setattr__(self, "completion_event_ids",
                           tuple(completion_event_ids))
        object.__setattr__(self, "first_token_event_id",
                           first_token_event_id)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "request_id": self.request_id,
            "arrival": self.arrival.to_dict(),
            "root_event_ids": list(self.root_event_ids),
            "completion_event_ids": list(self.completion_event_ids),
        }
        if self.first_token_event_id is not None:
            d["first_token_event_id"] = self.first_token_event_id
        return d

    @staticmethod
    def from_dict(d: Any) -> "PerformanceRequest":
        required = {"request_id", "arrival", "root_event_ids",
                    "completion_event_ids"}
        allowed = required | {"first_token_event_id"}
        if not isinstance(d, dict) or not required <= set(d):
            raise WorkloadError(f"request dict malformed: {d!r}")
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise WorkloadError(
                f"request has unknown fields {unknown}; the request schema "
                f"is closed")
        return PerformanceRequest(
            request_id=d["request_id"], arrival=QTime.from_dict(d["arrival"]),
            root_event_ids=tuple(d["root_event_ids"]),
            completion_event_ids=tuple(d["completion_event_ids"]),
            first_token_event_id=d.get("first_token_event_id"))


class TemporalEvent:
    """One local/communication event with provenance (§15)."""

    __slots__ = ("event_id", "kind", "duration", "resource", "deps",
                 "phase", "rank", "step", "request_id", "wave_d_operation_id",
                 "bytes_count", "is_first_token")

    __setattr__ = _freeze

    def __init__(self, event_id: str, kind: str, duration: QTime,
                 resource: str | None = None, *, deps: tuple[str, ...] = (),
                 phase: str | None = None, rank: int | None = None,
                 step: int | None = None, request_id: str | None = None,
                 wave_d_operation_id: str | None = None,
                 bytes_count: int | None = None,
                 is_first_token: bool = False) -> None:
        if not isinstance(event_id, str) or not event_id:
            raise WorkloadError("event_id must be a non-empty string")
        if kind == EVENT_NETWORK_OPERATION_REF:
            raise WorkloadError(
                "NETWORK_OPERATION_REF is UNSUPPORTED: BookSim exposes a "
                "global completion window, not per-operation completion "
                "cycles, so per-operation network timing cannot be "
                "justified. Declare ONE NETWORK_TRAFFIC_WINDOW event "
                "covering the whole traffic artifact instead.")
        if kind not in EVENT_KINDS:
            raise WorkloadError(
                f"kind must be one of {EVENT_KINDS}, got {kind!r}")
        if not isinstance(duration, QTime):
            raise WorkloadError("duration must be QTime (exact)")
        if duration < QTime.zero():
            raise WorkloadError(f"duration must be >= 0, got {duration}")
        if kind == EVENT_BARRIER and duration != QTime.zero():
            raise WorkloadError("BARRIER events have zero duration")
        if kind == EVENT_NETWORK_TRAFFIC_WINDOW:
            if duration != QTime.zero():
                raise WorkloadError(
                    "NETWORK_TRAFFIC_WINDOW declares duration 0; its real "
                    "duration comes ONLY from the evidence-bound window "
                    "(a declared duration here would be inert and "
                    "misleading)")
            if resource is not None:
                raise WorkloadError(
                    "NETWORK_TRAFFIC_WINDOW does not claim a local "
                    "resource")
            if wave_d_operation_id is not None:
                raise WorkloadError(
                    "NETWORK_TRAFFIC_WINDOW covers the WHOLE traffic "
                    "artifact, not one operation; it must not cite a "
                    "Wave-D operation id (§42)")
            if bytes_count is not None:
                raise WorkloadError(
                    "NETWORK_TRAFFIC_WINDOW does not carry bytes_count; "
                    "its time comes from the evidence-bound window")
        else:
            if resource is None:
                raise WorkloadError(
                    f"{kind} event requires a resource (§14)")
            if kind in MEMORY_KINDS:
                if not isinstance(bytes_count, int) or bytes_count < 0:
                    raise WorkloadError(
                        "memory events require int bytes_count >= 0")
            elif bytes_count is not None:
                # A byte count on a compute/barrier event would look
                # like modeled memory traffic and is never consumed.
                raise WorkloadError(
                    f"{kind} events do not carry bytes_count (only "
                    f"{MEMORY_KINDS} do); refusing a field that would "
                    f"silently do nothing")
        if rank is not None and (isinstance(rank, bool) or
                                 not isinstance(rank, int) or rank < 0):
            raise WorkloadError("rank must be None or int >= 0")
        if step is not None and (isinstance(step, bool) or
                                 not isinstance(step, int) or step < 0):
            raise WorkloadError("step must be None or int >= 0")
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "duration", duration)
        object.__setattr__(self, "resource", resource)
        object.__setattr__(self, "deps", tuple(deps))
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "rank", rank)
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "wave_d_operation_id",
                           wave_d_operation_id)
        object.__setattr__(self, "bytes_count", bytes_count)
        object.__setattr__(self, "is_first_token", bool(is_first_token)
                           and kind != EVENT_NETWORK_TRAFFIC_WINDOW)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event_id": self.event_id, "kind": self.kind,
            "duration": self.duration.to_dict(),
            "deps": list(self.deps),
        }
        for k in ("resource", "phase", "rank", "step", "request_id",
                  "wave_d_operation_id", "bytes_count"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.is_first_token:
            d["is_first_token"] = True
        return d

    @staticmethod
    def from_dict(d: Any) -> "TemporalEvent":
        required = {"event_id", "kind", "duration", "deps"}
        allowed = required | {"resource", "phase", "rank", "step",
                              "request_id", "wave_d_operation_id",
                              "bytes_count", "is_first_token"}
        if not isinstance(d, dict) or not required <= set(d):
            raise WorkloadError(f"event dict malformed: {d!r}")
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise WorkloadError(
                f"event {d.get('event_id')!r} has unknown fields {unknown}; "
                f"the event schema is closed")
        return TemporalEvent(
            event_id=d["event_id"], kind=d["kind"],
            duration=QTime.from_dict(d["duration"]),
            resource=d.get("resource"), deps=tuple(d["deps"]),
            phase=d.get("phase"), rank=d.get("rank"), step=d.get("step"),
            request_id=d.get("request_id"),
            wave_d_operation_id=d.get("wave_d_operation_id"),
            bytes_count=d.get("bytes_count"),
            is_first_token=bool(d.get("is_first_token", False)))


def canonical_events(events: tuple[TemporalEvent, ...]
                     ) -> tuple[TemporalEvent, ...]:
    """Semantic canonical order: (rank, step, event_id).

    Declaration order is nonsemantic (§77): identity and scheduling
    derive from this canonical order, so permuting the input list is
    identity-preserving. Ties are impossible (event ids unique).
    """
    return tuple(sorted(events, key=lambda e: (e.rank if e.rank is not None
                                               else -1,
                                               e.step if e.step is not None
                                               else -1,
                                               e.event_id)))


class TemporalWorkload:
    """Immutable event graph + explicit requests, bound to a model."""

    __slots__ = ("performance_model", "events", "requests", "_id",
                 "_wave_d_operation_ids")

    __setattr__ = _freeze

    def __init__(self, *, performance_model: PerformanceModel,
                 events: tuple[TemporalEvent, ...],
                 requests: tuple[PerformanceRequest, ...] = (),
                 wave_d_operation_ids: tuple[str, ...] = ()) -> None:
        if not isinstance(performance_model, PerformanceModel):
            raise WorkloadError("performance_model required")
        if not events:
            # A temporal overlay with nothing to schedule would report a
            # zero makespan that means nothing; refuse it.
            raise WorkloadError(
                "a temporal workload must declare at least one event")
        ids = [e.event_id for e in events]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise WorkloadError(f"duplicate event_ids: {dupes}")
        windows = [e.event_id for e in events
                   if e.kind == EVENT_NETWORK_TRAFFIC_WINDOW]
        if len(windows) > 1:
            raise WorkloadError(
                f"a workload declares at most ONE "
                f"NETWORK_TRAFFIC_WINDOW event (got {sorted(windows)}): "
                f"the global BookSim window cannot be split across "
                f"events")
        req_ids = [r.request_id for r in requests]
        if len(req_ids) != len(set(req_ids)):
            dupes = sorted({i for i in req_ids if req_ids.count(i) > 1})
            raise WorkloadError(
                f"duplicate request_ids {dupes}: the scheduler keys "
                f"release times by request id, so it must be unique")
        object.__setattr__(self, "performance_model", performance_model)
        object.__setattr__(self, "events",
                           canonical_events(tuple(events)))
        object.__setattr__(self, "requests", tuple(requests))
        object.__setattr__(self, "_id", None)
        object.__setattr__(self, "_wave_d_operation_ids",
                           tuple(wave_d_operation_ids))
        self._validate()

    # ── graph laws (§17) ────────────────────────────────────────
    def _validate(self) -> None:
        by_id = {e.event_id: e for e in self.events}
        model = self.performance_model
        req_ids = {r.request_id for r in self.requests}
        declared = set(self._wave_d_operation_ids)
        for e in self.events:
            for dep in e.deps:
                if dep not in by_id:
                    raise WorkloadError(
                        f"event {e.event_id!r} depends on missing event "
                        f"{dep!r}")
                if dep == e.event_id:
                    raise WorkloadError(
                        f"event {e.event_id!r} depends on itself")
            if e.resource is not None:
                try:
                    rdef = model.resource(e.resource)
                except Exception as exc:
                    raise WorkloadError(
                        f"event {e.event_id!r} references unknown resource "
                        f"{e.resource!r}: {exc}") from exc
                if e.kind in MEMORY_KINDS:
                    # The declared memory authority must MATCH what the
                    # scheduler will actually do, or the model would carry
                    # false provenance: a declared duration silently
                    # overridden by the shared rate law (or vice versa).
                    noop = (e.bytes_count == 0
                            and e.duration == QTime.zero())
                    if not noop:
                        if model.memory_source == "ANALYTICAL_BANDWIDTH":
                            if rdef.kind != "BANDWIDTH":
                                raise WorkloadError(
                                    f"memory event {e.event_id!r} is bound "
                                    f"to {rdef.kind} resource "
                                    f"{e.resource!r} but the model declares "
                                    f"memory_source=ANALYTICAL_BANDWIDTH; "
                                    f"the rate law needs a BANDWIDTH "
                                    f"resource")
                            if not e.bytes_count:
                                raise WorkloadError(
                                    f"memory event {e.event_id!r} declares "
                                    f"ANALYTICAL_BANDWIDTH timing with no "
                                    f"bytes to derive it from")
                            if e.duration != QTime.zero():
                                raise WorkloadError(
                                    f"memory event {e.event_id!r} declares "
                                    f"duration {e.duration} but the model "
                                    f"derives its time from the shared "
                                    f"rate law; the declared duration must "
                                    f"be 0 (two authorities cannot own one "
                                    f"duration)")
                        else:  # EXPLICIT_DURATION
                            if rdef.kind == "BANDWIDTH" and e.bytes_count:
                                raise WorkloadError(
                                    f"memory event {e.event_id!r} declares "
                                    f"EXPLICIT_DURATION but is bound to "
                                    f"BANDWIDTH resource {e.resource!r} "
                                    f"with {e.bytes_count} bytes: the "
                                    f"fluid scheduler would override the "
                                    f"declared duration. Declare "
                                    f"memory_source=ANALYTICAL_BANDWIDTH "
                                    f"or use an EXCLUSIVE resource")
            if e.request_id is not None and e.request_id not in req_ids:
                raise WorkloadError(
                    f"event {e.event_id!r} references unknown request "
                    f"{e.request_id!r}")
        # acyclicity via iterative DFS (§17: no cycles to encode loops)
        color: dict[str, int] = {e.event_id: 0 for e in self.events}
        for e in self.events:
            if color[e.event_id]:
                continue
            stack: list[tuple[str, tuple[str, ...], int]] = \
                [(e.event_id, by_id[e.event_id].deps, 0)]
            color[e.event_id] = 1
            while stack:
                node, deps, idx = stack[-1]
                if idx < len(deps):
                    stack[-1] = (node, deps, idx + 1)
                    d = deps[idx]
                    if color[d] == 1:
                        raise WorkloadError(
                            f"event graph has a cycle through {d!r} (§17)")
                    if color[d] == 0:
                        color[d] = 1
                        stack.append((d, by_id[d].deps, 0))
                else:
                    color[node] = 2
                    stack.pop()
        # request boundary validation (§52/§56)
        for r in self.requests:
            for rid in r.root_event_ids + r.completion_event_ids + \
                    ((r.first_token_event_id,) if
                     r.first_token_event_id else ()):
                if rid not in by_id:
                    raise WorkloadError(
                        f"request {r.request_id!r} references missing event "
                        f"{rid!r}")
            for rid in r.root_event_ids + r.completion_event_ids + \
                    ((r.first_token_event_id,)
                     if r.first_token_event_id else ()):
                ev = by_id[rid]
                if ev.request_id not in (None, r.request_id):
                    raise WorkloadError(
                        f"request {r.request_id!r} binds event {rid!r} "
                        f"already owned by request {ev.request_id!r}")
        # wave_d provenance check (§15): any event that cites a Wave-D
        # operation id must cite one from the declared set
        if declared:
            for e in self.events:
                if e.wave_d_operation_id is not None and \
                        e.wave_d_operation_id not in declared:
                    raise WorkloadError(
                        f"event {e.event_id!r} cites Wave-D operation "
                        f"{e.wave_d_operation_id!r} not in the declared "
                        f"set")

    # ── identity ────────────────────────────────────────────────
    def canonical(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            # Full model CONTENT, not just the id: content-addressing
            # makes the parent binding mechanical (content determines
            # performance_model_id) and to_dict/from_dict an exact
            # roundtrip — a persisted workload re-verifies on load.
            "performance_model": self.performance_model.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "requests": [r.to_dict() for r in self.requests],
            "wave_d_operation_ids": list(self._wave_d_operation_ids),
        }

    def temporal_workload_id(self) -> str:
        if self._id is None:
            import hashlib
            from veritx_dse.core.spec import canonical_json
            body = _TAG + "\0" + canonical_json(self.canonical())
            object.__setattr__(self, "_id",
                               hashlib.sha256(body.encode()).hexdigest())
        return self._id

    def declared_wave_d_operation_ids(self) -> tuple[str, ...]:
        """The Wave-D operation ids this overlay claims to schedule."""
        return self._wave_d_operation_ids

    def event(self, event_id: str) -> TemporalEvent:
        for e in self.events:
            if e.event_id == event_id:
                return e
        raise WorkloadError(f"unknown event {event_id!r}")

    # ── serialization ───────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return self.canonical()

    @staticmethod
    def from_dict(d: Any) -> "TemporalWorkload":
        if not isinstance(d, dict):
            raise WorkloadError("temporal workload must be a dict")
        allowed = {"schema_version", "performance_model", "events",
                   "requests", "wave_d_operation_ids"}
        if set(d) != allowed:
            raise WorkloadError(
                f"temporal workload fields must be exactly {sorted(allowed)}, "
                f"got {sorted(d)}")
        if d["schema_version"] != SCHEMA_VERSION:
            raise WorkloadError(f"schema_version must be {SCHEMA_VERSION}")
        model = PerformanceModel.from_dict(d["performance_model"])
        events = tuple(TemporalEvent.from_dict(e) for e in d["events"])
        requests = tuple(PerformanceRequest.from_dict(r) for r in d["requests"])
        return TemporalWorkload(
            performance_model=model, events=events, requests=requests,
            wave_d_operation_ids=tuple(d["wave_d_operation_ids"]))
