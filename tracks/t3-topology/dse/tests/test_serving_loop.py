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

from veritx_dse.backend import astra_namespace as ans
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


def _backend_for(machine, serving, *, mode):
    """A canonical backend for a fixture; LIVE needs the real identity."""
    if mode == cs.MODE_LIVE_CANONICAL:
        from veritx_dse.backend.producer import resolve_producer_identity
        identity = resolve_producer_identity(BUILT_FROM_SOURCE)
        return cs.CanonicalServingNetworkBackend(
            machine=machine, binding=serving,
            astra_binary=str(BUILT_FROM_SOURCE),
            astra_binary_sha256=identity.binary_sha256,
            astra_binary_size=identity.binary_size,
            astra_source_revision=identity.source_revision,
            execution_mode=mode)
    return cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary="/bin/true",
        astra_binary_sha256="a" * 64, astra_binary_size=1,
        astra_source_revision=None, execution_mode=mode)


def _tp2_fixture(*, mode=cs.MODE_REPLAY_ONLY):
    """4 independent serving instances x TP2 over 8 canonical participants.

    Instance ``i`` owns canonical ranks ``(2i, 2i+1)``; the rank -> endpoint
    mapping is the fixture's deliberately non-identity permutation.
    """
    compiled, projection, machine, binding, ns = _astra_namespace(
        granularity="collectives", participants=8)
    serving = cs.ServingNamespaceBinding(
        namespace=ns,
        instances=tuple(cs.ServingInstance(i, (2 * i, 2 * i + 1))
                        for i in range(4)),
        serving_config_id="cfg/tp2")
    return (machine, ns, serving, sl.VirtualNpuNamespace(binding=serving),
            _backend_for(machine, serving, mode=mode),
            sl.CanonicalLowering(
                resolved_fabric=compiled.resolved_fabric,
                mapping=compiled.mapping, attachment=compiled.attachment,
                parallelism=compiled.inventory.parallelism))


def _attr_int(attr) -> int:
    for field in ("uint64_val", "int64_val", "uint32_val", "int32_val"):
        value = getattr(attr, field, 0)
        if value:
            return int(value)
    return 0


