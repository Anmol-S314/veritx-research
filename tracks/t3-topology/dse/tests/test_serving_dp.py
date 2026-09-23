"""Slice 39 — dense data-parallel quorum semantics.

The rule under test throughout: **DP synchronization is not a DP network
collective**.  A synchronized round still contains exactly the per-instance TP
collectives Slice 38 creates; DP only decides *when* a batch may be sent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LMS = Path("/home/datavex/veritx-integration/third_party/llmservingsim")
if str(LMS) not in sys.path:
    sys.path.insert(0, str(LMS))

from test_backend_astra_namespace import _namespace as _astra_namespace
from test_serving_loop import (
    _profile, _run, _session_factory, _write_trace,
)
from test_serving_canonical import BUILT_FROM_SOURCE

from veritx_dse.backend import canonical_serving as cs
from veritx_dse.backend import serving_round as sround
from veritx_dse.simulation import serving_dp as sdp
from veritx_dse.simulation import serving_loop as sl

DP_A = cs.ServingDataParallelGroup("dpA", (0, 1))


# ── fixtures ──────────────────────────────────────────────────────────────

def _dp_fixture(*, participants=4, instance_count=2, groups=None):
    """TP2 replicas over one fixed machine, optionally DP-synchronized."""
    compiled, _projection, machine, _binding, ns = _astra_namespace(
        granularity="collectives", participants=participants)
    instances = tuple(
        cs.ServingInstance(i, (2 * i, 2 * i + 1)) for i in range(instance_count))
    serving = cs.ServingNamespaceBinding(
        namespace=ns, instances=instances, serving_config_id="cfg/dp")
    declared = (cs.ServingDataParallelGroups.build(binding=serving,
                                                   groups=groups)
                if groups is not None else None)
    backend = cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary="/bin/true",
        astra_binary_sha256="a" * 64, astra_binary_size=1,
        astra_source_revision=None, execution_mode=cs.MODE_REPLAY_ONLY)
    lowering = sl.CanonicalLowering(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    fixture = (machine, ns, serving, sl.VirtualNpuNamespace(binding=serving),
               backend, lowering)
    return fixture, declared


def _drive(tmp_path, rows, *, fixture, groups=None, expected=None, **kwargs):
    machine, ns, serving, npus, backend, lowering = fixture
    profile = _profile()
    req_num = len(rows)
    schedulers = sl.build_schedulers(profile=profile, npus=npus,
                                     req_num=req_num)
    router = sl.build_router(profile=profile, schedulers=schedulers,
                             req_num=req_num)
    dataset = _write_trace(tmp_path / "trace", rows)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    result = sl.run_request_driven_service(
        backend=backend, machine=machine, profile=profile, npus=npus,
        router=router, schedulers=schedulers, run_dir=tmp_path / "run",
        workload_id="wl/dp-test", lowering=lowering,
        session_factory=_session_factory(**kwargs),
        expected_requests=req_num if expected is None else expected,
        dp_groups=groups)
    return result, schedulers


def _row(tokens=8):
    return {"input_toks": tokens, "output_toks": 1, "arrival_time_ns": 0}


def _two_batch():
    from serving.core.scheduler import Scheduler
    scheduler = Scheduler(
        model="meta-llama/Llama-3.1-8B", node_id=0, instance_id=0,
        max_num_seqs=8, max_num_batched_tokens=1024, num_npus=2, tp_size=2,
        pp_size=1, npu_mem=1000, cpu_mem=1000, start_npu=0, pd_type=None, fp=1,
        block_size=16, req_num=1, prioritize_prefill=False,
        enable_prefix_caching=False, enable_prefix_sharing=False,
        prefix_pool=None, prefix_storage=0)
    scheduler.add_request([0, scheduler.model, 16, 8, 0, 0])
    return scheduler, scheduler.schedule(current=0, sys=0)


# ── DP group identity ─────────────────────────────────────────────────────

def test_dp_group_identity_is_content_addressed_and_binding_bound():
    fixture, groups = _dp_fixture(groups=(DP_A,))
    _machine_, _ns, serving, _npus, _backend, _lowering = fixture
    assert groups.serving_binding_id == serving.binding_id()
    assert groups.groups_id().startswith("sha256:")
    rebuilt = cs.ServingDataParallelGroups.build(binding=serving,
                                                 groups=(DP_A,))
    assert groups.groups_id() == rebuilt.groups_id()
    assert groups.identity_dict()["groups"] == [DP_A.identity_dict()]


def test_dp_grouping_does_not_touch_the_namespace_or_fabric():
    fixture, groups = _dp_fixture(groups=(DP_A,))
    machine, ns, serving, npus, _backend, _lowering = fixture
    before = (ns.namespace_id(), ns.rank_to_endpoint, ns.participant_mapping_id,
              machine.physical_id(), machine.resolved_fabric_hash,
              machine.prepared_id, ns.endpoint_count, ns.router_count)
    # the grouping only names instances; it cannot change any of these
    assert groups.group_of(0).instance_ids == (0, 1)
    assert (ns.namespace_id(), ns.rank_to_endpoint, ns.participant_mapping_id,
            machine.physical_id(), machine.resolved_fabric_hash,
            machine.prepared_id, ns.endpoint_count, ns.router_count) == before
    assert npus.canonical_endpoints() == ns.participant_endpoints()


def test_independent_instances_may_stay_outside_every_dp_group():
    fixture, groups = _dp_fixture(participants=8, instance_count=4,
                                  groups=(DP_A,))
    _machine_, _ns, _serving, _npus, _backend, _lowering = fixture
    assert groups.is_member(0) and groups.is_member(1)
    assert not groups.is_member(2) and not groups.is_member(3)
    assert groups.group_of(2) is None
    assert groups.group_of(3) is None


def test_dp_group_refuses_unknown_instance():
    fixture, _ = _dp_fixture()
    _machine_, _ns, serving, _npus, _backend, _lowering = fixture
    with pytest.raises(cs.ServingBoundaryError, match="unknown serving instance"):
        cs.ServingDataParallelGroups.build(
            binding=serving,
            groups=(cs.ServingDataParallelGroup("dpA", (0, 7)),))


def test_dp_group_refuses_an_instance_in_two_groups():
    fixture, _ = _dp_fixture(participants=8, instance_count=4)
    _machine_, _ns, serving, _npus, _backend, _lowering = fixture
    with pytest.raises(cs.ServingBoundaryError, match="more than one DP group"):
        cs.ServingDataParallelGroups.build(binding=serving, groups=(
            cs.ServingDataParallelGroup("dpA", (0, 1)),
            cs.ServingDataParallelGroup("dpB", (1, 2))))


def test_dp_group_refuses_duplicate_members_and_singletons():
    with pytest.raises(cs.ServingBoundaryError, match="at least two"):
        cs.ServingDataParallelGroup("dpA", (0,))
    with pytest.raises(cs.ServingBoundaryError, match="repeats a member"):
        cs.ServingDataParallelGroup("dpA", (0, 0))
    with pytest.raises(cs.ServingBoundaryError, match="must be sorted"):
        cs.ServingDataParallelGroup("dpA", (1, 0))
    with pytest.raises(cs.ServingBoundaryError, match="non-empty id"):
        cs.ServingDataParallelGroup("", (0, 1))


def test_dp_group_refuses_duplicate_group_ids():
    fixture, _ = _dp_fixture(participants=8, instance_count=4)
    _machine_, _ns, serving, _npus, _backend, _lowering = fixture
    with pytest.raises(cs.ServingBoundaryError, match="duplicate DP group id"):
        cs.ServingDataParallelGroups.build(binding=serving, groups=(
            cs.ServingDataParallelGroup("dpA", (0, 1)),
            cs.ServingDataParallelGroup("dpA", (2, 3))))


def test_dp_group_refuses_incompatible_tp_widths():
    compiled, _projection, machine, _binding, ns = _astra_namespace(
        granularity="collectives", participants=8)
    serving = cs.ServingNamespaceBinding(
        namespace=ns,
        instances=(cs.ServingInstance(0, (0, 1)),
                   cs.ServingInstance(1, (2, 3, 4, 5, 6, 7))),
        serving_config_id="cfg/mixed")
    with pytest.raises(cs.ServingBoundaryError, match="mixes TP widths"):
        cs.ServingDataParallelGroups.build(
            binding=serving,
            groups=(cs.ServingDataParallelGroup("dpA", (0, 1)),))


# ── padding semantics (exact historical mutations) ────────────────────────

def test_pad_batch_to_max_mutates_exactly_three_fields():
    _scheduler, batch = _two_batch()
    batch.decode_k_list = [7, 7]
    batch.prefill_q_list = [3]
    batch.prefill_k_list = [4]
    batch.q_list = [5]
    batch.requests = ["req"]
    before = (list(batch.decode_k_list), list(batch.prefill_q_list),
              list(batch.prefill_k_list), list(batch.q_list),
              list(batch.requests))
    original = batch.total_len
    kv_before = batch.kv_len
    pad = sdp.pad_batch_to_max(batch, original + 9)
    assert pad == 9
    assert batch.total_len == original + 9
    assert batch.kv_len == kv_before + 9     # 1 per padded token
    assert batch.num_decode == 9
    # the token lists and the request list are deliberately untouched
    assert (batch.decode_k_list, batch.prefill_q_list, batch.prefill_k_list,
            batch.q_list, batch.requests) == before


def test_pad_batch_to_max_is_a_noop_when_already_large_enough():
    _scheduler, batch = _two_batch()
    total, kv, decode = batch.total_len, batch.kv_len, batch.num_decode
    assert sdp.pad_batch_to_max(batch, total - 1) == 0
    assert (batch.total_len, batch.kv_len, batch.num_decode) \
        == (total, kv, decode)


def test_dp_dummy_is_a_real_batch_with_no_user_requests():
    from serving.core.request import Batch
    fixture, _ = _dp_fixture()
    _machine_, _ns, _serving, npus, _backend, _lowering = fixture
    profile = _profile()
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=1)
    dummy = sdp.make_dp_dummy(scheduler=schedulers[1], clock=0,
                              start_npu=npus.start_npu(1))
    assert isinstance(dummy, Batch)
    assert dummy.requests == []
    assert dummy.total_len == sdp.DP_DUMMY_TOTAL_LEN == 1
    assert dummy.sent is False
    assert dummy.batch_id == 0
    assert npus.start_npu(1) in dummy.fired
    # it lives in the real Scheduler lifecycle
    assert dummy in schedulers[1].inflight


def test_dp_dummy_retires_through_add_done_and_clears_inflight():
    fixture, _ = _dp_fixture()
    _machine_, _ns, _serving, npus, _backend, _lowering = fixture
    schedulers = sl.build_schedulers(profile=_profile(), npus=npus, req_num=1)
    scheduler = schedulers[1]
    dummy = sdp.make_dp_dummy(scheduler=scheduler, clock=0,
                              start_npu=npus.start_npu(1))
    for sys_id in npus.quorum_sys(1):
        _p, _g, finished = scheduler.add_done(dummy.batch_id, sys_id, 1000)
        assert finished == []
    assert scheduler.inflight == []
    assert scheduler.done == []
    assert scheduler.request == []


# ── coordinator state model ───────────────────────────────────────────────

def _coordinator():
    fixture, groups = _dp_fixture(groups=(DP_A,))
    _machine_, _ns, _serving, npus, _backend, _lowering = fixture
    return sdp.DpQuorumCoordinator(groups=groups), npus


def test_real_batch_enters_pending_unsent_and_cannot_be_overwritten():
    dp, _npus = _coordinator()
    _scheduler, batch = _two_batch()
    dp.note_real_batch(0, batch)
    assert batch.sent is False            # held, never sent on entry
    assert dp.has_pending() is True
    assert dp.ready_groups() == ()        # one of two members resolved
    assert dp.open_groups() == ("dpA",)
    with pytest.raises(sdp.ServingDpError, match="refusing to overwrite"):
        dp.note_real_batch(0, batch)


def test_a_batch_that_enters_already_sent_refuses():
    dp, _npus = _coordinator()
    _scheduler, batch = _two_batch()
    batch.sent = True
    with pytest.raises(sdp.ServingDpError, match="already marked sent"):
        dp.note_real_batch(0, batch)


def test_dummy_cannot_be_added_over_a_pending_batch():
    dp, npus = _coordinator()
    _scheduler, batch = _two_batch()
    dp.note_real_batch(0, batch)
    fixture, _ = _dp_fixture()
    _m, _n, _s, npus2, _b, _l = fixture
    schedulers = sl.build_schedulers(profile=_profile(), npus=npus2, req_num=1)
    dummy = sdp.make_dp_dummy(scheduler=schedulers[1], clock=0,
                              start_npu=npus2.start_npu(1))
    with pytest.raises(sdp.ServingDpError, match="already holds a pending"):
        dp.add_dummy(group_id="dpA", instance_id=0, dummy=dummy)


def test_dummy_carrying_user_requests_refuses():
    dp, _npus = _coordinator()
    _scheduler, batch = _two_batch()
    batch.requests = ["a-real-request"]
    with pytest.raises(sdp.ServingDpError, match="no user requests"):
        dp.add_dummy(group_id="dpA", instance_id=1, dummy=batch)


def test_a_group_with_no_real_batch_never_opens_or_completes():
    """Gate D: dummies exist only to close an already-open real quorum."""
    dp, _npus = _coordinator()
    assert dp.open_groups() == ()
    assert dp.ready_groups() == ()
    assert dp.complete_ready() == ()
    assert dp.has_pending() is False


def test_all_real_quorum_pads_to_the_group_max_not_the_sum():
    dp, _npus = _coordinator()
    _s1, small = _two_batch()
    _s2, large = _two_batch()
    small.total_len, large.total_len = 8, 41
    dp.note_real_batch(0, small)
    dp.note_real_batch(1, large)
    assert dp.ready_groups() == ("dpA",)
    (completed,) = dp.complete_ready()
    record = completed.record
    assert record.max_total_len == 41
    assert record.dp_sum_total_len == 41        # NOT 82
    assert record.max_total_len != 8 + 41
    assert [(m.instance_id, m.original_total_len, m.padded_total_len)
            for m in record.members] == [(0, 8, 41), (1, 41, 41)]
    assert record.real_members() == record.members
    assert record.dummy_members() == ()
    assert small.total_len == large.total_len == 41
    assert small.sent is True and large.sent is True
    assert dp.has_pending() is False


def test_real_plus_dummy_quorum_pads_the_dummy_up():
    dp, _npus = _coordinator()
    _scheduler, real = _two_batch()
    real.total_len = 17
    dp.note_real_batch(0, real)
    fixture, _ = _dp_fixture()
    _m, _n, _s, npus2, _b, _l = fixture
    schedulers = sl.build_schedulers(profile=_profile(), npus=npus2, req_num=1)
    dummy = sdp.make_dp_dummy(scheduler=schedulers[1], clock=0,
                              start_npu=npus2.start_npu(1))
    dp.add_dummy(group_id="dpA", instance_id=1, dummy=dummy)
    (completed,) = dp.complete_ready()
    assert completed.dummy_instances() == frozenset({1})
    assert [(m.instance_id, m.is_dummy, m.original_total_len,
             m.padded_total_len) for m in completed.record.members] \
        == [(0, False, 17, 17), (1, True, 1, 17)]
    assert dummy.total_len == 17
    assert dummy.requests == []
    assert sorted(completed.batch_map()) == [0, 1]


def test_quorum_record_refuses_a_group_sum():
    with pytest.raises(sround.ServingRoundError, match="max_total_len"):
        sround.DpQuorumRecord(
            group_id="dpA",
            members=(sround.DpMemberRecord(0, 0, False, 8, 16),
                     sround.DpMemberRecord(1, 0, False, 16, 16)),
            max_total_len=16, dp_sum_total_len=32)


def test_quorum_record_refuses_a_singleton_group():
    with pytest.raises(sround.ServingRoundError, match="member"):
        sround.DpQuorumRecord(
            group_id="dpA",
            members=(sround.DpMemberRecord(0, 0, False, 8, 8),),
            max_total_len=8, dp_sum_total_len=8)


# ── round plan: dummy is explicit, arithmetic runs after padding ──────────

def test_dummy_participation_is_explicit_not_inferred_from_empty_requests():
    fixture, _ = _dp_fixture()
    _m, _n, _s, _npus, _b, _l = fixture
    _scheduler, batch = _two_batch()
    batch.requests = []
    with pytest.raises(sround.ServingRoundError, match="no requests"):
        sround.plan_from_round(
            round_id=0, batches={0: batch}, instance_ranks={0: (0, 1)},
            participant_count=4, collective_kind="ALLREDUCE",
            collective_bytes_for=lambda *, tokens: 4096,
            compute_ns_for=lambda *, tokens: 10_000)
    plan = sround.plan_from_round(
        round_id=0, batches={0: batch}, instance_ranks={0: (0, 1)},
        participant_count=4, collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: 4096,
        compute_ns_for=lambda *, tokens: 10_000,
        dummy_instances=frozenset({0}), dp_group_ids={0: "dpA"})
    assert plan.batch_for(0).is_dp_dummy is True
    assert plan.batch_for(0).request_ids == ()


def test_a_real_dp_member_with_no_requests_is_refused():
    """An empty real batch can never masquerade as DP participation."""
    fixture, _ = _dp_fixture()
    _m, _n, _s, _npus, _b, _l = fixture
    _scheduler, batch = _two_batch()
    batch.requests = []
    with pytest.raises(sround.ServingRoundError, match="no requests"):
        sround.plan_from_round(
            round_id=0, batches={0: batch}, instance_ranks={0: (0, 1)},
            participant_count=4, collective_kind="ALLREDUCE",
            collective_bytes_for=lambda *, tokens: 4096,
            compute_ns_for=lambda *, tokens: 10_000,
            dp_group_ids={0: "dpA"})
    # ...and the plan type itself refuses the same lie
    with pytest.raises(sround.ServingRoundError, match="must say so"):
        sround.ServingBatchPlan(
            batch_id=0, instance_id=0, request_ids=(),
            participant_ranks=(0, 1), phase="decode", tokens=8,
            collective_kind="ALLREDUCE", collective_bytes=4096,
            compute_ns=10_000, dp_group_id="dpA")


def test_dp_round_identity_distinguishes_real_from_dummy_at_equal_tokens():
    fixture, _ = _dp_fixture()
    _m, _n, _s, _npus, _b, _l = fixture
    _scheduler, batch = _two_batch()
    batch.total_len = 16
    real = sround.plan_from_round(
        round_id=0, batches={0: batch}, instance_ranks={0: (0, 1)},
        participant_count=4, collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: 4096,
        compute_ns_for=lambda *, tokens: 10_000,
        dp_group_ids={0: "dpA"})
    batch.requests = []
    dummy = sround.plan_from_round(
        round_id=0, batches={0: batch}, instance_ranks={0: (0, 1)},
        participant_count=4, collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: 4096,
        compute_ns_for=lambda *, tokens: 10_000,
        dummy_instances=frozenset({0}), dp_group_ids={0: "dpA"})
    assert real.batch_for(0).tokens == dummy.batch_for(0).tokens == 16
    assert real.plan_id() != dummy.plan_id()


def test_declared_arithmetic_uses_the_padded_tokens():
    """compute/collective inputs are derived AFTER quorum padding."""
    fixture, _ = _dp_fixture()
    _m, _n, _s, _npus, _b, _l = fixture
    _scheduler, batch = _two_batch()
    batch.total_len = 41
    seen: list[int] = []
    plan = sround.plan_from_round(
        round_id=0, batches={0: batch}, instance_ranks={0: (0, 1)},
        participant_count=4, collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: seen.append(tokens) or 4096,
        compute_ns_for=lambda *, tokens: seen.append(tokens) or 10_000)
    assert seen == [41, 41]                    # not 17, not 17+41
    assert plan.batch_for(0).tokens == 41


def test_no_cross_instance_dp_collective_is_ever_projected():
    fixture, _ = _dp_fixture()
    _m, _n, _s, _npus, _b, _l = fixture
    _scheduler, batch = _two_batch()
    plan = sround.plan_from_round(
        round_id=0, batches={0: batch, 1: batch},
        instance_ranks={0: (0, 1), 1: (2, 3)}, participant_count=4,
        collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: 4096,
        compute_ns_for=lambda *, tokens: 10_000,
        dp_group_ids={0: "dpA", 1: "dpA"})
    from test_serving_tp_groups import _project
    compiled = _astra_namespace(granularity="collectives", participants=4)[0]
    projection = plan.to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    memberships = sorted(p for _, _, _, p in projection.collective_operations)
    assert memberships == [(0, 1), (2, 3)]
    assert (0, 1, 2, 3) not in memberships
    for op_id, kind, _payload, _parts in projection.collective_operations:
        assert "dp" not in op_id.lower()
        assert kind == "ALLREDUCE"


# ── end-to-end gates ──────────────────────────────────────────────────────

def test_gate_a_all_real_quorum(tmp_path):
    fixture, groups = _dp_fixture(groups=(DP_A,))
    _machine_, ns, _serving, _npus, _backend, _lowering = fixture
    result, _schedulers = _drive(
        tmp_path, [_row(8), _row(16)], fixture=fixture, groups=groups)
    assert len(result.rounds) == 1
    record = result.rounds[0]
    assert record.dispatched_instances == (0, 1)
    (quorum,) = record.dp_quorums
    assert quorum.max_total_len == 16
    assert quorum.dp_sum_total_len == 16
    assert [(m.instance_id, m.is_dummy, m.original_total_len,
             m.padded_total_len) for m in quorum.members] \
        == [(0, False, 8, 16), (1, False, 16, 16)]
    assert quorum.dummy_members() == ()
    # two separate TP collectives, each on its own instance's ranks
    contract = result.round_evidence[0].collective_contract
    assert len(contract) == 2
    assert len({row.astra_node_id for row in contract}) == 2
    assert sorted(row.endpoints for row in contract) == sorted(
        tuple(sorted(ns.endpoint_for(rank) for rank in (2 * i, 2 * i + 1)))
        for i in range(2))
    assert sorted(r.instance_id for r in result.requests) == [0, 1]
    assert sorted(r.request_id for r in result.requests) == ["0", "1"]


def test_gate_b_real_plus_dummy(tmp_path):
    fixture, groups = _dp_fixture(groups=(DP_A,))
    result, schedulers = _drive(tmp_path, [_row(8)], fixture=fixture,
                                groups=groups)
    record = result.rounds[0]
    # both members are dispatched: a dummy member is NOT an idle instance
    assert record.dispatched_instances == (0, 1)
    assert record.idle_instances == ()
    (quorum,) = record.dp_quorums
    assert [(m.instance_id, m.is_dummy, m.padded_total_len)
            for m in quorum.members] == [(0, False, 8), (1, True, 8)]
    assert quorum.dummy_members()[0].original_total_len \
        == sdp.DP_DUMMY_TOTAL_LEN
    # the dummy's TP group really executed: both instances report completions
    assert result.evidence.instances_with_completions == (0, 1)
    assert len(result.round_evidence[0].collective_contract) == 2
    # ...and the dummy retires nothing
    assert record.retired_request_ids == ("0",)
    assert [r.instance_id for r in result.requests] == [0]
    assert schedulers[1].done == []
    assert schedulers[1].inflight == []


def test_gate_c_independent_replica_is_unaffected(tmp_path):
    fixture, groups = _dp_fixture(participants=8, instance_count=4,
                                  groups=(DP_A,))
    rows = [_row(8) for _ in range(3)]
    result, _schedulers = _drive(tmp_path, rows, fixture=fixture,
                                 groups=groups)
    # instances 2 and 3 are not in the group: they dispatch independently
    assert len(result.rounds) == 1
    assert result.rounds[0].dispatched_instances == (0, 1, 2)
    assert len(result.rounds[0].dp_quorums) == 1
    (quorum,) = result.rounds[0].dp_quorums
    assert [m.instance_id for m in quorum.members] == [0, 1]
    assert sorted(r.instance_id for r in result.requests) == [0, 1, 2]
    # instance 3 is idle, instance 2 is independent: neither is DP-synced
    assert result.rounds[0].idle_instances == (3,)


def test_gate_d_no_work_creates_no_dummy(tmp_path):
    fixture, groups = _dp_fixture(groups=(DP_A,))
    result, schedulers = _drive(tmp_path, [], fixture=fixture, groups=groups)
    assert result.rounds == ()
    assert result.requests == ()
    assert all(s.inflight == [] for s in schedulers)
    assert all(s.done == [] for s in schedulers)


def test_non_dp_run_is_byte_identical_to_slice_38(tmp_path):
    """No declaration => exactly Slice 38, no implicit DP grouping."""
    fixture, _ = _dp_fixture()
    result, _schedulers = _drive(tmp_path, [_row(8), _row(8)], fixture=fixture,
                                 groups=None)
    record = result.rounds[0]
    assert record.dp_quorums == ()
    assert record.dispatched_instances == (0, 1)
    # independent replicas, each retiring its own request
    assert sorted(r.instance_id for r in result.requests) == [0, 1]
    for evidence in result.round_evidence:
        assert evidence.dp_quorums == ()
        assert "dp_quorums" not in evidence.identity_dict()
    # the round plan carries no DP participation either
    assert result.round_evidence[0].identity_dict().get("dp_quorums") is None


def test_dp_semantics_move_the_round_and_evidence_identity(tmp_path):
    """Same traffic, different service semantics => different identity."""
    plain_fixture, _ = _dp_fixture()
    dp_fixture, groups = _dp_fixture(groups=(DP_A,))
    plain, _ = _drive(tmp_path / "plain", [_row(8), _row(8)],
                      fixture=plain_fixture, groups=None)
    synced, _ = _drive(tmp_path / "dp", [_row(8), _row(8)],
                       fixture=dp_fixture, groups=groups)
    assert plain.round_evidence[0].evidence_id() \
        != synced.round_evidence[0].evidence_id()
    assert plain.rounds[0].plan_id != synced.rounds[0].plan_id
    # ...while the physical machine is untouched
    assert plain.evidence.machine_id == synced.evidence.machine_id
    assert plain.evidence.namespace_id == synced.evidence.namespace_id


def test_physical_identity_is_unchanged_by_dp_synchronization(tmp_path):
    fixture, groups = _dp_fixture(groups=(DP_A,))
    machine, ns, _serving, _npus, _backend, _lowering = fixture
    before = {
        "physical_id": machine.physical_id(),
        "resolved_fabric_hash": machine.resolved_fabric_hash,
        "prepared_id": machine.prepared_id,
        "standalone_config_sha256": machine.standalone_config_sha256,
        "route_artifact_hash": machine.route_artifact_hash,
        "vc_resource_hash": machine.vc_resource_hash,
        "packet_format_hash": machine.packet_format_hash,
        "rank_to_endpoint": ns.rank_to_endpoint,
        "machine_files": machine.files(),
    }
    _drive(tmp_path, [_row(8), _row(16)], fixture=fixture, groups=groups)
    assert before["physical_id"] == machine.physical_id()
    assert before["resolved_fabric_hash"] == machine.resolved_fabric_hash
    assert before["prepared_id"] == machine.prepared_id
    assert before["standalone_config_sha256"] \
        == machine.standalone_config_sha256
    assert before["route_artifact_hash"] == machine.route_artifact_hash
    assert before["vc_resource_hash"] == machine.vc_resource_hash
    assert before["packet_format_hash"] == machine.packet_format_hash
    assert before["rank_to_endpoint"] == ns.rank_to_endpoint
    assert before["machine_files"] == machine.files()


def test_pending_dp_work_prevents_false_quiescence(tmp_path):
    """A blocked member must refuse, not report the run as finished.

    The member is blocked by giving it an inflight batch, so no dummy can
    close the quorum.  The held real batch is unsent and must never retire.
    """
    fixture, groups = _dp_fixture(groups=(DP_A,))
    _machine_, _ns, _serving, npus, _backend, _lowering = fixture
    profile = _profile()
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=1)
    # block member 1: an inflight batch means schedule() returns None and no
    # dummy may be created over it
    sdp.make_dp_dummy(scheduler=schedulers[1], clock=0,
                      start_npu=npus.start_npu(1))
    router = sl.build_router(profile=profile, schedulers=schedulers, req_num=1)
    dataset = _write_trace(tmp_path / "trace", [_row(8)])
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    with pytest.raises(sl.ServingLoopError, match="pending DP batch"):
        sl.run_request_driven_service(
            backend=_backend, machine=_machine_, profile=profile, npus=npus,
            router=router, schedulers=schedulers, run_dir=tmp_path / "run",
            workload_id="wl/blocked", lowering=_lowering,
            session_factory=_session_factory(), expected_requests=1,
            dp_groups=groups)


def test_unsent_pending_batch_cannot_retire_or_reach_the_fabric():
    dp, _npus = _coordinator()
    _scheduler, batch = _two_batch()
    dp.note_real_batch(0, batch)
    # not ready: nothing to dispatch, nothing sent, nothing retired
    assert dp.complete_ready() == ()
    assert batch.sent is False
    assert dp.has_pending() is True


def test_endpoint_permutation_remains_active(tmp_path):
    fixture, groups = _dp_fixture(groups=(DP_A,))
    machine, ns, serving, _npus, _backend, _lowering = fixture
    assert any(r != e for r, e in ns.rank_to_endpoint)
    result, _ = _drive(tmp_path, [_row(8)], fixture=fixture, groups=groups)
    for row in result.round_evidence[0].collective_contract:
        ranks = tuple(sorted(rank for rank, endpoint in ns.rank_to_endpoint
                             if endpoint in row.endpoints))
        assert tuple(sorted(ns.endpoint_for(r) for r in ranks)) \
            == row.endpoints
        assert set(row.endpoints) <= set(ns.participant_endpoints())


# ── TP1 boundary ──────────────────────────────────────────────────────────

def test_tp1_dp_is_refused_rather_than_faking_a_collective():
    """A one-rank replica has no TP collective to project.

    The certified serving representation lowers each instance to a TP
    collective, so a TP1 DP member would have to emit a degenerate ALLREDUCE
    over one rank.  Slice 39 refuses that combination at the serving layer
    instead of inventing a collective, and the lowering would refuse it too.
    """
    compiled, _projection, machine, _binding, ns = _astra_namespace(
        granularity="collectives", participants=8)
    serving = cs.ServingNamespaceBinding(
        namespace=ns,
        instances=tuple(cs.ServingInstance(i, (i,)) for i in range(8)),
        serving_config_id="cfg/tp1")
    with pytest.raises(cs.ServingBoundaryError, match="TP width 1"):
        cs.ServingDataParallelGroups.build(
            binding=serving,
            groups=(cs.ServingDataParallelGroup("dpA", (0, 1)),))
    # the refusal is at the serving layer, with an explicit message; the
    # slice does NOT model TP1 DP as a degenerate positive ALLREDUCE


# ── live canonical dense-DP gate (§17) ────────────────────────────────────

import os  # noqa: E402

from test_serving_loop import _backend_for  # noqa: E402

_requires_built = pytest.mark.skipif(
    not BUILT_FROM_SOURCE.is_file(),
    reason="current-source ASTRA frontend not built")
_live_enabled = pytest.mark.skipif(
    os.environ.get("VERITX_LIVE_SERVING") != "1",
    reason="set VERITX_LIVE_SERVING=1 to run the live dense-DP gate")


def _dp_live_fixture(*, participants=4, instance_count=2, groups=None):
    compiled, _projection, machine, _binding, ns = _astra_namespace(
        granularity="collectives", participants=participants)
    instances = tuple(
        cs.ServingInstance(i, (2 * i, 2 * i + 1)) for i in range(instance_count))
    serving = cs.ServingNamespaceBinding(
        namespace=ns, instances=instances, serving_config_id="cfg/dp-live")
    declared = (cs.ServingDataParallelGroups.build(binding=serving,
                                                   groups=groups)
                if groups is not None else None)
    fixture = (machine, ns, serving, sl.VirtualNpuNamespace(binding=serving),
               _backend_for(machine, serving, mode=cs.MODE_LIVE_CANONICAL),
               sl.CanonicalLowering(
                   resolved_fabric=compiled.resolved_fabric,
                   mapping=compiled.mapping,
                   attachment=compiled.attachment,
                   parallelism=compiled.inventory.parallelism))
    return fixture, declared


def _drive_live(tmp_path, rows, *, fixture, groups):
    machine, ns, serving, npus, backend, lowering = fixture
    profile = _profile()
    schedulers = sl.build_schedulers(profile=profile, npus=npus,
                                     req_num=len(rows))
    router = sl.build_router(profile=profile, schedulers=schedulers,
                             req_num=len(rows))
    dataset = _write_trace(tmp_path / "trace", rows)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    result = sl.run_request_driven_service(
        backend=backend, machine=machine, profile=profile, npus=npus,
        router=router, schedulers=schedulers, run_dir=tmp_path / "run",
        workload_id="wl/dp-live", lowering=lowering, timeout_s=900,
        session_factory=None, expected_requests=len(rows),
        dp_groups=groups)
    return result, schedulers


@_requires_built
@_live_enabled
def test_real_live_dense_dp_gate_b_real_plus_dummy(tmp_path):
    """One real DP member + one explicit dummy, on the real fabric.

    Gate B is the valuable one: it proves the dummy actually executes (its TP
    group produces runtime evidence) and retires nothing.
    """
    fixture, groups = _dp_live_fixture(groups=(DP_A,))
    machine, ns, serving, npus, backend, lowering = fixture
    result, schedulers = _drive_live(tmp_path, [_row(8)], fixture=fixture,
                                     groups=groups)
    evidence = result.evidence
    evidence.assert_live()

    record = result.rounds[0]
    (quorum,) = record.dp_quorums
    assert quorum.max_total_len == quorum.dp_sum_total_len == 8
    assert [(m.instance_id, m.is_dummy, m.original_total_len,
             m.padded_total_len) for m in quorum.members] \
        == [(0, False, 8, 8), (1, True, 1, 8)]

    # both members are network-dispatched; the dummy's TP group really ran
    assert record.dispatched_instances == (0, 1)
    assert evidence.instances_with_completions == (0, 1)
    contract = result.round_evidence[0].collective_contract
    assert len(contract) == 2
    assert len({row.astra_node_id for row in contract}) == 2
    ledger = result.round_evidence[0].collective_ledger
    assert len(ledger) == 4                      # 2 TP groups x 2 endpoints
    submitters: dict[int, set] = {}
    for rank, node, _ctype, _members in ledger:
        submitters.setdefault(node, set()).add(rank)
    assert len(submitters) == 2
    assert all(len(peers) == 2 for peers in submitters.values())

    # retirement: the real member only, never the dummy
    assert record.retired_request_ids == ("0",)
    assert [r.instance_id for r in result.requests] == [0]
    assert schedulers[1].done == []
    assert schedulers[1].inflight == []
    assert schedulers[1].request == []
    # no cross-instance collective anywhere
    assert {row.collective_kind for row in contract} == {"ALLREDUCE"}
    assert all(len(row.endpoints) == 2 for row in contract)

    assert set(evidence.autonomous_injection_packets) <= {0, None}
    assert result.clock == sum(r.backend_cycles for r in result.rounds)

    print(f"\n[live-dp] group={quorum.group_id} "
          f"max={quorum.max_total_len} sum={quorum.dp_sum_total_len} "
          f"members="
          f"{[(m.instance_id, 'DUMMY' if m.is_dummy else 'REAL', m.original_total_len, m.padded_total_len) for m in quorum.members]}")
    for instance in serving.instances:
        ranks = tuple(sorted(instance.ranks))
        endpoints = serving.endpoints_of(instance.instance_id)
        print(f"  inst{instance.instance_id} ranks={ranks} "
              f"endpoints={endpoints}")
    for row in contract:
        ranks = tuple(sorted(rank for rank, endpoint in ns.rank_to_endpoint
                             if endpoint in row.endpoints))
        print(f"  op={row.operation_id} node={row.astra_node_id} "
              f"ranks={ranks} endpoints={row.endpoints} kind={row.collective_kind}")
    print(f"  retired={record.retired_request_ids} "
          f"dummy_finished={len(schedulers[1].done)} "
          f"injected={evidence.autonomous_injection_packets} "
          f"machine={machine.physical_id()[:24]} "
          f"evidence={evidence.evidence_id()[:24]}")


@_requires_built
@_live_enabled
def test_real_live_dense_dp_gate_a_all_real(tmp_path):
    """Two real members with different token counts, padded to the max."""
    fixture, groups = _dp_live_fixture(groups=(DP_A,))
    result, _schedulers = _drive_live(tmp_path, [_row(8), _row(16)],
                                      fixture=fixture, groups=groups)
    result.evidence.assert_live()
    (quorum,) = result.rounds[0].dp_quorums
    assert quorum.max_total_len == 16
    assert quorum.dp_sum_total_len == 16
    assert [(m.original_total_len, m.padded_total_len)
            for m in quorum.members] == [(8, 16), (16, 16)]
    assert quorum.dummy_members() == ()
    assert result.rounds[0].dispatched_instances == (0, 1)
    assert sorted(r.instance_id for r in result.requests) == [0, 1]
    assert len(result.round_evidence[0].collective_contract) == 2
    assert len(result.round_evidence[0].collective_ledger) == 4
    print(f"\n[live-dp-A] max={quorum.max_total_len} "
          f"sum={quorum.dp_sum_total_len} "
          f"padded={[(m.original_total_len, m.padded_total_len) for m in quorum.members]}")
