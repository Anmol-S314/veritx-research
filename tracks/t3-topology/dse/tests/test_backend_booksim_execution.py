"""Slice 32 — authenticated BookSim execution and evidence.

The fault matrix runs against an injected runner; the real gates run the
vendored fork when a binary is available and skip otherwise.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from test_backend_booksim_projection import _parents  # noqa: E402

from veritx_dse.backend import booksim_execution as bx
from veritx_dse.backend import evidence as ev
from veritx_dse.backend import producer as pd
from veritx_dse.backend.booksim_projection import prepare_booksim_input

_REPO = Path(__file__).resolve().parents[4]
REAL_CANDIDATES = (
    os.environ.get("VERITX_BOOKSIM_BIN"),
    str(_REPO / "third_party" / "booksim2" / "src" / "booksim"),
)

GOOD_STDOUT = (
    "Loaded text trace: 5 packets from workload.trace\n"
    "Packet latency average = 12.5\n"
    "Flit latency average = 4.5\n"
    "Hops average = 3.0\n"
    "Time taken is 900 cycles\n"
    "Completion time is 777 cycles\n"
)
GOOD_STDERR = "[trace] All 800 cycles, injected=5 — draining\n"

def _binary(tmp_path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "booksim"
    path.write_bytes(b"#!/bin/sh\nexit 0\n" + b"x" * 64)
    path.chmod(0o755)
    return path

def _runner(stdout=GOOD_STDOUT, stderr=GOOD_STDERR, returncode=0,
            timed_out=False):
    def run(command, cwd, timeout):
        return bx.ProcessOutcome(returncode=returncode, stdout=stdout,
                                 stderr=stderr, timed_out=timed_out)
    return run

def _runner_for(prepared, *, returncode=0, timed_out=False,
                stdout=None, stderr=None):
    """A runner whose output matches THIS prepared input's trace."""
    count = prepared.expected_packets
    stdout = stdout if stdout is not None else (
        f"Loaded text trace: {count} packets from workload.trace\n"
        "Packet latency average = 12.5\n"
        "Flit latency average = 4.5\n"
        "Time taken is 900 cycles\n"
        "Completion time is 777 cycles\n")
    stderr = stderr if stderr is not None else (
        f"[trace] All 800 cycles, injected={count} — draining\n")

    def run(command, cwd, timeout):
        return bx.ProcessOutcome(returncode=returncode, stdout=stdout,
                                 stderr=stderr, timed_out=timed_out)
    return run

def _prepared():
    return prepare_booksim_input(_parents()[1])

def _execute(tmp_path, *, prepared=None, runner=None, **kw):
    prepared = prepared or _prepared()
    return bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "run", timeout=30,
        runner=runner or _runner_for(prepared), **kw)

def test_supervised_runner_persists_partial_stdout_and_stderr_on_timeout(tmp_path):
    command = (sys.executable, "-c",
               "import sys,time; print('partial-out', flush=True); "
               "print('partial-err', file=sys.stderr, flush=True); "
               "time.sleep(2)")

    outcome = bx._supervised_runner(command, tmp_path, timeout=0.1)

    assert outcome.timed_out
    assert outcome.stdout == "partial-out\n"
    assert outcome.stderr == "partial-err\n"
    assert (tmp_path / "booksim.stdout.log").read_text() == outcome.stdout
    assert (tmp_path / "booksim.stderr.log").read_text() == outcome.stderr
    manifest = json.loads((tmp_path / "booksim-process-logs.json").read_text())
    assert manifest["timed_out"] is True
    assert manifest["logs"]["stdout"]["size_bytes"] == len(
        outcome.stdout.encode())
    assert manifest["logs"]["stdout"]["sha256"] == hashlib.sha256(
        outcome.stdout.encode()).hexdigest()
    assert manifest["logs"]["stderr"]["sha256"] == hashlib.sha256(
        outcome.stderr.encode()).hexdigest()
    from veritx_dse.core.run_bundle import finalize_run_bundle
    bundle = finalize_run_bundle(tmp_path)
    assert "booksim.stdout.log" in bundle["files"]
    assert "booksim.stderr.log" in bundle["files"]
    assert "booksim-process-logs.json" in bundle["files"]


