"""Explicit demand contract/generator/projection proofs, not native timing qualification."""
from dataclasses import replace
from types import SimpleNamespace
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.tensor_demand import (
    RemoteDemandPolicy, RemoteTensorDemand, project_remote_tensor_demand, run_document,
)
from veritx_dse.application.data_movement import execute_data_movement, AccessDenied
from veritx_dse.core.artifact import canonical_bytes
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.core.memory import byte_transaction_span, MemoryArtifactError
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.compile_model import AddressMap, AddressRange
from veritx_dse.model.access_policy import AddressSpace, AccessPolicyArtifact
from veritx_dse.model.physical_placement import PhysicalPlacement
from veritx_dse.model.tensor_demand import TensorDemandWorkload
from veritx_dse.model.transaction_intent import TransactionKind, SplittingPolicy, TransactionIntentError
from veritx_dse.workload.tensor_demand import lower_tensor_demand, LoweredTensorDemand, _access_fragments

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/tensor_demand_v5.json"


@pytest.fixture(scope="module")
def case():
    doc = json.loads(EXAMPLE.read_text())
    c = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    assert c.status == "COMPILED", c.error
    return c, TensorDemandWorkload.from_dict(doc["demand"]), RemoteDemandPolicy.from_dict(doc["transport"]), PhysicalPlacement.from_dict(doc["placement"])


def rebind(c, w, request):
    c = FabricCompiler().compile(request)
    assert c.status == "COMPILED", c.error
    return c, replace(w, design_hash=request.design_hash(), system_hash=c.compiled_system.system_hash())


def shard_change(w, index=0, **kw):
    t = w.tensors[0]
    shards = list(t.shards)
    shards[index] = replace(shards[index], **kw)
    return replace(w, tensors=(replace(t, shards=tuple(shards)),))


def test_byte_exact_cross_shard_strided_demand_and_remote_completion(case):
    c, w, policy, p = case
    d = lower_tensor_demand(c, w)
    assert (d.audit["storage_bytes"], d.audit["declared_payload_bytes"], d.audit["request_count"]) == (64, 52, 8)
    assert (d.audit["transaction_bytes"], d.audit["padding_bytes"]) == (128, 76)
    assert [r.payload_bytes for r in d.requests] == [9, 1, 10, 13, 7, 1, 1, 10]
    assert [r.tensor_offset_bytes for r in d.requests] == [20, 29, 30, 44, 57, 28, 29, 30]
    assert [r.target for r in d.requests] == [1, 1, 2, 2, 2, 1, 1, 2]
    assert all(r.payload_bytes + r.front_padding_bytes + r.back_padding_bytes == r.transaction_bytes for r in d.requests)
    remote = project_remote_tensor_demand(c, w, policy)
    reads = remote.completion_groups["read"]
    assert len(reads) == 5
    assert all(op.deps == reads for op in remote.workload.operations if op.kind is TransactionKind.WRITE)
    evidence = execute_data_movement(c, remote.workload, p).to_dict()
    rows = evidence["children"]
    when = lambda r, k: Fraction(r[k]["numerator"], r[k]["denominator"])
    assert min(when(r, "issued_s") for r in rows if r["kind"] == "WRITE") >= max(
        when(r, "completed_s") for r in rows if r["kind"] == "READ")
    assert evidence["summary"]["payload_bytes"] == 52
    assert evidence["summary"]["children_completed"] == 8
    assert evidence["summary"]["fifo_words_written"] == evidence["summary"]["fifo_words_read"]
    assert when(evidence["summary"], "completion_s") == Fraction(17, 40000000)
    assert d.to_dict()["scope"]["timing_modeled"] is False


def test_sparse_max_shard_fragment_walk_matches_brute_force_oracle():
    # Exercise maximum block/shard dimensions without materializing a demand artifact.
    shards = tuple(SimpleNamespace(offset_bytes=i * 16, size_bytes=16, shard_id=str(i))
                   for i in range(256))
    tensor = SimpleNamespace(shards=shards)
    access = SimpleNamespace(offset_bytes=0, count=4096, stride_bytes=1, block_bytes=1)
    expected = []
    for block_index in range(access.count):
        start = block_index * access.stride_bytes
        end = start + access.block_bytes
        for shard in shards:
            lo, hi = max(start, shard.offset_bytes), min(end, shard.offset_bytes + shard.size_bytes)
            if lo < hi:
                expected.append((block_index, shard.shard_id, lo, hi))
    actual = [(i, shard.shard_id, lo, hi) for i, shard, lo, hi in _access_fragments(tensor, access)]
    assert actual == expected
    assert len(actual) == 4096


