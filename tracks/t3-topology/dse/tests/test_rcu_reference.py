"""Topology-bound RCU reference laws; independent UINT32 arithmetic oracle."""
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from veritx_dse.model.attachment import AgentAttachmentArtifact, AgentInterfaceDescriptor, Endpoint
from veritx_dse.model.compile_model import AgentKind
from veritx_dse.model.placement import AgentInstance
from veritx_dse.model.topology_artifact import DirectedChannel, MaterializedFamily, Router, SharedLink, TopologyArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact
from veritx_dse.model.packet_format import derive_packet_format
from veritx_dse.model.reference_network import ReferenceNetworkError
from veritx_dse.model.rcu_reference import (
    PROFILE, RCUReferenceContract, ReducerState, execute_rcu, transition, validate_rcu_execution,
)
from veritx_dse.verification.reference_network import execute_request, load_json, validate_execution


def reference_parents(width=65):
    directions = [(0, 1), (1, 2), (1, 3), (2, 1), (3, 1), (1, 0), (2, 3), (3, 2)]
    channels = []
    out_ports, in_ports = {}, {}
    for i, (a, b) in enumerate(directions):
        src_port, dst_port = out_ports.get(a, 2), in_ports.get(b, 2)
        channels.append(DirectedChannel(i, a, src_port, b, dst_port, width, 1))
        out_ports[a], in_ports[b] = src_port + 1, dst_port + 1
    topology = TopologyArtifact(MaterializedFamily.CUSTOM,
        tuple(Router(r, (r,), 2) for r in range(4)), tuple(channels))
    interface = AgentInterfaceDescriptor(64, 32, "AXI", None, None)
    bindings = [(0, 0), (2, 0), (3, 0), (1, 0), (3, 1)]
    attachment = AgentAttachmentArtifact(topology.topology_hash(), tuple(
        Endpoint(i, AgentInstance(0, i, AgentKind.COMPUTE_TILE), r, port, interface)
        for i, (r, port) in enumerate(bindings)))
    vcs = VCResourceArtifact(2, (0, 1), (("reference", (0, 1)),), ((0, 0), (0, 1), (1, 1)))
    return topology, attachment, vcs, derive_packet_format(topology, attachment, vcs, max_packet_flits=2)


def rcu_contract(**overrides):
    topology, attachment, _, _ = reference_parents()
    fields = dict(topology=topology, attachment=attachment, group_id="reduce", contributors=(0, 1, 2),
                  root=0, reducer_router=1, lane_count=2, service_cycles=2,
                  inbound_paths=((0, (0,)), (1, (3,)), (2, (4,))), outbound_path=(5,),
                  operation="SUM", dtype="UINT32", overflow="WRAP_MOD_2_32")
    fields.update(overrides)
    return RCUReferenceContract(**fields)


def event(kind, cycle, event_id, epoch=0, **extra):
    return dict(kind=kind, cycle=cycle, event_id=event_id, epoch=epoch, group_id="reduce", **extra)


def rcu_request():
    contract = rcu_contract()
    events = [event("open", 0, "00"),
              event("contribute", 0, "01", endpoint=2, values=[2**32 - 1, 0]),
              event("contribute", 1, "02-busy", endpoint=1, values=[1, 2]),
              event("contribute", 2, "03", endpoint=1, values=[1, 2]),
              event("contribute", 4, "04", endpoint=0, values=[2**32 - 1, 3]),
              event("emit", 5, "05-early"), event("emit", 6, "06"),
              event("deliver", 9, "07", endpoint=0)]
    return dict(profile=PROFILE, topology=contract.topology.to_dict(), attachment=contract.attachment.to_dict(),
                contract=contract.to_dict(), events=events, until_cycle=10)


@pytest.mark.parametrize("order", list(permutations((0, 1, 2))))
def test_independent_sum_and_byte_hop_laws(order):
    contract = rcu_contract()
    vectors = {0: [2**32 - 1, 1], 1: [1, 2**32 - 1], 2: [2**32 - 1, 0]}
    events = [event("open", 0, "open")]
    events += [event("contribute", i * 2, f"z{i}", endpoint=e, values=vectors[e]) for i, e in enumerate(order)]
    events += [event("emit", 6, "emit"), event("deliver", 6, "deliver", endpoint=0)]
    # Tie order is event ID, so explicitly arrange emission before delivery.
    events[-2]["event_id"], events[-1]["event_id"] = "a-emit", "b-deliver"
    result = execute_rcu(contract, events, 6)
    assert result["result"] == [sum(vectors[e][lane] for e in order) % (1 << 32) for lane in range(2)]
    assert result["status"] == "DELIVERED"
    assert result["inbound_payload_bytes"] == result["inbound_hop_bytes"] == 3 * 2 * 4
    assert result["outbound_hop_bytes"] == 8
    assert result["accepted_contributions"] == 3
    assert not result["missing"]
    validate_rcu_execution(result, contract=contract, events=events, until_cycle=6)


