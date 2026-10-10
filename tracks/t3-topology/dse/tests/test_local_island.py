"""ABSTRACT_LOCAL_ISLAND_V1 boundaries and diagnostic end-to-end consumer."""
from dataclasses import replace
from fractions import Fraction as F
import json
from pathlib import Path

import pytest

from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.local_island import (
    IslandBucket, IslandAttachQueue, LocalIslandContract, IslandOffer,
)
from veritx_dse.simulation.local_island import simulate_local_island
from veritx_dse.application.local_island import (
    execute_local_island, LocalIslandEvidence, evaluate_experiment, main,
)


@pytest.fixture(scope="module")
def compilation():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import build_typed_preset_request
    result = FabricCompiler().compile(build_typed_preset_request("srota32_islands"))
    assert result.status == "COMPILED", result.error
    return result


def contract(compilation, *, rate=F(1, 2), initial=F(1), capacity=2, slots=(1,), latency=1):
    bundle = compilation.bundle
    classes = sorted(dict(bundle.vc_assignment.traffic_class_to_vcs))
    return LocalIslandContract(bundle.topology.topology_hash(), bundle.attachment.attachment_hash(), 1,
                               (IslandBucket(classes[0], rate, F(2), initial),),
                               (IslandAttachQueue(2, capacity, slots, latency),))


def offers(c, count=4, endpoint=2, cls=None):
    return tuple(IslandOffer(str(i), 0, endpoint, cls or c.buckets[0].traffic_class) for i in range(count))


def test_consumer_complete_replay_and_binding(compilation):
    c = contract(compilation)
    trace = offers(c)
    evidence = execute_local_island(compilation, c, trace, 9)
    execution = evidence.data["execution"]
    assert execution["status"] == "COMPLETE"
    assert execution["delivered_flits"] == 4
    assert [row["cycle"] for row in execution["admissions"]] == [0, 2, 4, 6]
    assert [row["cycle"] for row in execution["deliveries"]] == [1, 3, 5, 7]
    assert execute_local_island(compilation, c, tuple(reversed(trace)), 9) == evidence
    assert LocalIslandContract.from_dict(c.to_dict()) == c
    assert LocalIslandEvidence.from_dict(evidence.to_dict(), compilation=compilation, contract=c,
                                        offers=trace, horizon_cycles=9) == evidence
    assert evidence.data["scope"]["physical_timing"] is False
    tampered = evidence.to_dict()
    tampered["execution"]["deliveries"][0]["cycle"] = 0
    with pytest.raises(EvidenceInvalid, match="recomputed"):
        LocalIslandEvidence.from_dict(tampered, compilation=compilation, contract=c,
                                      offers=trace, horizon_cycles=9)
    changed = replace(c, buckets=(replace(c.buckets[0], rate=F(1)),))
    assert changed.artifact_id() != c.artifact_id()
    with pytest.raises(EvidenceInvalid):
        LocalIslandEvidence.from_dict(evidence.to_dict(), compilation=compilation, contract=changed,
                                      offers=trace, horizon_cycles=9)


@pytest.mark.parametrize("latency,admit,credit", [(0, [0, 1], 0), (2, [0, 3], 1)])
def test_credit_latency_and_no_same_edge_service(compilation, latency, admit, credit):
    c = contract(compilation, rate=F(1), initial=F(2), capacity=1, latency=latency)
    result = simulate_local_island(c, offers(c, 2), 5)
    assert [r["cycle"] for r in result["admissions"]] == admit
    assert [r["cycle"] for r in result["deliveries"]] == [a + 1 for a in admit]
    assert result["credits_in_flight"] == credit
    assert result["status"] == ("INCOMPLETE" if credit else "COMPLETE")
    for row in result["snapshots"]:
        q = row["queues"][0]
        assert q["credits"] + q["occupancy"] + q["credits_in_flight"] == 1


def test_full_capacity_does_not_spend_tokens(compilation):
    c = contract(compilation, rate=F(0), initial=F(2), capacity=1, slots=(0,))
    result = simulate_local_island(c, offers(c), 4)
    assert result["status"] == "INCOMPLETE"
    assert result["admitted_flits"] == 1 and result["delivered_flits"] == 0
    assert result["snapshots"][-1]["tokens"][c.buckets[0].traffic_class]["numerator"] == 1
    assert result["snapshots"][-1]["blocked_heads"][0]["reasons"] == ("NO_CREDIT",)
    assert len(result["pending"]) == 4


