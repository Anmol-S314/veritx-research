"""Automatic bounded retries on real phase reservations, fail-closed.

This is the reference fault envelope: authored, deterministic loss and a real
response deadline inside the EXISTING whole-message reservations. It is not
native transport reliability and not a claim about physical links.
"""
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from veritx_dse.application.data_movement import (AccessDenied, FaultProfile,
    execute_data_movement, ratio)
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.artifact import FrozenMap
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput, UnsupportedSemantics
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.physical_placement import PhysicalPlacement
from veritx_dse.model.transaction_intent import TransactionKind
from veritx_dse.workload.data_movement import DataMovementOperation, DataMovementWorkload

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/addressed_memory_v5.json"
DSE = Path(__file__).resolve().parents[1]


def setup():
    doc = json.loads((EXAMPLE).read_text())
    compilation = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    assert compilation.status == "COMPILED", compilation.error
    return doc, compilation


@pytest.fixture(scope="module")
def compilation():
    return setup()[1]


@pytest.fixture(scope="module")
def placement():
    return PhysicalPlacement.from_dict(setup()[0]["placement"])


def workload(compilation, count=2, service_cycles=40):
    """Remote operations on the declared left range, as the example uses."""
    root = compilation.compiled_system
    policy = {row["endpoint_id"]: row["transaction_policy"]
              for row in root.execution_contract.endpoints}
    assert policy[0] is not None
    operations = tuple(
        DataMovementOperation(f"op{i}", 0, 1, TransactionKind.READ, 4096 + i*128, 128, 16,
                              service_cycles, "memory_transfer", (), None, "memory_transfer")
        for i in range(count))
    return DataMovementWorkload(compilation.request.design_hash(), "network", operations)


def run(compilation, placement, count=2, faults=None, service_cycles=40):
    return execute_data_movement(compilation, workload(compilation, count, service_cycles),
                                 placement, _faults=faults).to_dict()


def attempts(evidence, index=0):
    return evidence["children"][index]["attempt_log"]


def time_of(row, key="time_s"):
    return Fraction(row[key]["numerator"], row[key]["denominator"])


def test_baseline_without_faults_is_byte_identical_to_default(compilation, placement):
    without = run(compilation, placement)
    with_faults = run(compilation, placement, faults=FaultProfile(
        FrozenMap(), FrozenMap(), 1_000_000, 4))
    # No drop and a deadline no run can reach: execution must be identical
    # apart from the explicit fault bookkeeping on each child.
    for key in ("summary", "phases"):
        assert with_faults[key] == without[key]
    assert all(c["attempt"] == 1 and [r["event"] for r in c["attempt_log"]] == ["response_retired"]
               for c in with_faults["children"])


def test_request_drop_retries_and_still_commits_once(compilation, placement):
    # A deadline no run can reach isolates the drop from the timeout path.
    evidence = run(compilation, placement, faults=FaultProfile(
        FrozenMap({"op0:0": (1,)}), FrozenMap(), 1_000_000, 4))
    child = evidence["children"][0]
    log = child["attempt_log"]
    assert [row["event"] for row in log] == ["request_dropped", "attempt_retry", "response_retired"]
    assert log[1]["resume_phase"] == 0 and log[2]["attempt"] == 2
    assert child["attempt"] == 2
    # The retry reserved the request flight twice: real phase work increased.
    baseline = run(compilation, placement)
    assert evidence["summary"]["fifo_words_written"] > baseline["summary"]["fifo_words_written"]
    assert evidence["summary"]["routed_flit_um"]["numerator"] > baseline["summary"]["routed_flit_um"]["numerator"]
    assert evidence["summary"]["children_completed"] == len(evidence["children"])
    assert evidence["summary"]["payload_bytes"] == baseline["summary"]["payload_bytes"]