def test_independent_byte_oracle_across_tx_and_shard_boundaries(case):
    c, original, _, _ = case
    # Independent oracle: enumerate logical bytes, not the lowering span math.
    for tx in (1, 2, 3, 4, 7, 8, 16, 32):
        t = replace(original.tensors[0], element_bytes=1, element_count=64,
                    shards=tuple(replace(s, transaction_bytes=tx) for s in original.tensors[0].shards))
        for offset, block, count, stride in ((0, 64, 1, 64), (29, 2, 1, 2),
                                             (20, 20, 2, 24), (0, 1, 32, 2), (63, 1, 1, 1)):
            a = replace(original.accesses[0], offset_bytes=offset, block_bytes=block,
                        count=count, stride_bytes=stride)
            w = replace(original, tensors=(t,), accesses=(a,))
            d = lower_tensor_demand(c, w)
            expected = []
            for i in range(count):
                for logical in range(offset + i*stride, offset + i*stride + block):
                    s = next(s for s in t.shards if s.offset_bytes <= logical < s.offset_bytes+s.size_bytes)
                    expected.append((i, logical, s.target, s.base_address + logical - s.offset_bytes))
            actual = [(r.block_index, r.tensor_offset_bytes+i, r.target, r.payload_address+i)
                      for r in d.requests for i in range(r.payload_bytes)]
            assert actual == expected
            assert d.audit["request_payload_bytes"] == count * block
            assert d.audit["transaction_bytes"] == d.audit["request_payload_bytes"] + d.audit["padding_bytes"]


def test_deterministic_identity_json_replay_and_shard_order(case):
    c, w, policy, _ = case
    d = lower_tensor_demand(c, w)
    assert LoweredTensorDemand.from_dict(json.loads(json.dumps(d.to_dict())), compilation=c, workload=w) == d
    d.revalidate(compilation=c, workload=w)
    assert TensorDemandWorkload.from_dict(w.to_dict()) == w
    assert lower_tensor_demand(c, w).to_dict() == d.to_dict()
    t = replace(w.tensors[0], shards=tuple(reversed(w.tensors[0].shards)))
    assert lower_tensor_demand(c, replace(w, tensors=(t,))).requests == d.requests
    remote = project_remote_tensor_demand(c, w, policy)
    assert RemoteTensorDemand.from_dict(remote.to_dict(), compilation=c, workload=w, policy=policy) == remote


def test_arbitrary_dag_serialization_not_schedule(case):
    c, w, policy, _ = case
    reordered = replace(w, accesses=tuple(reversed(w.accesses)))
    d = lower_tensor_demand(c, reordered)
    assert d.requests[0].access_id == "write"  # Authored serialization, not issue.
    remote = project_remote_tensor_demand(c, reordered, policy)
    assert remote.workload.operations == project_remote_tensor_demand(c, w, policy).workload.operations
    assert remote.demand_id != project_remote_tensor_demand(c, w, policy).demand_id


@pytest.mark.parametrize("mutation", ["payload", "target", "deps", "order", "audit", "id", "missing_id", "extra"])
def test_parent_recomputation_refuses_tampered_demand(case, mutation):
    c, w, _, _ = case
    doc = lower_tensor_demand(c, w).to_dict()
    if mutation in ("payload", "target", "deps"):
        key = {"payload": "payload_bytes", "target": "target", "deps": "deps"}[mutation]
        doc["requests"][0][key] = ["write"] if mutation == "deps" else 99
    elif mutation == "order":
        doc["requests"].reverse()
    elif mutation == "audit":
        doc["audit"]["request_payload_bytes"] += 1
    elif mutation == "id":
        doc["artifact_id"] = "0"*64
    elif mutation == "missing_id":
        doc.pop("artifact_id")
    else:
        doc["coherent"] = True
    with pytest.raises(EvidenceInvalid):
        LoweredTensorDemand.from_dict(doc, compilation=c, workload=w)


