"""Reusable execution kernel: event ordering, resource ownership, identity.

This module is the Phase-1 shared substrate for every future execution
capability (multiplane, coherence, faults, migration, IP instances, power).
It is a PURE ADDITIVE LAYER over ``application/data_movement.py``'s existing
event heap: the heap tuple shape ``(time, priority, serial, payload)``, the
serial counter's start value and the push order are byte-for-byte what the
historical inline ``heapq`` code produced, so evidence artifacts recomputed
through this kernel are unchanged.

What lives here (and nowhere else, so no feature grows its own copy):

1. ``EventPriority`` — the named, deterministic ordering rules for events at
   the same simulated time, including the reserved ranks that Phase-4/7
   features (timeout, cancellation, retry, fault injection) must use instead
   of inventing priorities.
2. ``EventQueue`` — exact-time (``Fraction``) deterministic event heap.
3. ``ResourceRegistry`` — one authoritative owner per contended resource:
   explicit capacity, per-lane free time, reservation guard (no double
   allocation), occupancy and queue (waiting) state. Replaces the ad-hoc
   ``lane_free[key] = t`` dict while remaining dict-readable (``.values()``)
   for the coupled runtime and for other sessions' callers that still pass a
   plain dict.
4. ``TransactionIdentity`` / ``IdentityRegistry`` — stable logical transaction
   identity, per-attempt identity, execution epoch, resource ownership and
   lifecycle state, shared by every future feature so retries, dedup,
   migration and cancellation all speak one identity system.

Deliberate boundary: this kernel models scheduling bookkeeping only. It makes
no timing, coherence, power or network claim of its own, and nothing here is
written into evidence artifacts (evidence stays owned by
``data_movement.DataMovementEvidence`` / ``coupled_tensor.CoupledTensorEvidence``).

Event-ordering rules (Phase-1 contract, tested in
``tests/test_execution_kernel.py``):

* Events compare by ``(exact time, priority rank, insertion serial)``.
* Lower priority rank executes first at equal simulated time; equal rank
  executes in insertion order (FIFO).
* ``PHASE_COMPLETION`` (0) precedes ``ADMISSION`` (1): a response/resource
  release that lands exactly on an issue edge or a deadline is observed
  before the competing event. Concretely, when a response and a timeout are
  scheduled for the same instant, the response (rank 0) is processed first
  and the timeout (rank 3) must re-check transaction state and suppress
  itself — a committed transaction never times out at its own response edge.
* Ranks 2..6 are reserved for state transitions, timeouts, cancellation,
  retries and fault injection respectively. V1 execution emits only ranks 0
  and 1; any future code that pushes a reserved rank must use these constants
  rather than a literal, so the ordering rules stay testable in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from fractions import Fraction
import heapq
from typing import Any, Iterable

from veritx_dse.core.errors import EvidenceInvalid, InvalidInput


class EventPriority(IntEnum):
    """Deterministic same-time ordering; lower rank executes first.

    V1 emits PHASE_COMPLETION and ADMISSION only. The remaining ranks are
    reserved so later phases extend the same ordering instead of inventing
    ad-hoc numeric priorities (which would silently reorder existing
    executions).
    """

    PHASE_COMPLETION = 0   # phase arrival/completion; releases resources
    ADMISSION = 1          # transaction issue and runtime dispatch (FIFO ties)
    STATE_TRANSITION = 2   # reserved: scheduled state transitions (Phase 7)
    TIMEOUT = 3            # reserved: transaction timeouts (Phase 4)
    CANCELLATION = 4       # reserved: cancellation events (Phase 4)
    RETRY = 5              # reserved: automatic retry scheduling (Phase 4)
    FAULT_INJECTION = 6    # reserved: fault controller events (Phase 4)


_KNOWN_PRIORITIES = frozenset(int(p) for p in EventPriority)


class EventQueue:
    """Exact-time deterministic event heap.

    Tuple shape ``(time, priority, serial, payload)`` matches the historical
    inline heap in ``data_movement.execute_data_movement`` exactly (serial
    starts at 1 and increments per push), so event order is bit-identical.
    """

    def __init__(self) -> None:
        self.events: list[tuple[Fraction, int, int, Any]] = []
        self._serial = 0

    def push(self, time: Fraction, priority: int, payload: Any) -> None:
        if not isinstance(time, Fraction):
            raise InvalidInput(
                f"event time must be an exact Fraction, got {type(time).__name__}")
        if int(priority) not in _KNOWN_PRIORITIES:
            raise InvalidInput(
                f"unknown event priority {priority!r}; known ranks: "
                f"{[(p.name, int(p)) for p in EventPriority]}")
        self._serial += 1
        heapq.heappush(self.events, (time, int(priority), self._serial, payload))

    def pop(self) -> tuple[Fraction, int, int, Any]:
        return heapq.heappop(self.events)

    def requeue(self, entry: tuple[Fraction, int, int, Any]) -> None:
        """Put back an already-popped entry (horizon pause), order preserved."""
        heapq.heappush(self.events, entry)

    @property
    def serial(self) -> int:
        """How many events have ever been pushed (stable replay identity)."""
        return self._serial

    def earliest(self) -> Fraction | None:
        return self.events[0][0] if self.events else None

    def __bool__(self) -> bool:
        return bool(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)


@dataclass(frozen=True)
class ResourceReservation:
    """One authoritative occupancy record on a contended resource."""

    key: tuple
    arrival: Fraction
    start: Fraction
    end: Fraction
    owner: str | None = None


class ResourceLane:
    """A single contended resource with explicit capacity and queue state.

    ``free_at`` is the exact time the next reservation may start — the same
    semantics the historical ``lane_free[key]`` dict carried, now guarded and
    observable. ``service_time`` is optional declared per-use service-cost
    metadata (reserved for IP-instance / plane declarations); the engine
    computes real durations exactly as before.
    """

    def __init__(self, key: tuple, *, capacity: int = 1,
                 service_time: Fraction | None = None) -> None:
        if type(capacity) is not int or capacity < 1:
            raise InvalidInput(f"lane {key!r} capacity must be an int >= 1")
        self.key = key
        self.capacity = capacity
        self.service_time = service_time
        self._slot_free = [Fraction(0)] * capacity
        self.reservations: list[ResourceReservation] = []
        self._busy_ends: list[Fraction] = []  # min-heap of live end times
        self.peak_occupancy = 0
        self.wait_count = 0
        self.total_wait = Fraction(0)
        self._last_start: Fraction | None = None

    def free_at(self) -> Fraction:
        """Earliest time any slot is free (dict ``.get(key, 0)`` equivalent)."""
        return min(self._slot_free)

    def reserve(self, *, arrival: Fraction, start: Fraction, end: Fraction,
                free_at: Fraction | None = None,
                owner: str | None = None) -> ResourceReservation:
        if start < arrival:
            raise EvidenceInvalid(
                f"resource {self.key!r} reservation starts at {start} before "
                f"its arrival {arrival}")
        if self._last_start is not None and start < self._last_start:
            raise EvidenceInvalid(
                f"resource {self.key!r} accepted an out-of-order reservation: "
                f"start {start} precedes the previous reservation's start "
                f"{self._last_start}")
        slot = min(range(self.capacity), key=lambda i: self._slot_free[i])
        if start < self._slot_free[slot]:
            raise EvidenceInvalid(
                f"resource double allocation on {self.key!r}: requested start "
                f"{start} precedes the lane's free time {self._slot_free[slot]}")
        if end < start:
            raise EvidenceInvalid(
                f"resource {self.key!r} reservation ends before it starts")
        if start > arrival:
            self.wait_count += 1
            self.total_wait += start - arrival
        # Occupancy sweep: starts are nondecreasing, so popping finished
        # intervals is exact; everything left started at or before `start`
        # and ends after `start`, i.e. genuinely overlaps this reservation.
        while self._busy_ends and self._busy_ends[0] <= start:
            heapq.heappop(self._busy_ends)
        heapq.heappush(self._busy_ends, end)
        self.peak_occupancy = max(self.peak_occupancy, len(self._busy_ends))
        self._slot_free[slot] = free_at if free_at is not None else end
        self._last_start = start
        reservation = ResourceReservation(self.key, arrival, start, end, owner)
        self.reservations.append(reservation)
        return reservation

    def active_at(self, when: Fraction) -> int:
        return sum(1 for r in self.reservations if r.start <= when < r.end)

    def assert_invariants(self) -> None:
        if len(self._slot_free) != self.capacity:
            raise EvidenceInvalid(f"lane {self.key!r} capacity drifted")
        if any(slot_free < 0 for slot_free in self._slot_free):
            raise EvidenceInvalid(f"lane {self.key!r} has negative free time")
        if self.peak_occupancy > self.capacity:
            raise EvidenceInvalid(
                f"lane {self.key!r} peak occupancy {self.peak_occupancy} "
                f"exceeds capacity {self.capacity}")
        if self.wait_count < 0 or self.total_wait < 0:
            raise EvidenceInvalid(f"lane {self.key!r} queue state drifted")
        previous: ResourceReservation | None = None
        for reservation in self.reservations:
            if previous is not None and reservation.start < previous.start:
                raise EvidenceInvalid(
                    f"lane {self.key!r} accepted out-of-order reservations")
            if reservation.owner is None:
                raise EvidenceInvalid(
                    f"lane {self.key!r} recorded a reservation without an "
                    f"authoritative owner")
            previous = reservation


class ResourceRegistry:
    """One authoritative owner per contended resource.

    Two subsystems must never allocate the same physical resource; every
    allocation goes through :meth:`reserve`, which refuses overlap. Lanes are
    declared explicitly when the engine knows them (channels, endpoints,
    crossings, engines) and auto-created at capacity 1 for backward
    compatibility with historical ``lane_free.get(key, 0)`` access.

    The registry is dict-readable (``.values()`` yields each lane's free
    time) so the coupled runtime's ``max(lane_free.values())`` drain check
    and any external caller passing a plain dict keep working unchanged.
    """

    def __init__(self) -> None:
        self._lanes: dict[tuple, ResourceLane] = {}

    def declare(self, key: tuple, *, capacity: int = 1,
                service_time: Fraction | None = None) -> ResourceLane:
        existing = self._lanes.get(key)
        if existing is not None:
            if existing.capacity != capacity:
                raise InvalidInput(
                    f"resource {key!r} already registered with capacity "
                    f"{existing.capacity}, cannot redeclare as {capacity}")
            return existing
        lane = ResourceLane(key, capacity=capacity, service_time=service_time)
        self._lanes[key] = lane
        return lane

    def lane(self, key: tuple) -> ResourceLane:
        return self._lanes.get(key) or self.declare(key)

    def free_at(self, key: tuple) -> Fraction:
        return self.lane(key).free_at()

    def reserve(self, key: tuple, *, arrival: Fraction, start: Fraction,
                end: Fraction, free_at: Fraction | None = None,
                owner: str | None = None) -> ResourceReservation:
        return self.lane(key).reserve(
            arrival=arrival, start=start, end=end, free_at=free_at, owner=owner)

    def active_at(self, key: tuple, when: Fraction) -> int:
        lane = self._lanes.get(key)
        return 0 if lane is None else lane.active_at(when)

    def queue_state(self, key: tuple) -> tuple[int, Fraction]:
        """(reservations that waited, cumulative waiting time) for a lane."""
        lane = self._lanes.get(key)
        if lane is None:
            return 0, Fraction(0)
        return lane.wait_count, lane.total_wait

    def values(self) -> Iterable[Fraction]:
        """Free times per declared lane — dict-compatible read surface."""
        return (lane.free_at() for lane in self._lanes.values())

    def keys(self):
        return self._lanes.keys()

    def __contains__(self, key) -> bool:
        return key in self._lanes

    def __len__(self) -> int:
        return len(self._lanes)

    def snapshot(self) -> dict:
        """Evidence-free introspection for tests and future tracing."""
        return {repr(key): {
            "capacity": lane.capacity,
            "free_at": lane.free_at(),
            "reservations": len(lane.reservations),
            "peak_occupancy": lane.peak_occupancy,
            "wait_count": lane.wait_count,
            "total_wait": lane.total_wait,
        } for key, lane in sorted(self._lanes.items(), key=lambda kv: repr(kv[0]))}

    def assert_invariants(self) -> None:
        for lane in self._lanes.values():
            lane.assert_invariants()


class TransactionPhase:
    """Lifecycle states shared by every execution capability.

    The first four values are exactly the state strings the coupled runtime
    already writes into its records, so one vocabulary covers both. FAILED
    and CANCELLED are reserved for Phase 4 and must not be invented
    elsewhere.
    """

    REQUEST_INFLIGHT = "REQUEST_INFLIGHT"
    MEMORY_QUEUED_OR_SERVICING = "MEMORY_QUEUED_OR_SERVICING"
    RESPONSE_INFLIGHT = "RESPONSE_INFLIGHT"
    RETIRED = "RETIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    LEGAL = frozenset({
        (REQUEST_INFLIGHT, MEMORY_QUEUED_OR_SERVICING),
        (REQUEST_INFLIGHT, RESPONSE_INFLIGHT),
        (REQUEST_INFLIGHT, FAILED),
        (REQUEST_INFLIGHT, CANCELLED),
        (MEMORY_QUEUED_OR_SERVICING, RESPONSE_INFLIGHT),
        (MEMORY_QUEUED_OR_SERVICING, FAILED),
        (MEMORY_QUEUED_OR_SERVICING, CANCELLED),
        (RESPONSE_INFLIGHT, RETIRED),
        (RESPONSE_INFLIGHT, FAILED),
        (RESPONSE_INFLIGHT, CANCELLED),
    })
    TERMINAL = frozenset({RETIRED, FAILED, CANCELLED})
    COMPLETION_OF = {RETIRED: "COMPLETED", FAILED: "FAILED",
                     CANCELLED: "CANCELLED"}


@dataclass
class TransactionIdentity:
    """Stable logical identity plus per-attempt execution identity.

    ``logical_transaction_id`` survives retries, dedup, cancellation and
    migration; ``attempt_id`` identifies one execution attempt of it;
    ``execution_epoch`` scopes dedup/reset epochs. Every future feature must
    reuse this object instead of building a parallel identity scheme.
    """

    logical_transaction_id: str
    attempt_id: int
    execution_epoch: int
    source: str
    destination: str
    operation: str
    dependency_ids: tuple[str, ...] = ()
    resource_ownership: list[tuple] = field(default_factory=list)
    current_state: str = TransactionPhase.REQUEST_INFLIGHT
    completion_state: str | None = None

    @property
    def attempt_key(self) -> tuple[str, int]:
        return (self.logical_transaction_id, self.attempt_id)


class IdentityRegistry:
    """Authoritative transaction identities for one execution run."""

    def __init__(self) -> None:
        self._by_attempt: dict[tuple[str, int], TransactionIdentity] = {}
        self._order: list[tuple[str, int]] = []
        self.epoch = 0

    def advance_epoch(self) -> int:
        self.epoch += 1
        return self.epoch

    def issue(self, *, logical_transaction_id: str, source: str,
              destination: str, operation: str,
              dependency_ids: tuple[str, ...] = (),
              attempt_id: int = 1,
              execution_epoch: int | None = None) -> TransactionIdentity:
        if type(attempt_id) is not int or attempt_id < 1:
            raise InvalidInput("attempt_id must be an int >= 1")
        key = (logical_transaction_id, attempt_id)
        if key in self._by_attempt:
            raise EvidenceInvalid(
                f"duplicate transaction attempt {key!r}: identities must be "
                f"issued once per (logical id, attempt)")
        identity = TransactionIdentity(
            logical_transaction_id=logical_transaction_id,
            attempt_id=attempt_id,
            execution_epoch=self.epoch if execution_epoch is None else execution_epoch,
            source=source, destination=destination, operation=operation,
            dependency_ids=tuple(sorted(dependency_ids)))
        self._by_attempt[key] = identity
        self._order.append(key)
        return identity

    def current_attempt(self, logical_transaction_id: str) -> int:
        attempts = [attempt for (logical, attempt) in self._by_attempt
                    if logical == logical_transaction_id]
        if not attempts:
            raise InvalidInput(
                f"unknown transaction {logical_transaction_id!r}")
        return max(attempts)

    def get(self, logical_transaction_id: str,
            attempt_id: int | None = None) -> TransactionIdentity:
        """Fetch one attempt; ``attempt_id=None`` means the CURRENT attempt."""
        if attempt_id is None:
            attempt_id = self.current_attempt(logical_transaction_id)
        try:
            return self._by_attempt[(logical_transaction_id, attempt_id)]
        except KeyError:
            raise InvalidInput(
                f"unknown transaction attempt "
                f"{(logical_transaction_id, attempt_id)!r}") from None

    def transition(self, logical_transaction_id: str, to_state: str,
                   *, attempt_id: int | None = None) -> TransactionIdentity:
        identity = self.get(logical_transaction_id, attempt_id)
        if identity.current_state in TransactionPhase.TERMINAL:
            raise EvidenceInvalid(
                f"transaction {logical_transaction_id!r} is terminal "
                f"({identity.current_state}) and cannot transition to {to_state}")
        if (identity.current_state, to_state) not in TransactionPhase.LEGAL:
            raise EvidenceInvalid(
                f"illegal transaction transition "
                f"{identity.current_state} -> {to_state} for "
                f"{logical_transaction_id!r}")
        identity.current_state = to_state
        if to_state in TransactionPhase.TERMINAL:
            identity.completion_state = TransactionPhase.COMPLETION_OF[to_state]
        return identity

    def own(self, logical_transaction_id: str, resource_key: tuple,
            *, attempt_id: int | None = None) -> TransactionIdentity:
        identity = self.get(logical_transaction_id, attempt_id)
        identity.resource_ownership.append(tuple(resource_key))
        return identity

    def repeat(self, logical_transaction_id: str) -> TransactionIdentity:
        """Spawn the next physical attempt of an existing logical transaction.

        The new attempt resumes in whatever lifecycle state the superseded
        attempt occupied (a request retry resumes REQUEST_INFLIGHT, a response
        retry resumes RESPONSE_INFLIGHT); the superseded attempt remains as
        history and is never transitioned again. This is how the fault
        envelope's bounded retries share ONE logical identity.
        """
        previous = self.get(logical_transaction_id)   # current attempt
        if previous.current_state in TransactionPhase.TERMINAL:
            raise EvidenceInvalid(
                f"transaction {logical_transaction_id!r} is terminal "
                f"({previous.current_state}); a terminal attempt cannot be "
                f"retried or superseded")
        successor = self.issue(
            logical_transaction_id=logical_transaction_id,
            attempt_id=previous.attempt_id + 1,
            source=previous.source,
            destination=previous.destination,
            operation=previous.operation,
            dependency_ids=previous.dependency_ids,
            execution_epoch=previous.execution_epoch)
        successor.current_state = previous.current_state
        return successor

    def retire(self, logical_transaction_id: str,
               *, attempt_id: int | None = None) -> TransactionIdentity:
        return self.transition(logical_transaction_id, TransactionPhase.RETIRED,
                               attempt_id=attempt_id)

    def all(self) -> tuple[TransactionIdentity, ...]:
        return tuple(self._by_attempt[key] for key in self._order)

    def __len__(self) -> int:
        return len(self._by_attempt)

    def assert_invariants(self) -> None:
        seen_logical: set[str] = set()
        for identity in self.all():
            if identity.current_state in TransactionPhase.TERMINAL:
                if identity.completion_state is None:
                    raise EvidenceInvalid(
                        f"terminal identity {identity.logical_transaction_id!r} "
                        f"has no completion state")
            elif identity.completion_state is not None:
                raise EvidenceInvalid(
                    f"live identity {identity.logical_transaction_id!r} already "
                    f"has completion state {identity.completion_state!r}")
            if identity.attempt_id < 1:
                raise EvidenceInvalid("attempt ids are 1-based")
            if (identity.logical_transaction_id in seen_logical
                    and identity.attempt_id == 1):
                raise EvidenceInvalid(
                    f"logical identity {identity.logical_transaction_id!r} "
                    f"issued twice at attempt 1")
            seen_logical.add(identity.logical_transaction_id)
        # Exactly one attempt per logical transaction is CURRENT (the highest
        # attempt id), and a superseded attempt is never touched afterwards.
        by_logical: dict[str, list[TransactionIdentity]] = {}
        for identity in self.all():
            by_logical.setdefault(identity.logical_transaction_id, []).append(identity)
        for logical, identities in by_logical.items():
            attempts = sorted(i.attempt_id for i in identities)
            if attempts != list(range(1, len(attempts) + 1)):
                raise EvidenceInvalid(
                    f"transaction {logical!r} has non-contiguous attempts {attempts}")


class ExecutionKernel:
    """One run's shared substrate: queue + resources + identities.

    ``data_movement.execute_data_movement`` creates one per execution (or
    accepts an injected one via the private ``_kernel`` hook for tests) and
    routes every event push, resource reservation and transaction issue
    through it.
    """

    def __init__(self) -> None:
        self.queue = EventQueue()
        self.resources = ResourceRegistry()
        self.identities = IdentityRegistry()

    def push(self, time: Fraction, priority: int, payload: Any) -> None:
        self.queue.push(time, priority, payload)

    def snapshot(self) -> dict:
        return {
            "events_pending": len(self.queue),
            "next_event_s": self.queue.earliest(),
            "events_issued": self.queue.serial,
            "resources": self.resources.snapshot(),
            "identities": len(self.identities),
            "epoch": self.identities.epoch,
        }

    def assert_invariants(self) -> None:
        self.resources.assert_invariants()
        self.identities.assert_invariants()


__all__ = [
    "EventPriority",
    "EventQueue",
    "ResourceLane",
    "ResourceReservation",
    "ResourceRegistry",
    "TransactionPhase",
    "TransactionIdentity",
    "IdentityRegistry",
    "ExecutionKernel",
]
