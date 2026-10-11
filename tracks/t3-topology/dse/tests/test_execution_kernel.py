"""Phase-1 shared execution kernel: ordering, resources, identity.

Three contracts are pinned here so later phases extend them instead of
forking them:

1. Same-time event ordering — named ranks, FIFO ties, and the boundary rule
   that a response retiring on the exact deadline instant is processed
   BEFORE the timeout (the fault envelope's deadline handler must re-check
   transaction state and suppress itself).
2. Resource registry — one authoritative owner per contended resource, no
   double allocation, exact release, declared capacity, observable queue
   state, and invariant detection under mutation.
3. Transaction identity — one logical id shared by every physical attempt,
   lifecycle states matching the execution records, and integration proof
   that wiring the kernel changes NO evidence byte while every child retires
   with recorded resource ownership.
"""
from fractions import Fraction
import json
from pathlib import Path

import pytest

from veritx_dse.application.data_movement import (
    FaultProfile, execute_data_movement)
from veritx_dse.application.execution_kernel import (
    EventPriority, EventQueue, ExecutionKernel, IdentityRegistry,
    ResourceRegistry, TransactionPhase)
from veritx_dse.core.artifact import FrozenMap
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput

from test_data_movement_execution import experiment

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


# --------------------------------------------------------------------------
# 1. Deterministic event ordering
# --------------------------------------------------------------------------

def test_event_priority_ranks_follow_the_documented_contract():
    ordered = [EventPriority.PHASE_COMPLETION, EventPriority.ADMISSION,
               EventPriority.STATE_TRANSITION, EventPriority.TIMEOUT,
               EventPriority.CANCELLATION, EventPriority.RETRY,
               EventPriority.FAULT_INJECTION]
    assert [int(p) for p in ordered] == [0, 1, 2, 3, 4, 5, 6]
    # The boundary rule: a completion is always ahead of a deadline, a
    # cancellation, a retry and a fault injection at the same instant.
    assert int(EventPriority.PHASE_COMPLETION) < int(EventPriority.TIMEOUT)


def test_response_on_the_deadline_instant_precedes_the_timeout():
    """Response wins the exact-tie: rank, not insertion luck, decides."""
    queue = EventQueue()
    t = Fraction(7, 8)
    # The timeout is pushed FIRST — if ranks did not matter it would pop
    # first (FIFO tie-break). The completion must still win.
    queue.push(t, EventPriority.TIMEOUT, "timeout")
    queue.push(t, EventPriority.PHASE_COMPLETION, "response_retired")
    assert queue.pop()[3] == "response_retired"
    assert queue.pop()[3] == "timeout"


def test_same_rank_events_pop_in_insertion_order():
    queue = EventQueue()
    for name in ("a", "b", "c"):
        queue.push(Fraction(1, 4), EventPriority.ADMISSION, name)
    assert [queue.pop()[3] for _ in range(3)] == ["a", "b", "c"]


def test_priority_ordering_beats_time_only_within_the_same_instant():
    queue = EventQueue()
    queue.push(Fraction(1, 2), EventPriority.TIMEOUT, "late")
    queue.push(Fraction(1, 3), EventPriority.FAULT_INJECTION, "early")
    assert queue.pop()[3] == "early"   # time dominates rank across instants
    assert queue.pop()[3] == "late"


def test_queue_refuses_unknown_priority_and_inexact_time():
    queue = EventQueue()
    with pytest.raises(InvalidInput, match="priority"):
        queue.push(Fraction(0), 7, "unranked")
    with pytest.raises(InvalidInput, match="Fraction"):
        queue.push(1, EventPriority.PHASE_COMPLETION, "float-time")
    with pytest.raises(InvalidInput, match="Fraction"):
        queue.push(1.5, EventPriority.PHASE_COMPLETION, "float-time")


def test_requeue_preserves_horizon_pause_order():
    queue = EventQueue()
    queue.push(Fraction(1), EventPriority.PHASE_COMPLETION, "x")
    queue.push(Fraction(2), EventPriority.ADMISSION, "y")
    entry = queue.pop()
    assert entry[3] == "x"
    queue.requeue(entry)
    assert queue.earliest() == Fraction(1)
    assert queue.pop()[3] == "x"
    assert queue.pop()[3] == "y"


def test_exact_fraction_times_survive_round_trip():
    queue = EventQueue()
    queue.push(Fraction(1, 3), EventPriority.PHASE_COMPLETION, "one-third")
    popped = queue.pop()
    assert popped[0] == Fraction(1, 3)
    assert popped[0].numerator == 1 and popped[0].denominator == 3


# --------------------------------------------------------------------------
# 2. Shared resource registry
# --------------------------------------------------------------------------

