"""Slice 36 — certified per-round serving qualification and round evidence."""
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
from veritx_dse.backend.producer import (
    ProducerError, resolve_producer_identity,
)

MODEL = "meta-llama/Llama-3.1-8B"
REPO = Path(__file__).resolve().parents[4]


# ── fixtures ──────────────────────────────────────────────────────────────

def _fixture(instance_count=4, granularity="collectives"):
    """compiled canonical design + machine + namespace + serving binding."""
    compiled, projection, machine, binding, ns = _astra_namespace(
        granularity=granularity)
    _, _, serving = _qualified(instance_count=instance_count,
                               granularity=granularity)
    return compiled, machine, ns, serving


def _backend(machine, serving, *, mode=cs.MODE_REPLAY_ONLY):
    if mode == cs.MODE_LIVE_CANONICAL:
        identity = resolve_producer_identity(BUILT_FROM_SOURCE)
        digest, size = identity.binary_sha256, identity.binary_size
    else:
        digest, size = "a" * 64, 123
    return cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary=str(BUILT_FROM_SOURCE),
        astra_binary_sha256=digest, astra_binary_size=size,
        astra_source_revision=None, execution_mode=mode)


def _plan(**overrides):
    base = dict(batch_id=0, instance_id=0,
                request_ids=("r0",), participant_ranks=tuple(range(16)),
                phase="prefill", tokens=16, collective_kind="ALLREDUCE",
                collective_bytes=1024, compute_ns=10_000)
    base.update(overrides)
    return sround.ServingBatchPlan(**base)