@pytest.mark.parametrize("token", ["-", "nan", "-nan", "inf", "-inf"])
def test_unavailable_and_nonfinite_metrics_become_none(token):
    stdout = (GOOD_STDOUT.replace("12.5", token)
              .replace("4.5", token))
    stats = bx.parse_booksim_stats(stdout, GOOD_STDERR)
    assert stats["packet_latency_avg"] is None
    assert stats["flit_latency_avg"] is None
    assert stats["completion_cycles"] == 777
    assert stats["loaded_trace_packets"] == 5

def test_request_time_percentiles_are_parsed_from_the_fork_stats():
    """The fork prints exact p50/p95/p99 over _all_latencies; the product
    must carry them, because a mean cannot answer a tail question."""
    stdout = (GOOD_STDOUT
              + "\tp50 = 11.0\n"
              + "\tp95 = 19.5\n"
              + "\tp99 = 24.25\n"
              + "\tpkt_count = 5\n"
              + "\thonest_avg = 12.75\n")
    stats = bx.parse_booksim_stats(stdout, GOOD_STDERR)
    assert stats["p50"] == 11.0
    assert stats["p95"] == 19.5
    assert stats["p99"] == 24.25
    assert stats["pkt_count"] == 5
    assert stats["honest_latency"] == 12.75

def test_percentiles_are_absent_when_the_fork_prints_none():
    stats = bx.parse_booksim_stats(GOOD_STDOUT, GOOD_STDERR)
    assert stats["p50"] is None
    assert stats["p95"] is None
    assert stats["p99"] is None
    assert stats["pkt_count"] is None
    assert stats["honest_latency"] is None

def test_latency_is_not_required_for_trace_driven_runs():
    stdout = ("Loaded text trace: 5 packets from workload.trace\n"
              "Time taken is 900 cycles\n"
              "Completion time is 777 cycles\n")
    stats = bx.parse_booksim_stats(stdout, GOOD_STDERR)
    assert stats["packet_latency_avg"] is None
    bx.assert_execution_gate(stats, expected_packets=5)

def test_completion_metric_is_window_invariant_and_time_taken_is_diagnostic():
    """F-0001: completion_cycles is last-ejection, not `Time taken is`."""
    narrow = bx.parse_booksim_stats(
        "Loaded text trace: 5 packets\n"
        "Time taken is 900 cycles\nCompletion time is 777 cycles\n",
        GOOD_STDERR)
    wide = bx.parse_booksim_stats(
        "Loaded text trace: 5 packets\n"
        "Time taken is 5000 cycles\nCompletion time is 777 cycles\n",
        GOOD_STDERR)
    assert narrow["completion_cycles"] == 777
    assert wide["completion_cycles"] == 777
    assert narrow["sample_window_cycles"] == 900
    assert wide["sample_window_cycles"] == 5000

def test_completion_after_the_run_window_is_refused():
    with pytest.raises(bx.BookSimExecutionError, match="exceeds the run window"):
        bx.parse_booksim_stats(
            "Loaded text trace: 5 packets\n"
            "Time taken is 100 cycles\nCompletion time is 777 cycles\n",
            GOOD_STDERR)

def test_required_evidence_is_fail_closed():
    with pytest.raises(bx.BookSimExecutionError, match="Loaded text trace"):
        bx.parse_booksim_stats("Completion time is 5 cycles\n", "")
    with pytest.raises(bx.BookSimExecutionError, match="Completion time"):
        bx.parse_booksim_stats("Loaded text trace: 5 packets\n"
                               "Time taken is 9 cycles\n", "")
    with pytest.raises(bx.BookSimExecutionError, match="not a completion"):
        bx.parse_booksim_stats("Loaded text trace: 5 packets\n", "")

def test_injected_count_is_read_from_the_trace_drain_line():
    stats = bx.parse_booksim_stats(GOOD_STDOUT, GOOD_STDERR)
    assert stats["injected_trace_packets"] == 5
    absent = bx.parse_booksim_stats(GOOD_STDOUT, "")
    assert absent["injected_trace_packets"] is None

