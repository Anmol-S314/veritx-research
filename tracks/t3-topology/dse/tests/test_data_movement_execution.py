"""Explicit V5 transaction/clock/placement execution, without signoff claims."""
from dataclasses import replace
from fractions import Fraction
import json

import pytest

from veritx_dse.application.data_movement import execute_data_movement, DataMovementEvidence
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import _typed_request
from veritx_dse.core.artifact import FrozenMap
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.compile_request_v5 import CompileRequestV5, AgentIntentV5
from veritx_dse.model.compile_model import AgentKind
from veritx_dse.model.domain_intent import (
    ClockSource, ClockSourceKind, ClockDomain, Crossing, CrossingMechanism,
    SignalKind, AsyncFIFOConfig, PointerEncoding,
)
from veritx_dse.model.physical_placement import PhysicalPlacement, RouterFootprint
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.model.transaction_intent import (
    TransactionPolicy, TransactionKind, OutstandingLimit, OrderingPolicy,
    OrderingMode, SplittingPolicy,
)
from veritx_dse.simulation.clocked_fifo import clocked_fifo_transfer
from veritx_dse.workload.data_movement import DataMovementWorkload, DataMovementOperation


def experiment(*, limit=2, strong=False, target_divider=4, split=128, spacing=1000):
    base = _typed_request(MeshIntent(side_length=2), endpoints=4, tp=2, payload_bytes=512)
    prototype = base.agents[0]
    base = replace(base, agents=tuple(replace(prototype, count=1, clock_domain="network",
        kind=AgentKind.HBM_CONTROLLER if i == 1 else AgentKind.COMPUTE_TILE) for i in range(4)),
        workload=replace(base.workload, collectives=tuple(
            replace(op, traffic_class="memory_transfer") for op in base.workload.collectives)))
    policy = TransactionPolicy(outstanding=OutstandingLimit(total=limit),
        ordering=OrderingPolicy(OrderingMode.STRONG if strong else OrderingMode.RELAXED,
                                strong, strong, strong, "memory-ops"),
        splitting=SplittingPolicy(512, split) if split else None)
    fifo = AsyncFIFOConfig(4, 64, 64, PointerEncoding.GRAY, 2)
    request = CompileRequestV5(base_v4=base,
        agent_intents=(AgentIntentV5(0, transaction_policy=policy, transaction_clock_domain="core"),
                       AgentIntentV5(1, transaction_clock_domain="memory"),
                       AgentIntentV5(2, transaction_clock_domain="network"),
                       AgentIntentV5(3, transaction_clock_domain="network")),
        clock_sources=(ClockSource("pll", ClockSourceKind.PLL, 1_000_000_000),),
        clock_domains=(ClockDomain("core", "pll", 1_000_000_000),
                       ClockDomain("network", "pll", 500_000_000, divider_num=2),
                       ClockDomain("memory", "pll", 1_000_000_000 // target_divider,
                                   divider_num=target_divider)),
        crossings=tuple(Crossing(f"{a}-{b}", a, b, SignalKind.BUS, CrossingMechanism.ASYNC_FIFO,
                                 async_fifo=fifo)
                        for a, b in (("core", "network"), ("network", "core"),
                                     ("network", "memory"), ("memory", "network"))))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    ids = {e.agent.group_index: e.endpoint_id for e in compilation.bundle.attachment.endpoints}
    workload = DataMovementWorkload(request.design_hash(), "network", (
        DataMovementOperation("write", ids[0], ids[1], TransactionKind.WRITE, 0x1000, 512, 16, 8, "memory_transfer"),
        DataMovementOperation("read", ids[0], ids[1], TransactionKind.READ, 0x2000, 512, 16, 8, "memory_transfer"),
    ))
    placement = PhysicalPlacement(compilation.compiled_system.resource_graph.artifact_id(),
        spacing + 200, spacing + 200,
        tuple(RouterFootprint(i, (i % 2)*spacing, (i // 2)*spacing, 100, 100) for i in range(4)))
    return compilation, workload, placement


def time(doc):
    r = doc["summary"]["completion_s"]
    return Fraction(r["numerator"], r["denominator"])


def test_explicit_read_write_executes_children_clocks_and_placement():
    c, w, p = experiment()
    c.compiled_system.revalidate()
    assert c.compiled_system.execution_contract is not None
    assert c.certificate.design_binding["extensions"]["execution_contract"] == c.compiled_system.execution_contract.artifact_id()
    result = execute_data_movement(c, w, p)
    doc = result.to_dict()
    assert doc["summary"]["parents_completed"] == 2
    assert doc["summary"]["children_completed"] == 8
    assert doc["summary"]["payload_bytes"] == 1024
    assert doc["summary"]["peak_outstanding"] == {"0": 2}
    assert doc["summary"]["fifo_words_written"] == doc["summary"]["fifo_words_read"] > 0
    assert any(e.get("blocked_write_cycles", 0) > 0 for e in doc["phases"])
    assert all(e.get("peak_occupancy", 0) <= 4 for e in doc["phases"])
    assert doc["scope"]["signoff_verified"] is False
    assert doc["scope"]["booksim_equivalent"] is False
    assert doc["wire_lengths"][0]["length_um"] == {"numerator": 1000, "denominator": 1}
    result.revalidate(c, w, p)
    assert DataMovementEvidence.from_dict(json.loads(json.dumps(doc)), compilation=c, workload=w, placement=p) == result


def test_credit_limit_and_clock_ratio_change_executed_schedule():
    runs = [execute_data_movement(*experiment(**kw)).to_dict()
            for kw in ({"limit": 1}, {"limit": 4}, {"limit": 4, "target_divider": 2})]
    assert time(runs[0]) > time(runs[1]) > time(runs[2])
    assert runs[0]["summary"]["peak_outstanding"]["0"] == 1
    assert runs[1]["summary"]["peak_outstanding"]["0"] == 4


def test_strong_ordering_waits_for_all_earlier_children_to_complete():
    result = execute_data_movement(*experiment(limit=8, strong=True)).to_dict()
    rows = result["children"]
    writes = [r for r in rows if r["child"]["parent_id"] == "write"]
    reads = [r for r in rows if r["child"]["parent_id"] == "read"]
    def value(row, key):
        return Fraction(row[key]["numerator"], row[key]["denominator"])
    assert min(value(r, "issued_s") for r in reads) >= max(value(r, "completed_s") for r in writes)


def test_explicit_parent_dependency_controls_relaxed_policy():
    c, w, p = experiment(limit=8)
    w = replace(w, operations=(w.operations[0], replace(w.operations[1], deps=("write",))))
    doc = execute_data_movement(c, w, p).to_dict()
    write_end = max(Fraction(r["completed_s"]["numerator"], r["completed_s"]["denominator"])
                    for r in doc["children"] if r["kind"] == "WRITE")
    assert all(Fraction(r["issued_s"]["numerator"], r["issued_s"]["denominator"]) >= write_end
               for r in doc["children"] if r["kind"] == "READ")


def test_placement_changes_geometry_not_network_or_clock_timing():
    c, w, p = experiment()
    expanded = replace(p, die_width_um=2200, die_height_um=2200,
        routers=tuple(replace(r, x_um=r.x_um*2, y_um=r.y_um*2) for r in p.routers))
    a, b = execute_data_movement(c, w, p).to_dict(), execute_data_movement(c, w, expanded).to_dict()
    assert time(a) == time(b)
    assert a["artifact_id"] != b["artifact_id"]
    assert a["system_hash"] == b["system_hash"]
    assert b["wire_lengths"][0]["length_um"]["numerator"] == 2000


@pytest.mark.parametrize("mutation", ["summary", "phase", "identity", "child"])
def test_resealed_evidence_tampering_refuses(mutation):
    c, w, p = experiment()
    result = execute_data_movement(c, w, p)
    doc = result.to_dict()
    if mutation == "summary":
        doc["summary"]["payload_bytes"] = 1
    elif mutation == "phase":
        doc["phases"][0]["completed_s"]["numerator"] += 1
    elif mutation == "identity":
        doc["placement_id"] = "0" * 64
    else:
        doc["children"][0]["child"]["address_start"] += 1
    doc.pop("artifact_id")
    resealed = DataMovementEvidence(FrozenMap(doc))
    with pytest.raises(EvidenceInvalid):
        resealed.revalidate(c, w, p)
    with pytest.raises(EvidenceInvalid):
        DataMovementEvidence.from_dict(resealed.to_dict(), compilation=c, workload=w, placement=p)


def test_missing_clock_crossing_and_foreign_workload_refuse():
    c, w, p = experiment()
    with pytest.raises(EvidenceInvalid):
        execute_data_movement(c, replace(w, design_hash="0"*64), p)
    req = replace(c.request, crossings=c.request.crossings[:-1])
    new = FabricCompiler().compile(req)
    with pytest.raises(UnsupportedSemantics, match="missing explicit crossing"):
        execute_data_movement(new, replace(w, design_hash=req.design_hash()), p)


def test_dropped_compiled_contract_is_not_admitted():
    c, _, _ = experiment()
    with pytest.raises(EvidenceInvalid):
        replace(c.compiled_system, execution_contract=None).revalidate()


@pytest.mark.parametrize("change", [{"router_id": 99}, {"x_um": 9999}, {"x_um": True}])
def test_illegal_placement_refuses(change):
    c, _, p = experiment()
    with pytest.raises(InvalidInput):
        altered = replace(p, routers=(replace(p.routers[0], **change),) + p.routers[1:])
        altered.validate_against(c.compiled_system.resource_graph)


def test_placement_overlap_and_missing_router_refuse():
    c, _, p = experiment()
    with pytest.raises(InvalidInput, match="overlap"):
        replace(p, routers=(p.routers[0], replace(p.routers[1], x_um=50), *p.routers[2:]))
    with pytest.raises(InvalidInput, match="exactly"):
        replace(p, routers=p.routers[:-1]).validate_against(c.compiled_system.resource_graph)
    assert PhysicalPlacement.from_dict(json.loads(json.dumps(p.to_dict()))) == p


@pytest.mark.parametrize("ratio", [(1, 1), (4, 1), (1, 4), (7, 3)])
def test_two_clock_fifo_conserves_and_backpressures(ratio):
    fifo = AsyncFIFOConfig(4, 64, 64, PointerEncoding.GRAY, 2)
    burst = clocked_fifo_transfer(config=fifo, write_hz=ratio[0], read_hz=ratio[1], words=32)
    assert burst.writes == burst.reads == 32
    assert 1 <= burst.peak_occupancy <= 4
    assert (burst.blocked_write_cycles > 0) == (ratio[0] > ratio[1])
    assert burst.reusable_s >= burst.completed_s > 0


def test_one_word_fifo_has_exact_future_edge_visibility():
    fifo = AsyncFIFOConfig(4, 64, 64, PointerEncoding.GRAY, 2)
    burst = clocked_fifo_transfer(config=fifo, write_hz=1, read_hz=1, words=1)
    # write at 0; pointer visible/read at 2; transfer ends after that read cycle.
    assert burst.completed_s == 3 and burst.reusable_s == 4


def test_execution_contract_exports_and_v5_json_replay():
    from veritx_dse.application.views import compilation_view, artifact_chain_view
    c, w, p = experiment()
    exported = json.loads(json.dumps(compilation_view(c)))
    contract = exported["design_extensions"]["execution_contract"]
    assert contract["endpoints"][0]["fabric_clock_domain"] == "network"
    assert contract["endpoints"][0]["transaction_clock_domain"] == "core"
    replayed = FabricCompiler().compile(CompileRequestV5.from_dict(exported["request"]))
    assert replayed.compiled_system.system_hash() == c.compiled_system.system_hash()
    nodes = {row["artifact"]: row for row in artifact_chain_view(c)["nodes"]}
    assert nodes["execution_contract"]["parents"] == ["v5_design", "attachment"]
    assert execute_data_movement(replayed, w, p) == execute_data_movement(c, w, p)


def test_custom_raw_hazard_is_completion_driven():
    c, w, p = experiment(limit=8)
    intent = c.request.agent_intents[0]
    policy = replace(intent.transaction_policy, ordering=OrderingPolicy(OrderingMode.CUSTOM, enforce_raw=True))
    req = replace(c.request, agent_intents=(replace(intent, transaction_policy=policy), *c.request.agent_intents[1:]))
    new = FabricCompiler().compile(req)
    w = replace(w, design_hash=req.design_hash(), operations=(w.operations[0], replace(w.operations[1], address=w.operations[0].address)))
    doc = execute_data_movement(new, w, p).to_dict()
    write_end = max(Fraction(r["completed_s"]["numerator"], r["completed_s"]["denominator"])
                    for r in doc["children"] if r["kind"] == "WRITE")
    assert all(Fraction(r["issued_s"]["numerator"], r["issued_s"]["denominator"]) >= write_end
               for r in doc["children"] if r["kind"] == "READ")


def test_unsplit_policy_executes_single_children():
    doc = execute_data_movement(*experiment(split=None)).to_dict()
    assert doc["summary"]["children_completed"] == 2
    assert doc["summary"]["payload_bytes"] == 1024


@pytest.mark.parametrize("field", ["transaction_clock_domain", "outstanding", "ordering", "fifo_width", "unresolved", "reorder"])
def test_missing_or_unsupported_execution_semantics_refuse(field):
    from veritx_dse.model.transaction_intent import ReorderingPolicy
    c, w, p = experiment()
    req = c.request
    intent = req.agent_intents[0]
    if field == "transaction_clock_domain":
        req = replace(req, agent_intents=(replace(intent, transaction_clock_domain=None), *req.agent_intents[1:]))
    elif field in ("outstanding", "ordering", "reorder"):
        changes = {field: None} if field != "reorder" else {"reordering": ReorderingPolicy(True, 2)}
        req = replace(req, agent_intents=(replace(intent, transaction_policy=replace(intent.transaction_policy, **changes)), *req.agent_intents[1:]))
    else:
        crossing = req.crossings[0]
        crossing = (replace(crossing, async_fifo=replace(crossing.async_fifo, write_width=32, read_width=32))
                    if field == "fifo_width" else replace(crossing, mechanism=CrossingMechanism.UNRESOLVED,
                                                           async_fifo=None, reason="no hardware selected"))
        req = replace(req, crossings=(crossing, *req.crossings[1:]))
    new = FabricCompiler().compile(req)
    assert new.status == "COMPILED", new.error
    with pytest.raises((InvalidInput, UnsupportedSemantics)):
        execute_data_movement(new, replace(w, design_hash=req.design_hash()), p)


def test_oversized_demand_refuses_before_materializing_children():
    c, w, p = experiment(split=None)
    w = replace(w, operations=(replace(w.operations[0], payload_bytes=1 << 50),))
    with pytest.raises(UnsupportedSemantics, match="envelope"):
        execute_data_movement(c, w, p)


def test_v5_clock_binding_requires_a_declared_domain_and_old_intent_bytes_stay_stable():
    c, _, _ = experiment()
    old = AgentIntentV5(0, transaction_policy=c.request.agent_intents[0].transaction_policy)
    assert "transaction_clock_domain" not in old.to_dict()
    assert AgentIntentV5.from_dict(old.to_dict()) == old
    from veritx_dse.model.compile_request_v5 import CompileRequestV5SchemaError
    with pytest.raises(CompileRequestV5SchemaError, match="undeclared"):
        replace(c.request, agent_intents=(replace(c.request.agent_intents[0], transaction_clock_domain="unknown"),))


def test_runnable_example_and_cli_emit_bound_evidence(tmp_path, capsys):
    from pathlib import Path
    import subprocess
    import sys
    from veritx_dse.application.data_movement import evaluate_experiment
    from veritx_dse.cli.cli import build_parser, DISPATCH
    from veritx_dse.core.logging import Ctx
    example = Path(__file__).resolve().parents[1] / "examples/addressed_memory_v5.json"
    expected = evaluate_experiment(json.loads(example.read_text())).to_dict()
    process = subprocess.run([sys.executable, "-m", "veritx_dse.application.data_movement", str(example)],
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == expected
    args = build_parser().parse_args(["--json", "evaluate", "data-movement", "--experiment", str(example)])
    ctx = Ctx(json_mode=True, verbosity=0)
    try:
        DISPATCH["evaluate"][args.eval_cmd](ctx, args)
        assert json.loads(capsys.readouterr().out) == expected
    finally:
        ctx.close()
    doc = json.loads(example.read_text())
    doc["workload"]["design_hash"] = "0"*64
    bad = tmp_path / "foreign.json"
    bad.write_text(json.dumps(doc))
    refused = subprocess.run([sys.executable, "-m", "veritx_dse.application.data_movement", str(bad)],
                             capture_output=True, text=True, timeout=30)
    assert refused.returncode == 1
    assert json.loads(refused.stdout)["status"] == "REFUSED"
    assert "Traceback" not in refused.stderr


def test_workload_closed_reader_and_dependency_validation():
    _, w, _ = experiment()
    assert DataMovementWorkload.from_dict(json.loads(json.dumps(w.to_dict()))) == w
    with pytest.raises(InvalidInput):
        DataMovementWorkload.from_dict({**w.to_dict(), "guess_memory": True})
    with pytest.raises(InvalidInput):
        replace(w, operations=(replace(w.operations[0], deps=("read",)), w.operations[1]))