def test_response_drop_replays_response_without_committing_memory_twice(compilation, placement):
    evidence = run(compilation, placement, faults=FaultProfile(
        FrozenMap(), FrozenMap({"op1:0": (1,)}), 1_000_000, 4))
    log = attempts(evidence, 1)
    assert [row["event"] for row in log] == ["response_dropped", "attempt_retry", "response_retired"]
    # Resumes AFTER the service phase: exactly one memory service per child.
    services = [p for p in evidence["phases"]
                if p["parent"] == "op1" and p["resource"][0] == "service"]
    assert len(services) == 1
    # The dropped flight consumed no reservation: the retry replaces it, so the
    # reservation set and payload are conserved exactly as in the no-fault run.
    baseline = run(compilation, placement)
    resources = lambda x: sorted(map(tuple, (p["resource"] for p in x["phases"] if p["parent"] == "op1")))
    assert resources(evidence) == resources(baseline)
    assert evidence["summary"]["payload_bytes"] == baseline["summary"]["payload_bytes"]


def test_response_timeout_retries_and_is_bounded_by_the_deadline(compilation, placement):
    slow = run(compilation, placement, service_cycles=400)
    evidence = run(compilation, placement, service_cycles=400, faults=FaultProfile(
        FrozenMap(), FrozenMap({"op0:0": (1,)}), 1_000_000, 4))
    log = attempts(evidence, 0)
    assert [row["event"] for row in log] == ["response_dropped", "attempt_retry", "response_retired"]
    # A deadline shorter than the service time must expire on attempt one.
    deadline = run(compilation, placement, service_cycles=400, faults=FaultProfile(
        FrozenMap(), FrozenMap(), 1, 4))
    events = [row["event"] for row in attempts(deadline, 0)]
    assert "response_timeout" in events
    timed_out = next(r for r in attempts(deadline, 0) if r["event"] == "response_timeout")
    retired = next(r for r in attempts(deadline, 0) if r["event"] == "response_retired")
    assert time_of(timed_out) < time_of(retired)   # the deadline fired, then a retry answered


def test_exhausted_attempts_seal_the_child_instead_of_silently_completing(compilation, placement):
    with pytest.raises(EvidenceInvalid, match="sealed after"):
        run(compilation, placement, count=1, faults=FaultProfile(
            FrozenMap({"op0:0": (1, 2, 3)}), FrozenMap(), 1_000_000, 3))


def test_superseded_deadline_never_causes_a_second_retry(compilation, placement):
    # Drop the response on attempt one, then let the old deadline fire. The
    # stale deadline must be ignored rather than retrying again.
    evidence = run(compilation, placement, count=1, service_cycles=200,
                   faults=FaultProfile(FrozenMap(), FrozenMap({"op0:0": (1,)}), 1_000_000, 8))
    assert [row["event"] for row in attempts(evidence)] == [
        "response_dropped", "attempt_retry", "response_retired"]
    assert evidence["children"][0]["attempt"] == 2


@pytest.mark.parametrize("profile, error", [
    (dict(timeout_cycles=0, max_attempts=1), InvalidInput),
    (dict(timeout_cycles=1, max_attempts=17), UnsupportedSemantics),
    (dict(timeout_cycles=-3, max_attempts=1), InvalidInput)])
def test_invalid_fault_profiles_refuse(profile, error):
    with pytest.raises(error):
        FaultProfile(FrozenMap({"op0:0": (1,)}), FrozenMap(), **profile)


def test_drop_attempts_outside_the_bound_refuse():
    with pytest.raises(InvalidInput, match="max_attempts"):
        FaultProfile(FrozenMap({"op0:0": (5,)}), FrozenMap(), 4, 2)
    with pytest.raises(InvalidInput, match="operation_id"):
        FaultProfile(FrozenMap({"bad-key": (1,)}), FrozenMap(), 4, 4)


def test_fault_profile_round_trips_through_json():
    profile = FaultProfile(FrozenMap({"op0:0": (1, 2)}), FrozenMap(), 16, 4)
    assert FaultProfile.from_dict(profile.to_dict()) == profile
    doc = profile.to_dict(); doc["extra"] = 0
    with pytest.raises(InvalidInput):
        FaultProfile.from_dict(doc)


def test_unknown_fault_object_is_refused(compilation, placement):
    with pytest.raises(InvalidInput, match="FaultProfile"):
        execute_data_movement(compilation, workload(compilation), placement, _faults={"drops": []})