def test_gate_refuses_truncation_zero_completion_and_failure_states():
    base = bx.parse_booksim_stats(GOOD_STDOUT, GOOD_STDERR)
    bx.assert_execution_gate(base, expected_packets=5)

    with pytest.raises(bx.BookSimExecutionError, match="trace evidence"):
        bx.assert_execution_gate(base, expected_packets=9)

    truncated = dict(base, injected_trace_packets=2)
    with pytest.raises(bx.BookSimExecutionError, match="truncated"):
        bx.assert_execution_gate(truncated, expected_packets=5)

    zero = dict(base, completion_cycles=0)
    with pytest.raises(bx.BookSimExecutionError, match="zero cycles"):
        bx.assert_execution_gate(zero, expected_packets=5)

    with pytest.raises(bx.BookSimExecutionError, match="unstable"):
        bx.assert_execution_gate(dict(base, simulation_unstable=True),
                                 expected_packets=5)
    with pytest.raises(bx.BookSimExecutionError, match="abort"):
        bx.assert_execution_gate(dict(base, abort_token="Assertion"),
                                 expected_packets=5)

def test_materialization_is_exact_and_tamper_closed(tmp_path):
    prepared = _prepared()
    written = bx.materialize_prepared(prepared, tmp_path / "run")
    for name, path in written.items():
        assert path.read_bytes() == prepared.files()[name]
    if prepared.topology_text is None:
        assert bx.TOPOLOGY_FILE not in written
    (tmp_path / "run" / bx.CONFIG_FILE).write_bytes(b"tampered")
    with pytest.raises(bx.BookSimExecutionError, match="different bytes"):
        bx.materialize_prepared(prepared, tmp_path / "run")

def test_stale_run_directory_is_refused(tmp_path):
    prepared = _prepared()
    run = tmp_path / "run"
    run.mkdir()
    (run / "stale-output.txt").write_text("old results")
    with pytest.raises(bx.BookSimExecutionError, match="stale"):
        bx.materialize_prepared(prepared, run)

def test_prepared_input_tamper_is_caught_before_spawn(tmp_path):
    prepared = _prepared()
    held_id = prepared.prepared_id()
    tampered = dataclasses.replace(prepared, config_text="topology = mesh;\n")
    with pytest.raises(bx.BookSimExecutionError,
                       match="modified after preparation"):
        bx.execute_prepared_booksim(
            prepared=tampered, binary=_binary(tmp_path),
            run_dir=tmp_path / "run", timeout=10,
            runner=_runner_for(prepared), expected_prepared_id=held_id)
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "ok", timeout=10,
        runner=_runner_for(prepared), expected_prepared_id=held_id)
    assert record.evidence.prepared_id == held_id

def test_missing_and_empty_binary_are_refused(tmp_path):
    prepared = _prepared()
    with pytest.raises(bx.BookSimExecutionError, match="not found"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=tmp_path / "absent",
            run_dir=tmp_path / "run", timeout=10,
            runner=_runner_for(prepared))
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    with pytest.raises(bx.BookSimExecutionError, match="empty"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=empty, run_dir=tmp_path / "run",
            timeout=10, runner=_runner_for(prepared))

def test_binary_swap_after_identification_is_refused(tmp_path):
    binary = _binary(tmp_path)
    identity = pd.resolve_producer_identity(binary)
    binary.write_bytes(b"#!/bin/sh\nexit 0\n" + b"y" * 64)
    with pytest.raises(pd.ProducerError, match="changed between identification"):
        pd.recheck_binary_digest(identity)

def test_dirty_or_unpinned_producer_cannot_be_reused(tmp_path):
    _, parents = _parents()
    prepared = prepare_booksim_input(parents)
    unpinned = pd.ProducerIdentity(
        binary_path=str(_binary(tmp_path)), binary_sha256="a" * 64,
        binary_size=10, source_revision=None, dirty=None, dirty_digest=None,
        manifest_verified=False)
    with pytest.raises(pd.ProducerError, match="build-time manifest"):
        pd.assert_pinned_producer(unpinned)
    dirty = dataclasses.replace(unpinned, source_revision="deadbeef",
                                dirty=True, dirty_digest="b" * 64,
                                manifest_verified=True)
    with pytest.raises(pd.ProducerError, match="DIRTY"):
        pd.assert_pinned_producer(dirty)
    with pytest.raises(bx.BookSimExecutionError, match="build-time manifest"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=_binary(tmp_path),
            run_dir=tmp_path / "run", timeout=10,
            runner=_runner_for(prepared), require_pinned_producer=True)

