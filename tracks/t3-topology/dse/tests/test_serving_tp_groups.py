"""Slice 38 — independent TP groups on one fixed canonical fabric.

The distinction under test::

    service configuration  =  communication demand   (changes per slice)
    resolved fabric        =  physical substrate     (never changes here)

Changing TP8 -> 4xTP2 must change the workload, collective and evidence
identity while leaving the physical machine byte-identical.
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
    _backend_for, _real_batch, _run, _tp2_fixture,
)

from veritx_dse.backend import astra_namespace as ans
from veritx_dse.backend import canonical_serving as cs
from veritx_dse.backend import serving_round as sround
from veritx_dse.backend.astra import AstraWorkloadProjection
from veritx_dse.core.errors import InvalidInput
from veritx_dse.simulation import serving_loop as sl
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
    collective_detail, compute_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2

TP2_INSTANCES = {i: (2 * i, 2 * i + 1) for i in range(4)}


# ── fixtures ──────────────────────────────────────────────────────────────

def _shape_pair():
    """TP8 and 4xTP2 serving bindings over ONE canonical physical machine.

    Both service geometries share the *same* machine and namespace objects:
    that is the claim under test, not an assumption.
    """
    compiled, _projection, machine, _binding, ns = _astra_namespace(
        granularity="collectives", participants=8)
    tp8 = cs.ServingNamespaceBinding(
        namespace=ns, instances=(cs.ServingInstance(0, tuple(range(8))),),
        serving_config_id="cfg/tp8")
    tp2 = cs.ServingNamespaceBinding(
        namespace=ns,
        instances=tuple(cs.ServingInstance(i, (2 * i, 2 * i + 1))
                        for i in range(4)),
        serving_config_id="cfg/tp2")
    return compiled, machine, ns, tp8, tp2


def _lowering(compiled):
    return sl.CanonicalLowering(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)


def _tp8_loop_fixture(*, mode=cs.MODE_REPLAY_ONLY):
    compiled, _projection, machine, _binding, ns = _astra_namespace(
        granularity="collectives", participants=8)
    serving = cs.ServingNamespaceBinding(
        namespace=ns, instances=(cs.ServingInstance(0, tuple(range(8))),),
        serving_config_id="cfg/tp8")
    return (machine, ns, serving, sl.VirtualNpuNamespace(binding=serving),
            _backend_for(machine, serving, mode=mode), _lowering(compiled))


def _batch_plan(*, instance_id, ranks, batch_id=0, tokens=16):
    return sround.ServingBatchPlan(
        batch_id=batch_id, instance_id=instance_id,
        request_ids=(f"inst{instance_id}:req0",),
        participant_ranks=tuple(ranks), phase="prefill", tokens=tokens,
        collective_kind="ALLREDUCE", collective_bytes=4096,
        compute_ns=10_000)


def _plan_for(*, round_id=0, instance_ranks=None, compute_ns=10_000):
    instance_ranks = TP2_INSTANCES if instance_ranks is None else instance_ranks
    return sround.plan_from_round(
        round_id=round_id,
        batches={i: _real_batch()[1] for i in instance_ranks},
        instance_ranks=instance_ranks, participant_count=8,
        collective_kind="ALLREDUCE",
        collective_bytes_for=lambda *, tokens: 4096,
        compute_ns_for=lambda *, tokens: compute_ns)


def _project(plan, compiled):
    return plan.to_round_projection(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)


def _ledger_line(*, rank, node, ctype=0, size=4096, members=(0, 1)):
    joined = ",".join(str(m) for m in members)
    return (f"[LEDGER][COLL_SUBMIT] rank={rank} astra_node={node} "
            f"comm_type={ctype} comm_size={size} priority=0 "
            f"involved_dims=[1,1,1,1] group_members=[{joined}] tick=0")


def _entries(lines):
    return sround.parse_collective_ledger(lines)


def _contract_and_ns():
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    projection = _project(_plan_for(), compiled)
    binding = ans.derive_collective_binding(namespace=ns, workload=projection)
    return (sround.collective_contract(projection=projection, binding=binding),
            ns, projection, binding, compiled)


# ── serving instance ranks become TP participants ─────────────────────────

def test_instance_ranks_become_collective_participants():
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    plan = _plan_for()
    projection = _project(plan, compiled)
    memberships = sorted(p for _, _, _, p in projection.collective_operations)
    assert memberships == [(0, 1), (2, 3), (4, 5), (6, 7)]
    for batch in plan.batches:
        assert batch.participant_ranks == TP2_INSTANCES[batch.instance_id]
    # the collective participant set is the instance's rank set, not endpoints
    assert all(len(p) == 2 for _, _, _, p in projection.collective_operations)


def test_independent_instances_are_not_encoded_as_dp():
    """4 instances x TP2 is not tp=2/dp=4: one TP axis, explicit members."""
    compiled, _machine_, _ns, _tp8, _tp2 = _shape_pair()
    plan = _plan_for()
    graph = plan.to_workload_graph(parallelism=compiled.inventory.parallelism)
    assert graph.participant_count == 8
    for op in graph.operations:
        participants = op.detail.get("participants")
        if participants is not None:
            assert len(participants) == 2
    assert getattr(graph.parallelism, "dp", 1) == 1
    assert getattr(graph.parallelism, "tp", 1) == 8   # the PHYSICAL tp


def test_tp_geometry_is_not_inferred_from_endpoint_numbering():
    """A permuted rank->endpoint map must not be read as TP geometry."""
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    assert any(r != e for r, e in ns.rank_to_endpoint)
    projection = _project(_plan_for(), compiled)
    binding = ans.derive_collective_binding(namespace=ns, workload=projection)
    for op_id, members, _mechanism in binding.operations:
        ranks = tuple(sorted(rank for rank, endpoint in ns.rank_to_endpoint
                             if endpoint in members))
        assert len(ranks) == 2
        assert tuple(sorted(ns.endpoint_for(r) for r in ranks)) == members


# ── owned compute ─────────────────────────────────────────────────────────

def _write_and_read_et(projection, tmp_path, stem="w"):
    from chakra.schema.protobuf import et_def_pb2 as pb
    from chakra.src.third_party.utils import protolib
    projection.write_chakra(directory=tmp_path, stem=stem)
    per_rank: dict[int, list[str]] = {}
    for path in sorted(tmp_path.glob(f"{stem}.et.*.et")):
        rank = int(path.name[len(stem) + 4:-3])
        names = []
        with open(path, "rb") as handle:
            metadata = pb.GlobalMetadata()
            protolib.decodeMessage(handle, metadata)
            while True:
                node = pb.Node()
                if not protolib.decodeMessage(handle, node):
                    break
                names.append(node.name)
        per_rank[rank] = names
    return per_rank


def test_owned_compute_appears_only_in_the_owner_rank_et(tmp_path):
    compiled, _machine_, _ns, _tp8, _tp2 = _shape_pair()
    projection = _project(_plan_for(), compiled)
    per_rank = _write_and_read_et(projection, tmp_path)
    assert sorted(per_rank) == list(range(8))
    for rank, names in per_rank.items():
        owned = [n for n in names if "-compute-" in n]
        assert owned == [f"round0-inst{rank // 2}-batch0-compute-r{rank}"]
        collectives = [n for n in names if n.endswith("-tp")]
        assert collectives == [f"round0-inst{rank // 2}-batch0-tp"]
        # the collective's declared participants contain this rank
        member_of = [op for op, _, _, p in projection.collective_operations
                     if rank in p]
        assert collectives == member_of


def test_global_compute_stays_backward_compatible(tmp_path):
    """No owner => every rank's ET, and an unchanged projection identity."""
    compiled, _machine_, _ns, _tp8, _tp2 = _shape_pair()
    ops = (
        OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=10_000,
                                            participant_count=8)),
        OperationNode(operation_id="ar", kind=KIND_COLLECTIVE, deps=("pre",),
                      detail=collective_detail(
                          collective_kind="ALLREDUCE",
                          participants=tuple(range(8)), payload_bytes=4096,
                          participant_count=8)),
    )
    graph = WorkloadGraph(parallelism=compiled.inventory.parallelism,
                          participant_count=8, operations=ops)
    projection = AstraWorkloadProjection.build(
        logical=LogicalMessageArtifactV2(graph=graph),
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment, et_granularity="collectives")
    # ownership is absent from the identity, so pre-Slice-38 ids are unchanged
    assert "compute_ownership" not in projection.identity_dict()
    per_rank = _write_and_read_et(projection, tmp_path)
    assert all("pre" in names for names in per_rank.values())
    assert projection.declared_compute_cycles() == 10_000