def test_projection_tamper_and_policy_binding(case):
    c, w, policy, _ = case
    remote = project_remote_tensor_demand(c, w, policy)
    doc = remote.to_dict()
    doc["workload"]["operations"][0]["address"] += 1
    with pytest.raises(EvidenceInvalid):
        RemoteTensorDemand.from_dict(doc, compilation=c, workload=w, policy=policy)
    slower = replace(policy, service_cycles=policy.service_cycles+1)
    assert project_remote_tensor_demand(c, w, slower).artifact_id() != remote.artifact_id()
    with pytest.raises(EvidenceInvalid):
        RemoteTensorDemand.from_dict(remote.to_dict(), compilation=c, workload=w, policy=slower)


@pytest.mark.parametrize("field", ["design_hash", "system_hash"])
def test_foreign_parent_hash_refuses(case, field):
    c, w, _, _ = case
    with pytest.raises(EvidenceInvalid):
        lower_tensor_demand(c, replace(w, **{field: "0"*64}))


@pytest.mark.parametrize("index,kw", [(0, {"target": 99}), (1, {"target": 1}),
    (0, {"base_address": 4098}), (0, {"base_address": 4100})])
def test_missing_wrong_owner_and_region_end_decode_refuses_even_unused(case, index, kw):
    c, w, _, _ = case
    with pytest.raises(InvalidInput):
        lower_tensor_demand(c, replace(shard_change(w, index, **kw), accesses=()))


def test_adjacent_decode_coverage_and_internal_gap(case):
    c, w, _, _ = case
    original = c.request.base_v4.address_map.ranges
    for gap in (0, 1):
        ranges = (AddressRange("a", 4099, 15, 1), AddressRange("b", 4114+gap, 15-gap, 1), original[1])
        req = replace(c.request, base_v4=replace(c.request.base_v4, address_map=AddressMap(ranges)))
        cc, ww = rebind(c, w, req)
        if gap:
            with pytest.raises(InvalidInput, match="gap"):
                lower_tensor_demand(cc, ww)
        else:
            assert lower_tensor_demand(cc, ww).audit["request_payload_bytes"] == 52


def test_target_address_width_and_64_bit_overflow(case):
    c, w, _, _ = case
    agents = tuple(replace(a, addr_width=16) if i == 1 else a for i, a in enumerate(c.request.base_v4.agents))
    cc, ww = rebind(c, w, replace(c.request, base_v4=replace(c.request.base_v4, agents=agents)))
    with pytest.raises(InvalidInput, match="width"):
        lower_tensor_demand(cc, shard_change(ww, base_address=65535))
    with pytest.raises(InvalidInput, match="overflow"):
        shard_change(w, base_address=2**64-1)


def test_local_address_space_refuses_but_local_endpoint_request_is_representable(case):
    c, w, policy, _ = case
    with pytest.raises(UnsupportedSemantics, match="LOCAL"):
        lower_tensor_demand(c, shard_change(w, address_space=AddressSpace.LOCAL))
    local = replace(w, accesses=(replace(w.accesses[0], issuer=1, offset_bytes=0, block_bytes=20,
                                       count=1, stride_bytes=20),))
    assert all(r.issuer == r.target for r in lower_tensor_demand(c, local).requests)
    with pytest.raises(UnsupportedSemantics, match="local"):
        project_remote_tensor_demand(c, local, policy)


def test_unknown_issuer_refuses(case):
    c, w, _, _ = case
    with pytest.raises(InvalidInput, match="issuer"):
        lower_tensor_demand(c, replace(w, accesses=(replace(w.accesses[0], issuer=99),)))


@pytest.mark.parametrize("field,value", [("issuer", True), ("offset_bytes", False), ("block_bytes", 0),
    ("count", 0), ("count", 4097), ("stride_bytes", -1), ("stride_bytes", 19),
    ("offset_bytes", 21), ("block_bytes", 19), ("stride_bytes", 25), ("offset_bytes", 22),
    ("tensor_id", "missing"), ("deps", ("missing",)), ("deps", ("read",)),
    ("deps", ("write", "write")), ("count", 2.0)])