def test_timeout_and_nonzero_exit_fail_closed(tmp_path):
    prepared = _prepared()
    with pytest.raises(bx.BookSimExecutionError, match="timed out"):
        _execute(tmp_path, prepared=prepared,
                 runner=_runner_for(prepared, timed_out=True))
    with pytest.raises(bx.BookSimExecutionError, match="exited 3"):
        _execute(tmp_path, prepared=prepared,
                 runner=_runner_for(prepared, returncode=3))

def test_injected_runner_never_produces_reusable_evidence(tmp_path):
    prepared = _prepared()
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "run", timeout=10,
        runner=_runner_for(prepared))
    evidence = record.evidence
    assert evidence.transport == ev.EXECUTION_TRANSPORT_TEST_INJECTED
    assert evidence.execution_fidelity == bx.FIDELITY_TEST_INJECTED
    with pytest.raises(ev.BackendEvidenceError, match="supervised production"):
        ev.admit_for_certified_product(evidence)
    with pytest.raises(ev.BackendEvidenceError, match="supervised production"):
        ev.verify_reusable_record(
            record, prepared_id=prepared.prepared_id(),
            config_sha256=evidence.config_sha256,
            trace_sha256=evidence.trace_sha256,
            binary_sha256=evidence.binary_sha256)

def test_route_observation_is_never_claimed_as_observed(tmp_path):
    record = _execute(tmp_path)
    assert record.evidence.route_observation \
        == bx.ROUTE_OBSERVATION_QUALIFIED_ONLY
    blob = str(record.evidence.to_dict())
    assert "route_equivalence" not in blob
    assert "EXACT" not in blob

def test_attempt_metadata_does_not_move_scientific_identity(tmp_path):
    record = _execute(tmp_path)
    other = dataclasses.replace(
        record.attempt, wall_time_s=999.0, run_dir="/elsewhere",
        binary_path="/other/booksim", host="other-host")
    assert other.to_dict() != record.attempt.to_dict()
    assert record.evidence.evidence_id() \
        == dataclasses.replace(record.evidence).evidence_id()
    payload = record.evidence.scientific_payload()
    for token in ("wall_time", "run_dir", "binary_path", "host", "command"):
        assert token not in payload

def test_evidence_bytes_tamper_and_transplant_are_refused(tmp_path):
    prepared = _prepared()
    record = _execute(tmp_path, prepared=prepared)
    assert record.ref is not None
    ev.read_verified_evidence(record.ref)

    path = Path(record.ref.path)
    original = path.read_bytes()
    path.write_bytes(original.replace(b"777", b"999"))
    with pytest.raises(ev.BackendEvidenceError, match="modified after execution"):
        ev.read_verified_evidence(record.ref)
    path.write_bytes(original)

    supervised = ev.ExecutionRecord(
        evidence=dataclasses.replace(
            record.evidence,
            transport=ev.EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
            execution_fidelity=bx.FIDELITY_QUALIFIED,
            producer_source_revision="a" * 40,
            producer_dirty=False,
            build_manifest_sha256="c" * 64,
            build_recipe_version=ev.BOOKSIM_BUILD_RECIPE_VERSION,
            route_observation=bx.ROUTE_OBSERVATION_OBSERVED,
            route_dump_sha256="d" * 64),
        attempt=record.attempt)
    ok = ev.verify_reusable_record(
        supervised, prepared_id=record.evidence.prepared_id,
        config_sha256=record.evidence.config_sha256,
        trace_sha256=record.evidence.trace_sha256,
        binary_sha256=record.evidence.binary_sha256)
    assert ok.prepared_id == record.evidence.prepared_id

    from veritx_dse.model.compile_model import TopologyFamily
    other_prepared = prepare_booksim_input(
        _parents(family=TopologyFamily.CONCENTRATED_MESH, anynet=True)[1])
    assert other_prepared.prepared_id() != record.evidence.prepared_id
    with pytest.raises(ev.BackendEvidenceError, match="prepared_id"):
        ev.verify_reusable_record(
            supervised, prepared_id=other_prepared.prepared_id,
            config_sha256=record.evidence.config_sha256,
            trace_sha256=record.evidence.trace_sha256,
            binary_sha256=record.evidence.binary_sha256)
    with pytest.raises(ev.BackendEvidenceError, match="different BookSim binary"):
        ev.verify_reusable_record(
            supervised, prepared_id=record.evidence.prepared_id,
            config_sha256=record.evidence.config_sha256,
            trace_sha256=record.evidence.trace_sha256,
            binary_sha256="f" * 64)
    with pytest.raises(ev.BackendEvidenceError, match="input digests"):
        ev.verify_reusable_record(
            supervised, prepared_id=record.evidence.prepared_id,
            config_sha256="0" * 64,
            trace_sha256=record.evidence.trace_sha256,
            binary_sha256=record.evidence.binary_sha256)