def test_compute_floor_is_the_max_chain_not_the_sum():
    compiled, _machine_, _ns, _tp8, _tp2 = _shape_pair()
    projection = _project(_plan_for(compute_ns=26_000), compiled)
    assert projection.declared_compute_cycles() == 26_000
    assert projection.declared_compute_cycles() != 4 * 26_000
    assert all(projection.compute_owner(op_id) is not None
               for op_id, _ in projection.compute_operations)


def test_owner_outside_the_participant_namespace_refuses():
    compiled, _machine_, _ns, _tp8, _tp2 = _shape_pair()
    ops = (
        OperationNode(operation_id="c", kind=KIND_COMPUTE, owner=99,
                      detail=compute_detail(duration_ns=1,
                                            participant_count=8)),
    )
    with pytest.raises(InvalidInput, match="outside the participant namespace"):
        WorkloadGraph(parallelism=compiled.inventory.parallelism,
                      participant_count=8, operations=ops)


def test_projection_refuses_an_owner_outside_its_participant_namespace():
    compiled, _machine_, _ns, _tp8, _tp2 = _shape_pair()
    with pytest.raises(Exception):
        AstraWorkloadProjection(
            messages=(), participant_count=2, message_artifact_id="m",
            workload_id="w", resolved_fabric_hash="f", mapping_hash="m",
            attachment_hash="a", compute_operations=(("c", 1),),
            compute_owners=(("c", 7),))