def test_zero_rate_is_not_unregulated_and_future_offers_remain_pending(compilation):
    c = contract(compilation, rate=F(0), initial=F(0))
    trace = offers(c, 1) + (IslandOffer("future", 8, 2, c.buckets[0].traffic_class),)
    result = simulate_local_island(c, trace, 3)
    assert result["status"] == "INCOMPLETE" and result["admitted_flits"] == 0
    assert {o["state"] for o in result["pending"]} == {"NOT_YET_ARRIVED", "UPSTREAM_BACKPRESSURED"}


def test_bucket_isolation_shared_router_scope_and_fifo_starvation(compilation):
    c = contract(compilation)
    # Simulator contract allows explicit class names; consumer checks canonical declarations separately.
    c = replace(c, buckets=(IslandBucket("a", F(0), F(1), F(0)),
                            IslandBucket("b", F(0), F(1), F(1))),
                queues=(IslandAttachQueue(2, 2, (1,), 0), IslandAttachQueue(3, 2, (1,), 0)))
    trace = (IslandOffer("a", 0, 2, "a"), IslandOffer("b", 0, 2, "b"),
             IslandOffer("c", 0, 3, "b"), IslandOffer("d", 0, 3, "b"))
    result = simulate_local_island(c, trace, 4)
    assert [r["offer_id"] for r in result["admissions"]] == ["c"]
    assert result["token_debits"] == {"a": 0, "b": 1}
    assert result["status"] == "INCOMPLETE"


def test_router_bucket_is_shared_across_local_endpoints(compilation):
    c = contract(compilation, rate=F(0), initial=F(1), latency=0)
    c = replace(c, queues=c.queues + (IslandAttachQueue(3, 2, (1,), 0),))
    trace = offers(c, 1) + (IslandOffer("other", 0, 3, c.buckets[0].traffic_class),)
    result = execute_local_island(compilation, c, trace, 4).data["execution"]
    assert result["admitted_flits"] == 1
    assert result["admissions"][0]["offer_id"] == "0"
    assert result["pending"][0]["offer_id"] == "other"
    assert result["status"] == "INCOMPLETE"