def test_naked_path_is_never_reusable(tmp_path):
    record = _execute(tmp_path)
    assert record.ref is not None
    with pytest.raises(ev.BackendEvidenceError, match="EvidenceRef"):
        ev.read_verified_evidence(record.ref.path)
    with pytest.raises(ev.BackendEvidenceError, match="cannot be reused"):
        ev.read_reusable_record(record.ref.path)

def test_write_evidence_refuses_to_overwrite_a_claim(tmp_path):
    ev.write_evidence(tmp_path, {"a": 1})
    ev.write_evidence(tmp_path, {"a": 1})
    with pytest.raises(ev.BackendEvidenceError, match="refusing to overwrite"):
        ev.write_evidence(tmp_path, {"a": 2})

def test_non_finite_stats_are_refused_at_evidence_construction():
    with pytest.raises(ev.BackendEvidenceError, match="finite"):
        ev.require_finite(float("nan"), "x")
    with pytest.raises(ev.BackendEvidenceError, match="finite"):
        ev.require_finite(float("inf"), "x")

def _real_binary() -> Path | None:
    for candidate in REAL_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None

_requires_binary = pytest.mark.skipif(
    _real_binary() is None, reason="no BookSim binary available")

def _execute_real(tmp_path, *, anynet=False):
    from veritx_dse.model.compile_model import TopologyFamily
    if anynet:
        _, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                              anynet=True)
    else:
        _, parents = _parents()
    prepared = prepare_booksim_input(parents)
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_real_binary(),
        run_dir=tmp_path / "run", timeout=600)
    return prepared, record

@_requires_binary
def test_real_native_mesh_execution_gate(tmp_path):
    prepared, record = _execute_real(tmp_path)
    evidence = record.evidence
    assert record.attempt.returncode if hasattr(record.attempt, "returncode") \
        else True
    assert evidence.exit_status == 0
    assert evidence.stats["loaded_trace_packets"] == prepared.expected_packets
    injected = evidence.stats["injected_trace_packets"]
    assert injected in (None, prepared.expected_packets)
    assert evidence.stats["completion_cycles"] > 0
    assert evidence.route_observation == bx.ROUTE_OBSERVATION_OBSERVED
    assert evidence.route_dump_sha256 is not None
    assert evidence.to_dict()["evidence_id"] == evidence.evidence_id()
    print(f"\nmesh prepared_id={prepared.prepared_id()[:20]} "
          f"binary={evidence.binary_sha256[:20]} "
          f"completion={evidence.stats['completion_cycles']} "
          f"loaded={evidence.stats['loaded_trace_packets']} "
          f"injected={injected} evidence={evidence.evidence_id()[:20]}")

@_requires_binary
def test_real_anynet_execution_gate(tmp_path):
    prepared, record = _execute_real(tmp_path, anynet=True)
    from veritx_dse.backend.booksim_projection import parse_config_values
    values = parse_config_values(prepared.config_text)
    assert values["topology"] == "anynet"
    assert values["routing_function"] == "min"
    assert f"{values['routing_function']}_{values['topology']}" == "min_anynet"
    assert record.evidence.exit_status == 0
    assert record.evidence.stats["loaded_trace_packets"] \
        == prepared.expected_packets
    assert record.evidence.stats["completion_cycles"] > 0
    assert record.evidence.route_observation \
        == bx.ROUTE_OBSERVATION_OBSERVED
    assert record.evidence.route_dump_sha256 is not None
    print(f"\nanynet completion="
          f"{record.evidence.stats['completion_cycles']} "
          f"latency={record.evidence.stats['packet_latency_avg']}")