def active_state(contract):
    state, _ = transition(contract, ReducerState(), event("open", 0, "0"))
    state, _ = transition(contract, state, event("contribute", 0, "1", endpoint=0, values=[1, 2]))
    return state


@pytest.mark.parametrize("bad,reason", [
    (event("contribute", 1, "x", endpoint=1, values=[0, 0]), "BUSY"),
    (event("contribute", 2, "x", endpoint=0, values=[1, 2]), "DUPLICATE_CONTRIBUTOR"),
    (event("contribute", 2, "x", endpoint=0, values=[3, 4]), "DUPLICATE_CONTRIBUTOR"),
    (event("contribute", 2, "x", endpoint=9, values=[0, 0]), "UNKNOWN_CONTRIBUTOR"),
    (event("contribute", 2, "x", endpoint=True, values=[0, 0]), "UNKNOWN_CONTRIBUTOR"),
    (event("contribute", 2, "x", epoch=1, endpoint=1, values=[0, 0]), "WRONG_EPOCH"),
    (event("contribute", 2, "x", endpoint=1, values=[True, 0]), "INVALID_UINT32_VECTOR"),
    (event("contribute", 2, "x", endpoint=1, values=[-1, 0]), "INVALID_UINT32_VECTOR"),
    (event("contribute", 2, "x", endpoint=1, values=[2**32, 0]), "INVALID_UINT32_VECTOR"),
    (event("contribute", 2, "x", endpoint=1, values=[1.0, 0]), "INVALID_UINT32_VECTOR"),
    (event("contribute", 2, "x", endpoint=1, values=[0]), "INVALID_UINT32_VECTOR"),
    (event("emit", 9, "x"), "RESULT_NOT_READY"),
    (event("deliver", 9, "x", endpoint=0), "NOT_EMITTED"),
    (event("deliver", 9, "x", endpoint=1), "WRONG_ROOT"),
    (event("open", 9, "x", epoch=1), "ACTIVE_EPOCH"),
])
def test_rejection_is_state_identity_preserving(bad, reason):
    contract = rcu_contract()
    state = active_state(contract)
    after, response = transition(contract, state, bad)
    assert after is state
    assert response == {"accepted": False, "reason": reason}


def test_exact_busy_boundary_abort_missing_epoch_and_no_implicit_delivery():
    contract = rcu_contract()
    state = active_state(contract)
    state, response = transition(contract, state, event("contribute", 2, "boundary", endpoint=1, values=[0, 0]))
    assert response["accepted"] and state.busy_until == 4
    state, response = transition(contract, state, event("abort", 3, "abort"))
    assert response["missing"] == [2] and state.status == "ABORTED" and state.busy_until == 3
    after, response = transition(contract, state, event("open", 3, "stale", epoch=0))
    assert after is state and response["reason"] == "NONINCREASING_EPOCH"
    state, response = transition(contract, state, event("open", 3, "next", epoch=2))
    assert response["accepted"]
    after, response = transition(contract, state, event("abort", 2, "past", epoch=2))
    assert after is state and response["reason"] == "OUT_OF_ORDER_CYCLE"
    after, response = transition(contract, state, {**event("abort", 3, "group", epoch=2), "group_id": "wrong"})
    assert after is state and response["reason"] == "WRONG_GROUP"
    request = rcu_request()
    partial = execute_rcu(contract, request["events"][:5], 6)
    assert partial["result"] == [2**32 - 1, 5] and partial["emitted_at"] is None and partial["delivered_at"] is None
    partial = execute_rcu(contract, request["events"][:5], 5)
    assert partial["result"] is None
    partial = execute_rcu(contract, request["events"][:2], 20)
    assert partial["result"] is None and partial["missing"] == [0, 1]


@pytest.mark.parametrize("overrides", [
    {"operation": "MAX"}, {"dtype": "INT32"}, {"overflow": "SATURATE"}, {"lane_count": True},
    {"lane_count": 0}, {"service_cycles": 0}, {"contributors": (0, 0, 2)}, {"root": 99},
    {"reducer_router": 99}, {"inbound_paths": ((0, (5,)), (1, (3,)), (2, (4,)))},
    {"outbound_path": ()}, {"outbound_path": (99,)},
    {"inbound_paths": ((0, (0,)), (1, (3,)))},
])
def test_invalid_contracts(overrides):
    with pytest.raises(ValueError):
        rcu_contract(**overrides)


def test_local_paths_root_is_explicit_contributor_shared_resource_refused():
    contract = rcu_contract(contributors=(3,), root=3, inbound_paths=((3, ()),), outbound_path=())
    events = [event("open", 0, "0"), event("contribute", 0, "1", endpoint=3, values=[7, 8])]
    result = execute_rcu(contract, events, 2)
    assert result["result"] == [7, 8] and result["inbound_hop_bytes"] == 0
    t = contract.topology
    shared = replace(t, shared_links=(SharedLink(0, 0, (1, 2), 65, 1),))
    with pytest.raises(ValueError, match="CHANNEL only"):
        replace(contract, topology=shared, attachment=replace(contract.attachment, topology_hash=shared.topology_hash()))


