"""Slice 37 — request-driven certified serving orchestration loop (§11/§14).

The gates here are *request-level*: a real JSONL goes through the real
vendored ``Router``/``Scheduler``/``Batch``, into a qualified canonical round,
back out through real ``Scheduler.add_done`` retirement, and the TTFT/latency
that come out are the ones the vendored ``Request`` set.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

import pytest

LMS = Path("/home/datavex/veritx-integration/third_party/llmservingsim")
if str(LMS) not in sys.path:
    sys.path.insert(0, str(LMS))

from test_backend_astra_namespace import _namespace as _astra_namespace
from test_serving_canonical import BUILT_FROM_SOURCE, _qualified

from veritx_dse.backend import canonical_serving as cs
from veritx_dse.backend import serving_round as sround
from veritx_dse.simulation import serving_loop as sl
from veritx_dse.simulation import serving_runtime as sr

MODEL = "meta-llama/Llama-3.1-8B"
REPO = Path(__file__).resolve().parents[4]


# ── fixtures ──────────────────────────────────────────────────────────────

def _loop_fixture(*, instance_count=4, mode=cs.MODE_REPLAY_ONLY):
    """qualified machine + serving binding + virtual NPU namespace + backend."""
    compiled, projection, machine, binding, ns = _astra_namespace(
        granularity="collectives")
    _, _, serving = _qualified(instance_count=instance_count,
                               granularity="collectives")
    npus = sl.VirtualNpuNamespace(binding=serving)
    # a LIVE backend must carry the real producer identity: the digest is
    # validated against the binary on disk, so the dummy-digest convention is
    # only valid for replay mode
    if mode == cs.MODE_LIVE_CANONICAL:
        from veritx_dse.backend.producer import resolve_producer_identity
        identity = resolve_producer_identity(BUILT_FROM_SOURCE)
        backend = cs.CanonicalServingNetworkBackend(
            machine=machine, binding=serving, astra_binary=str(BUILT_FROM_SOURCE),
            astra_binary_sha256=identity.binary_sha256,
            astra_binary_size=identity.binary_size,
            astra_source_revision=identity.source_revision,
            execution_mode=mode)
    else:
        backend = cs.CanonicalServingNetworkBackend(
            machine=machine, binding=serving, astra_binary="/bin/true",
            astra_binary_sha256="a" * 64, astra_binary_size=1,
            astra_source_revision=None, execution_mode=mode)
    lowering = sl.CanonicalLowering(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    return machine, ns, serving, npus, backend, lowering


def _profile(**overrides):
    base = dict(model=MODEL, collective_bytes_per_rank=4096,
                compute_base_ns=10_000, compute_per_token_ns=1_000)
    base.update(overrides)
    return sl.CertifiedServiceProfile(**base)


class LedgerSession:
    """Scripted canonical session that emits comm lines *and* a real ledger."""

    def __init__(self, argv, *, cwd=None, endpoints=(), members=(),
                 comm_endpoints=None, cycles=4242, comm=7,
                 collective_bytes=4096, ledger_type=0, inject=None,
                 drop_ledger=False):
        self.argv = argv
        self.cwd = cwd
        self._endpoints = tuple(endpoints)
        self._comm_endpoints = tuple(
            endpoints if comm_endpoints is None else comm_endpoints)
        self._members = tuple(members)
        self._cycles = cycles
        self._comm = comm
        self._size = collective_bytes
        self._type = ledger_type
        self._inject = inject
        self._drop_ledger = drop_ledger

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read_startup(self):
        return sr.BackendReply(
            ["[workload] sys[0] finished, 1 cycles\n", "Waiting"], "Waiting")

    def command(self, line, *, expect_reply=True, timeout=None):
        if not expect_reply:
            return None
        lines = [f"[workload] sys[{e}] finished, {self._cycles} cycles, "
                 f"exposed communication {self._cycles} cycles."
                 for e in self._endpoints]
        lines.append("Waiting")
        return sr.BackendReply(lines, "Waiting")

    def stderr_text(self):
        rows = [f"[statistics] sys[{e}], Comm time: {self._comm}\n"
                for e in self._comm_endpoints]
        if self._inject is not None:
            rows.append(f"[trace] All 0 cycles, injected={self._inject} — "
                        "draining\n")
        if not self._drop_ledger:
            members = ",".join(str(m) for m in self._members)
            for rank in self._members:
                rows.append(
                    f"[LEDGER][COLL_SUBMIT] rank={rank} astra_node={rank} "
                    f"comm_type={self._type} comm_size={self._size} "
                    f"priority=0 involved_dims=[1,1,1,1] "
                    f"group_members=[{members}] tick=0\n")
        return "".join(rows)


def _session_factory(**kwargs):
    def factory(argv, cwd=None):
        return LedgerSession(argv, cwd=cwd, **kwargs)
    return factory


def _write_trace(directory: Path, rows) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dataset = directory / "requests.jsonl"
    dataset.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return dataset


def _run(tmp_path, rows, *, instance_count=4, req_num=None, session=None,
         expected_requests=None, mode=cs.MODE_REPLAY_ONLY, **overrides):
    """Drive a real JSONL through the loop with a scripted canonical round."""
    machine, ns, serving, npus, backend, lowering = _loop_fixture(
        instance_count=instance_count, mode=mode)
    profile = _profile(**overrides.pop("profile", {}))
    req_num = len(rows) if req_num is None else req_num
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=req_num)
    router = sl.build_router(profile=profile, schedulers=schedulers,
                             req_num=req_num)
    dataset = _write_trace(tmp_path / "trace", rows)
    load_dir = tmp_path / "load"
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=load_dir)
    kwargs = dict(endpoints=ns.participant_endpoints(),
                  members=ns.participant_endpoints())
    kwargs.update(session or {})
    result = sl.run_request_driven_service(
        backend=backend, machine=machine, profile=profile, npus=npus,
        router=router, schedulers=schedulers, run_dir=tmp_path / "run",
        workload_id="wl/loop-test", lowering=lowering,
        session_factory=_session_factory(**kwargs),
        expected_requests=len(rows) if expected_requests is None
        else expected_requests)
    return result, (machine, ns, serving, npus, backend, lowering), schedulers


def _real_batch(*, batch_id_seed=0):
    from serving.core.scheduler import Scheduler
    scheduler = Scheduler(
        model=MODEL, node_id=0, instance_id=0, max_num_seqs=8,
        max_num_batched_tokens=1024, num_npus=4, tp_size=4, pp_size=1,
        npu_mem=1000, cpu_mem=1000, start_npu=0, pd_type=None, fp=1,
        block_size=16, req_num=1, prioritize_prefill=False,
        enable_prefix_caching=False, enable_prefix_sharing=False,
        prefix_pool=None, prefix_storage=0)
    scheduler.add_request([batch_id_seed, MODEL, 16, 8, 0, 0])
    return scheduler, scheduler.schedule(current=0, sys=0)


# ── virtual NPU namespace (the contiguity problem) ────────────────────────

def test_virtual_npu_spans_are_contiguous_and_cover_every_instance():
    _, ns, serving, npus, _, _ = _loop_fixture(instance_count=4)
    assert npus.num_npus == 4
    assert [npus.start_npu(i) for i in range(4)] == [0, 4, 8, 12]
    # contiguous, non-overlapping, dense
    covered = [n for i in range(4) for n in npus.span(i)]
    assert covered == list(range(npus.virtual_npu_count))
    assert npus.virtual_npu_count == ns.participant_count


def test_add_done_quorum_is_the_span_ends_not_the_rank_set():
    """The scheduler needs start_npu and start_npu+num_npus-1 to retire."""
    _, _, serving, npus, _, _ = _loop_fixture(instance_count=4)
    assert npus.quorum_sys(0) == (0, 3)
    assert npus.quorum_sys(3) == (12, 15)
    # ...and that span is not the instance's rank set, which is permuted
    assert set(npus.quorum_sys(1)) != set(serving.instance_for(1).ranks)


def test_virtual_npu_translates_to_permuted_canonical_ranks():
    _, ns, serving, npus, _, _ = _loop_fixture(instance_count=4)
    assert any(r != e for r, e in ns.rank_to_endpoint)
    for npu in range(npus.virtual_npu_count):
        rank = npus.rank_of_npu(npu)
        assert npus.npu_of_rank(rank) == npu           # round trip
        assert npus.endpoint_of_npu(npu) == ns.endpoint_for(rank)
        assert npus.instance_of_npu(npu) == serving.instance_of_rank(rank)
    # the translation is a permutation of the canonical ranks, not a relabel
    assert npus.canonical_ranks() == tuple(range(ns.participant_count))
    assert npus.canonical_endpoints() == ns.participant_endpoints()
    assert not all(npus.rank_of_npu(n) == n
                   for n in range(npus.virtual_npu_count))


def test_virtual_npu_namespace_is_content_addressed():
    _, _, _, npus, _, _ = _loop_fixture(instance_count=4)
    _, _, _, same, _, _ = _loop_fixture(instance_count=4)
    assert npus.translation_id() == same.translation_id()
    assert npus.translation_id().startswith("sha256:")


def test_virtual_npu_refuses_heterogeneous_instances():
    _, ns, _, _, _, _ = _loop_fixture(instance_count=4)
    uneven = cs.ServingNamespaceBinding(
        namespace=ns,
        instances=(cs.ServingInstance(0, (0, 1, 2)),
                   cs.ServingInstance(1, tuple(range(3, 16)))),
        serving_config_id="cfg/uneven")
    with pytest.raises(sl.ServingLoopError, match="homogeneous"):
        sl.VirtualNpuNamespace(binding=uneven)


def test_virtual_npu_refuses_out_of_range_npu():
    _, _, _, npus, _, _ = _loop_fixture(instance_count=4)
    with pytest.raises(sl.ServingLoopError, match="outside"):
        npus.rank_of_npu(npus.virtual_npu_count)
    with pytest.raises(sl.ServingLoopError, match="outside"):
        npus.instance_of_npu(-1)


# ── round plan over a whole service step ──────────────────────────────────

def test_plan_from_round_reads_only_real_batch_fields():
    _, first = _real_batch(batch_id_seed=0)
    _, second = _real_batch(batch_id_seed=1)
    plan = sround.plan_from_round(
        round_id=5, batches={0: first, 1: second},
        participant_ranks=range(16), collective_kind="ALLREDUCE",
        collective_bytes=4096, compute_ns=20_000)
    assert plan.batch_id == 5
    assert plan.instance_id == -1                 # a round is not one instance
    assert plan.phase == "prefill"
    assert plan.tokens == first.total_len + second.total_len
    assert len(plan.request_ids) == 2
    blob = json.dumps(plan.identity_dict(), sort_keys=True)
    for forbidden in ("endpoint", "npu", "router", "booksim", "chakra"):
        assert forbidden not in blob.lower()


def test_plan_from_round_binds_every_contributing_batch_and_request():
    _, first = _real_batch(batch_id_seed=0)
    base = sround.plan_from_round(
        round_id=1, batches={0: first}, participant_ranks=range(16),
        collective_kind="ALLREDUCE", collective_bytes=4096, compute_ns=10_000)
    other = sround.plan_from_round(
        round_id=2, batches={0: first}, participant_ranks=range(16),
        collective_kind="ALLREDUCE", collective_bytes=4096, compute_ns=10_000)
    assert base.plan_id() != other.plan_id()      # the round id is bound
    assert any("inst0" in rid for rid in base.request_ids)


def test_plan_from_round_refuses_empty_or_non_batch_input():
    with pytest.raises(sround.ServingRoundError, match="at least one real"):
        sround.plan_from_round(
            round_id=0, batches={}, participant_ranks=range(4),
            collective_kind="ALLREDUCE", collective_bytes=1, compute_ns=1)
    with pytest.raises(sround.ServingRoundError, match="integer batch_id"):
        sround.plan_from_round(
            round_id=0, batches={0: object()}, participant_ranks=range(4),
            collective_kind="ALLREDUCE", collective_bytes=1, compute_ns=1)


def test_round_spans_the_full_participant_set(tmp_path):
    """The certified profile's one-group constraint, asserted explicitly."""
    machine, ns, serving, npus, backend, lowering = _loop_fixture(
        instance_count=4)
    _, batch = _real_batch()
    plan = sround.plan_from_round(
        round_id=0, batches={0: batch}, participant_ranks=npus.canonical_ranks(),
        collective_kind="ALLREDUCE", collective_bytes=4096, compute_ns=10_000)
    assert plan.participant_ranks == tuple(range(ns.participant_count))
    projection = plan.to_round_projection(
        resolved_fabric=lowering.resolved_fabric, mapping=lowering.mapping,
        attachment=lowering.attachment, parallelism=lowering.parallelism)
    staged = backend.stage_round(workload=projection, directory=tmp_path)
    assert tuple(e for e, _ in staged.endpoint_files) \
        == ns.participant_endpoints()
    qualification, _ = sround.qualify_round(
        machine=machine, plan=plan, backend=backend, staged=staged,
        directory=tmp_path, resolved_fabric=lowering.resolved_fabric,
        mapping=lowering.mapping, attachment=lowering.attachment,
        parallelism=lowering.parallelism)
    assert qualification.expansion_authority == cs.EXPANSION_AUTHORITY_ASTRA