# ── communicator groups ───────────────────────────────────────────────────

def test_four_memberships_give_four_deterministic_groups():
    _contract, _ns, _projection, binding, _compiled = _contract_and_ns()
    assert binding.groups.group_ids() == (1, 2, 3, 4)
    assert len(binding.groups.memberships) == 4
    assert binding.binding_id().startswith("sha256:")


def test_operation_id_resolves_exact_membership():
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    projection = _project(_plan_for(), compiled)
    binding = ans.derive_collective_binding(namespace=ns, workload=projection)
    for op_id, _kind, _payload, participants in \
            projection.collective_operations:
        expected = tuple(sorted(ns.endpoint_for(r) for r in participants))
        assert binding.membership_for(op_id) == expected
        assert binding.group_id_for(op_id) == binding.groups.id_for(expected)
        assert binding.mechanism_for(op_id) \
            == ans.MECHANISM_COMMUNICATOR_GROUP_RING


def test_unknown_collective_operation_refuses():
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    binding = ans.derive_collective_binding(
        namespace=ns, workload=_project(_plan_for(), compiled))
    with pytest.raises(ans.AstraNamespaceError, match="no collective binding"):
        binding.membership_for("round9-inst9-batch9-tp")
    with pytest.raises(ans.AstraNamespaceError, match="no collective binding"):
        binding.mechanism_for("round9-inst9-batch9-tp")


def test_same_membership_reuses_one_group_and_different_ones_differ():
    groups = ans.CommunicatorGroups(memberships=((1, (0, 1)), (2, (2, 3))))
    assert groups.id_for((1, 0)) == 1          # order-insensitive
    assert groups.id_for((2, 3)) == 2
    with pytest.raises(ans.AstraNamespaceError, match="no communicator group"):
        groups.id_for((0, 2))
    with pytest.raises(ans.AstraNamespaceError, match="reuse one group"):
        ans.CommunicatorGroups(memberships=((1, (0, 1)), (2, (0, 1))))