def _qualified_round(tmp_path, *, plan=None, instance_count=4):
    compiled, machine, ns, serving = _fixture(instance_count=instance_count)
    backend = _backend(machine, serving)
    plan = plan or _plan()
    projection = plan.to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    staged = backend.stage_round(workload=projection, directory=tmp_path)
    qualification, projection2 = sround.qualify_round(
        machine=machine, plan=plan, backend=backend, staged=staged,
        directory=tmp_path, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    return machine, ns, serving, backend, plan, staged, qualification


# ── real Batch -> plan ────────────────────────────────────────────────────

def _real_batch():
    from serving.core.scheduler import Scheduler
    scheduler = Scheduler(
        model=MODEL, node_id=0, instance_id=0, max_num_seqs=8,
        max_num_batched_tokens=1024, num_npus=4, tp_size=4, pp_size=1,
        npu_mem=1000, cpu_mem=1000, start_npu=0, pd_type="prefill", fp=1,
        block_size=16, req_num=1, prioritize_prefill=False,
        enable_prefix_caching=False, enable_prefix_sharing=False,
        prefix_pool=None, prefix_storage=0)
    scheduler.add_request([0, MODEL, 16, 8, 0, 0])
    batch = scheduler.schedule(current=0, sys=0)
    assert batch is not None
    return scheduler, batch


def test_plan_from_real_llmservingsim_batch():
    scheduler, batch = _real_batch()
    plan = sround.plan_from_batch(
        batch, instance_id=scheduler.instance_id,
        participant_ranks=range(16), collective_kind="ALLREDUCE",
        collective_bytes=1024, compute_ns=10_000)
    assert plan.batch_id == batch.batch_id
    assert plan.instance_id == 0
    assert plan.phase == "prefill"
    assert len(plan.request_ids) == len(batch.requests) == 1
    assert plan.participant_ranks == tuple(range(16))
    assert plan.plan_id().startswith("sha256:")


def test_plan_from_batch_reads_only_serving_owned_fields():
    scheduler, batch = _real_batch()
    plan = sround.plan_from_batch(
        batch, instance_id=0, participant_ranks=range(4),
        collective_kind="ALLGATHER", collective_bytes=2048,
        compute_ns=5000)
    identity = json.dumps(plan.identity_dict(), sort_keys=True)
    # no physical placement may leak into a serving plan
    for forbidden in ("endpoint", "npu", "router", "booksim", "chakra",
                      "topology"):
        assert forbidden not in identity.lower()


def test_plan_requires_a_real_batch():
    with pytest.raises(sround.ServingRoundError, match="real Batch"):
        sround.plan_from_batch(object(), instance_id=0, participant_ranks=(0,),
                               collective_kind="ALLREDUCE",
                               collective_bytes=1, compute_ns=1)


def test_plan_identity_is_deterministic_and_sensitive():
    first = _plan()
    assert first.plan_id() == _plan().plan_id()
    for field, value in (("collective_bytes", 4096),
                         ("collective_kind", "ALLGATHER"),
                         ("phase", "decode"),
                         ("compute_ns", 20_000),
                         ("participant_ranks", tuple(range(8))),
                         ("batch_id", 7)):
        mutated = dataclasses.replace(first, **{field: value})
        assert mutated.plan_id() != first.plan_id(), f"{field} not bound"


def test_plan_rejects_unsupported_collective_kind():
    with pytest.raises(sround.ServingRoundError, match="unsupported collective"):
        _plan(collective_kind="RING_CUSTOM")
    with pytest.raises(sround.ServingRoundError, match="positive collective"):
        _plan(collective_bytes=0)


def test_plan_rejects_bad_phase_and_empty_participants():
    with pytest.raises(sround.ServingRoundError, match="prefill or decode"):
        _plan(phase="warmup")
    with pytest.raises(sround.ServingRoundError, match="no participant ranks"):
        _plan(participant_ranks=())


# ── lowering is intent-only (expansion stays ASTRA's) ─────────────────────

def test_round_lowering_keeps_astra_as_expansion_authority():
    compiled, machine, ns, serving = _fixture()
    projection = _plan().to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    assert projection.expansion_authority() == "astra_comm_coll"
    assert projection.et_granularity == "collectives"
    # the round is emitted as collective INTENT for ASTRA to expand: the
    # projection also carries the canonical expansion, but the emission
    # granularity is what makes ASTRA the authority
    assert projection.collective_operations
    kinds = {kind for _, kind, _, _ in projection.collective_operations}
    assert kinds == {"ALLREDUCE"}
    sizes = {payload for _, _, payload, _ in projection.collective_operations}
    assert sizes == {1024}


def test_round_lowering_never_carries_endpoint_ids():
    compiled, machine, ns, serving = _fixture()
    projection = _plan().to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    identity = json.dumps(projection.identity_dict(), sort_keys=True)
    assert "endpoint" not in identity
    assert ns.participant_endpoints()  # the namespace owns endpoints


# ── round qualification (§6) ──────────────────────────────────────────────

def test_round_qualification_binds_machine_round_and_namespace(tmp_path):
    machine, ns, serving, backend, plan, staged, qual = _qualified_round(tmp_path)
    identity = qual.identity_dict()
    for field in ("physical_machine_id", "machine_id", "plan_id",
                  "round_projection_id", "namespace_id",
                  "participant_mapping_id", "serving_binding_id",
                  "staged_workload_id", "communicator_group_id",
                  "astra_binary_sha256", "expansion_authority",
                  "network_evidence_tier"):
        assert identity[field], f"{field} is not bound into the round"
    assert identity["physical_machine_id"] == machine.physical_id()
    assert identity["namespace_id"] == ns.namespace_id()
    assert identity["participant_mapping_id"] == ns.participant_mapping_id
    assert identity["staged_workload_id"] == staged.translation_id
    assert identity["expansion_authority"] == "astra_comm_coll"
    assert identity["network_evidence_tier"] == cs.TIER_ASTRA_OWNED_COLLECTIVE
    assert qual.round_id().startswith("sha256:")


def test_stable_machine_identity_is_workload_independent():
    compiled, machine, ns, serving = _fixture()
    other = _plan(batch_id=9, collective_bytes=8192, compute_ns=99_000,
                  collective_kind="ALLGATHER")
    first = _plan()
    assert machine.physical_id() == machine.physical_id()
    # physical_id must not move when only the round workload changes
    from veritx_dse.backend import astra_machine as am
    projection_a = first.to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    assert other.plan_id() != first.plan_id()
    assert projection_a.projection_id() != other.to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism).projection_id()
    assert machine.physical_id() not in (
        projection_a.projection_id(), other.plan_id())