# ── the upstream '../' load quirk, handled deliberately ───────────────────

def test_load_request_trace_resolves_the_upstream_parent_path(tmp_path):
    """Router.load_requests opens f'../{path}'; no ambient chdir survives."""
    _, _, _, npus, _, _ = _loop_fixture(instance_count=4)
    profile = _profile()
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=1)
    router = sl.build_router(profile=profile, schedulers=schedulers, req_num=1)
    dataset = _write_trace(tmp_path / "elsewhere" / "nested",
                           [{"input_toks": 8, "output_toks": 2,
                             "arrival_time_ns": 0}])
    before = Path.cwd()
    returned = sl.load_request_trace(router=router, dataset=dataset,
                                     load_directory=tmp_path / "loaddir")
    assert returned == dataset.resolve()
    assert Path.cwd() == before                  # cwd restored, never ambient
    assert router.has_pending_requests()
    assert router.route_arrived_requests(0) == 1
    assert sum(len(s.request) for s in schedulers) == 1


def test_load_request_trace_refuses_a_missing_dataset(tmp_path):
    _, _, _, npus, _, _ = _loop_fixture(instance_count=4)
    profile = _profile()
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=1)
    router = sl.build_router(profile=profile, schedulers=schedulers, req_num=1)
    with pytest.raises(sl.ServingLoopError, match="trace not found"):
        sl.load_request_trace(router=router,
                              dataset=tmp_path / "absent.jsonl",
                              load_directory=tmp_path / "load")