def test_strict_access_bounds_alignment_dependencies_and_integers(case, field, value):
    _, w, _, _ = case
    with pytest.raises(InvalidInput):
        replace(w, accesses=(replace(w.accesses[0], **{field: value}),))


@pytest.mark.parametrize("value", ["CACHE", "AUTHORED_HIT", "", None, True])
def test_unsupported_cache_policy_refuses(case, value):
    _, w, _, _ = case
    with pytest.raises(UnsupportedSemantics):
        replace(w.accesses[0], cache_policy=value)


def test_cycle_and_duplicate_access_tensor_ids_refuse(case):
    _, w, _, _ = case
    for accesses in ((replace(w.accesses[0], deps=("write",)), w.accesses[1]), (w.accesses[0], w.accesses[0])):
        with pytest.raises(InvalidInput):
            replace(w, accesses=accesses)
    with pytest.raises(InvalidInput):
        replace(w, tensors=(w.tensors[0], w.tensors[0]))


@pytest.mark.parametrize("index,kw", [(0, {"size_bytes": 28}), (0, {"size_bytes": 32}),
    (1, {"offset_bytes": 32}), (1, {"base_address": 4100, "target": 1}),
    (0, {"transaction_bytes": True}), (0, {"transaction_bytes": 0}),
    (0, {"transaction_bytes": 65537}), (0, {"size_bytes": 0}),
    (0, {"size_bytes": 29}), (1, {"shard_id": "left"})])
def test_gap_overlap_alias_alignment_and_invalid_shards_refuse(case, index, kw):
    _, w, _, _ = case
    with pytest.raises(InvalidInput):
        shard_change(w, index, **kw)


def test_tensor_size_law(case):
    _, w, _, _ = case
    for kw in ({"size_bytes": 66}, {"element_count": True}, {"element_bytes": 0}):
        with pytest.raises(InvalidInput):
            replace(w.tensors[0], **kw)


@pytest.mark.parametrize("path", [(), ("tensors", 0), ("tensors", 0, "shards", 0), ("accesses", 0)])
def test_closed_readers_refuse_unknown_or_missing_fields(case, path):
    _, w, _, _ = case
    for unknown in (True, False):
        doc = w.to_dict()
        row = doc
        for key in path:
            row = row[key]
        if unknown:
            row["inferred_hits"] = 0
        else:
            row.pop(next(iter(row)) if path else "accesses")
        with pytest.raises(InvalidInput):
            TensorDemandWorkload.from_dict(doc)
    doc = w.to_dict(); doc["schema_version"] = True
    with pytest.raises(InvalidInput):
        TensorDemandWorkload.from_dict(doc)


def test_zero_demand_and_repeat_read_storage_not_demand_counterexample(case):
    c, w, policy, _ = case
    empty = replace(w, tensors=(), accesses=())
    d = lower_tensor_demand(c, empty)
    assert d.requests == () and d.audit["request_payload_bytes"] == 0
    assert lower_tensor_demand(c, replace(w, accesses=())).audit["storage_bytes"] == 64
    with pytest.raises(UnsupportedSemantics, match="empty"):
        project_remote_tensor_demand(c, empty, policy)
    full = replace(w.accesses[0], offset_bytes=0, block_bytes=64, count=1, stride_bytes=64)
    once = replace(w, accesses=(full,))
    twice = replace(w, accesses=(full, replace(full, access_id="reread", deps=("read",))))
    one, two = lower_tensor_demand(c, once), lower_tensor_demand(c, twice)
    assert one.audit["storage_bytes"] == two.audit["storage_bytes"] == 64
    assert one.audit["request_payload_bytes"] == 64 and two.audit["request_payload_bytes"] == 128
    assert len(two.requests) == 2*len(one.requests)
    assert once.design_hash == twice.design_hash  # Same catalog name/collective payload, different demand.
    assert one.artifact_id() != two.artifact_id()