@pytest.mark.parametrize("rate", [F(0), F(1, 3), F(3, 2)])
@pytest.mark.parametrize("capacity", [1, 3])
@pytest.mark.parametrize("latency", [0, 2])
def test_finite_trace_invariants(compilation, rate, capacity, latency):
    c = contract(compilation, rate=rate, initial=F(2), capacity=capacity,
                 slots=(0, 2), latency=latency)
    trace = tuple(replace(o, arrival_cycle=i // 2) for i, o in enumerate(offers(c, 7)))
    result = simulate_local_island(c, trace, 25)
    assert simulate_local_island(c, tuple(reversed(trace)), 25) == result
    assert result["offered_flits"] == result["delivered_flits"] + len(result["pending"])
    assert len({r["offer_id"] for r in result["admissions"]}) == result["admitted_flits"]
    assert len({r["offer_id"] for r in result["deliveries"]}) == result["delivered_flits"]
    for row in result["snapshots"]:
        queue = row["queues"][0]
        assert queue["occupancy"] + queue["credits"] + queue["credits_in_flight"] == capacity
        assert 0 <= queue["occupancy"] <= capacity
        assert sum(r["cycle"] <= row["cycle"] for r in result["admissions"]) <= F(2) + rate * row["cycle"]


def test_periodic_service_and_burst_cap(compilation):
    c = contract(compilation, rate=F(3, 2), initial=F(2), capacity=2, slots=(0, 0, 2), latency=0)
    result = simulate_local_island(c, offers(c, 4), 6)
    assert [r["cycle"] for r in result["deliveries"]] == [2, 2, 5, 5]
    assert result["status"] == "COMPLETE"
    for row in result["snapshots"]:
        t = row["tokens"][c.buckets[0].traffic_class]
        assert 0 <= F(t["numerator"], t["denominator"]) <= 2


@pytest.mark.parametrize("changes,error", [
    ({"topology_hash": "wrong"}, EvidenceInvalid),
    ({"attachment_hash": "wrong"}, EvidenceInvalid),
    ({"router_id": 0}, InvalidInput),
    ({"router_id": 999}, InvalidInput),
    ({"queues": (IslandAttachQueue(4, 1, (1,), 0),)}, InvalidInput),
    ({"queues": (IslandAttachQueue(999, 1, (1,), 0),)}, InvalidInput),
    ({"buckets": (IslandBucket("unknown", F(1), F(1), F(1)),)}, InvalidInput),
])
def test_consumer_refuses_bad_binding(compilation, changes, error):
    c = replace(contract(compilation), **changes)
    with pytest.raises(error):
        execute_local_island(compilation, c, (), 3)


def test_placement_only_and_failed_compilation_refuse(compilation):
    with pytest.raises(InvalidInput, match="explicit"):
        execute_local_island(compilation, None, (), 3)
    with pytest.raises(UnsupportedSemantics, match="placement"):
        simulate_local_island(None, (), 3)
    with pytest.raises(InvalidInput, match="successful"):
        execute_local_island(None, contract(compilation), (), 3)


@pytest.mark.parametrize("doc_mutation", [
    lambda d: d.update(rate=1),
    lambda d: d.pop("semantics"),
    lambda d: d["semantics"].update(debit="NATIVE"),
    lambda d: d["buckets"][0].update(rate={"numerator": 1, "denominator": 0}),
    lambda d: d["buckets"][0].update(rate={"numerator": 2, "denominator": 4}),
    lambda d: d["buckets"][0].update(rate=0.5),
    lambda d: d["queues"][0].update(capacity_flits=True),
    lambda d: d["queues"][0].update(service_slots=[]),
    lambda d: d["queues"][0].update(credit_latency_cycles=-1),
])
def test_strict_contract_loader(compilation, doc_mutation):
    doc = contract(compilation).to_dict()
    doc_mutation(doc)
    with pytest.raises((InvalidInput, UnsupportedSemantics)):
        LocalIslandContract.from_dict(doc)


@pytest.mark.parametrize("bucket", [lambda: IslandBucket("x", 0.5, F(1), F(0)),
                                     lambda: IslandBucket("x", F(-1), F(1), F(0)),
                                     lambda: IslandBucket("x", F(0), F(1, 2), F(0)),
                                     lambda: IslandBucket("x", F(0), F(1), F(2))])
def test_invalid_bucket(bucket):
    with pytest.raises(InvalidInput):
        bucket()


def test_offer_bounds_duplicates_and_horizon(compilation):
    c = contract(compilation)
    o = offers(c, 1)[0]
    for trace in ((o, o), (replace(o, endpoint_id=99),), (replace(o, traffic_class="foreign"),)):
        with pytest.raises(InvalidInput):
            simulate_local_island(c, trace, 3)
    for horizon in (0, True, -1, 1.5):
        with pytest.raises(InvalidInput):
            simulate_local_island(c, (o,), horizon)
    with pytest.raises(UnsupportedSemantics, match="million"):
        simulate_local_island(c, (o,), 1_000_000)
    with pytest.raises(InvalidInput):
        IslandOffer("bad", -1, 2, "x")
    with pytest.raises(InvalidInput):
        replace(c, queues=c.queues + c.queues)
    with pytest.raises(InvalidInput):
        replace(c, buckets=c.buckets + c.buckets)


def test_non_srota_and_absent_island_refuse(compilation):
    from veritx_dse.model.topology_artifact import MaterializedFamily, materialize_family, materialize_srota
    bundle = compilation.bundle
    for topology, error in ((materialize_family(MaterializedFamily.CONCENTRATED_MESH,
                                               endpoint_count=32, concentration=2), UnsupportedSemantics),
                            (materialize_srota(k=4, concentration=2, mecs_row=True,
                                               mecs_col=True), InvalidInput)):
        attachment = replace(bundle.attachment, topology_hash=topology.topology_hash())
        c = replace(contract(compilation), topology_hash=topology.topology_hash(),
                    attachment_hash=attachment.attachment_hash())
        with pytest.raises(error):
            c.validate_against(topology, attachment, {c.buckets[0].traffic_class})


def test_examples_and_cli(capsys, tmp_path):
    examples = Path(__file__).resolve().parent.parent / "examples"
    positive = examples / "local_island_positive.json"
    negative = examples / "local_island_negative.json"
    result = evaluate_experiment(json.loads(positive.read_text()))
    assert result.data["execution"]["status"] == "COMPLETE"
    main([str(positive)])
    assert json.loads(capsys.readouterr().out)["execution"]["status"] == "COMPLETE"
    with pytest.raises(SystemExit) as exc:
        main([str(negative)])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "REFUSED"
    incomplete = json.loads(positive.read_text())
    incomplete["horizon_cycles"] = 1
    assert evaluate_experiment(incomplete).data["execution"]["status"] == "INCOMPLETE"
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(incomplete))
    with pytest.raises(SystemExit) as exc:
        main([str(path)])
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["execution"]["status"] == "INCOMPLETE"