def test_undeclared_lane_starts_free_and_reserve_updates_it():
    registry = ResourceRegistry()
    assert registry.free_at(("channel", 0)) == Fraction(0)
    registry.reserve(("channel", 0), arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(5), owner="t#0")
    assert registry.free_at(("channel", 0)) == Fraction(5)
    assert list(registry.values()) == [Fraction(5)]
    assert ("channel", 0) in registry


def test_double_allocation_is_refused():
    registry = ResourceRegistry()
    key = ("service", 1)
    registry.reserve(key, arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(5), owner="t#0")
    with pytest.raises(EvidenceInvalid, match="double allocation"):
        registry.reserve(key, arrival=Fraction(1), start=Fraction(3),
                         end=Fraction(4), owner="t#1")


def test_out_of_order_reservation_is_refused():
    registry = ResourceRegistry()
    key = ("interface", 0, "out")
    registry.reserve(key, arrival=Fraction(0), start=Fraction(10),
                     end=Fraction(12), owner="t#0")
    with pytest.raises(EvidenceInvalid, match="out-of-order"):
        registry.reserve(key, arrival=Fraction(1), start=Fraction(5),
                         end=Fraction(6), owner="t#1")


def test_reservation_before_its_arrival_is_refused():
    registry = ResourceRegistry()
    with pytest.raises(EvidenceInvalid, match="before"):
        registry.reserve(("channel", 2), arrival=Fraction(4),
                         start=Fraction(3), end=Fraction(6), owner="t#0")


def test_queue_state_records_waiting_and_delay():
    registry = ResourceRegistry()
    key = ("channel", 3)
    registry.reserve(key, arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(10), owner="t#0")
    registry.reserve(key, arrival=Fraction(2), start=Fraction(10),
                     end=Fraction(11), owner="t#1")   # waited 8/1
    count, total = registry.queue_state(key)
    assert count == 1 and total == Fraction(8)
    assert registry.queue_state(("channel", 99)) == (0, Fraction(0))


def test_declared_capacity_two_admits_two_overlapping_owners():
    registry = ResourceRegistry()
    key = ("engine", 0)
    registry.declare(key, capacity=2)
    registry.reserve(key, arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(10), owner="t#0")
    registry.reserve(key, arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(5), owner="t#1")
    lane = registry.lane(key)
    assert lane.peak_occupancy == 2
    with pytest.raises(EvidenceInvalid, match="double allocation"):
        registry.reserve(key, arrival=Fraction(0), start=Fraction(0),
                         end=Fraction(1), owner="t#2")
    registry.assert_invariants()


def test_registry_is_dict_readable_for_the_coupled_drain_check():
    registry = ResourceRegistry()
    registry.reserve(("channel", 0), arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(3), owner="t#0")
    registry.reserve(("service", 1), arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(9), owner="t#1")
    # coupled_tensor's DRAIN_RESET does max([now, *lane_free.values()]).
    assert max([Fraction(0), *registry.values()]) == Fraction(9)


def test_reservations_require_an_authoritative_owner():
    registry = ResourceRegistry()
    registry.reserve(("channel", 0), arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(1), owner=None)
    with pytest.raises(EvidenceInvalid, match="owner"):
        registry.assert_invariants()


def test_snapshot_exposes_capacity_occupancy_and_queue_state():
    registry = ResourceRegistry()
    key = ("channel", 0)
    registry.reserve(key, arrival=Fraction(0), start=Fraction(2),
                     end=Fraction(6), owner="t#0")
    snap = registry.snapshot()[repr(key)]
    assert snap["capacity"] == 1
    assert snap["free_at"] == Fraction(6)
    assert snap["reservations"] == 1
    assert snap["peak_occupancy"] == 1
    assert snap["wait_count"] == 1
    assert snap["total_wait"] == Fraction(2)


def test_mutated_lane_state_is_detected():
    registry = ResourceRegistry()
    key = ("channel", 0)
    registry.reserve(key, arrival=Fraction(0), start=Fraction(0),
                     end=Fraction(1), owner="t#0")
    lane = registry.lane(key)
    lane._slot_free[0] = Fraction(-1)
    with pytest.raises(EvidenceInvalid, match="negative free time"):
        registry.assert_invariants()
    lane._slot_free[0] = Fraction(1)
    lane.peak_occupancy = 7
    with pytest.raises(EvidenceInvalid, match="exceeds capacity"):
        registry.assert_invariants()


# --------------------------------------------------------------------------
# 3. Transaction identity
# --------------------------------------------------------------------------

def _issue(registry, logical="op0#0", **kwargs):
    return registry.issue(logical_transaction_id=logical,
                          source="ep0", destination="ep1", operation="READ",
                          **kwargs)