# ── the ledger filter (regression for a real Slice-36 bug) ────────────────

def test_ledger_filter_matches_the_tag_the_runtime_actually_emits():
    """The runtime emits [LEDGER][COLL_SUBMIT]; a [LEDGER][COLL] prefix match
    matches nothing and silently disables §9 validation."""
    line = ("[LEDGER][COLL_SUBMIT] rank=0 astra_node=0 comm_type=0 "
            "comm_size=4096 priority=0 involved_dims=[1,1,1,1] "
            "group_members=[0,1] tick=0")
    assert sr.collective_ledger_lines("noise\n" + line + "\n") == (line,)
    # the other ledger tags must not be mistaken for a submission
    assert sr.collective_ledger_lines(
        "[LEDGER][COLL_COMPLETE] rank=0\n[LEDGER][STATE] round=1\n") == ()
    parsed = sround.parse_collective_ledger(
        sr.collective_ledger_lines(line))
    assert len(parsed) == 1 and parsed[0].comm_size == 4096


# ── the loop: real trace -> real rounds -> real service metrics ───────────

def test_real_jsonl_is_driven_to_real_ttft_and_latency(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0}]
    result, _, schedulers = _run(tmp_path, rows, instance_count=4)
    assert len(result.requests) == 2
    assert len(result.rounds) >= 2                # prefill + decode rounds
    for request in result.requests:
        # these are the vendored Request's own numbers, not ours
        assert request.ttft_ns > 0
        assert request.end_ns == request.arrival_ns + request.latency_ns
        assert request.end_ns >= request.ttft_ns
        assert request.latency_ns == request.end_ns - request.arrival_ns
    # the clock is the sum of the fabric's own cycle counts
    assert result.clock == sum(r.backend_cycles for r in result.rounds)
    # every request is really retired in its scheduler
    done = sorted(int(r.id) for s in schedulers for r in s.done)
    assert done == [0, 1]