@pytest.mark.parametrize("field,value", [("artifact_hash", "tampered"), ("topology_hash", "foreign"),
    ("attachment_hash", "foreign"), ("semantics", "pipelined"), ("root", 1), ("unknown", 1)])
def test_strict_reload_identity_and_real_path_binding(field, value):
    contract = rcu_contract()
    data = contract.to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        RCUReferenceContract.from_dict(data, topology=contract.topology, attachment=contract.attachment)
    assert RCUReferenceContract.from_dict(contract.to_dict(), topology=contract.topology, attachment=contract.attachment) == contract


@pytest.mark.parametrize("mutation", ["result", "trace", "hash", "boolean", "input"])
def test_execution_tamper_rejected(mutation):
    request = rcu_request()
    evidence = execute_request(request)
    validate_execution(evidence, request=request)
    if mutation == "result":
        evidence["result"]["result"][0] = 0
    elif mutation == "trace":
        evidence["result"]["trace"].pop()
    elif mutation == "hash":
        evidence["artifact_hash"] = "foreign"
    elif mutation == "boolean":
        evidence["result"]["trace"][0]["response"]["accepted"] = 1
    else:
        evidence["request"] = deepcopy(request)
        evidence["request"]["events"][0]["epoch"] = 1
    with pytest.raises(ValueError):
        validate_execution(evidence, request=request)


def test_replay_ids_strict_event_keys_horizon():
    request = rcu_request()
    request["events"][1]["event_id"] = request["events"][0]["event_id"]
    with pytest.raises(ValueError, match="unique"):
        execute_request(request)
    request = rcu_request()
    request["events"][0]["unknown"] = 1
    with pytest.raises(ValueError):
        execute_request(request)
    with pytest.raises(ValueError, match="horizon"):
        execute_rcu(rcu_contract(), rcu_request()["events"], 2)


def test_cli_example_deterministic_roundtrip_and_duplicate_key_refusal(tmp_path):
    example = Path(__file__).parents[1] / "examples/rcu_reference_v1.json"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    outputs = [tmp_path / "first.json", tmp_path / "second.json"]
    command = [sys.executable, "-m", "veritx_dse.verification.reference_network", "--input", str(example)]
    subprocess.run(command + ["--output", str(outputs[0])], check=True, env=env)
    subprocess.run(command + ["--output", str(outputs[1]), "--verify-evidence", str(outputs[0])], check=True, env=env)
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    result = json.loads(outputs[0].read_text())["result"]
    assert result["status"] == "DELIVERED" and result["rejections"] == {"BUSY": 1, "RESULT_NOT_READY": 1}
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"profile":"x", "profile":"y"}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_json(duplicate)


def test_emit_deliver_once_only_completed_epoch_reset_and_stale_contribution():
    contract = rcu_contract()
    state = ReducerState()
    events = rcu_request()["events"]
    for e in events:
        state, _ = transition(contract, state, e)
    assert state.status == "DELIVERED"
    for e in (event("emit", 10, "again"), event("deliver", 10, "again", endpoint=0)):
        after, response = transition(contract, state, e)
        assert after is state and not response["accepted"]
    state, response = transition(contract, state, event("open", 10, "new", epoch=1))
    assert response["accepted"] and not state.accepted and state.accumulator == (0, 0)
    after, response = transition(contract, state, event("contribute", 10, "stale", endpoint=0, values=[1, 2]))
    assert after is state and response["reason"] == "WRONG_EPOCH"
    # Even all contributors admitted is not an emitted/delivered result.
    done = execute_rcu(contract, [*events[:5], event("abort", 5, "abort")], 20)
    assert done["status"] == "ABORTED" and done["missing"] == [] and done["result"] is None


@pytest.mark.parametrize("change", ["path", "root", "contributors", "placement"])
def test_rehashed_invalid_contract_still_checks_real_terminal_and_resource_binding(change):
    from veritx_dse.core.artifact import content_id
    contract = rcu_contract()
    data = contract.to_dict()
    if change == "path":
        data["inbound_paths"][0][1] = [5]
    elif change == "root":
        data["root"] = 1  # existing endpoint but outbound still terminates at router0
    elif change == "contributors":
        data["contributors"] = [0, 1]
    else:
        data["reducer_router"] = 2
    data.pop("artifact_hash")
    data["artifact_hash"] = content_id(PROFILE, data)
    with pytest.raises(ValueError):
        RCUReferenceContract.from_dict(data, topology=contract.topology, attachment=contract.attachment)


def test_missing_parent_hash_boolean_schema_and_multiplane_are_not_accepted():
    request = rcu_request()
    request["topology"].pop("topology_hash")
    with pytest.raises(ValueError):
        execute_request(request)
    c = rcu_contract()
    with pytest.raises(ValueError):
        replace(c, topology=replace(c.topology, schema_version=True))
    t = replace(c.topology, planes=("c", "d"))
    with pytest.raises(ValueError, match="Plane D"):
        replace(c, topology=t, attachment=replace(c.attachment, topology_hash=t.topology_hash()))