def test_round_cannot_transplant_onto_an_incompatible_machine(tmp_path):
    """A round qualified for one machine must not run on another."""
    machine, ns, serving, backend, plan, staged, qual = _qualified_round(tmp_path)
    from test_backend_astra_machine import _machine
    other_machine = _machine(anynet=True)[4]
    assert other_machine.physical_id() != machine.physical_id()
    # the round binds both identities, so a transplant is detectable
    identity = qual.identity_dict()
    assert identity["machine_id"] == machine.machine_id()
    assert identity["physical_machine_id"] == machine.physical_id()
    assert identity["machine_id"] != other_machine.machine_id()
    assert identity["physical_machine_id"] != other_machine.physical_id()


def test_round_refuses_when_staged_endpoints_do_not_match_participants(tmp_path):
    compiled, machine, ns, serving = _fixture()
    backend = _backend(machine, serving)
    # a namespace over a different participant count cannot stage this round
    plan = _plan(participant_ranks=tuple(range(8)))
    projection = plan.to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)
    staged = backend.stage_round(workload=projection, directory=tmp_path)
    with pytest.raises(sround.ServingRoundError, match="staged endpoints"):
        sround.qualify_round(
            machine=machine, plan=plan, backend=backend, staged=staged,
            directory=tmp_path, resolved_fabric=compiled.resolved_fabric,
            mapping=compiled.mapping, attachment=compiled.attachment,
            parallelism=compiled.inventory.parallelism)


# ── ASTRA producer authentication (§7) ────────────────────────────────────

def test_false_astra_binary_digest_refuses():
    _, machine, ns, serving = _fixture()
    with pytest.raises(cs.ServingBoundaryError, match="digest does not match"):
        cs.CanonicalServingNetworkBackend(
            machine=machine, binding=serving,
            astra_binary=str(BUILT_FROM_SOURCE), astra_binary_sha256="b" * 64,
            astra_binary_size=1, astra_source_revision=None,
            execution_mode=cs.MODE_LIVE_CANONICAL)


def test_false_astra_binary_size_refuses():
    _, machine, ns, serving = _fixture()
    identity = resolve_producer_identity(BUILT_FROM_SOURCE)
    with pytest.raises(cs.ServingBoundaryError, match="size does not match"):
        cs.CanonicalServingNetworkBackend(
            machine=machine, binding=serving,
            astra_binary=str(BUILT_FROM_SOURCE),
            astra_binary_sha256=identity.binary_sha256,
            astra_binary_size=identity.binary_size + 1,
            astra_source_revision=None,
            execution_mode=cs.MODE_LIVE_CANONICAL)


def test_correct_identity_resolves_and_rechecks(tmp_path):
    _, machine, ns, serving = _fixture()
    backend = _backend(machine, serving, mode=cs.MODE_LIVE_CANONICAL)
    identity = backend.producer_identity()
    assert identity.binary_sha256 == backend.astra_binary_sha256
    assert identity.binary_size == backend.astra_binary_size
    backend.recheck_before_spawn()          # clean: no refusal


def test_binary_substitution_before_spawn_refuses(tmp_path):
    """A binary swapped after qualification must not execute."""
    import shutil
    copied = tmp_path / "AstraSim_BookSim2"
    shutil.copy2(BUILT_FROM_SOURCE, copied)
    _, machine, ns, serving = _fixture()
    identity = resolve_producer_identity(copied)
    backend = cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary=str(copied),
        astra_binary_sha256=identity.binary_sha256,
        astra_binary_size=identity.binary_size,
        astra_source_revision=None, execution_mode=cs.MODE_LIVE_CANONICAL)
    # swap the artifact after qualification
    copied.write_bytes(copied.read_bytes() + b"\x00tampered")
    with pytest.raises(cs.ServingBoundaryError, match="changed before spawn"):
        backend.recheck_before_spawn()


def test_replay_mode_does_not_claim_a_producer_identity():
    _, machine, ns, serving = _fixture()
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY)
    backend.recheck_before_spawn()          # no-op by design


# ── ledger validation (§9) ────────────────────────────────────────────────