def test_arrival_times_actually_gate_service(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 3, "arrival_time_ns": 9000}]
    result, _, _ = _run(tmp_path, rows, instance_count=4)
    late = next(r for r in result.requests if r.arrival_ns == 9000)
    early = next(r for r in result.requests if r.arrival_ns == 0)

    def round_of(request_id):
        for record in result.rounds:
            if request_id in record.retired_request_ids:
                return record.round_index
        raise AssertionError(f"{request_id} was never retired")

    # the late request cannot be served before its arrival is even routable
    assert late.request_id not in result.rounds[0].retired_request_ids
    assert round_of(late.request_id) > round_of(early.request_id)
    # and its first token is measured from *its* arrival, not the run start
    assert late.ttft_ns > 0
    assert late.end_ns > late.arrival_ns
    # no round that finished before the arrival could have served it
    for record in result.rounds:
        if record.clock_after <= late.arrival_ns:
            assert late.request_id not in record.retired_request_ids


def test_evidence_carries_real_round_evidence_ids_and_service_metrics(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0}]
    result, (machine, ns, serving, npus, backend, _), _ = _run(
        tmp_path, rows, instance_count=4)
    evidence = result.evidence
    assert evidence.request_count == 1
    assert evidence.rounds == len(result.rounds)
    assert evidence.backend_evidence_ids == tuple(
        e.evidence_id() for e in result.round_evidence)
    assert all(eid.startswith("sha256:") for eid in evidence.backend_evidence_ids)
    # the synthetic backend_id:round_index form is gone
    assert all(":" not in eid.split("sha256:")[-1]
               for eid in evidence.backend_evidence_ids)
    assert evidence.machine_id == machine.machine_id()
    assert evidence.namespace_id == ns.namespace_id()
    assert evidence.instances_with_completions == (0, 1, 2, 3)
    assert evidence.every_instance_served()
    evidence.assert_all_instances_served()
    assert result.virtual_npu_id == npus.translation_id()
    assert result.profile_id == _profile().profile_id()