def test_generated_request_limit_refuses_before_unbounded_expansion(case, monkeypatch):
    c, w, _, _ = case
    # 256 accesses * 512 bytes, tx=1 => >65536 requests despite bounded payload.
    # Reuse persistent storage, never allocate guessed operands.
    req = replace(c.request, base_v4=replace(c.request.base_v4, address_map=AddressMap((
        AddressRange("left", 4099, 256, 1), AddressRange("right", 8197, 256, 2)))))
    c, w = rebind(c, w, req)
    t = replace(w.tensors[0], size_bytes=512, element_count=256, shards=(
        replace(w.tensors[0].shards[0], size_bytes=256, transaction_bytes=1),
        replace(w.tensors[0].shards[1], offset_bytes=256, size_bytes=256, transaction_bytes=1)))
    a = replace(w.accesses[0], offset_bytes=0, block_bytes=512, count=1, stride_bytes=512)
    accesses = tuple(replace(a, access_id=f"read{i}") for i in range(256))
    import veritx_dse.workload.tensor_demand as lowerer
    monkeypatch.setattr(lowerer, "DemandRequest", lambda *_: pytest.fail("allocated before expansion preflight"))
    with pytest.raises(UnsupportedSemantics, match="request bound"):
        lower_tensor_demand(c, replace(w, tensors=(t,), accesses=accesses))


def test_full_range_authorization_still_precedes_remote_issue(case):
    c, w, policy, p = case
    denied = replace(c.request, access_policy=AccessPolicyArtifact(()))
    cc, ww = rebind(c, w, denied)
    remote = project_remote_tensor_demand(cc, ww, policy)
    # Resource graph is unchanged, but placement remains checked by runner.
    with pytest.raises(AccessDenied) as caught:
        execute_data_movement(cc, remote.workload, p)
    assert caught.value.authorization["issued_children"] == 0


def test_existing_ragged_transaction_split_refusal_is_preserved(case):
    c, w, policy, p = case
    first = c.request.agent_intents[0]
    req = replace(c.request, agent_intents=(replace(first, transaction_policy=replace(
        first.transaction_policy, splitting=SplittingPolicy(512, 128))), *c.request.agent_intents[1:]))
    cc, ww = rebind(c, w, req)
    with pytest.raises(TransactionIntentError, match="multiple"):
        execute_data_movement(cc, project_remote_tensor_demand(cc, ww, policy).workload, p)


@pytest.mark.parametrize("start,size,tx", [(True,1,16), (0,0,16), (0,1,False), (2**64-1,2,16)])
def test_shared_byte_span_strict_validation(start, size, tx):
    with pytest.raises(MemoryArtifactError):
        byte_transaction_span(start, size, tx)