def test_issue_creates_stable_identity_with_sorted_dependencies():
    registry = IdentityRegistry()
    identity = _issue(registry, dependency_ids={"b", "a"})
    assert identity.logical_transaction_id == "op0#0"
    assert identity.attempt_id == 1
    assert identity.execution_epoch == 0
    assert identity.dependency_ids == ("a", "b")
    assert identity.current_state == TransactionPhase.REQUEST_INFLIGHT
    assert identity.completion_state is None
    assert registry.get("op0#0") is identity


def test_duplicate_attempt_is_refused():
    registry = IdentityRegistry()
    _issue(registry)
    with pytest.raises(EvidenceInvalid, match="duplicate transaction attempt"):
        _issue(registry)


def test_illegal_and_terminal_transitions_refuse():
    registry = IdentityRegistry()
    _issue(registry)
    # No skipping straight to RETIRED: the lifecycle must pass memory and
    # response states (except where a no-service child retires via response).
    with pytest.raises(EvidenceInvalid, match="illegal transaction transition"):
        registry.transition("op0#0", TransactionPhase.RETIRED)
    with pytest.raises(EvidenceInvalid, match="illegal transaction transition"):
        registry.transition("op0#0", "MADE_UP_STATE")
    registry.transition("op0#0", TransactionPhase.MEMORY_QUEUED_OR_SERVICING)
    registry.transition("op0#0", TransactionPhase.RESPONSE_INFLIGHT)
    registry.retire("op0#0")
    assert registry.get("op0#0").completion_state == "COMPLETED"
    with pytest.raises(EvidenceInvalid, match="terminal"):
        registry.transition("op0#0", TransactionPhase.FAILED)


def test_lifecycle_walk_mirrors_execution_states_and_ownership():
    registry = IdentityRegistry()
    _issue(registry)
    registry.transition("op0#0", TransactionPhase.MEMORY_QUEUED_OR_SERVICING)
    registry.own("op0#0", ("channel", 0))
    registry.transition("op0#0", TransactionPhase.RESPONSE_INFLIGHT)
    registry.own("op0#0", ("service", 1))
    registry.retire("op0#0")
    identity = registry.get("op0#0")
    assert identity.resource_ownership == [("channel", 0), ("service", 1)]
    registry.assert_invariants()


def test_failed_and_cancelled_attempts_carry_completion_state():
    registry = IdentityRegistry()
    _issue(registry, logical="op1#0")
    registry.transition("op1#0", TransactionPhase.FAILED)
    assert registry.get("op1#0").completion_state == "FAILED"
    _issue(registry, logical="op2#0")
    registry.transition("op2#0", TransactionPhase.CANCELLED)
    assert registry.get("op2#0").completion_state == "CANCELLED"
    registry.assert_invariants()


def test_repeat_shares_one_logical_identity_across_physical_attempts():
    registry = IdentityRegistry()
    first = _issue(registry)
    registry.transition("op0#0", TransactionPhase.MEMORY_QUEUED_OR_SERVICING)
    registry.own("op0#0", ("service", 1))
    second = registry.repeat("op0#0")
    # Same logical id, next attempt id, resumes exactly where the child was.
    assert second.logical_transaction_id == first.logical_transaction_id
    assert second.attempt_id == 2
    assert second.current_state == TransactionPhase.MEMORY_QUEUED_OR_SERVICING
    assert first.current_state == TransactionPhase.MEMORY_QUEUED_OR_SERVICING
    # The current attempt is what transitions resolve to now.
    registry.transition("op0#0", TransactionPhase.RESPONSE_INFLIGHT)
    assert registry.get("op0#0", 2).current_state == TransactionPhase.RESPONSE_INFLIGHT
    assert registry.get("op0#0", 1).current_state == TransactionPhase.MEMORY_QUEUED_OR_SERVICING
    registry.retire("op0#0")
    assert registry.current_attempt("op0#0") == 2
    assert registry.get("op0#0", 2).completion_state == "COMPLETED"
    assert len(registry) == 2
    registry.assert_invariants()


def test_repeating_a_terminal_transaction_is_refused():
    registry = IdentityRegistry()
    _issue(registry)
    registry.transition("op0#0", TransactionPhase.MEMORY_QUEUED_OR_SERVICING)
    registry.transition("op0#0", TransactionPhase.RESPONSE_INFLIGHT)
    registry.retire("op0#0")
    with pytest.raises(EvidenceInvalid, match="terminal"):
        registry.repeat("op0#0")


def test_epoch_scopes_attempts_and_mutated_completion_is_detected():
    registry = IdentityRegistry()
    assert registry.advance_epoch() == 1
    identity = _issue(registry)
    assert identity.execution_epoch == 1
    identity.completion_state = "COMPLETED"   # tamper: live but "complete"
    with pytest.raises(EvidenceInvalid, match="already"):
        registry.assert_invariants()


# --------------------------------------------------------------------------
# 4. Integration: the wired executor
# --------------------------------------------------------------------------