def _ledger_line(*, rank=0, node=1, ctype=0, size=1024,
                 members="{0,1,2,3}", dims="[1,1,1,1]", tick=0):
    return (f"[LEDGER][COLL_SUBMIT] rank={rank} astra_node={node} "
            f"comm_type={ctype} comm_size={size} priority=0 "
            f"involved_dims={dims} group_members={members} tick={tick}")


def test_ledger_parses_structurally():
    entries = sround.parse_collective_ledger([_ledger_line()])
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.rank, entry.comm_type, entry.comm_size) == (0, 0, 1024)
    assert entry.members == (0, 1, 2, 3)
    assert entry.has_group is True
    assert entry.kind == "ALLREDUCE"
    assert sround.parse_collective_ledger(["unrelated"]) == ()
    assert sround.parse_collective_ledger(
        [_ledger_line(members="none")])[0].has_group is False


def test_ledger_type_mismatch_refuses():
    plan = _plan(collective_kind="ALLREDUCE")
    entries = sround.parse_collective_ledger(
        [_ledger_line(ctype=2)])          # ALLGATHER
    with pytest.raises(sround.ServingRoundError, match="collective type"):
        sround.validate_collective_ledger(
            entries, plan=plan, expected_members=(0, 1, 2, 3))


def test_ledger_byte_size_mismatch_refuses():
    plan = _plan(collective_bytes=1024)
    entries = sround.parse_collective_ledger([_ledger_line(size=2048)])
    with pytest.raises(sround.ServingRoundError, match="byte-size mismatch"):
        sround.validate_collective_ledger(
            entries, plan=plan, expected_members=(0, 1, 2, 3))


def test_ledger_membership_mismatch_refuses():
    plan = _plan()
    entries = sround.parse_collective_ledger(
        [_ledger_line(members="{0,1,2,3}")])
    with pytest.raises(sround.ServingRoundError, match="membership mismatch"):
        sround.validate_collective_ledger(
            entries, plan=plan, expected_members=(0, 1, 2, 3, 4))


def test_ledger_without_a_group_refuses():
    plan = _plan()
    entries = sround.parse_collective_ledger([_ledger_line(members="none")])
    with pytest.raises(sround.ServingRoundError, match="without a"):
        sround.validate_collective_ledger(
            entries, plan=plan, expected_members=(0, 1, 2, 3))


def test_ledger_from_a_rank_outside_the_projection_refuses():
    plan = _plan()
    entries = sround.parse_collective_ledger(
        [_ledger_line(rank=9, members="{0,1,2,3}")])
    with pytest.raises(sround.ServingRoundError, match="outside the projected"):
        sround.validate_collective_ledger(
            entries, plan=plan, expected_members=(0, 1, 2, 3))


def test_missing_ledger_refuses():
    with pytest.raises(sround.ServingRoundError, match="never submitted"):
        sround.validate_collective_ledger(
            (), plan=_plan(), expected_members=(0, 1, 2, 3))


def test_valid_ledger_passes():
    plan = _plan(collective_kind="ALLREDUCE", collective_bytes=1024)
    entries = sround.parse_collective_ledger(
        [_ledger_line(rank=r, size=1024, members="{0,1,2,3}")
         for r in range(4)])
    sround.validate_collective_ledger(
        entries, plan=plan, expected_members=(0, 1, 2, 3))


# ── round evidence (§8) ───────────────────────────────────────────────────

class _Outcome:
    def __init__(self, *, dispatched=(0, 1, 2, 3), completions=None,
                 attributions=(), ledger=(), injected=0, cycles=1000):
        self.round_index = 0
        self.dispatched_instances = list(dispatched)
        self.endpoint_completions = tuple(sorted((completions or {}).items()))
        self.attributions = list(attributions)
        self.collective_ledger = tuple(ledger)
        self.autonomous_injection_packets = injected
        self.backend_cycles = cycles


def _round_evidence(tmp_path, **outcome_kwargs):
    machine, ns, serving, backend, plan, staged, qual = _qualified_round(tmp_path)
    outcome = _Outcome(**outcome_kwargs)
    evidence = sround.round_evidence_from_outcome(
        qualification=qual, outcome=outcome, machine=machine,
        parser_version="srota/astra-stats-parser/v1")
    return machine, ns, qual, evidence