def test_example_cli_fresh_process_replay_and_negative_parent(tmp_path):
    command = [sys.executable, "-m", "veritx_dse.application.tensor_demand", str(EXAMPLE)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout
    doc = json.loads(first.stdout)
    assert doc["demand"]["audit"]["request_payload_bytes"] == 52
    bad = json.loads(EXAMPLE.read_text()); bad["demand"]["system_hash"] = "0"*64
    with pytest.raises(EvidenceInvalid):
        run_document(bad)
    bad_path = tmp_path / 'bad-parent.json'
    bad_path.write_text(json.dumps(bad))
    refused = subprocess.run([*command[:-1], str(bad_path)], capture_output=True, text=True)
    assert refused.returncode == 2
    assert json.loads(refused.stdout)['status'] == 'REFUSED'


def test_non_power_of_two_granularity_deterministic_replay(case):
    c, w, _, _ = case
    w = replace(w, tensors=(replace(w.tensors[0], shards=tuple(
        replace(s, transaction_bytes=7) for s in w.tensors[0].shards)),))
    d = lower_tensor_demand(c, w)
    assert all(r.transaction_address % 7 == 0 for r in d.requests)
    assert d.audit['request_payload_bytes'] == 52
    assert d.audit['transaction_bytes'] == 7 * len(d.requests)
    assert d.audit['transaction_bytes'] == 52 + d.audit['padding_bytes']
    assert LoweredTensorDemand.from_dict(d.to_dict(), compilation=c, workload=w) == d


def test_resealed_wrong_address_with_same_byte_totals_is_not_evidence(case):
    c, w, _, _ = case
    d = lower_tensor_demand(c, w)
    forged = replace(d, requests=(replace(d.requests[0], payload_address=d.requests[0].payload_address+1), *d.requests[1:]))
    assert forged.artifact_id() != d.artifact_id()
    assert forged.audit == d.audit
    with pytest.raises(EvidenceInvalid):
        LoweredTensorDemand.from_dict(forged.to_dict(), compilation=c, workload=w)


@pytest.mark.parametrize('field,value', [('network_clock','missing'), ('traffic_class','missing'),
    ('response_traffic_class','missing'), ('control_bytes',True), ('service_cycles',False)])
def test_transport_inputs_not_inferred_and_checked_by_real_consumer(case, field, value):
    c, w, policy, p = case
    with pytest.raises(InvalidInput):
        bad = replace(policy, **{field: value})
        execute_data_movement(c, project_remote_tensor_demand(c, w, bad).workload, p)


@pytest.mark.parametrize('oversize', ['tensors', 'shards', 'accesses', 'blocks', 'payload'])
def test_input_expansion_limits_refuse_adversarial_intent(case, oversize):
    _, w, _, _ = case
    doc = w.to_dict()
    if oversize == 'tensors':
        doc['tensors'] *= 65
    elif oversize == 'shards':
        doc['tensors'][0]['shards'] *= 129
    elif oversize == 'accesses':
        doc['accesses'] *= 129
    elif oversize == 'blocks':
        doc['accesses'] = [{**doc['accesses'][0], 'access_id': f'a{i}', 'count': 2049,
                           'offset_bytes': 0, 'block_bytes': 2, 'stride_bytes': 2} for i in range(2)]
        # Extend explicitly declared storage, not inferred memory.
        doc['tensors'][0].update(element_count=4096, size_bytes=8192,
            shards=[{**doc['tensors'][0]['shards'][0], 'size_bytes':8192}])
    else:
        size = 16 * 1024 * 1024 + 2
        doc['tensors'][0].update(element_count=size//2, size_bytes=size,
            shards=[{**doc['tensors'][0]['shards'][0], 'size_bytes':size}])
        doc['accesses'] = [{**doc['accesses'][0], 'offset_bytes':0, 'block_bytes':size,
                           'count':1, 'stride_bytes':size}]
    with pytest.raises(InvalidInput):
        TensorDemandWorkload.from_dict(doc)


def test_physical_alias_between_distinct_tensor_identities_refuses(case):
    _, w, _, _ = case
    with pytest.raises(InvalidInput, match='alias'):
        replace(w, tensors=(w.tensors[0], replace(w.tensors[0], tensor_id='replica')))


def test_invalid_compilation_and_v4_parent_refuse(case):
    c, w, _, _ = case
    with pytest.raises(InvalidInput):
        lower_tensor_demand(replace(c, status='UNSUPPORTED', bundle=None, certificate=None), w)
    v4 = FabricCompiler().compile(c.request.base_v4)
    assert v4.status == 'COMPILED', v4.error
    with pytest.raises(UnsupportedSemantics, match='V5'):
        lower_tensor_demand(v4, w)


def test_exact_target_width_region_end_is_valid(case):
    c, w, _, _ = case
    agents = tuple(replace(a, addr_width=16) if i == 1 else a for i, a in enumerate(c.request.base_v4.agents))
    right = c.request.base_v4.address_map.ranges[1]
    req = replace(c.request, base_v4=replace(c.request.base_v4, agents=agents,
        address_map=AddressMap((AddressRange('last-bytes', 65506, 30, 1), right))))
    c, w = rebind(c, w, req)
    w = shard_change(w, base_address=65506)
    w = replace(w, accesses=(replace(w.accesses[0], offset_bytes=0, block_bytes=30, count=1, stride_bytes=30),))
    d = lower_tensor_demand(c, w)
    assert d.requests[-1].payload_address + d.requests[-1].payload_bytes == 65536
    assert d.audit['request_payload_bytes'] == 30
    with pytest.raises(InvalidInput, match='width'):
        lower_tensor_demand(c, shard_change(w, base_address=65507))
