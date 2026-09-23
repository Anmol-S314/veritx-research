"""Slice 34 — participant → ASTRA endpoint namespace and communicator groups."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from test_backend_astra_machine import _machine, _projection, BOOKSIM_SOURCE
from test_backend_booksim_projection import _parents

from veritx_dse.backend import astra_execution as ax
from veritx_dse.backend import astra_namespace as ans
from veritx_dse.backend.booksim_projection import prepare_booksim_input
from veritx_dse.workload.traffic import ParticipantEndpointMapping

REPO = Path(__file__).resolve().parents[4]
WORKLOAD_CC = (REPO / "third_party" / "astra-sim" / "astra-sim" / "workload"
               / "Workload.cc")
COMM_GROUP_CC = (REPO / "third_party" / "astra-sim" / "astra-sim" / "system"
                 / "CommunicatorGroup.cc")


def _permutation(participant_count: int, endpoints) -> tuple[tuple[int, int], ...]:
    """A deliberately non-identity rank→endpoint table."""
    pool = list(endpoints)
    rows = []
    for rank in range(participant_count):
        rows.append((rank, pool[(rank * 7 + 3) % len(pool)]))
    assert len({e for _, e in rows}) == participant_count, "not a permutation"
    assert any(r != e for r, e in rows), "permutation degenerated to identity"
    return tuple(rows)


def _namespace(*, permuted=True, granularity="collectives", participants=16):
    compiled, parents, prepared, projection, machine = _machine(
        granularity=granularity, participants=participants)
    endpoints = list(range(machine.astra_sys_count))
    if permuted:
        # leave the driver endpoint(s) out; bind participants to a subset
        pool = endpoints[:participants]
        rows = _permutation(participants, pool)
    else:
        rows = tuple((r, r) for r in range(participants))
    binding = ParticipantEndpointMapping(
        participant_count=participants, rank_to_endpoint=rows,
        fabric_id=machine.resolved_fabric_hash)
    ns = ans.build_namespace(machine=machine, workload=projection,
                             binding=binding,
                             endpoint_count=machine.astra_sys_count,
                             router_count=machine.router_count)
    return compiled, projection, machine, binding, ns


def _stage(tmp_path, projection, ns, *, stem="workload", granularity=None):
    src = tmp_path / "canonical"
    projection.write_chakra(directory=src, stem=stem)
    return ans.stage_endpoint_workload(
        workload=projection, namespace=ns, source_directory=src,
        target_directory=tmp_path / "run", stem=stem)


# ── 1. rank != endpoint ───────────────────────────────────────────────────

def test_permuted_mapping_is_not_identity():
    _, _, _, binding, ns = _namespace()
    assert ns.rank_to_endpoint == binding.rank_to_endpoint
    assert any(r != e for r, e in ns.rank_to_endpoint)
    assert ns.endpoint_for(0) != 0


def test_endpoint_for_is_exact_and_total():
    _, _, _, _, ns = _namespace()
    table = dict(ns.rank_to_endpoint)
    for rank in range(ns.participant_count):
        assert ns.endpoint_for(rank) == table[rank]
    with pytest.raises(ans.AstraNamespaceError, match="no endpoint binding"):
        ns.endpoint_for(ns.participant_count + 5)


def test_namespace_is_deterministic():
    _, _, _, _, first = _namespace()
    _, _, _, _, second = _namespace()
    assert first.namespace_id() == second.namespace_id()
    assert first.identity_dict() == second.identity_dict()


def test_mapping_transplant_changes_namespace_identity():
    _, _, _, _, permuted = _namespace(permuted=True)
    _, _, _, _, identity = _namespace(permuted=False)
    assert permuted.namespace_id() != identity.namespace_id()
    assert permuted.participant_mapping_id != identity.participant_mapping_id


# ── 2. ET staging uses the endpoint namespace ─────────────────────────────

def test_et_filenames_use_endpoint_namespace(tmp_path):
    _, projection, machine, _, ns = _namespace()
    staged = _stage(tmp_path, projection, ns)
    assert staged.endpoints() == ns.participant_endpoints()
    for endpoint, path in staged.endpoint_files:
        assert path.name == f"workload.et.{endpoint}.et"
        assert path.is_file()
    assert staged.base.name == "workload.et"


def test_non_participant_endpoints_receive_no_et(tmp_path):
    _, projection, machine, _, ns = _namespace()
    staged = _stage(tmp_path, projection, ns)
    for endpoint in ns.idle_endpoints():
        assert not (tmp_path / "run" / f"workload.et.{endpoint}.et").exists()
    assert not (tmp_path / "run"
                / f"workload.et.{machine.participant_count}.et").exists()
    # the participant set is a strict subset of the fabric's endpoints
    assert ns.idle_endpoints()


def test_staging_reports_endpoint_translation(tmp_path):
    _, projection, _, _, ns = _namespace(granularity="messages")
    staged = _stage(tmp_path, projection, ns, granularity="messages")
    assert staged.translated_send_recv > 0
    assert staged.translation_id.startswith("sha256:")


# ── 3. SEND/RECV endpoint translation ─────────────────────────────────────

def _read_attrs(path):
    from chakra.schema.protobuf import et_def_pb2 as pb
    from chakra.src.third_party.utils import protolib
    rows = []
    with open(path, "rb") as handle:
        meta = pb.GlobalMetadata()
        assert protolib.decodeMessage(handle, meta)
        while True:
            node = pb.Node()
            if not protolib.decodeMessage(handle, node):
                break
            attrs = {a.name: a for a in node.attr}
            rows.append((node.type, node.name, attrs))
    return rows


def test_send_recv_attributes_use_endpoint_namespace(tmp_path):
    _, projection, _, _, ns = _namespace(granularity="messages")
    staged = _stage(tmp_path, projection, ns, granularity="messages")
    from chakra.schema.protobuf import et_def_pb2 as pb
    mapped = {e: p for e, p in staged.endpoint_files}
    checked = 0
    for endpoint, path in staged.endpoint_files:
        for node_type, _name, attrs in _read_attrs(path):
            if node_type not in (pb.COMM_SEND_NODE, pb.COMM_RECV_NODE):
                continue
            for attr_name in ("comm_src", "comm_dst"):
                if attr_name not in attrs:
                    continue
                value = int(attrs[attr_name].int32_val)
                assert value in mapped, \
                    f"{attr_name}={value} is not an executed endpoint"
                checked += 1
    assert checked > 0, "no SEND/RECV attribute was checked"
    assert mapped  # endpoints staged by endpoint id


def test_canonical_message_identity_remains_rank_based():
    """The canonical artifact is untouched; only the runtime view changes."""
    _, projection, machine, _, ns = _namespace(granularity="messages")
    assert projection.participant_count == ns.participant_count
    identity = json.dumps(projection.identity_dict(), sort_keys=True)
    for token in ("endpoint", "endpoint_id"):
        assert token not in identity
    assert machine.workload_projection_id == projection.projection_id()


# ── 4. communicator groups ────────────────────────────────────────────────

def test_group_ids_are_deterministic_and_positive():
    _, _, _, _, first = _namespace()
    _, _, _, _, second = _namespace()
    assert first.groups.group_ids() == second.groups.group_ids()
    assert all(gid > 0 for gid in first.groups.group_ids())
    assert first.groups.groups_id() == second.groups.groups_id()


def test_same_participant_set_reuses_one_group():
    _, _, _, _, ns = _namespace()
    members = ns.groups.memberships[0][1]
    assert ns.groups.id_for(members) == ns.groups.id_for(tuple(members))


def test_different_participant_sets_get_different_groups():
    groups = ans.CommunicatorGroups(
        memberships=((1, (0, 1)), (2, (2, 3))))
    assert groups.id_for((0, 1)) != groups.id_for((2, 3))
    assert groups.groups_id()


def test_duplicate_memberships_are_refused():
    with pytest.raises(ans.AstraNamespaceError, match="reuse one group"):
        ans.CommunicatorGroups(memberships=((1, (0, 1)), (2, (0, 1))))


def test_group_membership_is_endpoint_sorted_and_canonical():
    _, _, _, _, ns = _namespace()
    for _gid, members in ns.groups.memberships:
        assert tuple(sorted(members)) == members
        assert len(set(members)) == len(members)
        assert set(members) <= set(ns.participant_endpoints())


def test_group_document_is_astra_json(tmp_path):
    _, _, _, _, ns = _namespace()
    path = ans.write_communicator_groups(ns, tmp_path)
    payload = json.loads(path.read_text())
    assert set(payload) == {str(g) for g in ns.groups.group_ids()}
    for key, members in payload.items():
        assert int(key) > 0
        assert members == sorted(members)


def test_group_configuration_bytes_tamper_refuses(tmp_path):
    _, _, _, _, ns = _namespace()
    path = ans.write_communicator_groups(ns, tmp_path)
    path.write_text('{"1": [5]}\n')
    with pytest.raises(ans.AstraNamespaceError, match="already holds"):
        ans.write_communicator_groups(ns, tmp_path)


# ── 5. pg_name attribute ──────────────────────────────────────────────────

def test_pg_name_is_a_chakra_string_attribute(tmp_path):
    _, projection, _, _, ns = _namespace()
    staged = _stage(tmp_path, projection, ns)
    from chakra.schema.protobuf import et_def_pb2 as pb
    found = 0
    for _endpoint, path in staged.endpoint_files:
        for node_type, _name, attrs in _read_attrs(path):
            if node_type != pb.COMM_COLL_NODE:
                continue
            assert "pg_name" in attrs, "collective lacks a pg_name attribute"
            attr = attrs["pg_name"]
            assert attr.WhichOneof("value") == "string_val"
            assert int(attr.string_val) in ns.groups.group_ids()
            found += 1
    assert found == staged.pg_name_nodes > 0


def test_collective_never_relies_on_the_default_group():
    """Every participant set is smaller than the endpoint population."""
    _, _, machine, _, ns = _namespace()
    for _gid, members in ns.groups.memberships:
        assert len(members) < machine.astra_sys_count
    assert "0" not in {str(g) for g in ns.groups.group_ids()}


# ── 6. collective topology mechanism ─────────────────────────────────────

def test_subgroup_collectives_use_the_communicator_group_ring():
    _, _, _, _, ns = _namespace()
    assert ns.mechanisms() == (ans.MECHANISM_COMMUNICATOR_GROUP_RING,)
    for _op, mechanism in ns.collective_mechanisms:
        assert mechanism == ans.MECHANISM_COMMUNICATOR_GROUP_RING


def test_global_mechanism_only_when_the_group_is_the_whole_machine():
    assert ans.collective_mechanism(endpoints=(0, 1, 2), endpoint_count=3) \
        == ans.MECHANISM_GLOBAL_LOGICAL_TOPOLOGY
    assert ans.collective_mechanism(endpoints=(0, 1), endpoint_count=3) \
        == ans.MECHANISM_COMMUNICATOR_GROUP_RING


def test_collective_mechanism_is_identity_bound():
    _, _, _, _, ns = _namespace()
    identity = ns.identity_dict()
    assert identity["collective_mechanisms"]
    mutated = dataclasses.replace(
        ns, collective_mechanisms=((
            ns.collective_mechanisms[0][0],
            ans.MECHANISM_GLOBAL_LOGICAL_TOPOLOGY),))
    assert mutated.namespace_id() != ns.namespace_id()


def test_source_contract_group_smaller_than_cluster_builds_a_ring():
    source = COMM_GROUP_CC.read_text()
    assert "generator->total_nodes) == involved_NPUs.size()" in source
    assert "new RingTopology(" in source
    assert "RingTopology::Dimension::Local" in source
    # the subgroup path forces a one-dimensional plan and removes it after
    assert "dimensions_involved(1, true)" in source
    assert "should_be_removed = true" in source


# ── 7. source contract: idle endpoints ────────────────────────────────────

def test_source_contract_missing_endpoint_et_becomes_idle():
    source = WORKLOAD_CC.read_text()
    assert 'et_filename + "." + to_string(sys->id) + ".et"' in source
    assert "idle NPU, treating as empty" in source
    assert "this->et_feeder = nullptr;" in source
    assert "this->is_finished = true;" in source


def test_source_contract_pg_name_is_a_node_attribute():
    node_cpp = (REPO / "third_party" / "astra-sim" / "extern"
                / "graph_frontend" / "chakra" / "src" / "feeder"
                / "et_feeder_node.cpp").read_text()
    assert 'attr_name == "pg_name"' in node_cpp
    assert "attr.string_val()" in node_cpp


# ── 8. refusals ───────────────────────────────────────────────────────────

def test_missing_participant_binding_refuses():
    _, projection, machine, _, _ = _namespace()
    short = ParticipantEndpointMapping(
        participant_count=4, rank_to_endpoint=tuple((r, r) for r in range(4)),
        fabric_id=machine.resolved_fabric_hash)
    with pytest.raises(Exception, match="covers 4 ranks|participant"):
        ans.build_namespace(machine=machine, workload=projection,
                            binding=short,
                            endpoint_count=machine.astra_sys_count,
                            router_count=machine.router_count)


def test_duplicate_endpoint_binding_refuses():
    with pytest.raises(Exception):
        ParticipantEndpointMapping(
            participant_count=2, rank_to_endpoint=((0, 5), (1, 5)),
            fabric_id="f" * 64)


def test_endpoint_outside_the_fabric_namespace_refuses():
    _, projection, machine, _, _ = _namespace()
    rows = list(ns := _namespace()[4].rank_to_endpoint)
    rows[1] = (rows[1][0], 9999)
    bad = ParticipantEndpointMapping(
        participant_count=machine.participant_count,
        rank_to_endpoint=tuple(rows),
        fabric_id=machine.resolved_fabric_hash)
    with pytest.raises(Exception, match="outside the fabric"):
        ans.build_namespace(machine=machine, workload=projection, binding=bad,
                            endpoint_count=machine.astra_sys_count,
                            router_count=machine.router_count)


def test_endpoint_count_not_router_count_defines_the_sys_namespace():
    _, _, machine, _, ns = _namespace()
    # the ASTRA Sys namespace is the BookSim NODE count (k**n = 25), which is
    # neither the attached-endpoint count (17) nor "routers" for AnyNet
    assert ns.endpoint_count == machine.astra_sys_count == 25
    assert ns.router_count == machine.router_count == 25
    assert ns.attached_endpoint_count == machine.endpoint_count == 17
    assert ns.endpoint_namespace() == tuple(range(machine.astra_sys_count))
    assert machine.astra_sys_count > machine.endpoint_count, \
        "the Sys namespace must be larger than the attached endpoint set"
    memory = json.loads(machine.memory_config_text)
    assert memory["num-nodes"] == machine.astra_sys_count


def test_idle_endpoint_with_communication_refuses():
    _, _, machine, _, ns = _namespace()
    idle = ns.idle_endpoints()[0]
    outcome = ax.AstraOutcome(
        returncode=0,
        stdout="".join(
            f"[workload] sys[{e}] finished, 1000 cycles, exposed communication "
            "1000 cycles.\n" for e in range(machine.astra_sys_count)),
        stderr="".join(
            f"[statistics] sys[{e}], Wall time: 1000\n"
            f"[statistics] sys[{e}], Comm time: "
            f"{777 if e == idle else 10}\n"
            for e in list(ns.participant_endpoints()) + [idle]))
    money = ax.parse_astra_stats(outcome.stdout, outcome.stderr)
    with pytest.raises(ax.AstraExecutionError,
                       match="non-participant fabric endpoint"):
        ax.assert_astra_gate(
            money, machine=machine, injected=None,
            participant_endpoints=ns.participant_endpoints(),
            endpoint_count=ns.endpoint_count)


def test_participant_endpoint_omission_refuses():
    _, _, machine, _, ns = _namespace()
    participants = ns.participant_endpoints()[:-1]
    stdout = "".join(
        f"[workload] sys[{e}] finished, 1000 cycles, exposed communication "
        "1000 cycles.\n" for e in range(machine.astra_sys_count))
    stderr = "".join(
        f"[statistics] sys[{e}], Wall time: 1000\n"
        f"[statistics] sys[{e}], Comm time: 10\n"
        for e in participants)
    money = ax.parse_astra_stats(stdout, stderr)
    with pytest.raises(ax.AstraExecutionError, match="projected endpoints"):
        ax.assert_astra_gate(money, machine=machine, injected=None,
                             participant_endpoints=ns.participant_endpoints(),
                             endpoint_count=ns.endpoint_count)


# ── 9. evidence namespaces ────────────────────────────────────────────────

def _fake_execution(tmp_path, machine, ns=None, *, exposed=30):
    binary = tmp_path / "AstraSim_BookSim2"
    tmp_path.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"#!/bin/sh\nexit 0\n" + b"x" * 64)
    binary.chmod(0o755)
    participants = (ns.participant_endpoints() if ns is not None
                    else tuple(range(machine.participant_count)))
    stdout = "".join(
        f"[workload] sys[{e}] finished, 50000 cycles, exposed communication "
        "50000 cycles.\n" for e in range(machine.astra_sys_count))
    # only executing endpoints get a statistics entry
    stderr = "".join(
        f"[statistics] sys[{e}], Wall time: 50000\n"
        f"[statistics] sys[{e}], Comm time: {exposed}\n"
        for e in participants)
    outcome = ax.AstraOutcome(returncode=0, stdout=stdout, stderr=stderr)

    def runner(command, cwd, timeout):
        return outcome
    return ax.execute_astra_machine(
        machine=machine, binary=binary, run_dir=tmp_path / "run",
        workload_configuration=binary, runner=runner, namespace=ns)


def test_evidence_carries_both_namespaces(tmp_path):
    _, _, machine, _, ns = _namespace()
    evidence = _fake_execution(tmp_path, machine, ns)
    assert evidence.namespace_binding == ax.NAMESPACE_BINDING_CANONICAL
    assert evidence.namespace_id == ns.namespace_id()
    assert evidence.rank_to_endpoint == ns.rank_to_endpoint
    assert evidence.endpoint_count == machine.astra_sys_count
    assert evidence.astra_sys_count == machine.astra_sys_count
    assert evidence.idle_fabric_endpoints == ns.idle_endpoints()
    assert evidence.rank_count == ns.participant_count
    # endpoint namespace is complete; the rank view is the mapped subset
    assert len(evidence.per_endpoint_cycles) == machine.astra_sys_count
    assert len(evidence.per_rank_cycles) == ns.participant_count
    assert dict(evidence.per_rank_cycles) == {
        r: dict(evidence.per_endpoint_cycles)[e]
        for r, e in ns.rank_to_endpoint}


def test_rank_view_is_a_mapping_not_a_relabelling(tmp_path):
    _, _, machine, _, ns = _namespace()
    evidence = _fake_execution(tmp_path, machine, ns)
    for rank, cycles in evidence.per_rank_cycles:
        assert 0 <= rank < ns.participant_count
        assert cycles == dict(evidence.per_endpoint_cycles)[
            ns.endpoint_for(rank)]


def test_identity_binding_is_declared_when_no_mapping_is_supplied(tmp_path):
    _, _, machine, _, _ = _namespace()
    evidence = _fake_execution(tmp_path, machine, None)
    assert evidence.namespace_binding == ax.NAMESPACE_BINDING_IDENTITY
    assert evidence.rank_to_endpoint == tuple(
        (r, r) for r in range(machine.participant_count))
    assert evidence.namespace_id.startswith("sha256:")


def test_namespace_machine_mismatch_refuses(tmp_path):
    _, _, machine, _, ns = _namespace()
    other = _machine(anynet=True)[4]
    assert other.machine_id() != machine.machine_id()
    binary = tmp_path / "b"
    tmp_path.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"x" * 8)
    with pytest.raises(ax.AstraExecutionError, match="different machine"):
        ax.execute_astra_machine(
            machine=other, binary=binary, run_dir=tmp_path / "run",
            workload_configuration=binary, namespace=ns,
            runner=lambda c, d, t: ax.AstraOutcome(0, "", ""))


def test_comm_group_argument_is_passed_to_the_runtime(tmp_path):
    _, _, machine, _, ns = _namespace()
    evidence = _fake_execution(tmp_path, machine, ns)
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_COLLECTIVE
    assert evidence.expansion_authority == "astra_comm_coll"
    group_file = tmp_path / "run" / ans.COMM_GROUP_FILE
    assert group_file.is_file()
    assert json.loads(group_file.read_text())


# ── 10. ASTRA-owned vs canonical-message authority ─────────────────────────

def test_group_execution_stays_labelled_astra_expansion(tmp_path):
    _, _, machine, _, ns = _namespace(granularity="collectives")
    evidence = _fake_execution(tmp_path, machine, ns)
    assert evidence.expansion_authority == "astra_comm_coll"
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_COLLECTIVE


def test_canonical_message_mode_cannot_be_confused(tmp_path):
    _, _, machine, _, ns = _namespace(granularity="messages")
    evidence = _fake_execution(tmp_path, machine, ns)
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_MESSAGES
    assert evidence.expansion_authority == "srota_logical_messages"
    with pytest.raises(ax.AstraExecutionError, match="not interchangeable"):
        ax.assert_comparable(
            evidence, _fake_execution(tmp_path / "b",
                                      _machine(granularity="collectives")[4]))


# ── 11. no fabric mutation ────────────────────────────────────────────────

def test_the_fabric_is_not_altered_to_fit_the_workload():
    _, _, machine, _, ns = _namespace()
    # endpoint/router counts are the canonical fabric's, untouched
    assert machine.endpoint_count < machine.astra_sys_count
    assert ns.endpoint_count == machine.astra_sys_count
    assert ns.router_count == machine.router_count
    identity = json.dumps(ns.identity_dict(), sort_keys=True)
    for forbidden in ("trim", "renumber", "drop_host", "astra_only"):
        assert forbidden not in identity
    # the canonical attachment still carries the driver endpoint
    assert machine.endpoint_count > machine.participant_count


# ── 12. real execution: canonical participants on the full fabric ─────────

from test_backend_astra_machine import (  # noqa: E402
    BUILT_FROM_SOURCE, real_astra_binary,
)

_requires_built = pytest.mark.skipif(
    not BUILT_FROM_SOURCE.is_file(),
    reason="current-source ASTRA frontend not built")


def _real_run(tmp_path, *, granularity="collectives"):
    compiled, parents, prepared, projection, machine = _machine(
        granularity=granularity)
    endpoints = list(range(machine.astra_sys_count))
    rows = _permutation(machine.participant_count,
                        endpoints[:machine.participant_count])
    binding = ParticipantEndpointMapping(
        participant_count=machine.participant_count, rank_to_endpoint=rows,
        fabric_id=machine.resolved_fabric_hash)
    ns = ans.build_namespace(machine=machine, workload=projection,
                             binding=binding,
                             endpoint_count=machine.astra_sys_count,
                             router_count=machine.router_count)
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    staged = _stage(tmp_path, projection, ns, stem="workload")
    evidence = ax.execute_astra_machine(
        machine=machine, binary=BUILT_FROM_SOURCE, run_dir=run,
        workload_configuration=staged.base, timeout_s=900,
        namespace=ns, booksim_source_root=BOOKSIM_SOURCE)
    return machine, ns, staged, evidence


@_requires_built
def test_real_canonical_participants_on_the_full_fabric(tmp_path):
    machine, ns, staged, evidence = _real_run(tmp_path)
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_COLLECTIVE
    assert evidence.expansion_authority == "astra_comm_coll"
    assert evidence.namespace_binding == ax.NAMESPACE_BINDING_CANONICAL
    assert evidence.namespace_id == ns.namespace_id()
    assert evidence.rank_to_endpoint == ns.rank_to_endpoint
    # every participant endpoint completed, no duplicates
    assert set(dict(evidence.per_endpoint_cycles)) \
        >= set(ns.participant_endpoints())
    assert dict(evidence.per_rank_cycles)
    assert len(evidence.per_rank_cycles) == ns.participant_count
    # every non-participant endpoint is idle and carried no communication
    idle_comm = dict(evidence.per_endpoint_exposed_comm)
    for endpoint in evidence.idle_fabric_endpoints:
        assert idle_comm.get(endpoint, 0) == 0, \
            f"idle endpoint {endpoint} carried {idle_comm[endpoint]} cycles"
    assert evidence.autonomous_injection_packets in (None, 0)
    assert evidence.aggregate_cycles > 0
    assert evidence.aggregate_exposed_comm > 0
    assert len(evidence.astra_binary_sha256.split(":")[-1]) == 64
    print(f"\n[real] ns={evidence.namespace_id[:16]} "
          f"ranks={evidence.rank_count} sys={evidence.astra_sys_count} "
          f"endpoints={machine.endpoint_count} routers={machine.router_count} "
          f"groups={ns.groups.group_ids()} "
          f"idle={evidence.idle_fabric_endpoints} "
          f"aggregate={evidence.aggregate_cycles} "
          f"comm={evidence.aggregate_exposed_comm} "
          f"injected={evidence.autonomous_injection_packets} "
          f"bin={evidence.astra_binary_sha256[:16]}")


@_requires_built
def test_real_rerun_is_deterministic(tmp_path):
    _, _, _, first = _real_run(tmp_path / "a")
    _, _, _, second = _real_run(tmp_path / "b")
    assert first.evidence_id() == second.evidence_id()
    assert first.per_endpoint_cycles == second.per_endpoint_cycles
    assert first.per_rank_cycles == second.per_rank_cycles


@_requires_built
def test_real_evidence_names_the_collective_mechanism(tmp_path):
    _, ns, _, evidence = _real_run(tmp_path)
    assert ns.mechanisms() == (ans.MECHANISM_COMMUNICATOR_GROUP_RING,)
    identity = json.dumps(ns.identity_dict(), sort_keys=True)
    assert ans.MECHANISM_COMMUNICATOR_GROUP_RING in identity
    # group evidence is ASTRA expansion, never Slice-29 schedule evidence
    assert evidence.expansion_authority == "astra_comm_coll"
    assert "srota_logical_messages" not in identity


@_requires_built
def test_real_canonical_message_mode_with_endpoint_translation(tmp_path):
    _, ns, staged, evidence = _real_run(tmp_path, granularity="messages")
    assert staged.translated_send_recv > 0
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_MESSAGES
    assert evidence.expansion_authority == "srota_logical_messages"
    assert evidence.status in (ax.STATUS_EXECUTED,
                               ax.STATUS_UNSUPPORTED_MESSAGE_MODE)
    print(f"\n[real-msg] status={evidence.status} "
          f"comm={evidence.aggregate_exposed_comm}")