class StagedRuntimeSession:
    """A contract-faithful fake runtime.

    It reads what the round ACTUALLY staged -- the per-endpoint Chakra ETs and
    the round's ``comm_group.json`` -- and reports exactly those collectives in
    the runtime's own ledger grammar.  So it is a check on the *staging*, not a
    script: a round that stages the wrong node id, membership or size cannot
    produce a ledger that validates.
    """

    def __init__(self, argv, *, cwd=None, cycles=4242, comm=7, inject=None,
                 drop_ledger=False, override_size=None, override_type=None,
                 override_members=None, drop_submitter=None, extra_node=None,
                 silent_comm=False, extra_comm_endpoint=None):
        self.argv = argv
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self._cycles = cycles
        self._comm = comm
        self._inject = inject
        self._drop_ledger = drop_ledger
        self._override_size = override_size
        self._override_type = override_type
        self._override_members = override_members
        self._drop_submitter = drop_submitter
        self._extra_node = extra_node
        self._silent_comm = silent_comm
        self._extra_comm_endpoint = extra_comm_endpoint
        self._base = None
        self._rows: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read_startup(self):
        return sr.BackendReply(
            ["[workload] sys[0] finished, 1 cycles\n", "Waiting"], "Waiting")

    def command(self, line, *, expect_reply=True, timeout=None):
        if line.startswith("load "):
            self._base = Path(line[5:].strip())
            return None
        if not expect_reply:
            return None
        self._rows = self._read_staged_collectives()
        lines = [f"[workload] sys[{endpoint}] finished, {self._cycles} "
                 f"cycles, exposed communication {self._cycles} cycles."
                 for endpoint in self._staged_endpoints()]
        lines.append("Waiting")
        return sr.BackendReply(lines, "Waiting")

    # -- reading the staged round -----------------------------------------
    def _staged_endpoints(self) -> list[int]:
        assert self._base is not None
        found = []
        for path in self._base.parent.glob(self._base.name + ".*.et"):
            suffix = path.name[len(self._base.name) + 1:-3]
            if suffix.isdigit():
                found.append(int(suffix))
        return sorted(found)

    def _read_staged_collectives(self) -> list[dict]:
        from chakra.schema.protobuf import et_def_pb2 as pb
        from chakra.src.third_party.utils import protolib
        groups = json.loads((self.cwd / ans.COMM_GROUP_FILE).read_text())
        rows: list[dict] = []
        for endpoint in self._staged_endpoints():
            path = self._base.parent / f"{self._base.name}.{endpoint}.et"
            with open(path, "rb") as handle:
                metadata = pb.GlobalMetadata()
                protolib.decodeMessage(handle, metadata)
                while True:
                    node = pb.Node()
                    if not protolib.decodeMessage(handle, node):
                        break
                    if node.type != pb.COMM_COLL_NODE:
                        continue
                    attrs = {a.name: a for a in node.attr}
                    rows.append({
                        "endpoint": endpoint, "node_id": int(node.id),
                        "name": node.name,
                        "comm_type": _attr_int(attrs["comm_type"]),
                        "comm_size": _attr_int(attrs["comm_size"]),
                        "members": tuple(
                            groups[attrs["pg_name"].string_val]),
                    })
        return rows

    # -- reporting --------------------------------------------------------
    def stderr_text(self) -> str:
        rows: list[str] = []
        comm: dict[int, int] = {}
        if not self._silent_comm:
            for row in self._rows:
                comm[row["endpoint"]] = (comm.get(row["endpoint"], 0)
                                         + self._comm)
        if self._extra_comm_endpoint is not None:
            comm[self._extra_comm_endpoint] = self._comm
        for endpoint in sorted(comm):
            rows.append(f"[statistics] sys[{endpoint}], Comm time: "
                        f"{comm[endpoint]}\n")
        if self._inject is not None:
            rows.append(f"[trace] All 0 cycles, injected={self._inject} — "
                        "draining\n")
        if self._drop_ledger:
            return "".join(rows)
        for row in self._rows:
            if row["endpoint"] == self._drop_submitter:
                continue
            size = (self._override_size if self._override_size is not None
                    else row["comm_size"])
            ctype = (self._override_type if self._override_type is not None
                     else row["comm_type"])
            members = (self._override_members
                       if self._override_members is not None
                       else row["members"])
            joined = ",".join(str(m) for m in members)
            rows.append(
                f"[LEDGER][COLL_SUBMIT] rank={row['endpoint']} "
                f"astra_node={row['node_id']} comm_type={ctype} "
                f"comm_size={size} priority=0 involved_dims=[1,1,1,1] "
                f"group_members=[{joined}] tick=0\n")
        if self._extra_node is not None:
            rows.append(
                f"[LEDGER][COLL_SUBMIT] rank=0 astra_node={self._extra_node} "
                "comm_type=0 comm_size=4096 priority=0 "
                "involved_dims=[1,1,1,1] group_members=[0,1] tick=0\n")
        return "".join(rows)


def _session_factory(**kwargs):
    def factory(argv, cwd=None):
        return StagedRuntimeSession(argv, cwd=cwd, **kwargs)
    return factory


def _write_trace(directory: Path, rows) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dataset = directory / "requests.jsonl"
    dataset.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return dataset


def _run(tmp_path, rows, *, fixture=None, instance_count=4, req_num=None,
         session=None, expected_requests=None, mode=cs.MODE_REPLAY_ONLY,
         live=False, timeout_s=900, **overrides):
    """Drive a real JSONL through the loop with a contract-faithful runtime.

    ``live=True`` spawns the real ASTRA binary instead of the fake runtime.
    """
    if fixture is None:
        fixture = _loop_fixture(instance_count=instance_count, mode=mode)
    machine, ns, serving, npus, backend, lowering = fixture
    profile = _profile(**overrides.pop("profile", {}))
    req_num = len(rows) if req_num is None else req_num
    schedulers = sl.build_schedulers(profile=profile, npus=npus, req_num=req_num)
    router = sl.build_router(profile=profile, schedulers=schedulers,
                             req_num=req_num)
    dataset = _write_trace(tmp_path / "trace", rows)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=tmp_path / "load")
    result = sl.run_request_driven_service(
        backend=backend, machine=machine, profile=profile, npus=npus,
        router=router, schedulers=schedulers, run_dir=tmp_path / "run",
        workload_id="wl/loop-test", lowering=lowering,
        timeout_s=timeout_s,
        session_factory=(None if live else _session_factory(**(session or {}))),
        expected_requests=len(rows) if expected_requests is None
        else expected_requests)
    return result, fixture, schedulers


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