def test_kernel_wiring_is_byte_identical_to_default_execution():
    compilation, workload, placement = experiment()
    plain = execute_data_movement(compilation, workload, placement).to_dict()
    kernel = ExecutionKernel()
    wired = execute_data_movement(compilation, workload, placement,
                                  _kernel=kernel).to_dict()
    # artifact_id included: stable artifact identity, not just equal counts.
    assert wired == plain
    kernel.assert_invariants()


def test_deterministic_replay_across_fresh_kernels():
    compilation, workload, placement = experiment()
    runs = []
    for _ in range(2):
        kernel = ExecutionKernel()
        runs.append(execute_data_movement(compilation, workload, placement,
                                          _kernel=kernel).artifact_id())
    assert runs[0] == runs[1]


def test_every_child_identity_retires_with_resource_ownership():
    compilation, workload, placement = experiment()
    plain = execute_data_movement(compilation, workload, placement).to_dict()
    kernel = ExecutionKernel()
    execute_data_movement(compilation, workload, placement, _kernel=kernel)
    identities = kernel.identities.all()
    assert len(identities) == plain["summary"]["children_completed"]
    for identity in identities:
        assert identity.current_state == TransactionPhase.RETIRED
        assert identity.completion_state == "COMPLETED"
        assert identity.resource_ownership          # touched real resources
        assert identity.attempt_id == 1
    snapshot = kernel.resources.snapshot()
    assert snapshot and all(row["reservations"] > 0 for row in snapshot.values())
    assert all(row["peak_occupancy"] <= row["capacity"] for row in snapshot.values())
    kernel.assert_invariants()


def test_resource_contention_is_observable_through_the_registry():
    compilation, workload, placement = experiment()
    kernel = ExecutionKernel()
    execute_data_movement(compilation, workload, placement, _kernel=kernel)
    # The shared channel(s) serialize both children of the shared target.
    waits = [(key, *kernel.resources.queue_state(key)) for key
             in kernel.resources.keys() if key[0] == "channel"]
    assert waits, "the experiment must reserve network channels"
    assert all(count >= 0 and total >= 0 for _key, count, total in waits)


def test_fault_run_spawns_attempt_identities_under_one_logical_id():
    compilation, workload, placement = experiment()
    faults = FaultProfile(FrozenMap({"write:0": (1,)}), FrozenMap(),
                          1_000_000, 4)
    kernel = ExecutionKernel()
    evidence = execute_data_movement(compilation, workload, placement,
                                     _faults=faults, _kernel=kernel).to_dict()
    assert any(c.get("attempt") == 2 for c in evidence["children"])
    attempts = [i for i in kernel.identities.all()
                if i.logical_transaction_id == "write#0"]
    assert [i.attempt_id for i in attempts] == [1, 2]
    # Superseded attempt stays as history; the current attempt retired.
    assert attempts[0].current_state == TransactionPhase.REQUEST_INFLIGHT
    assert attempts[1].current_state == TransactionPhase.RETIRED
    assert kernel.identities.current_attempt("write#0") == 2
    assert kernel.identities.get("write#0", 2).completion_state == "COMPLETED"
    kernel.assert_invariants()


def test_invalid_kernel_object_is_refused():
    compilation, workload, placement = experiment()
    with pytest.raises(InvalidInput, match="ExecutionKernel"):
        execute_data_movement(compilation, workload, placement, _kernel={})


def test_coupled_execution_retires_every_identity_and_syncs_the_epoch():
    from veritx_dse.application.coupled_tensor import execute_coupled_tensor
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.tensor_demand import RemoteDemandPolicy
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.coupled_tensor import CoupledTensorWorkload
    from veritx_dse.model.physical_placement import PhysicalPlacement
    doc = json.loads((EXAMPLES / "coupled_tensor_v5.json").read_text())
    compilation = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    assert compilation.status == "COMPILED", compilation.error
    workload = CoupledTensorWorkload.from_dict(doc["workload"])
    policy = RemoteDemandPolicy.from_dict(doc["transport"])
    placement = PhysicalPlacement.from_dict(doc["placement"])
    plain = execute_coupled_tensor(compilation, workload, policy, placement).to_dict()
    kernel = ExecutionKernel()
    wired = execute_coupled_tensor(compilation, workload, policy, placement,
                                   None, _kernel=kernel).to_dict()
    assert wired == plain
    assert plain["status"] == "COMPLETE"
    identities = kernel.identities.all()
    assert len(identities) == plain["summary"]["children_issued"]
    assert all(i.current_state == TransactionPhase.RETIRED for i in identities)
    # DRAIN_RESET epochs and identity epochs are one system.
    assert kernel.identities.epoch == plain["endpoint_epoch"]
    assert all(i.execution_epoch <= plain["endpoint_epoch"] for i in identities)
    kernel.assert_invariants()