def test_round_evidence_is_content_addressed_and_complete(tmp_path):
    machine, ns, qual, evidence = _round_evidence(
        tmp_path, completions={e: 1 for e in range(16)},
        ledger=[_ledger_line(rank=r) for r in range(4)])
    identity = evidence.identity_dict()
    for field in ("qualification_id", "machine_id", "physical_machine_id",
                  "plan_id", "round_projection_id", "namespace_id",
                  "participant_mapping_id", "staged_workload_id",
                  "communicator_group_id", "astra_binary_sha256",
                  "embedded_fabric_abi_version", "standalone_config_sha256",
                  "network_evidence_tier", "expansion_authority",
                  "dispatched_instances", "per_endpoint_completions",
                  "collective_ledger", "autonomous_injection_packets",
                  "backend_cycles", "parser_version"):
        assert field in identity, f"{field} not bound into round evidence"
    assert evidence.evidence_id().startswith("sha256:")
    assert identity["qualification_id"] == qual.round_id()
    assert identity["machine_id"] == machine.machine_id()
    assert identity["astra_binary_sha256"] == qual.astra_binary_sha256
    assert evidence.evidence_id() == sround.round_evidence_from_outcome(
        qualification=qual, outcome=_Outcome(
            completions={e: 1 for e in range(16)},
            ledger=[_ledger_line(rank=r) for r in range(4)]),
        machine=machine, parser_version="srota/astra-stats-parser/v1"
    ).evidence_id()


@pytest.mark.parametrize("field,value", [
    ("per_endpoint_completions", ((0, 2), (1, 1))),
    ("autonomous_injection_packets", 5),
    ("backend_cycles", 999),
    ("dispatched_instances", (0, 1, 2)),
    ("collective_ledger", ((0, 1, 0, (7, 8)),)),
    ("astra_binary_sha256", "c" * 64),
    ("machine_id", "d" * 64),
    ("namespace_id", "e" * 64),
])
def test_tampering_with_a_measured_round_statistic_changes_identity(
        tmp_path, field, value):
    _, _, _, evidence = _round_evidence(tmp_path)
    tampered = dataclasses.replace(evidence, **{field: value})
    assert tampered.evidence_id() != evidence.evidence_id(), \
        f"{field} is not authenticated by the round evidence"


def test_top_level_evidence_references_real_round_evidence_ids(tmp_path):
    from veritx_dse.simulation import serving_runtime as sr
    machine, ns, serving, backend, plan, staged, qual = _qualified_round(tmp_path)
    evidence = sround.round_evidence_from_outcome(
        qualification=qual,
        outcome=_Outcome(completions={e: 1 for e in range(16)},
                         ledger=[_ledger_line(rank=r) for r in range(4)]),
        machine=machine, parser_version="srota/astra-stats-parser/v1")
    top = sr.build_serving_evidence(
        backend=backend, rounds=(), workload_id="wl/round-refs",
        round_evidence=(evidence,))
    assert top.backend_evidence_ids == (evidence.evidence_id(),)
    assert ":" not in top.backend_evidence_ids[0].split("sha256:")[-1]


# ── real Router / arrival semantics ───────────────────────────────────────

def _router(tmp_path, jsonl_rows, *, policy="RR"):
    from serving.core.router import Router
    from serving.core.scheduler import Scheduler
    schedulers = []
    for instance_id in range(2):
        schedulers.append(Scheduler(
            model=MODEL, node_id=instance_id, instance_id=instance_id,
            max_num_seqs=8, max_num_batched_tokens=1024, num_npus=4,
            tp_size=4, pp_size=1, npu_mem=1000, cpu_mem=1000,
            start_npu=instance_id * 4, pd_type="prefill", fp=1, block_size=16,
            req_num=len(jsonl_rows), prioritize_prefill=False,
            enable_prefix_caching=False, enable_prefix_sharing=False,
            prefix_pool=None, prefix_storage=0))
    dataset = tmp_path / "requests.jsonl"
    dataset.write_text("\n".join(json.dumps(row) for row in jsonl_rows) + "\n")
    router = Router(num_instances=2, schedulers=schedulers,
                    req_num=len(jsonl_rows), routing_policy=policy)
    # upstream resolves the dataset as f'../{path}', so load it from a
    # directory one level below the file rather than rewriting upstream
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    cwd = Path.cwd()
    try:
        os.chdir(run_dir)
        router.load_requests("requests.jsonl")
    finally:
        os.chdir(cwd)
    return router, schedulers