def test_group_numbering_is_stable_under_semantically_equal_reordering():
    """Group numbers come from sorted membership, not operation order."""
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    # the same membership SET, assigned to different instances
    forward = _plan_for(instance_ranks={0: (0, 1), 1: (2, 3)})
    swapped = _plan_for(instance_ranks={0: (2, 3), 1: (0, 1)})
    binding_a = ans.derive_collective_binding(
        namespace=ns, workload=_project(forward, compiled))
    binding_b = ans.derive_collective_binding(
        namespace=ns, workload=_project(swapped, compiled))
    # membership is semantic, so the group document is identical...
    assert binding_a.memberships() == binding_b.memberships()
    assert binding_a.groups.groups_id() == binding_b.groups.groups_id()
    # ...while the operation->membership binding correctly differs
    assert binding_a.binding_id() != binding_b.binding_id()


def test_binding_refuses_groups_that_do_not_cover_its_memberships():
    groups = ans.CommunicatorGroups(memberships=((1, (0, 1)),))
    with pytest.raises(ans.AstraNamespaceError, match="do not cover"):
        ans.AstraCollectiveBinding(
            namespace_id="n", workload_projection_id="w", endpoint_count=8,
            operations=(("op", (2, 3), ans.MECHANISM_COMMUNICATOR_GROUP_RING),),
            groups=groups)


def test_round_binding_does_not_change_the_stable_namespace():
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    before = (ns.namespace_id(), ns.rank_to_endpoint,
              ns.participant_mapping_id)
    projection = _project(_plan_for(), compiled)
    binding = ans.derive_collective_binding(namespace=ns, workload=projection)
    assert binding.namespace_id == ns.namespace_id()
    assert binding.endpoint_count == ns.endpoint_count
    assert (ns.namespace_id(), ns.rank_to_endpoint,
            ns.participant_mapping_id) == before
    assert binding.workload_projection_id == projection.projection_id()


# ── ledger contract, keyed by ASTRA node id ───────────────────────────────

def test_ledger_contract_separates_collectives_by_node_id():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    assert len(contract) == 4
    assert len({row.astra_node_id for row in contract}) == 4
    # same kind and size everywhere, so ONLY the node id distinguishes them
    assert {row.collective_kind for row in contract} == {"ALLREDUCE"}
    assert {row.payload_bytes for row in contract} == {4096}
    assert len({row.endpoints for row in contract}) == 4
    assert len({row.operation_id for row in contract}) == 4


def _valid_lines(contract):
    return [_ledger_line(rank=endpoint, node=row.astra_node_id,
                         members=row.endpoints)
            for row in contract for endpoint in row.endpoints]


def test_valid_ledger_passes_per_node():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    lines = _valid_lines(contract)
    assert len(lines) == 8                     # 4 groups x 2 endpoints
    sround.validate_collective_ledger_contract(_entries(lines),
                                               contract=contract)


