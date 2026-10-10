"""Network forks, not source-replicated streams; independent obligation oracle."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_rcu_reference import reference_parents
from veritx_dse.model.multicast_tree import (
    PROFILE, MulticastTreeContract, SinkCredit, execute_multicast, validate_multicast_execution,
)
from veritx_dse.verification.reference_network import execute_request, validate_execution


def multicast_contract(**overrides):
    topology, attachment, vcs, packet_format = reference_parents()
    payload = overrides.get("payload_bytes", 43)
    n = (payload * 8 + packet_format.payload_bits_per_flit - 1) // packet_format.payload_bits_per_flit
    fields = dict(topology=topology, attachment=attachment, vc_resource=vcs, packet_format=packet_format,
                  operation_id="fanout", source=0, destinations=(1, 2, 3, 4), traffic_class="reference",
                  payload_bytes=payload, edges=((0, 0), (1, 1), (2, 1)), injection_vc=0, input_vc_capacity=2,
                  injection_cycles=tuple(range(n)), sinks=tuple(SinkCredit(e, 1, 2, tuple(range(80))) for e in (1, 2, 3, 4)),
                  tick_bound=80)
    fields.update(overrides)
    return MulticastTreeContract(**fields)


def multicast_request():
    contract = multicast_contract()
    # One blocked selected local sink prevents both onward branches.
    contract = replace(contract, sinks=tuple(replace(s, ready_ticks=tuple(range(6, 80))) if s.endpoint == 3 else s for s in contract.sinks))
    return dict(profile=PROFILE, topology=contract.topology.to_dict(), attachment=contract.attachment.to_dict(),
                vc_resource=contract.vc_resource.to_dict(), packet_format=contract.packet_format.to_dict(), contract=contract.to_dict())


def independent_trace_oracle(contract, evidence):
    """No production token/arithmetic/obligation helpers used here.

    Derives endpoint-per-flit obligations and start-occupancy/credit laws from
    actual parents and consumes observed movements, not executor counters.
    """
    endpoints = {e.endpoint_id: e.router_id for e in contract.attachment.endpoints}
    root = endpoints[contract.source]
    channels = {c.channel_id: c for c in contract.topology.channels}
    outgoing = {}
    parent = {}
    for cid, vc in contract.edges:
        channel = channels[cid]
        outgoing.setdefault(channel.src_router, []).append((cid, vc, channel.dst_router))
        parent[channel.dst_router] = channel.src_router
    target_sets = {}
    routers = {root} | set(parent)
    for router in routers:
        target_sets[router] = set()
        for endpoint in contract.destinations:
            at = endpoints[endpoint]
            while True:
                if at == router:
                    target_sets[router].add(endpoint)
                    break
                if at not in parent:
                    break
                at = parent[at]
    q = {r: [] for r in routers}
    local = {r: {e for e in contract.destinations if endpoints[e] == r} for r in routers}
    done = {e: [] for e in contract.destinations}
    credits = {s.endpoint: s.capacity for s in contract.sinks}
    returns = {s.endpoint: [] for s in contract.sinks}
    sinks = {s.endpoint: s for s in contract.sinks}
    payload_width = contract.packet_format.flit_width_bits - (2 * contract.packet_format.endpoint_width_bits + 2 + contract.packet_format.vc_width_bits)
    count = (contract.payload_bytes * 8 + payload_width - 1) // payload_width
    injected = 0
    edges_observed = {cid: [] for cid, _ in contract.edges}
    for step in evidence["trace"]:
        tick = step["tick"]
        for e in credits:
            credits[e] += returns[e].count(tick)
            returns[e] = [t for t in returns[e] if t != tick]
        start = deepcopy(q)
        used_links = set()
        seen_routers = set()
        for move in step["moves"]:
            r = move["router"]
            assert r not in seen_routers
            seen_routers.add(r)
            seq = move["token"]["sequence"]
            assert start[r][0] == seq
            assert move["token"]["operation_id"] == contract.operation_id
            assert move["token"]["packet"] == seq // contract.packet_format.max_packet_flits
            assert move["token"]["flit"] == seq % contract.packet_format.max_packet_flits
            assert move["token"]["payload_range_bits"] == [seq * payload_width, min((seq + 1) * payload_width, contract.payload_bytes * 8)]
            assert move["edges"] == [[cid, vc] for cid, vc, _ in outgoing.get(r, [])]
            assert move["deliveries"] == sorted(local[r])  # exact once, all or none
            child_targets = [target_sets[c] for _, _, c in outgoing.get(r, [])]
            partitions = child_targets + [{e} for e in local[r]]
            assert set().union(*partitions) == target_sets[r]
            assert sum(len(p) for p in partitions) == len(target_sets[r])
            assert q[r].pop(0) == seq
            for cid, _, child in outgoing.get(r, []):
                assert cid not in used_links
                used_links.add(cid)
                assert len(start[child]) < contract.input_vc_capacity
                q[child].append(seq)
                edges_observed[cid].append(seq)
            for e in local[r]:
                assert tick in sinks[e].ready_ticks and credits[e] > 0
                credits[e] -= 1
                if sinks[e].return_delay:
                    returns[e].append(tick + sinks[e].return_delay)
                else:
                    credits[e] += 1
                done[e].append(seq)
        if step["injected"] is not None:
            assert step["injected"]["sequence"] == injected
            assert len(start[root]) < contract.input_vc_capacity
            assert contract.injection_cycles[injected] <= tick
            q[root].append(injected)
            injected += 1
        assert {row["router"]: row["sequences"] for row in step["input_vcs"]} == q
        for e in contract.destinations:
            assert credits[e] + len(returns[e]) == sinks[e].capacity
            assert done[e] == list(range(len(done[e])))
            for seq in range(count):
                assert int(seq >= injected) + done[e].count(seq) + sum(q[r].count(seq) for r in routers if e in target_sets[r]) == 1
        assert all(len(v) <= contract.input_vc_capacity for v in q.values())
    assert evidence["source_injected_flits"] == injected
    assert evidence["edge_flits"] == [[cid, v] for cid, v in sorted(edges_observed.items())]
    assert evidence["modeled_link_wire_bits"] == sum(len(v) for v in edges_observed.values()) * contract.packet_format.flit_width_bits
    assert evidence["delivered"] == [dict(endpoint=e, sequences=done[e], payload_bits=sum(min(payload_width, contract.payload_bytes * 8 - seq * payload_width) for seq in done[e])) for e in contract.destinations]
    if evidence["outcome"] == "COMPLETE":
        assert injected == count and all(not v for v in q.values())
        assert all(done[e] == list(range(count)) for e in done)


@pytest.mark.parametrize("payload", [1, 7, 43, 137])
@pytest.mark.parametrize("capacity", [1, 2, 4])
@pytest.mark.parametrize("delay", [0, 1, 3])
def test_independent_packetization_credit_and_obligation_laws(payload, capacity, delay):
    contract = multicast_contract(payload_bytes=payload, input_vc_capacity=capacity,
        sinks=tuple(SinkCredit(e, 2, delay, tuple(range(80))) for e in (1, 2, 3, 4)))
    result = execute_multicast(contract)
    assert result["outcome"] == "COMPLETE"
    independent_trace_oracle(contract, result)
    width = contract.packet_format.payload_bits_per_flit
    n = (payload * 8 + width - 1) // width
    assert result["source_injected_payload_bits"] == payload * 8
    assert result["source_injected_flits"] == n  # NOT n * destinations
    assert result["completed_edge_flits"] == n * 3  # shared trunk counted once
    assert all(row["payload_bits"] == payload * 8 for row in result["delivered"])
    assert result["modeled_link_wire_bits"] % 8 != 0 or n % 8 == 0
    assert len(result["original_tokens"]) == n
    assert result["fork_events"] == n * 2  # branch at router1 + two co-located sinks router3
    validate_multicast_execution(result, contract=contract)


def test_blocked_child_forbids_sibling_partial_delivery_then_recovers():
    contract = multicast_contract()
    sinks = tuple(replace(s, ready_ticks=tuple(range(10, 80))) if s.endpoint == 2 else s for s in contract.sinks)
    contract = replace(contract, sinks=sinks, input_vc_capacity=1)
    result = execute_multicast(contract)
    independent_trace_oracle(contract, result)
    assert result["outcome"] == "COMPLETE"
    # Router3 waits atomically for sink2, even though sink4 is always ready.
    assert not any(4 in m["deliveries"] for t in result["trace"] if t["tick"] < 10 for m in t["moves"])
    # Backpressure propagates to router1: full child blocks BOTH children and local endpoint3.
    blocked = [t for t in result["trace"] if any(b["router"] == 1 and "INPUT_VC_FULL:3" in b["reasons"] for b in t["blocked"])]
    assert blocked and all(not any(m["router"] == 1 for m in t["moves"]) for t in blocked)


def test_bounded_incomplete_missing_obligations_not_deadlock_or_success():
    contract = multicast_contract(sinks=tuple(SinkCredit(e, 1, 0, () if e == 3 else tuple(range(80))) for e in (1, 2, 3, 4)))
    result = execute_multicast(contract)
    independent_trace_oracle(contract, result)
    assert result["outcome"] == "BOUNDED_INCOMPLETE"
    assert result["ticks_executed"] == 80
    assert all(row["payload_bits"] == 0 for row in result["delivered"])
    assert all(row["pending_source"] or row["inflight"] for row in result["outstanding_obligations"])
    assert result["trace"][-1]["blocked"]


def test_root_local_delivery_with_onward_fork_and_single_router_tree():
    contract = multicast_contract(destinations=(0, 1), edges=((0, 0), (1, 1)),
                                 sinks=tuple(SinkCredit(e, 1, 0, tuple(range(80))) for e in (0, 1)))
    result = execute_multicast(contract)
    independent_trace_oracle(contract, result)
    assert result["outcome"] == "COMPLETE"
    assert result["fork_events"] == result["source_injected_flits"]
    contract = replace(contract, destinations=(0,), edges=(), sinks=(SinkCredit(0, 1, 0, tuple(range(80))),))
    result = execute_multicast(contract)
    independent_trace_oracle(contract, result)
    assert result["completed_edge_flits"] == 0 and result["outcome"] == "COMPLETE"
    assert result["trace"][0]["moves"] == []  # even zero-delay sink can't consume injection this tick


@pytest.mark.parametrize("overrides", [
    {"source": 99}, {"destinations": (1, 1)}, {"destinations": (99,)}, {"destinations": ()},
    {"payload_bytes": 0}, {"payload_bytes": True}, {"input_vc_capacity": 0}, {"tick_bound": 0},
    {"injection_vc": 9}, {"traffic_class": "unknown"}, {"edges": ((0, 9), (1, 1), (2, 1))},
    {"edges": ((0, 0), (1, 1))},  # missing coverage
    {"edges": ((0, 0), (1, 1), (2, 1), (6, 1))},  # reconvergence
    {"edges": ((0, 0), (1, 1), (3, 1))},  # cycle
    {"edges": ((6, 1), (7, 1))},  # disconnected cycle
    {"edges": ((99, 0),)}, {"edges": ((0, 1), (1, 0), (2, 0))},  # illegal VC transition
    {"edges": ((0, 0), (0, 0), (1, 1), (2, 1))},
    {"destinations": (1,), "sinks": (SinkCredit(1, 1, 0, tuple(range(80))),)},  # dead branch
    {"sinks": ()}, {"injection_cycles": ()}, {"injection_cycles": (True,)},
])
def test_invalid_tree_contracts(overrides):
    with pytest.raises(ValueError):
        multicast_contract(**overrides)


@pytest.mark.parametrize("field,value", [("artifact_hash", "tamper"), ("topology_hash", "foreign"),
    ("attachment_hash", "foreign"), ("vc_resource_hash", "foreign"), ("packet_format_hash", "foreign"),
    ("source", 2), ("unknown", 1), ("semantics", {})])
def test_strict_reload_parents_hashes_semantics(field, value):
    contract = multicast_contract()
    args = dict(topology=contract.topology, attachment=contract.attachment, vc_resource=contract.vc_resource, packet_format=contract.packet_format)
    assert MulticastTreeContract.from_dict(contract.to_dict(), **args) == contract
    data = contract.to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        MulticastTreeContract.from_dict(data, **args)


@pytest.mark.parametrize("mutation", ["loss", "duplicate", "unexpected", "range", "packet", "fork", "wire", "input"])
def test_tampered_execution_replay_and_independent_oracle(mutation):
    contract = multicast_contract()
    result = execute_multicast(contract)
    move = next(m for t in result["trace"] for m in t["moves"] if m["deliveries"])
    if mutation == "loss":
        result["delivered"][0]["sequences"].pop()
    elif mutation == "duplicate":
        move["deliveries"].append(move["deliveries"][0])
    elif mutation == "unexpected":
        move["deliveries"].append(99)
    elif mutation == "range":
        move["token"]["payload_range_bits"][0] += 1
    elif mutation == "packet":
        move["token"]["packet"] += 1
    elif mutation == "fork":
        move["edges"].pop()
    elif mutation == "wire":
        result["modeled_link_wire_bits"] += 1
    else:
        result["trace"][0]["input_vcs"][0]["sequences"].append(99)
    with pytest.raises(ValueError):
        validate_multicast_execution(result, contract=contract)
    with pytest.raises((AssertionError, KeyError)):
        independent_trace_oracle(contract, result)


def test_parent_recomputed_binding_rejects_self_consistent_wrong_format_and_foreign_attachment():
    contract = multicast_contract()
    wrong_topology = replace(contract.topology, channels=tuple(replace(c, width_bits=64) for c in contract.topology.channels))
    with pytest.raises(ValueError):
        replace(contract, topology=wrong_topology)
    with pytest.raises(ValueError):
        replace(contract, packet_format=replace(contract.packet_format, topology_hash="foreign", packet_format_hash=""))
    with pytest.raises(ValueError):
        replace(contract, vc_resource=replace(contract.vc_resource, allowed_transitions=((0, 0),), artifact_hash=""))


def test_deterministic_input_schedule_not_hidden_source_replication():
    contract = multicast_contract(injection_cycles=(0,) * len(multicast_contract().injection_cycles))
    result = execute_multicast(contract)
    independent_trace_oracle(contract, result)
    assert result == execute_multicast(contract)
    assert all(t["injected"] is None or isinstance(t["injected"], dict) for t in result["trace"])
    assert result["source_injected_payload_bits"] == contract.payload_bytes * 8


def test_cli_example_replay_is_byte_deterministic_and_identity_bound(tmp_path):
    example = Path(__file__).parents[1] / "examples/multicast_tree_v1.json"
    outputs = [tmp_path / "first.json", tmp_path / "second.json"]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-m", "veritx_dse.verification.reference_network", "--input", str(example)]
    subprocess.run(command + ["--output", str(outputs[0])], check=True, env=env)
    subprocess.run(command + ["--output", str(outputs[1]), "--verify-evidence", str(outputs[0])], check=True, env=env)
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    request = json.loads(example.read_text())
    evidence = json.loads(outputs[0].read_text())
    validate_execution(evidence, request=request)
    assert evidence["result"]["outcome"] == "COMPLETE"
    request["contract"]["tick_bound"] += 1
    with pytest.raises(ValueError):
        validate_execution(evidence, request=request)


@pytest.mark.parametrize("change", ["cycle", "transition", "coverage", "capacity"])
def test_rehashed_invalid_tree_is_not_admitted_by_trusted_hash_declaration(change):
    from veritx_dse.core.artifact import content_id
    contract = multicast_contract()
    data = contract.to_dict()
    if change == "cycle":
        data["edges"] = [[0, 0], [1, 1], [3, 1]]
    elif change == "transition":
        data["edges"] = [[0, 1], [1, 0], [2, 0]]
    elif change == "coverage":
        data["edges"].pop()
    else:
        data["input_vc_capacity"] = 0
    data.pop("artifact_hash")
    data["artifact_hash"] = content_id(PROFILE, data)
    with pytest.raises(ValueError):
        MulticastTreeContract.from_dict(data, topology=contract.topology, attachment=contract.attachment,
            vc_resource=contract.vc_resource, packet_format=contract.packet_format)


def test_shared_resource_parent_refused_and_sink_rows_strict():
    from veritx_dse.model.topology_artifact import SharedLink
    from veritx_dse.model.packet_format import derive_packet_format
    c = multicast_contract()
    t = replace(c.topology, shared_links=(SharedLink(0, 0, (1, 2), 65, 1),))
    a = replace(c.attachment, topology_hash=t.topology_hash())
    f = derive_packet_format(t, a, c.vc_resource, max_packet_flits=2)
    with pytest.raises(ValueError, match="CHANNEL only"):
        replace(c, topology=t, attachment=a, packet_format=f)
    for data in ({"endpoint": 1, "capacity": True, "return_delay": 0, "ready_ticks": []},
                 {"endpoint": 1, "capacity": 1, "return_delay": 0, "ready_ticks": [True]},
                 {"endpoint": 1, "capacity": 1, "return_delay": 0, "ready_ticks": [1, 1]},
                 {"endpoint": 1, "capacity": 1, "return_delay": -1, "ready_ticks": []},
                 {"endpoint": 1, "capacity": 1, "return_delay": 0, "ready_ticks": [], "extra": 1}):
        with pytest.raises(ValueError):
            SinkCredit.from_dict(data)