def _round_plan(*, round_id=0, batches, instance_ranks, participant_count):
    return sround.plan_from_round(
        round_id=round_id, batches=batches, instance_ranks=instance_ranks,
        participant_count=participant_count, collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: 4096,
        compute_ns_for=lambda *, tokens: 10_000 + 1_000 * tokens)


def test_plan_from_round_keeps_one_batch_plan_per_instance():
    _, first = _real_batch(batch_id_seed=0)
    _, second = _real_batch(batch_id_seed=1)
    plan = _round_plan(batches={0: first, 1: second},
                       instance_ranks={0: (0, 1), 1: (2, 3)},
                       participant_count=8)
    assert plan.round_id == 0
    assert plan.instance_ids() == (0, 1)
    assert plan.batch_for(0).participant_ranks == (0, 1)
    assert plan.batch_for(1).participant_ranks == (2, 3)
    assert plan.batch_for(0).tokens == first.total_len
    assert plan.batch_for(1).tokens == second.total_len
    blob = json.dumps(plan.identity_dict(), sort_keys=True)
    for forbidden in ("endpoint", "npu", "router", "booksim", "chakra"):
        assert forbidden not in blob.lower()


def test_plan_from_round_never_aggregates_tokens_across_instances():
    """Each batch's declared values come from ITS OWN tokens (\u00a712)."""
    seen: list[tuple[str, int]] = []
    _, first = _real_batch(batch_id_seed=0)
    _, second = _real_batch(batch_id_seed=1)
    sround.plan_from_round(
        round_id=0, batches={0: first, 1: second},
        instance_ranks={0: (0, 1), 1: (2, 3)}, participant_count=8,
        collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: seen.append(("b", tokens)) or 4096,
        compute_ns_for=lambda *, tokens: seen.append(("n", tokens)) or 10_000)
    assert ("n", first.total_len) in seen
    assert ("n", second.total_len) in seen
    assert ("n", first.total_len + second.total_len) not in seen


def test_plan_from_round_binds_every_contributing_batch_and_request():
    _, first = _real_batch(batch_id_seed=0)
    base = _round_plan(batches={0: first}, instance_ranks={0: (0, 1)},
                       participant_count=8)
    other = _round_plan(round_id=2, batches={0: first},
                        instance_ranks={0: (0, 1)}, participant_count=8)
    assert base.plan_id() != other.plan_id()      # the round id is bound
    assert base.batch_for(0).request_ids[0].startswith("inst0:")


def test_local_batch_ids_may_collide_without_operation_id_collision():
    """Every Scheduler numbers batches from zero, so batch 0 recurs."""
    _, first = _real_batch(batch_id_seed=0)
    _, second = _real_batch(batch_id_seed=1)
    plan = _round_plan(batches={0: first, 1: second},
                       instance_ranks={0: (0, 1), 1: (2, 3)},
                       participant_count=8)
    assert plan.batch_for(0).batch_id == plan.batch_for(1).batch_id == 0
    ids = plan.operation_ids()
    assert len(set(ids)) == len(ids)
    assert len(ids) == 6            # (2 owned compute + 1 collective) x 2
    assert all("round0" in op and "batch0" in op for op in ids)


def test_plan_from_round_refuses_empty_or_non_batch_input():
    with pytest.raises(sround.ServingRoundError, match="at least one real"):
        _round_plan(batches={}, instance_ranks={}, participant_count=4)
    with pytest.raises(sround.ServingRoundError, match="integer batch_id"):
        _round_plan(batches={0: object()}, instance_ranks={0: (0,)},
                    participant_count=4)
    with pytest.raises(sround.ServingRoundError, match="no canonical ranks"):
        _round_plan(batches={0: _real_batch()[1]}, instance_ranks={},
                    participant_count=4)


