"""veritx_dse.wavee.workload — temporal overlay + event graph (§14–§17).

Wave E does **not** add COMPUTE/KV timing to sealed Wave-D semantics
(§8). The overlay *references* Wave-D operations by id and declares
local compute/memory events with explicit provenance. The event graph
is the causal object the scheduler consumes:

    temporal_workload_id = H(performance_model_id, canonical events,
                             dependencies, resources, requests)

Event kinds (small vocabulary, §14): COMPUTE, MEMORY_READ, MEMORY_WRITE,
MEMORY_COPY, NETWORK_OPERATION_REF, BARRIER.

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

from veritx_dse.wavee.model import (
    RESOURCE_KIND_BANDWIDTH, RESOURCE_KIND_EXCLUSIVE,
    WaveEPerformanceModel,
)
from veritx_dse.wavee.time import QTime

SCHEMA_VERSION = 1
_TAG = "srota/wavee/temporal-workload/v1"

EVENT_COMPUTE = "COMPUTE"
EVENT_MEMORY_READ = "MEMORY_READ"
EVENT_MEMORY_WRITE = "MEMORY_WRITE"
EVENT_MEMORY_COPY = "MEMORY_COPY"
EVENT_NETWORK_OPERATION_REF = "NETWORK_OPERATION_REF"
EVENT_BARRIER = "BARRIER"
EVENT_KINDS = (EVENT_COMPUTE, EVENT_MEMORY_READ, EVENT_MEMORY_WRITE,
               EVENT_MEMORY_COPY, EVENT_NETWORK_OPERATION_REF, EVENT_BARRIER)

MEMORY_KINDS = (EVENT_MEMORY_READ, EVENT_MEMORY_WRITE, EVENT_MEMORY_COPY)


class WorkloadError(Exception):
    """Typed refusal for invalid temporal workloads (§17/§127)."""

    code = "INVALID_TEMPORAL_WORKLOAD"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class WaveERequest:
    """Explicit request grouping (§52). Never inferred from packets."""

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
    def from_dict(d: Any) -> "WaveERequest":
        if not isinstance(d, dict) or \
                not {"request_id", "arrival", "root_event_ids",
                     "completion_event_ids"} <= set(d):
            raise WorkloadError(f"request dict malformed: {d!r}")
        return WaveERequest(
            request_id=d["request_id"], arrival=QTime.from_dict(d["arrival"]),
            root_event_ids=tuple(d["root_event_ids"]),
            completion_event_ids=tuple(d["completion_event_ids"]),
            first_token_event_id=d.get("first_token_event_id"))


class WaveETemporalEvent:
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
        if kind not in EVENT_KINDS:
            raise WorkloadError(
                f"kind must be one of {EVENT_KINDS}, got {kind!r}")
        if not isinstance(duration, QTime):
            raise WorkloadError("duration must be QTime (exact)")
        if duration < QTime.zero():
            raise WorkloadError(f"duration must be >= 0, got {duration}")
        if kind == EVENT_BARRIER and duration != QTime.zero():
            raise WorkloadError("BARRIER events have zero duration")
        if kind == EVENT_NETWORK_OPERATION_REF:
            if resource is not None:
                raise WorkloadError(
                    "NETWORK_OPERATION_REF does not claim a local resource")
            if wave_d_operation_id is None:
                raise WorkloadError(
                    "NETWORK_OPERATION_REF requires wave_d_operation_id "
                    "provenance (§15)")
        else:
            if resource is None:
                raise WorkloadError(
                    f"{kind} event requires a resource (§14)")
            if kind in MEMORY_KINDS:
                if not isinstance(bytes_count, int) or bytes_count < 0:
                    raise WorkloadError(
                        "memory events require int bytes_count >= 0")
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
                           and kind != EVENT_NETWORK_OPERATION_REF)

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
    def from_dict(d: Any) -> "WaveETemporalEvent":
        if not isinstance(d, dict) or \
                not {"event_id", "kind", "duration", "deps"} <= set(d):
            raise WorkloadError(f"event dict malformed: {d!r}")
        return WaveETemporalEvent(
            event_id=d["event_id"], kind=d["kind"],
            duration=QTime.from_dict(d["duration"]),
            resource=d.get("resource"), deps=tuple(d["deps"]),
            phase=d.get("phase"), rank=d.get("rank"), step=d.get("step"),
            request_id=d.get("request_id"),
            wave_d_operation_id=d.get("wave_d_operation_id"),
            bytes_count=d.get("bytes_count"),
            is_first_token=bool(d.get("is_first_token", False)))


def canonical_events(events: tuple[WaveETemporalEvent, ...]
                     ) -> tuple[WaveETemporalEvent, ...]:
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


class WaveETemporalWorkload:
    """Immutable event graph + explicit requests, bound to a model."""

    __slots__ = ("performance_model", "events", "requests", "_id",
                 "_wave_d_operation_ids")

    __setattr__ = _freeze

    def __init__(self, *, performance_model: WaveEPerformanceModel,
                 events: tuple[WaveETemporalEvent, ...],
                 requests: tuple[WaveERequest, ...] = (),
                 wave_d_operation_ids: tuple[str, ...] = ()) -> None:
        if not isinstance(performance_model, WaveEPerformanceModel):
            raise WorkloadError("performance_model required")
        ids = [e.event_id for e in events]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise WorkloadError(f"duplicate event_ids: {dupes}")
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
                    model.resource(e.resource)
                except Exception as exc:
                    raise WorkloadError(
                        f"event {e.event_id!r} references unknown resource "
                        f"{e.resource!r}: {exc}") from exc
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
            for rid in r.root_event_ids + r.completion_event_ids:
                ev = by_id[rid]
                if ev.request_id not in (None, r.request_id):
                    raise WorkloadError(
                        f"request {r.request_id!r} binds event {rid!r} "
                        f"already owned by request {ev.request_id!r}")
        # wave_d provenance check (§15): every NETWORK_OPERATION_REF
        # must cite a declared Wave-D operation id
        if declared:
            for e in self.events:
                if e.wave_d_operation_id is not None and \
                        e.wave_d_operation_id not in declared and \
                        e.kind == EVENT_NETWORK_OPERATION_REF:
                    raise WorkloadError(
                        f"event {e.event_id!r} cites Wave-D operation "
                        f"{e.wave_d_operation_id!r} not in the declared set")

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

    def event(self, event_id: str) -> WaveETemporalEvent:
        for e in self.events:
            if e.event_id == event_id:
                return e
        raise WorkloadError(f"unknown event {event_id!r}")

    # ── serialization ───────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return self.canonical()

    @staticmethod
    def from_dict(d: Any) -> "WaveETemporalWorkload":
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
        model = WaveEPerformanceModel.from_dict(d["performance_model"])
        events = tuple(WaveETemporalEvent.from_dict(e) for e in d["events"])
        requests = tuple(WaveERequest.from_dict(r) for r in d["requests"])
        return WaveETemporalWorkload(
            performance_model=model, events=events, requests=requests,
            wave_d_operation_ids=tuple(d["wave_d_operation_ids"]))