def test_real_router_loads_jsonl_and_respects_arrival(tmp_path):
    rows = [{"input_toks": 16, "output_toks": 8, "arrival_time_ns": 0},
            {"input_toks": 32, "output_toks": 8, "arrival_time_ns": 5000}]
    router, schedulers = _router(tmp_path, rows)
    assert router.has_pending_requests()
    # upstream floors the first arrival at 1 (its own convention)
    assert router.get_first_arrival_time() == 1
    # nothing arrives before its arrival time
    assert router.route_arrived_requests(0) == 1
    assert sum(len(s.request) for s in schedulers) == 1
    assert sum(len(s.request) for s in schedulers) == 1
    assert router.route_arrived_requests(4000) == 0
    assert router.route_arrived_requests(5000) == 1
    assert not router.has_pending_requests()
    assert sum(len(s.request) for s in schedulers) == 2


def test_real_router_round_robin_selects_both_instances(tmp_path):
    rows = [{"input_toks": 16, "output_toks": 8, "arrival_time_ns": 0},
            {"input_toks": 16, "output_toks": 8, "arrival_time_ns": 0}]
    router, schedulers = _router(tmp_path, rows, policy="RR")
    router.route_arrived_requests(0)
    per_instance = [len(s.request) for s in schedulers]
    assert per_instance == [1, 1], per_instance


def test_real_router_load_policy_uses_least_loaded_instance(tmp_path):
    rows = [{"input_toks": 16, "output_toks": 8, "arrival_time_ns": 0},
            {"input_toks": 16, "output_toks": 8, "arrival_time_ns": 0}]
    router, schedulers = _router(tmp_path, rows, policy="LOAD")
    router.route_arrived_requests(0)
    assert sum(len(s.request) for s in schedulers) == 2


def test_real_scheduler_produces_a_batch_from_a_routed_request(tmp_path):
    rows = [{"input_toks": 16, "output_toks": 8, "arrival_time_ns": 0}]
    router, schedulers = _router(tmp_path, rows)
    router.route_arrived_requests(0)
    batches = []
    for scheduler in schedulers:
        batch = scheduler.schedule(current=0, sys=scheduler.start_npu)
        if batch is not None:
            batches.append(batch)
    assert len(batches) == 1
    batch = batches[0]
    assert batch.sent is False           # Batch.sent protection intact
    plan = sround.plan_from_batch(
        batch, instance_id=0, participant_ranks=range(4),
        collective_kind="ALLREDUCE", collective_bytes=1024,
        compute_ns=10_000)
    assert plan.batch_id == batch.batch_id
    # a completion cannot retire a batch that was never dispatched
    from veritx_dse.backend import astra_namespace as ans
    _, _, serving = _qualified(instance_count=4)
    with pytest.raises(cs.ServingBoundaryError, match="dispatched no batch"):
        cs.attribute_completions(
            per_endpoint={serving.endpoints_of(0)[0]: 1}, binding=serving,
            dispatched=frozenset())


# ── endpoint permutation retained ─────────────────────────────────────────

def test_endpoint_permutation_is_retained_in_the_round(tmp_path):
    machine, ns, serving, backend, plan, staged, qual = _qualified_round(tmp_path)
    assert any(r != e for r, e in ns.rank_to_endpoint)
    assert qual.participant_mapping_id == ns.participant_mapping_id
    assert "endpoint" not in json.dumps(plan.identity_dict(), sort_keys=True)
    staged_members = tuple(sorted(e for e, _ in staged.endpoint_files))
    assert staged_members == ns.participant_endpoints()
    # the mapping is non-identity even though the endpoint SET coincides
    assert dict(ns.rank_to_endpoint) != {r: r for r in range(16)}
    assert ns.endpoint_for(0) != 0