def test_round_preserves_independent_tp_groups(tmp_path):
    """A round over 4 instances is four TP2 collectives, never one TP8."""
    machine, ns, serving, npus, backend, lowering = _tp2_fixture()
    _, batch = _real_batch()
    plan = _round_plan(batches={i: batch for i in range(4)},
                       instance_ranks={i: (2 * i, 2 * i + 1) for i in range(4)},
                       participant_count=8)
    projection = plan.to_round_projection(
        resolved_fabric=lowering.resolved_fabric, mapping=lowering.mapping,
        attachment=lowering.attachment, parallelism=lowering.parallelism)
    assert len(projection.collective_operations) == 4
    memberships = sorted(p for _, _, _, p
                         in projection.collective_operations)
    assert memberships == [(0, 1), (2, 3), (4, 5), (6, 7)]
    # owned compute: the floor is the max per-rank chain, not the sum
    chain = plan.batch_for(0).compute_ns
    assert projection.declared_compute_cycles() == chain
    assert projection.declared_compute_cycles() != 4 * chain


def test_round_qualification_binds_the_collective_binding(tmp_path):
    machine, ns, serving, npus, backend, lowering = _tp2_fixture()
    _, batch = _real_batch()
    plan = _round_plan(batches={i: batch for i in range(4)},
                       instance_ranks={i: (2 * i, 2 * i + 1) for i in range(4)},
                       participant_count=8)
    projection = plan.to_round_projection(
        resolved_fabric=lowering.resolved_fabric, mapping=lowering.mapping,
        attachment=lowering.attachment, parallelism=lowering.parallelism)
    binding = ans.derive_collective_binding(namespace=ns, workload=projection)
    assert len(binding.groups.memberships) == 4
    staged = backend.stage_round(workload=projection, directory=tmp_path,
                                 collective_binding=binding)
    assert staged.collective_binding_id == binding.binding_id()
    assert tuple(e for e, _ in staged.endpoint_files) \
        == ns.participant_endpoints()
    qualification, _ = sround.qualify_round(
        machine=machine, plan=plan, backend=backend, staged=staged,
        directory=tmp_path, resolved_fabric=lowering.resolved_fabric,
        mapping=lowering.mapping, attachment=lowering.attachment,
        parallelism=lowering.parallelism, collective_binding=binding)
    assert qualification.expansion_authority == cs.EXPANSION_AUTHORITY_ASTRA
    assert qualification.collective_binding_id == binding.binding_id()
    assert qualification.communicator_group_id == binding.groups.groups_id()
    assert len(qualification.collective_contract) == 4
    # compute nodes occupy ids 1..8, so the four collectives are 9..12
    assert {row.astra_node_id for row in qualification.collective_contract} \
        == {9, 10, 11, 12}
    assert {row.collective_kind for row in qualification.collective_contract} \
        == {"ALLREDUCE"}


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
    # only the instance that actually had a batch executed fabric work
    assert evidence.instances_with_completions == (0,)
    assert not evidence.every_instance_served()
    assert result.virtual_npu_id == npus.translation_id()
    assert result.profile_id == _profile().profile_id()


def test_evidence_carries_the_collective_contract(tmp_path):
    """A round's evidence names each collective's node, membership and size."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}
            for _ in range(4)]
    result, _, _ = _run(tmp_path, rows, instance_count=4)
    for evidence in result.round_evidence:
        assert evidence.collective_binding_id
        assert evidence.collective_contract
        for row in evidence.collective_contract:
            assert row.endpoints
            assert row.payload_bytes > 0
            assert row.collective_kind == "ALLREDUCE"
            assert row.astra_node_id > 0
        assert evidence.identity_dict()["collective_binding_id"] \
            == evidence.collective_binding_id


def test_service_run_identity_is_content_addressed(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0}]
    first, _, _ = _run(tmp_path / "a", rows, instance_count=4)
    second, _, _ = _run(tmp_path / "b", rows, instance_count=4)
    # no paths, pids or wall time may enter the scientific identity
    assert first.run_id() == second.run_id()
    blob = json.dumps(first.identity_dict(), sort_keys=True)
    for token in ("/tmp", "pid", "run_dir", "wall_time", "elapsed"):
        assert token not in blob


def test_a_round_that_serves_one_instance_leaves_the_others_idle(tmp_path):
    """Idle instances get no compute and no collective -- not fake work."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    result, _, _ = _run(tmp_path, rows, instance_count=4)
    assert len(result.rounds) == 1
    first = result.rounds[0]
    # RR routes the single request to instance 0, so 1..3 had no batch
    assert first.batch_ids == ((0, 0),)
    assert first.dispatched_instances == (0,)
    assert first.idle_instances == (1, 2, 3)
    # exactly one communicator group was bound, not one per instance
    assert len(first.group_ids) == 1
    # ...and no request was retired for an instance that dispatched nothing
    assert first.retired_request_ids == ("0",)
    assert result.requests[0].instance_id == 0
    evidence = result.round_evidence[0]
    assert evidence.dispatched_instances == (0,)
    assert {row[2] for row in evidence.completion_attributions} == {0}
    assert len(evidence.collective_contract) == 1