def test_service_run_identity_is_content_addressed(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0}]
    first, _, _ = _run(tmp_path / "a", rows, instance_count=4)
    second, _, _ = _run(tmp_path / "b", rows, instance_count=4)
    # no paths, pids or wall time may enter the scientific identity
    assert first.run_id() == second.run_id()
    blob = json.dumps(first.identity_dict(), sort_keys=True)
    for token in ("/tmp", "pid", "run_dir", "wall_time", "elapsed"):
        assert token not in blob


def test_a_round_that_serves_one_instance_still_spans_all_of_them(tmp_path):
    """A full-participant round exercises idle instances too -- recorded, not
    silently treated as their work."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    result, _, _ = _run(tmp_path, rows, instance_count=4)
    assert len(result.rounds) == 1
    first = result.rounds[0]
    # RR routes the single request to instance 0, so 1..3 had no batch
    assert first.batch_ids == ((0, 0),)
    assert first.idle_instances == (1, 2, 3)
    # ...and no request was retired for an instance that dispatched nothing
    assert first.retired_request_ids == ("0",)
    assert result.requests[0].instance_id == 0


def test_a_round_that_does_not_exercise_every_instance_refuses(tmp_path):
    """The full-participant claim is verified, not assumed."""
    machine, ns, serving, npus, backend, lowering = _loop_fixture(
        instance_count=4)
    profile = _profile()
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=1)
    router = sl.build_router(profile=profile, schedulers=schedulers, req_num=1)
    dataset = _write_trace(tmp_path / "trace", rows)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    all_endpoints = ns.participant_endpoints()
    silent = set(serving.endpoints_of(3))
    with pytest.raises(sl.ServingLoopError, match="reported no endpoint work"):
        sl.run_request_driven_service(
            backend=backend, machine=machine, profile=profile, npus=npus,
            router=router, schedulers=schedulers, run_dir=tmp_path / "run",
            workload_id="wl/partial", lowering=lowering,
            session_factory=_session_factory(
                endpoints=all_endpoints, members=all_endpoints,
                comm_endpoints=tuple(e for e in all_endpoints
                                     if e not in silent)))


def test_every_instance_gets_served_when_the_trace_spreads(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}
            for _ in range(4)]
    result, _, _ = _run(tmp_path, rows, instance_count=4)
    assert sorted(r.instance_id for r in result.requests) == [0, 1, 2, 3]
    assert result.evidence.every_instance_served()


def test_ttft_is_monotonic_in_the_round_the_request_was_served(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    result, _, _ = _run(tmp_path, rows, instance_count=4)
    # a one-round trace retires in round 0, so TTFT is exactly the round cost
    assert all(r.ttft_ns == result.rounds[0].backend_cycles
               for r in result.requests)


# ── the loop fails closed, never inventing a result ───────────────────────

def test_a_wrong_collective_size_in_the_ledger_refuses(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sround.ServingRoundError, match="byte-size mismatch"):
        _run(tmp_path, rows, instance_count=4,
             session={"collective_bytes": 4096 + 1})


def test_a_wrong_collective_type_in_the_ledger_refuses(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sround.ServingRoundError, match="collective type"):
        _run(tmp_path, rows, instance_count=4, session={"ledger_type": 2})


def test_a_missing_ledger_refuses(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sround.ServingRoundError, match="never submitted"):
        _run(tmp_path, rows, instance_count=4, session={"drop_ledger": True})


def test_autonomous_fabric_injection_refuses(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(cs.ServingBoundaryError, match="injected"):
        _run(tmp_path, rows, instance_count=4, session={"inject": 42})


def test_a_partial_run_is_not_service_evidence(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sl.ServingLoopError, match="declared 2 requests"):
        _run(tmp_path, rows, instance_count=4, expected_requests=2)


def test_pd_disaggregation_is_refused_not_approximated(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    machine, ns, serving, npus, backend, lowering = _loop_fixture(
        instance_count=4)
    profile = _profile()
    schedulers = list(sl.build_schedulers(profile=profile, npus=npus,
                                          req_num=1))
    schedulers[0].pd_type = "prefill"          # a PD prefill instance
    router = sl.build_router(profile=profile, schedulers=schedulers, req_num=1)
    dataset = _write_trace(tmp_path / "trace", rows)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    with pytest.raises(sl.ServingLoopError, match="PD disaggregation"):
        sl.run_request_driven_service(
            backend=backend, machine=machine, profile=profile, npus=npus,
            router=router, schedulers=schedulers, run_dir=tmp_path / "run",
            workload_id="wl/pd", lowering=lowering,
            session_factory=_session_factory(
                endpoints=ns.participant_endpoints(),
                members=ns.participant_endpoints()))


def test_scheduler_and_instance_counts_must_agree(tmp_path):
    machine, ns, serving, npus, backend, lowering = _loop_fixture(
        instance_count=4)
    profile = _profile()
    schedulers = list(sl.build_schedulers(profile=profile, npus=npus,
                                          req_num=1))[:-1]
    router = sl.build_router(profile=profile, schedulers=schedulers, req_num=1)
    with pytest.raises(sl.ServingLoopError, match="schedulers for"):
        sl.run_request_driven_service(
            backend=backend, machine=machine, profile=profile, npus=npus,
            router=router, schedulers=schedulers, run_dir=tmp_path / "run",
            workload_id="wl/mismatch", lowering=lowering)


# ── the declared profile ──────────────────────────────────────────────────

def test_profile_rejects_an_uncertified_routing_policy():
    with pytest.raises(sl.ServingLoopError, match="routing policy"):
        _profile(routing_policy="CUSTOM")


def test_profile_rejects_nonpositive_quantities():
    with pytest.raises(sl.ServingLoopError, match="max_num_seqs"):
        _profile(max_num_seqs=0)
    with pytest.raises(sl.ServingLoopError, match="positive collective"):
        _profile(collective_bytes_per_rank=0)
    with pytest.raises(sl.ServingLoopError, match="compute model"):
        _profile(compute_base_ns=0)


def test_profile_compute_model_is_declared_and_linear():
    profile = _profile(compute_base_ns=100, compute_per_token_ns=10)
    assert profile.compute_ns(tokens=0) == 100
    assert profile.compute_ns(tokens=50) == 600
    assert profile.collective_bytes(tokens=50) == 4096


def test_profile_identity_changes_with_every_declared_input():
    base = _profile()
    for field, value in (("routing_policy", "LOAD"),
                         ("collective_bytes_per_rank", 8192),
                         ("compute_per_token_ns", 7),
                         ("max_num_seqs", 4)):
        mutated = dataclasses.replace(base, **{field: value})
        assert mutated.profile_id() != base.profile_id(), field


def test_build_schedulers_is_non_disaggregated_by_default():
    _, _, _, npus, _, _ = _loop_fixture(instance_count=4)
    schedulers = sl.build_schedulers(profile=_profile(), npus=npus, req_num=1)
    assert [s.pd_type for s in schedulers] == [None, None, None, None]
    assert [s.start_npu for s in schedulers] == [0, 4, 8, 12]
    assert all(s.num_npus == 4 for s in schedulers)


# ── real live request-driven gate (§14/§15) ───────────────────────────────

_requires_built = pytest.mark.skipif(
    not BUILT_FROM_SOURCE.is_file(),
    reason="current-source ASTRA frontend not built")

#: a live round costs ~2.5 minutes, so the live gate is opt-in: set
#: VERITX_LIVE_SERVING=1 to run a real request trace through the real binary.
_live_enabled = pytest.mark.skipif(
    os.environ.get("VERITX_LIVE_SERVING") != "1",
    reason="set VERITX_LIVE_SERVING=1 to run the live serving loop")


@_requires_built
@_live_enabled
def test_real_live_request_driven_service(tmp_path):
    """A real JSONL drives real ASTRA/BookSim rounds to a real TTFT."""
    from veritx_dse.backend.producer import resolve_producer_identity
    machine, ns, serving, npus, _, lowering = _loop_fixture(
        instance_count=4, mode=cs.MODE_LIVE_CANONICAL)
    identity = resolve_producer_identity(BUILT_FROM_SOURCE)
    backend = cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary=str(BUILT_FROM_SOURCE),
        astra_binary_sha256=identity.binary_sha256,
        astra_binary_size=identity.binary_size,
        astra_source_revision=identity.source_revision,
        execution_mode=cs.MODE_LIVE_CANONICAL)
    profile = _profile()
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    req_num = len(rows)
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=req_num)
    router = sl.build_router(profile=profile, schedulers=schedulers,
                             req_num=req_num)
    dataset = _write_trace(tmp_path / "trace", rows)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    result = sl.run_request_driven_service(
        backend=backend, machine=machine, profile=profile, npus=npus,
        router=router, schedulers=schedulers, run_dir=tmp_path / "run",
        workload_id="wl/live-loop", lowering=lowering, timeout_s=900,
        expected_requests=req_num)
    result.evidence.assert_live()
    result.evidence.assert_all_instances_served()
    assert len(result.requests) == req_num
    for request in result.requests:
        assert request.ttft_ns > 0
        assert request.end_ns >= request.ttft_ns
    assert result.clock == sum(r.backend_cycles for r in result.rounds)
    print(f"\n[live-loop] rounds={len(result.rounds)} clock={result.clock} "
          f"ttft={[r.ttft_ns for r in result.requests]} "
          f"served={result.evidence.instances_with_completions} "
          f"run={result.run_id()[:24]}")


# ── fast pre-flight for the live path ─────────────────────────────────────

def test_live_mode_wiring_is_verified_without_spawning(tmp_path):
    """Seconds-fast sweep of the whole LIVE path with only the subprocess
    swapped out.

    A real ASTRA round costs ~2.5 minutes and the live gate needs several, so
    use this to verify wiring/identity/ledger/metadata cheaply and reserve the
    ``VERITX_LIVE_SERVING=1`` gate for the actual physical execution.
    """
    rows = [{"input_toks": 8, "output_toks": 2, "arrival_time_ns": 0}]
    result, (machine, ns, serving, npus, backend, lowering), schedulers = _run(
        tmp_path, rows, mode=cs.MODE_LIVE_CANONICAL)
    # a real producer identity was resolved and rechecked before spawn
    assert backend.producer is not None
    assert backend.astra_binary_sha256 == backend.producer.binary_sha256
    assert backend.astra_binary_size == backend.producer.binary_size
    backend.recheck_before_spawn()
    # the run is live-classified and reusable, not replay-only
    assert result.evidence.execution_mode == cs.MODE_LIVE_CANONICAL
    assert result.evidence.reusable()
    result.evidence.assert_live()
    # real round evidence, content-addressed, referenced by the top evidence
    assert result.round_evidence
    for evidence in result.round_evidence:
        assert evidence.evidence_id().startswith("sha256:")
        assert evidence.astra_binary_sha256 == backend.astra_binary_sha256
    assert result.evidence.backend_evidence_ids == tuple(
        e.evidence_id() for e in result.round_evidence)
    # real Request metrics, no invented TTFT
    assert result.requests
    for request in result.requests:
        assert request.ttft_ns > 0
        assert request.end_ns >= request.ttft_ns
        assert request.latency_ns >= 0
    # ledger validation ran against the round's projected membership
    assert any(record.evidence_id for record in result.rounds)