@_requires_binary
def test_real_repeat_run_scientific_evidence_is_identical(tmp_path):
    prepared, first = _execute_real(tmp_path / "a")
    _, second = _execute_real(tmp_path / "b")
    assert first.evidence.evidence_id() == second.evidence.evidence_id()
    assert first.attempt.run_dir != second.attempt.run_dir
    assert first.evidence.stats == second.evidence.stats

@_requires_binary
def test_real_late_trace_event_is_not_truncated(tmp_path):
    """A deliberately late event still injects under the declared schedule."""
    from veritx_dse.workload.graph import (
        KIND_COLLECTIVE, KIND_COMPUTE, KIND_P2P, OperationNode,
        WorkloadGraph, collective_detail, compute_detail, p2p_detail,
    )
    from veritx_dse.workload.messages import LogicalMessageArtifactV2
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2
    from veritx_dse.backend import booksim_projection as bp
    compiled = _parents()[0]
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism, participant_count=16,
        operations=(
            OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                          detail=compute_detail(duration_ns=10000,
                                                participant_count=16)),
            OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                          deps=("pre",),
                          detail=collective_detail(
                              collective_kind="ALLREDUCE",
                              participants=tuple(range(16)),
                              payload_bytes=1024, participant_count=16)),
            OperationNode(operation_id="late", kind=KIND_P2P, deps=("ar",),
                          detail=p2p_detail(role="TRANSFER", src_rank=0,
                                            dst_rank=15, payload_bytes=4096,
                                            participant_count=16)),
        ))
    logical = LogicalMessageArtifactV2(graph=graph)
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        inventory=compiled.inventory, packet_format=compiled.packet_format)
    _, base = _parents()
    parents = dataclasses.replace(base, physical_traffic=traffic)
    prepared = bp.prepare_booksim_input(parents)
    schedule = bp.trace_schedule(traffic)
    assert schedule["sample_period"] * schedule["max_samples"] \
        >= schedule["max_timestamp"] + 1
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_real_binary(),
        run_dir=tmp_path / "run", timeout=600)
    assert record.evidence.stats["loaded_trace_packets"] \
        == schedule["expected_packets"]
    injected = record.evidence.stats["injected_trace_packets"]
    assert injected in (None, schedule["expected_packets"])


def test_observed_watch_plan_spreads_samples_across_the_run():
    """A prefix of packet ids is a cold-start sample, not a sample of the run."""
    from veritx_dse.backend.booksim_execution import observed_watch_plan
    trace = "\n".join(f"0 {index} 1 1 8" for index in range(8928)) + "\n"
    ids, plan = observed_watch_plan(trace, budget=96)
    assert plan["declared_packets"] == 8928
    assert plan["stride"] == 93
    assert plan["sampled_packets"] == len(ids) == 96
    assert ids[0] == 0 and ids[-1] > 8800
    assert ids == sorted(set(ids))
    # The rule is recorded, so a reader can reproduce or challenge the sample.
    assert "every 93th" in plan["rule"]


def test_observed_watch_plan_handles_short_and_empty_traces():
    from veritx_dse.backend.booksim_execution import observed_watch_plan
    ids, plan = observed_watch_plan("0 0 1 1 8\n\n# comment\n% comment\n", budget=96)
    assert ids == [0]
    assert plan["stride"] == 1 and plan["declared_packets"] == 1
    ids, plan = observed_watch_plan("", budget=96)
    assert ids == []
    assert plan["declared_packets"] == 0 and plan["stride"] is None


def test_amendment_writes_only_the_sampled_watch_ids():
    from veritx_dse.backend.booksim_execution import amend_config_for_series
    amended = amend_config_for_series(
        "topology=mesh;\n", sample_period_cycles=10, run_hash="a" * 64,
        binary_sha256="b" * 64, link_capacity=1, trace_sha256="c" * 64,
        config_sha256="d" * 64, watch_packet_ids=(0, 47, 94))
    assert "watch_out = observed_hops.log;" in amended
    assert "watch_packets = {0,47,94};" in amended
    # An unsampled call must not leave a watch file behind.
    plain = amend_config_for_series(
        "topology=mesh;\n", sample_period_cycles=10, run_hash="a" * 64,
        binary_sha256="b" * 64, link_capacity=1, trace_sha256="c" * 64,
        config_sha256="d" * 64)
    assert "watch_packets" not in plain and "watch_out" not in plain