def test_a_dispatched_instance_without_execution_evidence_refuses(tmp_path):
    """Retirement is bookkeeping; execution evidence is the real gate."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sl.ServingLoopError,
                       match="no endpoint execution evidence"):
        _run(tmp_path, rows, instance_count=4,
             session={"silent_comm": True})


def test_a_pass_echo_from_an_undispatched_instance_refuses(tmp_path):
    """The historical pass-echo protection survives the rework."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    fixture = _loop_fixture(instance_count=4)
    _, ns, serving, _, _, _ = fixture
    # RR dispatches instance 0, so instance 3 is idle this round
    idle_endpoint = serving.endpoints_of(3)[0]
    with pytest.raises(cs.ServingBoundaryError, match="dispatched no batch"):
        _run(tmp_path, rows, fixture=fixture,
             session={"extra_comm_endpoint": idle_endpoint})


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


def test_live_round_reads_evidence_only_after_stderr_quiescence(tmp_path):
    """stdout and stderr are separate pipes; evidence must not be read early.

    The drain is a Python readline loop racing the C++ producer, so reading
    the evidence buffer as soon as a reply lands silently loses measured
    statistics.  This pins the ordering contract that prevents that.
    """
    machine, ns, serving, npus, backend, lowering = _loop_fixture()
    plan = _round_plan(batches={0: _real_batch()[1]},
                       instance_ranks={0: (0, 1)}, participant_count=16)
    projection = plan.to_round_projection(
        resolved_fabric=lowering.resolved_fabric, mapping=lowering.mapping,
        attachment=lowering.attachment, parallelism=lowering.parallelism)
    calls: list[str] = []

    class OrderedSession:
        def __init__(self, argv, cwd=None):
            self.argv = argv

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read_startup(self):
            return sr.BackendReply(["Waiting"], "Waiting")

        def command(self, line, *, expect_reply=True, timeout=None):
            if not expect_reply:
                return None
            calls.append("run")
            return sr.BackendReply(
                ["[workload] sys[0] finished, 5 cycles."], "Waiting")

        def await_stderr_quiescence(self, **kwargs):
            calls.append("quiesce")
            return True

        def stderr_text(self):
            calls.append("stderr")
            return ""

    sr.run_live_round(
        backend=backend, workload=projection, run_dir=tmp_path / "run",
        dispatched_instances=frozenset({0}),
        session_factory=lambda argv, cwd=None: OrderedSession(argv, cwd))
    assert calls == ["run", "quiesce", "stderr"]


# ── the loop fails closed, never inventing a result ───────────────────────

def test_a_wrong_collective_size_in_the_ledger_refuses(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sround.ServingRoundError, match="bytes"):
        _run(tmp_path, rows, instance_count=4,
             session={"override_size": 4096 + 1})


def test_a_wrong_collective_type_in_the_ledger_refuses(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    with pytest.raises(sround.ServingRoundError, match="projected ALLREDUCE"):
        _run(tmp_path, rows, instance_count=4, session={"override_type": 2})


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
    # Slice 38: only the instances that supplied a batch may report work, and
    # every one of them must.  The global "all instances" gate is the 4xTP2
    # gate's job (test_serving_tp_groups), not this one.
    dispatched = set(result.rounds[0].dispatched_instances)
    assert dispatched, "the round dispatched nothing"
    assert set(result.evidence.instances_with_completions) == dispatched
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