def test_missing_one_rank_submission_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    victim = contract[0]
    lines = [line for line in _valid_lines(contract)
             if not (f"astra_node={victim.astra_node_id}" in line
                     and line.startswith(f"[LEDGER][COLL_SUBMIT] "
                                         f"rank={victim.endpoints[0]} "))]
    with pytest.raises(sround.ServingRoundError, match="1 of 2 endpoints"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


def test_wrong_group_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    lines = [_ledger_line(rank=endpoint, node=row.astra_node_id,
                          members=(6, 7))
             for row in contract for endpoint in row.endpoints]
    with pytest.raises(sround.ServingRoundError, match="projected membership"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


def test_wrong_collective_size_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    lines = [_ledger_line(rank=endpoint, node=row.astra_node_id, size=4096 + 8,
                          members=row.endpoints)
             for row in contract for endpoint in row.endpoints]
    with pytest.raises(sround.ServingRoundError, match="projected 4096 bytes"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


def test_wrong_collective_kind_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    lines = [_ledger_line(rank=endpoint, node=row.astra_node_id, ctype=2,
                          members=row.endpoints)
             for row in contract for endpoint in row.endpoints]
    with pytest.raises(sround.ServingRoundError, match="projected ALLREDUCE"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


def test_unexpected_collective_node_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    lines = _valid_lines(contract)
    lines.append(_ledger_line(rank=0, node=999, members=(0, 1)))
    with pytest.raises(sround.ServingRoundError, match="never projected"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


def test_a_whole_collective_missing_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    victim = contract[-1]
    lines = [_ledger_line(rank=endpoint, node=row.astra_node_id,
                          members=row.endpoints)
             for row in contract if row is not victim
             for endpoint in row.endpoints]
    with pytest.raises(sround.ServingRoundError, match="never submitted"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


def test_a_group_without_a_communicator_group_refuses():
    contract, _ns, _projection, _binding, _compiled = _contract_and_ns()
    victim = contract[0]
    lines = [_ledger_line(rank=endpoint, node=row.astra_node_id,
                          members=row.endpoints)
             for row in contract for endpoint in row.endpoints
             if row is not victim]
    lines.append(
        f"[LEDGER][COLL_SUBMIT] rank={victim.endpoints[0]} "
        f"astra_node={victim.astra_node_id} comm_type=0 comm_size=4096 "
        "priority=0 involved_dims=[1,1,1,1] group_members=none tick=0")
    with pytest.raises(sround.ServingRoundError, match="without a communicator"):
        sround.validate_collective_ledger_contract(_entries(lines),
                                                   contract=contract)


# ── the fixed-fabric differential proof ───────────────────────────────────

def test_tp8_and_4xtp2_execute_on_the_same_physical_machine():
    """The product philosophy, asserted: workload changed, fabric did not."""
    compiled, machine, ns, tp8, tp2 = _shape_pair()
    # both service geometries share exactly one machine and one namespace
    assert tp8.namespace is tp2.namespace is ns

    fabric_before = {
        "resolved_fabric_hash": machine.resolved_fabric_hash,
        "physical_machine_id": machine.physical_id(),
        "machine_id": machine.machine_id(),
        "prepared_id": machine.prepared_id,
        "standalone_config_sha256": machine.standalone_config_sha256,
        "route_artifact_hash": machine.route_artifact_hash,
        "vc_resource_hash": machine.vc_resource_hash,
        "packet_format_hash": machine.packet_format_hash,
        "topology_hash": machine.topology_hash,
        "endpoint_count": machine.endpoint_count,
        "router_count": machine.router_count,
        "flit_bytes": machine.flit_bytes,
        "rank_to_endpoint": ns.rank_to_endpoint,
        "namespace_id": ns.namespace_id(),
        "machine_files": machine.files(),
    }

    tp8_plan = sround.ServingRoundPlan(
        round_id=0, participant_count=8,
        batches=(_batch_plan(instance_id=0, ranks=tuple(range(8))),))
    tp2_plan = _plan_for()
    tp8_projection = _project(tp8_plan, compiled)
    tp2_projection = _project(tp2_plan, compiled)

    # --- the workload differs -------------------------------------------
    assert len(tp8_projection.collective_operations) == 1
    assert len(tp2_projection.collective_operations) == 4
    assert tp8_projection.projection_id() != tp2_projection.projection_id()
    assert tp8_plan.plan_id() != tp2_plan.plan_id()
    tp8_binding = ans.derive_collective_binding(namespace=ns,
                                                workload=tp8_projection)
    tp2_binding = ans.derive_collective_binding(namespace=ns,
                                                workload=tp2_projection)
    assert tp8_binding.binding_id() != tp2_binding.binding_id()
    assert tp8_binding.groups.to_json() != tp2_binding.groups.to_json()
    assert len(tp8_binding.groups.memberships) == 1
    assert len(tp2_binding.groups.memberships) == 4
    # same kind and the same per-collective size, so bytes cannot explain it
    assert {row.payload_bytes for row in sround.collective_contract(
        projection=tp8_projection, binding=tp8_binding)} == {4096}
    assert {row.payload_bytes for row in sround.collective_contract(
        projection=tp2_projection, binding=tp2_binding)} == {4096}
    assert {row.collective_kind for row in sround.collective_contract(
        projection=tp2_projection, binding=tp2_binding)} == {"ALLREDUCE"}

    # --- the fabric did not move ----------------------------------------
    assert fabric_before["resolved_fabric_hash"] \
        == machine.resolved_fabric_hash
    assert fabric_before["physical_machine_id"] == machine.physical_id()
    assert fabric_before["machine_id"] == machine.machine_id()
    assert fabric_before["prepared_id"] == machine.prepared_id
    assert fabric_before["standalone_config_sha256"] \
        == machine.standalone_config_sha256
    assert fabric_before["rank_to_endpoint"] == ns.rank_to_endpoint
    assert fabric_before["machine_files"] == machine.files()
    assert fabric_before["namespace_id"] == ns.namespace_id()


def test_tp8_and_4xtp2_differ_in_round_evidence_identity(tmp_path):
    """Four TP2 groups must not hash like one TP8 group at equal bytes."""
    row = {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}
    tp8, _, _ = _run(tmp_path / "tp8", [row], fixture=_tp8_loop_fixture())
    tp2, _, _ = _run(tmp_path / "tp2", [dict(row) for _ in range(4)],
                     fixture=_tp2_fixture())
    tp8_evidence = tp8.round_evidence[0]
    tp2_evidence = tp2.round_evidence[0]
    # same physical machine, different execution identity
    assert tp8_evidence.physical_machine_id == tp2_evidence.physical_machine_id
    assert tp8_evidence.machine_id == tp2_evidence.machine_id
    assert tp8_evidence.namespace_id == tp2_evidence.namespace_id
    assert tp8_evidence.evidence_id() != tp2_evidence.evidence_id()
    assert len(tp8_evidence.collective_contract) == 1
    assert len(tp2_evidence.collective_contract) == 4
    assert {len(r.endpoints) for r in tp8_evidence.collective_contract} == {8}
    assert {len(r.endpoints) for r in tp2_evidence.collective_contract} == {2}
    # same kind, same per-collective bytes: only grouping distinguishes them
    for evidence in (tp8_evidence, tp2_evidence):
        assert {r.collective_kind for r in evidence.collective_contract} \
            == {"ALLREDUCE"}
        assert {r.payload_bytes for r in evidence.collective_contract} \
            == {4096}
    assert tp8_evidence.collective_binding_id \
        != tp2_evidence.collective_binding_id
    assert {row.endpoints for row in tp8_evidence.collective_contract} \
        != {row.endpoints for row in tp2_evidence.collective_contract}


# ── the loop: 4xTP2 end to end (contract-faithful runtime) ────────────────

def test_four_tp2_groups_drive_four_real_batches(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}
            for _ in range(4)]
    result, fixture, schedulers = _run(tmp_path, rows, fixture=_tp2_fixture())
    _machine_, ns, _serving, _npus, _backend, _lowering_ = fixture
    assert len(result.rounds) == 1
    record = result.rounds[0]
    assert record.dispatched_instances == (0, 1, 2, 3)
    assert record.idle_instances == ()
    assert len(record.group_ids) == 4
    contract = result.round_evidence[0].collective_contract
    assert len(contract) == 4
    assert sorted(row.endpoints for row in contract) == sorted(
        tuple(sorted(ns.endpoint_for(r) for r in ranks))
        for ranks in TP2_INSTANCES.values())
    assert len({row.astra_node_id for row in contract}) == 4
    # four independent TP2 collectives, never one TP8 collective
    assert len(result.evidence.endpoint_completions) == 8
    assert result.evidence.instances_with_completions == (0, 1, 2, 3)
    assert result.evidence.every_instance_served()
    assert sorted(r.instance_id for r in result.requests) == [0, 1, 2, 3]
    assert len(schedulers) == 4
    assert all(s.done for s in schedulers)


def test_idle_instances_receive_no_collective(tmp_path):
    """Only the instances with work may emit a collective or a completion."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 100_000},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 100_000}]
    result, fixture, _ = _run(tmp_path, rows, fixture=_tp2_fixture())
    _machine_, ns, serving, _npus, _backend, _lowering_ = fixture
    first = result.rounds[0]
    # RR routes the two arrived requests to instances 0 and 1
    assert set(first.dispatched_instances) == {0, 1}
    assert first.idle_instances == (2, 3)
    assert len(first.group_ids) == 2
    evidence = result.round_evidence[0]
    assert len(evidence.collective_contract) == 2
    executed = {row[2] for row in evidence.completion_attributions}
    assert executed == {0, 1}
    for idle in first.idle_instances:
        assert set(serving.endpoints_of(idle)).isdisjoint(
            {row[0] for row in evidence.completion_attributions})
    # the idle instances' requests were not retired in the first round
    assert set(first.retired_request_ids) == {"0", "1"}


def test_endpoint_permutation_remains_active(tmp_path):
    compiled, _machine_, ns, _tp8, _tp2 = _shape_pair()
    assert any(r != e for r, e in ns.rank_to_endpoint)
    assert ns.endpoint_for(0) != 0
    # the map is a permutation of the participant endpoints, not a relabel
    assert sorted(e for _, e in ns.rank_to_endpoint) \
        == list(ns.participant_endpoints())
    projection = _project(_plan_for(), compiled)
    binding = ans.derive_collective_binding(namespace=ns, workload=projection)
    for row in sround.collective_contract(projection=projection,
                                          binding=binding):
        ranks = tuple(sorted(rank for rank, endpoint in ns.rank_to_endpoint
                             if endpoint in row.endpoints))
        assert tuple(sorted(ns.endpoint_for(r) for r in ranks)) \
            == row.endpoints
        # at least one group's endpoints are NOT its ranks, so nothing here
        # could have been inferred by numeric coincidence
    assert any(tuple(sorted(ns.endpoint_for(r) for r in ranks))
               != tuple(sorted(ranks))
               for ranks in TP2_INSTANCES.values())


# ── real 4xTP2 canonical gate (§14) and idle gate (§15) ───────────────────

from test_serving_canonical import BUILT_FROM_SOURCE  # noqa: E402
import os  # noqa: E402

_requires_built = pytest.mark.skipif(
    not BUILT_FROM_SOURCE.is_file(),
    reason="current-source ASTRA frontend not built")
_live_enabled = pytest.mark.skipif(
    os.environ.get("VERITX_LIVE_SERVING") != "1",
    reason="set VERITX_LIVE_SERVING=1 to run the live 4xTP2 gate")


def _group_tables(result, ns, serving):
    """(rank membership, physical endpoint membership) per collective."""
    rows = []
    for row in result.round_evidence[0].collective_contract:
        ranks = tuple(sorted(rank for rank, endpoint in ns.rank_to_endpoint
                             if endpoint in row.endpoints))
        instance = serving.instance_of_rank(ranks[0])
        rows.append((instance, row.operation_id, ranks, row.endpoints,
                     row.astra_node_id))
    return rows


@_requires_built
@_live_enabled
def test_real_4xtp2_canonical_gate(tmp_path):
    """4 independent instances x TP2 on ONE unchanged canonical fabric."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}
            for _ in range(4)]
    result, fixture, schedulers = _run(
        tmp_path, rows, fixture=_tp2_fixture(mode=cs.MODE_LIVE_CANONICAL),
        live=True, timeout_s=900)
    machine, ns, serving, npus, backend, lowering = fixture
    evidence = result.evidence
    evidence.assert_live()
    evidence.assert_all_instances_served()

    contract = result.round_evidence[0].collective_contract
    assert len(contract) == 4, "expected four independent TP collectives"
    assert {len(row.endpoints) for row in contract} == {2}
    assert len({row.astra_node_id for row in contract}) == 4
    assert {row.collective_kind for row in contract} == {"ALLREDUCE"}
    assert {row.payload_bytes for row in contract} == {4096}

    # runtime ledger proof: four distinct groups, exactly 2 submitters each
    ledger = result.round_evidence[0].collective_ledger
    assert len(ledger) == 8, "expected 8 submissions, not one 8-rank collective"
    submitters: dict[int, set] = {}
    for rank, node, _ctype, members in ledger:
        submitters.setdefault(node, set()).add(rank)
        assert tuple(sorted(members)) == tuple(
            sorted(row.endpoints for row in contract
                   if row.astra_node_id == node)[0])
    assert len(submitters) == 4
    assert all(len(peers) == 2 for peers in submitters.values())
    for row in contract:
        assert submitters[row.astra_node_id] == set(row.endpoints)

    # no rank == endpoint assumption anywhere
    assert any(r != e for r, e in ns.rank_to_endpoint)
    for row in contract:
        ranks = tuple(sorted(rank for rank, endpoint in ns.rank_to_endpoint
                             if endpoint in row.endpoints))
        assert tuple(sorted(ns.endpoint_for(r) for r in ranks)) \
            == row.endpoints

    # every dispatched instance executed, and every batch retired
    assert result.rounds[0].dispatched_instances == (0, 1, 2, 3)
    assert evidence.instances_with_completions == (0, 1, 2, 3)
    assert sorted(r.instance_id for r in result.requests) == [0, 1, 2, 3]
    assert all(s.done for s in schedulers)
    for request in result.requests:
        assert request.ttft_ns > 0
        assert request.end_ns >= request.ttft_ns
    # the embedded fabric injected nothing of its own
    assert set(evidence.autonomous_injection_packets) <= {0, None}
    assert result.clock == sum(r.backend_cycles for r in result.rounds)

    print("\n[live-4xtp2] rounds=%d clock=%d groups=%d submissions=%d"
          % (len(result.rounds), result.clock, len(contract), len(ledger)))
    for instance, op_id, ranks, endpoints, node in _group_tables(
            result, ns, serving):
        print(f"  inst{instance} node={node} ranks={ranks} "
              f"endpoints={endpoints} op={op_id}")
    print(f"  machine={machine.physical_id()[:24]} "
          f"fabric={machine.resolved_fabric_hash[:24]} "
          f"evidence={evidence.evidence_id()[:24]}")


@_requires_built
@_live_enabled
def test_real_idle_instance_gate(tmp_path):
    """Only the instances with work may emit a collective or a completion."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 10 ** 9},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 10 ** 9}]
    result, fixture, schedulers = _run(
        tmp_path, rows, fixture=_tp2_fixture(mode=cs.MODE_LIVE_CANONICAL),
        live=True, timeout_s=900)
    machine, ns, serving, npus, backend, lowering = fixture
    first = result.rounds[0]
    assert set(first.dispatched_instances) == {0, 1}
    assert first.idle_instances == (2, 3)
    evidence = result.round_evidence[0]
    assert len(evidence.collective_contract) == 2
    assert len(evidence.collective_ledger) == 4     # 2 groups x 2 endpoints
    executed = {row[2] for row in evidence.completion_attributions}
    assert executed == {0, 1}
    for idle in first.idle_instances:
        assert set(serving.endpoints_of(idle)).isdisjoint(
            {row[0] for row in evidence.completion_attributions})
    print(f"\n[live-idle] dispatched={first.dispatched_instances} "
          f"idle={first.idle_instances} "
          f"groups={len(evidence.collective_contract)} "
          f"submissions={len(evidence.collective_ledger)}")
