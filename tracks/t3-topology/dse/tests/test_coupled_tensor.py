"""Connected reference causality, contents, overlap and endpoint envelopes."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

import pytest

from veritx_dse.application.coupled_tensor import execute_coupled_tensor, run_document, CoupledTensorEvidence
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.tensor_demand import RemoteDemandPolicy
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.application.data_movement import AccessDenied
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.coupled_tensor import CoupledTensorWorkload
from veritx_dse.model.physical_placement import PhysicalPlacement

EXAMPLE = Path(__file__).resolve().parents[1]/"examples/coupled_tensor_v5.json"


@pytest.fixture
def doc():
    return json.loads(EXAMPLE.read_text())


def run(doc):
    return run_document(doc).to_dict()


def time(row, key="time_s"):
    return Fraction(row[key]["numerator"], row[key]["denominator"])


def compute(nid, deps=(), cycles=20, engine="alu"):
    return {"node_id": nid, "kind": "COMPUTE", "engine_id": engine,
            "cycles": cycles, "occupancy": 1, "deps": list(deps)}


def reset(nid, deps, cycles=5):
    return {"node_id": nid, "kind": "DRAIN_RESET", "reset_clock": "memory", "cycles": cycles, "deps": list(deps)}


def add_owner_cache_tensor(doc, accesses, *, chain=True):
    w = doc["workload"]
    tensor = w["demand"]["tensors"][0]
    tensor.update(element_bytes=1, element_count=30, size_bytes=30, shards=[{
        "shard_id": "cache-shard", "offset_bytes": 0, "size_bytes": 30,
        "target": 1, "address_space": "GLOBAL", "base_address": 4099, "transaction_bytes": 16}])
    initial = bytes(range(30))
    w["initial_images"]["activation"] = initial.hex()
    w["demand"]["accesses"][0].update(offset_bytes=0, block_bytes=4, count=1, stride_bytes=4)
    w["access_values"]["read"] = initial[:4].hex()
    w["demand"]["accesses"][1].update(offset_bytes=8, block_bytes=4, count=1, stride_bytes=4)
    w["access_values"]["write"] = b"WXYZ".hex()
    w["cache_profile"] = {"line_bytes": 4, "capacity_bytes": 8,
        "lookup_cycles": 2, "line_fill_service_cycles": 3}
    previous = None
    for access_id, kind, offset, expected, value in accesses:
        logical_offset = offset + 1
        w["demand"]["accesses"].append({"access_id": access_id, "tensor_id": "activation",
            "issuer": 0, "kind": kind, "offset_bytes": logical_offset, "block_bytes": 4,
            "count": 1, "stride_bytes": 4, "deps": [previous if chain and previous else "write"],
            "cache_policy": "OWNER_CACHE"})
        w["access_values"][access_id] = (expected if kind == "READ" else value).hex()
        w["nodes"].append({"node_id": "cache_" + access_id, "kind": "ACCESS",
            "access_id": access_id, "deps": ["cache_" + previous] if chain and previous else ["store"]})
        previous = access_id


def add_retry(doc, original="read", deps=("store",)):
    w = doc["workload"]
    a = deepcopy(next(a for a in w["demand"]["accesses"] if a["access_id"] == original))
    a.update(access_id="retry", deps=["write"])
    w["demand"]["accesses"].append(a)
    w["nodes"].append({"node_id": "repeat", "kind": "ACCESS", "access_id": "retry", "retry_of": original, "deps": list(deps)})
    w["access_values"]["retry"] = w["access_values"][original]


def rebind(doc, edit):
    request = CompileRequestV5.from_dict(doc["design"])
    request = edit(request)
    c = FabricCompiler().compile(request)
    assert c.status == "COMPILED", c.error
    doc["design"] = request.to_dict()
    doc["workload"]["demand"].update(design_hash=request.design_hash(), system_hash=c.compiled_system.system_hash())
    return c


def test_connected_contents_and_exact_causality(doc):
    x = run(doc)
    assert x["status"] == "COMPLETE"
    initial = bytearray(range(64)); initial[28:40] = bytes([170]*12)
    assert x["final_images"]["activation"] == initial.hex()
    assert x["read_results"]["read"]["hex"] == doc["workload"]["access_values"]["read"]
    assert x["read_results"]["read"]["complete"]
    kernel = x["compute_intervals"][0]
    read_done = next(time(r) for r in x["ledger"] if r["event"] == "access_complete" and r["id"] == "load")
    assert time(kernel, "start_s") >= read_done
    assert time(kernel, "completion_s") - time(kernel, "start_s") == Fraction(20, 250_000_000)
    writes = [c for c in x["children"] if c["kind"] == "WRITE"]
    assert min(time(c, "issued_s") for c in writes) >= time(kernel, "completion_s")
    s = x["summary"]
    assert s["payload_bytes"] == s["useful_payload_bytes"] == 52
    assert s["children_issued"] == s["children_committed"] == s["children_responded"] == 8
    assert s["children_live"] == s["children_source_held"] == 0
    assert s["write_bytes_committed"] == 12
    assert s["read_bytes_returned"] == 40
    assert s["fifo_words_reserved_written"] == s["fifo_words_reserved_read"] == 72
    assert time(s, "elapsed_s") == Fraction(509, 10**9)
    assert all(span["decision"]["observed"] for a in x["authorizations"] for span in a["spans"])


def test_slow_memory_moves_compute_and_later_injections_not_independent_compute(doc):
    doc["workload"]["nodes"].append(compute("independent", cycles=10, engine="other"))
    doc["workload"]["engines"].append({"engine_id": "other", "clock": "network", "capacity": 1})
    fast = run(doc)
    doc["transport"]["service_cycles"] *= 10
    slow = run(doc)
    intervals = lambda x: {r["node_id"]: r for r in x["compute_intervals"]}
    assert intervals(fast)["independent"] == intervals(slow)["independent"]
    assert time(intervals(slow)["kernel"], "start_s") > time(intervals(fast)["kernel"], "start_s")
    first_write = lambda x: min(time(r, "issued_s") for r in x["children"] if r["kind"] == "WRITE")
    assert first_write(slow) > first_write(fast)


def test_overlap_vs_serial_capacity_and_same_edge_release(doc):
    doc["workload"]["nodes"] += [compute("a", cycles=1000), compute("b", cycles=1000)]
    serial = run(doc)
    doc["workload"]["engines"][0]["capacity"] = 3
    overlap = run(doc)
    intervals = lambda x: {r["node_id"]: r for r in x["compute_intervals"]}
    s, o = intervals(serial), intervals(overlap)
    assert time(s["b"], "start_s") == time(s["a"], "completion_s")
    assert time(o["a"], "start_s") == time(o["b"], "start_s") == 0
    assert time(serial["summary"], "elapsed_s") > time(overlap["summary"], "elapsed_s")
    assert overlap["summary"]["peak_engine_occupancy"]["alu"] == 3


def test_all_same_time_completions_precede_canonical_resource_contenders(doc):
    w = doc["workload"]
    w["engines"] += [{"engine_id": e, "clock": "memory", "capacity": 1} for e in ("e1", "e2")]
    w["nodes"] += [compute("a_release", cycles=1, engine="e1"), compute("b_release", cycles=1, engine="e2"),
                   compute("z_work", deps=["a_release"], cycles=10), compute("a_work", deps=["b_release"], cycles=10)]
    x = run(doc)
    intervals = {r["node_id"]: r for r in x["compute_intervals"]}
    assert time(intervals["a_work"], "start_s") == time(intervals["a_release"], "completion_s")
    assert time(intervals["z_work"], "start_s") == time(intervals["a_work"], "completion_s")
    same_time = [r for r in x["ledger"] if time(r) == time(intervals["a_work"], "start_s")]
    assert [r["event"] for r in same_time] == ["compute_complete", "compute_complete", "compute_reserved"]


def test_credit_one_backpressures_live_injections(doc):
    from veritx_dse.model.transaction_intent import OutstandingLimit
    fast = run(doc)
    def edit(r):
        intent = r.agent_intents[0]
        intent = replace(intent, transaction_policy=replace(intent.transaction_policy, outstanding=OutstandingLimit(total=1)))
        return replace(r, agent_intents=(intent, *r.agent_intents[1:]))
    rebind(doc, edit)
    slow = run(doc)
    assert slow["summary"]["peak_outstanding"] == {"0": 1}
    assert time(slow["children"][1], "issued_s") >= time(slow["children"][0], "completed_s")
    assert time(fast["children"][1], "issued_s") < time(fast["children"][0], "completed_s")
    assert time(slow["summary"], "elapsed_s") > time(fast["summary"], "elapsed_s")


def test_inclusive_horizon_and_partial_ownership(doc):
    doc["workload"]["horizon_cycles"] = 1
    x = run(doc)
    assert x["status"] == "INCOMPLETE"
    assert x["summary"]["children_issued"] == x["summary"]["children_responded"] + x["summary"]["children_live"]
    assert x["pending_nodes"]
    assert time(x["summary"], "elapsed_s") == time(x["summary"], "horizon_s")
    assert not any(span["decision"]["observed"] for a in x["authorizations"] for span in a["spans"])
    assert not x["read_results"]["read"]["complete"]
    assert x["read_results"]["read"]["hex"] is None
    assert x["summary"]["children_declared"] == x["summary"]["children_source_held"] + sum(x["summary"]["child_states"].values())
    assert x["summary"]["children_memory_accepted"] == x["summary"]["children_committed"] + x["summary"]["child_states"]["MEMORY_QUEUED_OR_SERVICING"]
    # Exact completion is 509ns, between adjacent 250MHz memory edges.
    doc["workload"]["horizon_clock"] = "memory"
    doc["workload"]["horizon_cycles"] = 128  # 512ns includes completion
    assert run(doc)["status"] == "COMPLETE"
    doc["workload"]["horizon_cycles"] = 127
    assert run(doc)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("mutation", ["cycle", "unknown", "engine", "bool", "duration", "image", "value", "field", "gap"])
def test_strict_negative_inputs(doc, mutation):
    w = doc["workload"]
    if mutation == "cycle": w["nodes"][0]["deps"] = ["store"]
    elif mutation == "unknown": w["nodes"][0]["deps"] = ["absent"]
    elif mutation == "engine": w["nodes"][1]["engine_id"] = "absent"
    elif mutation == "bool": w["nodes"][1]["cycles"] = True
    elif mutation == "duration": del w["nodes"][1]["cycles"]
    elif mutation == "image": w["initial_images"]["activation"] = "00"
    elif mutation == "value": w["access_values"].pop("read")
    elif mutation == "field": w["coherent"] = True
    elif mutation == "gap": w["demand"]["tensors"][0]["shards"][0]["size_bytes"] -= 2
    with pytest.raises(InvalidInput): run(doc)


@pytest.mark.parametrize("kind", ["COHERENT", "POWER_OFF", "SIDEBAND", "ATOMIC", "TIMEOUT_RETRY"])
def test_unsupported_actions_refuse_not_fake_protocol(doc, kind):
    doc["workload"]["nodes"].append({"node_id": "unsupported", "kind": kind, "deps": []})
    with pytest.raises(UnsupportedSemantics): run(doc)


def test_cache_intent_refuses(doc):
    doc["workload"]["demand"]["accesses"][0]["cache_policy"] = "LRU"
    with pytest.raises(UnsupportedSemantics): run(doc)


def test_owner_cache_lru_hit_miss_eviction_and_service_costs(doc):
    initial = bytearray(range(16)); initial[8:12] = b"WXYZ"
    add_owner_cache_tensor(doc, [(f"r{i}", "READ", offset, initial[offset+1:offset+5], b"")
                                 for i, offset in enumerate((0, 0, 4, 8, 0))])
    x = run(doc)
    rows = [c for c in x["children"] if c["child"]["parent_id"].startswith("tensor-request")]
    cache_records = [c for c in x["children"] if "owner_cache_plan" in c]
    assert len(cache_records) == 5
    assert [r["owner_cache_plan"]["misses"] != [] for r in cache_records] == [True, False, True, True, True]
    service = [p["service_cycles"] for p in x["phases"] if p["parent"] in {c["child"]["parent_id"] for c in cache_records} and "service_cycles" in p]
    assert sorted(service) == [2, 5, 5, 5, 5]
    stats = x["cache_statistics"]
    assert (stats["line_lookups"], stats["hits"], stats["misses"], stats["evictions"]) == (5, 1, 4, 2)
    assert stats["backing_read_bytes"] == 16
    assert x["scope"]["cache_policy"] == "ABSTRACT_OWNER_CACHE_REFERENCE"
    assert x["summary"]["payload_bytes"] == 28  # cache does not suppress network payload


def test_owner_cache_queued_miss_then_hit_is_serial_at_target(doc):
    image = bytes(range(16))
    add_owner_cache_tensor(doc, [("p", "READ", 0, image[1:5], b""),
                                 ("q", "READ", 0, image[1:5], b"")], chain=False)
    x = run(doc)
    rows = [c for c in x["children"] if "owner_cache_plan" in c]
    assert len(rows) == 2
    assert sorted(c["owner_cache_plan"]["cycles"] for c in rows) == [2, 5]
    assert x["cache_statistics"]["misses"] == 1
    assert x["cache_statistics"]["hits"] == 1
    service = [p for p in x["phases"] if p.get("service_cycles") in (2, 5)
               and p["parent"] in {c["child"]["parent_id"] for c in rows}]
    assert len(service) == 2
    assert max(Fraction(p["start_s"]["numerator"], p["start_s"]["denominator"]) for p in service) >= min(
        Fraction(p["completed_s"]["numerator"], p["completed_s"]["denominator"]) for p in service)


def test_owner_cache_write_invalidation_and_retry_snapshot(doc):
    initial = bytes(range(16))
    add_owner_cache_tensor(doc, [("before", "READ", 0, initial[1:5], b""),
        ("warm", "READ", 0, initial[1:5], b""), ("write-cache", "WRITE", 0, b"", b"WXYZ"),
        ("after-write", "READ", 0, b"WXYZ", b"")])
    x = run(doc)
    assert x["read_results"]["after-write"]["hex"] == b"WXYZ".hex()
    assert x["cache_statistics"]["invalidations"] == 1
    assert x["cache_statistics"]["misses"] >= 2
    assert bytes.fromhex(x["final_images"]["activation"][:16])[:8] == b"\x00WXYZ\x05\x06\x07"


def test_owner_cache_bypass_write_invalidates_owner_copy(doc):
    image = bytes(range(16))
    add_owner_cache_tensor(doc, [("warm", "READ", 0, image[1:5], b"")])
    w = doc["workload"]
    w["demand"]["accesses"].append({"access_id": "uncached-write", "tensor_id": "activation",
        "issuer": 0, "kind": "WRITE", "offset_bytes": 1, "block_bytes": 4,
        "count": 1, "stride_bytes": 4, "deps": ["warm"], "cache_policy": "BYPASS"})
    w["access_values"]["uncached-write"] = b"ABCD".hex()
    w["nodes"].append({"node_id": "uncached_write", "kind": "ACCESS",
        "access_id": "uncached-write", "deps": ["cache_warm"]})
    w["demand"]["accesses"].append({"access_id": "cold", "tensor_id": "activation",
        "issuer": 0, "kind": "READ", "offset_bytes": 1, "block_bytes": 4,
        "count": 1, "stride_bytes": 4, "deps": ["uncached-write"], "cache_policy": "OWNER_CACHE"})
    w["access_values"]["cold"] = b"ABCD".hex()
    w["nodes"].append({"node_id": "cache_cold", "kind": "ACCESS", "access_id": "cold",
        "deps": ["uncached_write"]})
    x = run(doc)
    assert x["read_results"]["cold"]["hex"] == b"ABCD".hex()
    assert x["cache_statistics"]["invalidations"] == 1
    assert x["cache_statistics"]["misses"] == 2


def test_owner_cache_retry_replays_snapshot_without_touching_lru(doc):
    image = bytes(range(16))
    add_owner_cache_tensor(doc, [("before", "READ", 0, image[1:5], b""),
        ("write-cache", "WRITE", 0, b"", b"WXYZ"), ("after-write", "READ", 0, b"WXYZ", b"")])
    add_retry(doc, original="before", deps=("cache_write-cache",))
    x = run(doc)
    retry = next(c for c in x["children"] if c.get("owner_cache_plan", {}).get("retry"))
    assert x["read_results"]["retry"]["hex"] == image[1:5].hex()
    assert retry["owner_cache_plan"]["cycles"] == 2
    assert retry["owner_cache_plan"]["misses"] == []
    assert x["cache_statistics"]["dedup_lookups"] == 1
    assert x["cache_statistics"]["dedup_lookup_cycles"] == 2
    assert x["cache_statistics"]["hits"] == 1  # the WRITE lookup only; retry is not a hit


def test_owner_cache_retry_of_resident_line_does_not_count_as_hit_or_touch_lru(doc):
    image = bytes(range(16))
    add_owner_cache_tensor(doc, [("before", "READ", 0, image[1:5], b"")])
    add_retry(doc, original="before", deps=("cache_before",))
    x = run(doc)
    retry = next(c for c in x["children"] if c.get("owner_cache_plan", {}).get("retry"))
    assert x["read_results"]["retry"]["hex"] == image[1:5].hex()
    assert retry["owner_cache_plan"]["cycles"] == 2
    assert x["cache_statistics"]["line_lookups"] == 1
    assert x["cache_statistics"]["dedup_lookups"] == 1
    assert x["cache_statistics"]["hits"] == 0


def test_owner_cache_retry_after_eviction_keeps_original_read_snapshot(doc):
    image = bytearray(range(16)); image[8:12] = b"WXYZ"
    add_owner_cache_tensor(doc, [("original", "READ", 0, image[1:5], b""),
        ("evict-a", "READ", 4, image[5:9], b""), ("evict-b", "READ", 8, image[9:13], b"")])
    add_retry(doc, original="original", deps=("cache_evict-b",))
    x = run(doc)
    retry = next(c for c in x["children"] if c.get("owner_cache_plan", {}).get("retry"))
    assert x["read_results"]["retry"]["hex"] == image[1:5].hex()
    assert retry["owner_cache_plan"]["cycles"] == 2
    assert x["cache_statistics"]["evictions"] == 1
    assert x["cache_statistics"]["misses"] == 3
    assert x["cache_statistics"]["dedup_lookups"] == 1


def test_owner_cache_reset_clears_cache_and_horizon_does_not_commit_fill(doc):
    image = bytes(range(16))
    add_owner_cache_tensor(doc, [("first", "READ", 0, image[1:5], b"")])
    w = doc["workload"]
    w["nodes"].append(reset("cache_reset", ["cache_first"], cycles=0))
    w["demand"]["accesses"].append({"access_id": "second", "tensor_id": "activation",
        "issuer": 0, "kind": "READ", "offset_bytes": 1, "block_bytes": 4,
        "count": 1, "stride_bytes": 4, "deps": ["first"], "cache_policy": "OWNER_CACHE"})
    w["access_values"]["second"] = image[1:5].hex()
    w["nodes"].append({"node_id": "cache_second", "kind": "ACCESS", "access_id": "second",
                       "deps": ["cache_reset"]})
    x = run(doc)
    assert x["cache_statistics"]["misses"] == 2
    doc["workload"]["horizon_cycles"] = 1
    partial = run(doc)
    assert partial["status"] == "INCOMPLETE"
    assert partial["cache_statistics"]["line_lookups"] == 0
    assert partial["cache_statistics"]["backing_read_bytes"] == 0


def test_owner_cache_line_boundary_and_uninitialized_fill_refuse_before_issue(doc):
    add_owner_cache_tensor(doc, [("r", "READ", 0, bytes(range(1, 5)), b"")])
    assert run(doc)["status"] == "COMPLETE"
    doc["workload"]["cache_profile"].update(line_bytes=8, capacity_bytes=16)
    with pytest.raises(UnsupportedSemantics, match="same initialized shard"):
        run(doc)


def test_owner_cache_profile_bounds_and_bypass_compatibility(doc):
    original = run(doc)
    assert "cache_statistics" not in original
    assert original["scope"]["cache_policy"] == "BYPASS"
    doc["workload"]["cache_profile"] = {"line_bytes": 3, "capacity_bytes": 9,
        "lookup_cycles": 0, "line_fill_service_cycles": 1}
    with pytest.raises(InvalidInput, match="power of two"):
        run(doc)
    assert original == run(json.loads(EXAMPLE.read_text()))


def test_owner_cache_cannot_be_silently_lowered_by_demand_only_consumer(doc):
    from veritx_dse.model.tensor_demand import TensorDemandWorkload
    from veritx_dse.workload.tensor_demand import lower_tensor_demand
    doc["workload"]["demand"]["accesses"][0]["cache_policy"] = "OWNER_CACHE"
    compilation = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    with pytest.raises(UnsupportedSemantics, match="coupled owner-cache"):
        lower_tensor_demand(compilation, TensorDemandWorkload.from_dict(doc["workload"]["demand"]))


def test_unprotected_write_race_refuses_and_explicit_dependency_repairs(doc):
    doc["workload"]["demand"]["accesses"][1]["deps"] = []
    doc["workload"]["nodes"][2]["deps"] = []
    with pytest.raises(UnsupportedSemantics, match="unsequenced"): run(doc)
    doc["workload"]["nodes"][2]["deps"] = ["load"]
    assert run(doc)["status"] == "COMPLETE"


def test_compiled_ordering_edges_cycle_refused(doc):
    from veritx_dse.model.transaction_intent import OrderingPolicy, OrderingMode
    doc["workload"]["demand"]["accesses"][1]["deps"] = []
    doc["workload"]["nodes"][2]["deps"] = []
    doc["workload"]["nodes"][0]["deps"] = ["store"]
    def edit(r):
        i = r.agent_intents[0]
        p = replace(i.transaction_policy, ordering=OrderingPolicy(OrderingMode.STRONG, True, True, True, "memory-ops"))
        return replace(r, agent_intents=(replace(i, transaction_policy=p), *r.agent_intents[1:]))
    rebind(doc, edit)
    with pytest.raises(InvalidInput, match="cycle"): run(doc)


def test_corrupt_expected_read_is_not_byte_conservation_success(doc):
    doc["workload"]["access_values"]["read"] = "ff"*40
    with pytest.raises(EvidenceInvalid, match="expected bytes"): run(doc)


def test_retry_read_snapshot_after_intervening_write(doc):
    add_retry(doc)
    x = run(doc)
    assert x["status"] == "COMPLETE"
    assert x["read_results"]["retry"]["hex"] == x["read_results"]["read"]["hex"]
    assert bytes.fromhex(x["final_images"]["activation"])[28:40] == bytes([170]*12)
    assert x["summary"]["deduplicated_payload_bytes"] == x["summary"]["retry_payload_bytes"] == 40
    assert x["summary"]["retry_flits_planned"] > 0
    assert x["summary"]["retry_flits_planned"] + x["summary"]["useful_flits_planned"] == x["summary"]["flits_declared"]
    assert x["summary"]["write_bytes_committed"] == 12
    assert x["summary"]["payload_bytes"] == 92


def test_retry_write_does_not_mutate_twice(doc):
    add_retry(doc, "write")
    x = run(doc)
    assert x["summary"]["write_bytes_committed"] == 12
    assert x["summary"]["deduplicated_payload_bytes"] == 12
    assert x["summary"]["children_responded"] == 11


@pytest.mark.parametrize("mutation", ["payload", "range", "dependency", "chain", "unknown", "epoch"])
def test_invalid_retry_refuses_before_issue(doc, mutation):
    add_retry(doc, "write")
    w = doc["workload"]
    if mutation == "payload": w["access_values"]["retry"] = "bb"*12
    elif mutation == "range": w["demand"]["accesses"][-1]["offset_bytes"] += 2
    elif mutation == "dependency":
        w["nodes"][-1]["deps"] = []; w["demand"]["accesses"][-1]["deps"] = []
    elif mutation == "chain": w["nodes"][-1]["retry_of"] = "retry"
    elif mutation == "unknown": w["nodes"][-1]["retry_of"] = "missing"
    elif mutation == "epoch":
        w["nodes"].append(reset("reset", ["store"]))
        w["nodes"][3]["deps"] = ["reset"]
    with pytest.raises((InvalidInput, UnsupportedSemantics)): run(doc)


def test_drain_reset_retains_image_advances_epoch_and_allows_compute_overlap(doc):
    w = doc["workload"]
    w["nodes"].append(reset("reset", ["load"], cycles=100))
    w["nodes"][2]["deps"].append("reset")
    x = run(doc)
    assert x["status"] == "COMPLETE" and x["endpoint_epoch"] == 1
    r = x["reset_intervals"][0]
    assert time(r, "start_s") >= max(time(c, "completed_s") for c in x["children"] if c["kind"] == "READ")
    read_parents = {c["child"]["parent_id"] for c in x["children"] if c["kind"] == "READ"}
    read_phases = [p for p in x["phases"] if p["parent"] in read_parents]
    assert time(r,"start_s") >= max(time(p,"reusable_s") for p in read_phases)
    assert any(time(p,"reusable_s") > time(p,"completed_s") for p in read_phases)
    assert time(r, "completion_s") - time(r, "start_s") == Fraction(100,250_000_000)
    assert time(x["compute_intervals"][0], "completion_s") < time(r, "completion_s")
    assert all(c["epoch"] == 1 for c in x["children"] if c["kind"] == "WRITE")
    assert bytes.fromhex(x["final_images"]["activation"])[28:40] == bytes([170]*12)
    doc["workload"]["horizon_cycles"] = 200
    partial = run(doc)
    assert partial["status"] == "INCOMPLETE" and partial["endpoint_epoch"] == 0
    assert partial["summary"]["children_live"] == 0
    assert partial["summary"]["children_source_held"] == 3


def test_ordered_zero_and_finite_resets_and_comparability(doc):
    w = doc["workload"]
    w["nodes"] += [reset("r1", ["load"], 0), reset("r2", ["r1"], 2)]
    w["nodes"][2]["deps"].append("r2")
    x = run(doc)
    assert x["endpoint_epoch"] == 2
    assert time(x["reset_intervals"][0], "start_s") == time(x["reset_intervals"][0], "completion_s")
    w["nodes"][2]["deps"] = ["kernel"]
    with pytest.raises(InvalidInput, match="comparable"): run(doc)


def test_zero_time_compute_barrier_closure_and_node_permutation(doc):
    w = doc["workload"]
    w["nodes"][1]["cycles"] = 0
    w["nodes"].append({"node_id": "join", "kind": "BARRIER", "deps": ["kernel"]})
    w["nodes"][2]["deps"] = ["join"]
    x = run(doc)
    w["nodes"].reverse()
    y = run(doc)
    assert x["ledger"] == y["ledger"]
    assert x["children"] == y["children"]
    assert x["workload_id"] != y["workload_id"]  # Authored identity preserves serialization.


def test_evidence_recompute_rejects_corruption_and_partial_replay(doc):
    c = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    w = CoupledTensorWorkload.from_dict(doc["workload"])
    p = PhysicalPlacement.from_dict(doc["placement"])
    policy = RemoteDemandPolicy.from_dict(doc["transport"])
    for w in (w, replace(w, horizon_cycles=1)):
        x = execute_coupled_tensor(c,w,policy,p)
        x.revalidate(compilation=c, workload=w, policy=policy, placement=p)
        assert CoupledTensorEvidence.from_dict(x.to_dict(), compilation=c, workload=w, policy=policy, placement=p) == x
        bad = x.to_dict(); bad["summary"]["children_responded"] += 1
        with pytest.raises(EvidenceInvalid):
            CoupledTensorEvidence.from_dict(bad, compilation=c, workload=w, policy=policy, placement=p)


@pytest.mark.parametrize("field", ["response", "order", "image", "epoch"])
def test_resealed_value_and_ledger_tamper_refused(doc, field):
    from veritx_dse.core.artifact import content_id
    c = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    w = CoupledTensorWorkload.from_dict(doc["workload"])
    p = PhysicalPlacement.from_dict(doc["placement"])
    policy = RemoteDemandPolicy.from_dict(doc["transport"])
    bad = execute_coupled_tensor(c,w,policy,p).to_dict()
    if field == "response":
        row = next(c for c in bad["children"] if "response_hex" in c)
        row["response_hex"] = "ff"*(len(row["response_hex"])//2)
    elif field == "order": bad["ledger"].reverse()
    elif field == "image": bad["final_images"]["activation"] = "ff"*64
    elif field == "epoch": bad["endpoint_epoch"] += 1
    body = {k:v for k,v in bad.items() if k != "artifact_id"}
    bad["artifact_id"] = content_id("veritx/CoupledTensorEvidence/v1",body)
    with pytest.raises(EvidenceInvalid):
        CoupledTensorEvidence.from_dict(bad,compilation=c,workload=w,policy=policy,placement=p)


def test_write_then_read_mutation_through_response_path(doc):
    add_retry(doc)
    doc["workload"]["nodes"][-1].pop("retry_of")
    image = bytearray(range(64)); image[28:40] = bytes([170]*12)
    doc["workload"]["access_values"]["retry"] = (image[20:40]+image[44:64]).hex()
    x = run(doc)
    assert x["read_results"]["retry"]["hex"] == doc["workload"]["access_values"]["retry"]
    assert x["summary"]["deduplicated_payload_bytes"] == 0


def test_endpoint_child_splitting_and_parent_assembly(doc):
    from veritx_dse.model.transaction_intent import SplittingPolicy
    # Every generated request is split into byte children; no padding mutation.
    def edit(r):
        i = r.agent_intents[0]
        p = replace(i.transaction_policy, splitting=SplittingPolicy(65536, 1))
        return replace(r, agent_intents=(replace(i, transaction_policy=p), *r.agent_intents[1:]))
    rebind(doc, edit)
    x = run(doc)
    assert x["summary"]["children_issued"] == x["summary"]["children_responded"] == 52
    assert x["summary"]["payload_bytes"] == 52
    assert x["read_results"]["read"]["hex"] == doc["workload"]["access_values"]["read"]
    assert x["summary"]["write_bytes_committed"] == 12
    add_retry(doc, "write")
    y = run(doc)
    assert y["summary"]["children_responded"] == 64
    assert y["summary"]["write_bytes_committed"] == 12
    assert y["summary"]["deduplicated_payload_bytes"] == 12


def test_full_authorization_denial_before_any_commit(doc, monkeypatch):
    from veritx_dse.model.access_policy import AccessPolicyArtifact
    import veritx_dse.application.coupled_tensor as module
    c = rebind(doc, lambda r: replace(r, access_policy=AccessPolicyArtifact(())))
    assert c.compiled_system.access_system is not None
    committed = []
    monkeypatch.setattr(module._ReferenceRuntime, "commit", lambda *args: committed.append(args))
    with pytest.raises(AccessDenied) as error:
        run(doc)
    assert error.value.authorization["issued_children"] == 0 and committed == []


def test_target_service_contention_never_overlaps(doc):
    from veritx_dse.model.transaction_intent import OutstandingLimit
    def edit(r):
        i = r.agent_intents[0]
        p = replace(i.transaction_policy, outstanding=OutstandingLimit(total=8))
        return replace(r, agent_intents=(replace(i, transaction_policy=p), *r.agent_intents[1:]))
    rebind(doc, edit)
    doc["transport"]["service_cycles"] = 100
    x = run(doc)
    service = [r for r in x["phases"] if r["resource"][0] == "service"]
    for target in (1, 2):
        rows = sorted((r for r in service if r["resource"][1] == target), key=lambda r: time(r,"start_s"))
        assert len(rows) > 1
        assert all(time(a,"completed_s") <= time(b,"start_s") for a,b in zip(rows,rows[1:]))
    assert any(time(a,"start_s") < time(b,"completed_s") and time(b,"start_s") < time(a,"completed_s")
               for a in service for b in service if a["resource"] != b["resource"])


def test_exact_horizon_edge_compute_and_reset_closure(doc):
    # Zero-time boundary closure includes reset/compute completion, not only
    # events strictly before the horizon. Block later writes past this edge.
    w = doc["workload"]
    w["nodes"].append(compute("edge", cycles=2, engine="network_engine"))
    w["engines"].append({"engine_id":"network_engine","clock":"network","capacity":1})
    w["horizon_cycles"] = 2
    x = run(doc)
    assert x["status"] == "INCOMPLETE"
    assert any(r["event"] == "compute_complete" and r["id"] == "edge" and time(r) == time(x["summary"],"horizon_s") for r in x["ledger"])
    w["nodes"].append(reset("reset", [], 1))
    w["nodes"][0]["deps"] = ["reset"]
    w["nodes"][2]["deps"].append("reset")
    x = run(doc)
    assert x["endpoint_epoch"] == 1
    assert time(x["reset_intervals"][0],"completion_s") == time(x["summary"],"horizon_s")


def test_defensive_deadlock_witness_is_not_horizon_completion(doc, monkeypatch):
    import veritx_dse.application.coupled_tensor as module
    # Controlled internal gate failure, NOT a supported workload fault mode.
    monkeypatch.setattr(module._ReferenceRuntime,"ready",lambda *_: False)
    x = run(doc)
    assert x["status"] == "DEADLOCK"
    assert x["summary"]["children_issued"] == 0
    assert x["summary"]["children_source_held"] == 8
    assert x["pending_nodes"] == ["kernel","load","store"]


def test_unknown_clock_and_reorder_refusals(doc):
    from veritx_dse.model.transaction_intent import ReorderingPolicy
    w = doc["workload"]
    w["engines"][0]["clock"] = "missing"
    with pytest.raises(InvalidInput): run(doc)
    w["engines"][0]["clock"] = "memory"
    # Existing V5 reordering is structural; reference refuses execution.
    def edit(r):
        i=r.agent_intents[0]
        p=replace(i.transaction_policy,reordering=ReorderingPolicy(enabled=True,max_window=2))
        return replace(r,agent_intents=(replace(i,transaction_policy=p),*r.agent_intents[1:]))
    rebind(doc, edit)
    with pytest.raises(UnsupportedSemantics,match="reorder"): run(doc)


def test_cli_fresh_process_replay_and_negative(tmp_path):
    command = [sys.executable,"-m","veritx_dse.application.coupled_tensor", str(EXAMPLE)]
    a = subprocess.run(command,capture_output=True,check=True).stdout
    b = subprocess.run(command,capture_output=True,check=True).stdout
    assert a == b
    doc = json.loads(EXAMPLE.read_text()); doc["workload"]["power_action"] = "OFF"
    p = tmp_path/"bad.json"; p.write_text(json.dumps(doc))
    result = subprocess.run(command[:-1]+[str(p)],capture_output=True)
    assert result.returncode == 2 and json.loads(result.stdout)["status"] == "REFUSED"
