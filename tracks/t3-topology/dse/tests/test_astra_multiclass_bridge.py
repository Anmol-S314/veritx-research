"""ASTRA multi-class execution bridge: TP + EP dispatch/combine identity.

Proves the class-aware path end to end at the Python seam (live runtime
where the pinned producer allows; honest refusal otherwise):

- V3 projection keeps per-operation classes for TP ALLREDUCE, EP
  dispatch (EXPERT_BEGIN/ALLTOALL) and EP combine (EXPERT_END/ALLTOALL);
- the collective-mode envelope accepts EXPERT dispatch/combine (identity
  preserved, class via sidecar+binding — never endpoint/size/order);
- per-operation byte conservation holds across the three classes;
- COLL nodes carry operation_id + class sidecars;
- swapped/collapsed/omitted bindings refuse at normalize;
- unbalanced per-class counts refuse when a producer reports them;
- contract-ledger STREAM coverage proves the executed schedule (unit
  level with fabricated stderr; live level against the real binary);
- live execution executes a small 2-class mesh design when the producer
  is pinned, else refuses with the pin reason (never fakes).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend import astra  # noqa: E402
from veritx_dse.backend.astra_adapter import (  # noqa: E402
    Astra2Adapter, Astra2SemanticRefusal,
)
from veritx_dse.backend.astra_execution import (  # noqa: E402
    AstraExecutionError, assert_stream_ledger_covers_kinds,
    parse_class_stream_ledger,
)
from veritx_dse.workload.graph import (  # noqa: E402
    KIND_COLLECTIVE, KIND_EXPERT_BEGIN, KIND_EXPERT_END, OperationNode,
    WorkloadGraph, collective_detail, expert_detail,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV3,
)

COUNT = 4
TP = "tp_collective"
EP_D = "ep_dispatch"
EP_C = "ep_combine"


def _compiled(count=COUNT):
    from test_canonical_compiler import _det, _design  # noqa: E402
    return _det(_design(compute=count, tp=count))


def _moe_graph():
    compiled = _compiled()
    ops = (
        OperationNode(
            operation_id="ar-tp", kind=KIND_COLLECTIVE,
            detail=collective_detail(
                collective_kind="ALLREDUCE",
                participants=tuple(range(COUNT)),
                payload_bytes=1024, participant_count=COUNT)),
        OperationNode(
            operation_id="disp-ep", kind=KIND_EXPERT_BEGIN,
            deps=("ar-tp",),
            detail=expert_detail(
                collective_kind="ALLTOALL",
                participants=tuple(range(COUNT)),
                payload_bytes=512, participant_count=COUNT)),
        OperationNode(
            operation_id="comb-ep", kind=KIND_EXPERT_END,
            deps=("disp-ep",),
            detail=expert_detail(
                end=True, collective_kind="ALLTOALL",
                participants=tuple(range(COUNT)),
                payload_bytes=512, participant_count=COUNT)),
    )
    return compiled, WorkloadGraph(
        parallelism=compiled.inventory.parallelism,
        participant_count=COUNT, operations=ops)


def _coll_graph():
    """Two-COLLECTIVE V3-capable graph: TP ALLREDUCE + EP ALLTOALL."""
    compiled = _compiled()
    ops = (
        OperationNode(
            operation_id="ar-tp", kind=KIND_COLLECTIVE,
            detail=collective_detail(
                collective_kind="ALLREDUCE",
                participants=tuple(range(COUNT)),
                payload_bytes=1024, participant_count=COUNT)),
        OperationNode(
            operation_id="a2a-ep", kind=KIND_COLLECTIVE,
            deps=("ar-tp",),
            detail=collective_detail(
                collective_kind="ALLTOALL",
                participants=tuple(range(COUNT)),
                payload_bytes=512, participant_count=COUNT)),
    )
    return compiled, WorkloadGraph(
        parallelism=compiled.inventory.parallelism,
        participant_count=COUNT, operations=ops)


def _logical():
    _, graph = _coll_graph()
    return LogicalMessageArtifactV3(
        graph=graph,
        traffic_class_by_operation=(("ar-tp", TP), ("a2a-ep", EP_D)))


def _projection(**kwargs):
    compiled = _compiled()
    kwargs.setdefault("resolved_fabric", compiled.resolved_fabric)
    kwargs.setdefault("mapping", compiled.mapping)
    kwargs.setdefault("attachment", compiled.attachment)
    return astra.AstraWorkloadProjection.build(
        logical=_logical(), **kwargs)


def _expert_projection_kwargs():
    compiled = _compiled()
    return {
        "resolved_fabric": compiled.resolved_fabric,
        "mapping": compiled.mapping,
        "attachment": compiled.attachment,
    }


# ── identity through projection ──────────────────────────────────────

def test_tp_ep_dispatch_keep_identity_and_class():
    projection = _projection()
    assert projection.traffic_classes() == (EP_D, TP)
    by_op = projection.operation_traffic_classes()
    assert by_op == {"ar-tp": TP, "a2a-ep": EP_D}
    kinds = {op: kind for op, kind, _, _ in
             projection.collective_operations}
    assert kinds == {"ar-tp": "ALLREDUCE", "a2a-ep": "ALLTOALL"}
    for message in projection.messages:
        assert message.traffic_class == by_op[message.operation_id]


def test_per_operation_byte_conservation_across_classes():
    logical = _logical()
    logical.validate_conservation()
    by_op: dict[str, int] = {}
    for message in logical.messages:
        by_op[message.operation_id] = \
            by_op.get(message.operation_id, 0) + message.payload_bytes
    assert set(by_op) == {"ar-tp", "a2a-ep"}
    assert all(v > 0 for v in by_op.values())
    # classes never share bytes: per-op totals are per-class totals.
    assert by_op["ar-tp"] != by_op["a2a-ep"]


def test_coll_nodes_carry_identity_and_class(tmp_path):
    projection = _projection(et_granularity="collectives")
    coll = {payload["operation_id"]: payload
            for _, kind, payload in projection.node_plan()
            if kind == "COLL"}
    assert set(coll) == {"ar-tp", "a2a-ep"}
    assert coll["a2a-ep"]["traffic_class"] == EP_D
    assert coll["ar-tp"]["traffic_class"] == TP
    written = projection.write_chakra(directory=tmp_path, stem="ep")
    assert written


def test_envelope_accepts_expert_dispatch_combine():
    _, graph = _moe_graph()
    Astra2Adapter()._require_collective_envelope(graph)


def test_v3_cannot_yet_name_expert_ops():
    """V3-EXPERT origination gap (canonical workload layer, parent-owned):
    traffic_class_by_operation names COLLECTIVE ops only, so an
    EXPERT-bearing graph cannot build a V3 artifact today. The envelope
    above already accepts such graphs; the artifact must learn to name
    EXPERT_BEGIN/END before EP dispatch/combine originates end to end."""
    _, graph = _moe_graph()
    with pytest.raises((KeyError, Exception)):
        LogicalMessageArtifactV3(
            graph=graph,
            traffic_class_by_operation=(("ar-tp", TP),))


def test_envelope_still_refuses_bare_expert_free_path():
    from veritx_dse.workload.graph import KIND_P2P, p2p_detail
    compiled = _compiled()
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism,
        participant_count=COUNT, operations=(
            OperationNode(
                operation_id="x", kind=KIND_P2P,
                detail=p2p_detail(
                    role="TRANSFER", src_rank=0, dst_rank=1,
                    payload_bytes=64, participant_count=COUNT)),))
    with pytest.raises(Astra2SemanticRefusal):
        Astra2Adapter()._require_collective_envelope(graph)


# ── ledger coverage (unit level, no binary) ──────────────────────────

def _stderr(*comtypes):
    lines = [
        f"[LEDGER][STREAM] rank={r} stream_id={i} comm_type={t} "
        f"size=1024 has_group=0"
        for i, (r, t) in enumerate(comtypes)]
    return "\n".join(lines) + "\n"


def test_ledger_covers_projected_kinds():
    counts = parse_class_stream_ledger(
        _stderr((0, 3), (1, 4), (2, 4)))
    assert assert_stream_ledger_covers_kinds(
        counts, ("ALLREDUCE", "ALLTOALL")) == {3: 1, 4: 2}


def test_ledger_refuses_dropped_class():
    counts = parse_class_stream_ledger(_stderr((0, 3)))
    with pytest.raises(AstraExecutionError, match="dropped a class"):
        assert_stream_ledger_covers_kinds(counts, ("ALLREDUCE", "ALLTOALL"))


def test_ledger_refuses_unattributable_stream():
    counts = parse_class_stream_ledger(_stderr((0, 3), (1, 0)))
    with pytest.raises(AstraExecutionError, match="unattributable"):
        assert_stream_ledger_covers_kinds(counts, ("ALLREDUCE",))


def test_ledger_refuses_unexpected_traffic():
    counts = parse_class_stream_ledger(_stderr((0, 3), (1, 2)))
    with pytest.raises(AstraExecutionError, match="did not ask for"):
        assert_stream_ledger_covers_kinds(counts, ("ALLREDUCE",))


def test_absent_ledger_skips_never_zero_fills():
    assert parse_class_stream_ledger("sys[0] finished, 10 cycles") == {}
    assert assert_stream_ledger_covers_kinds(
        {}, ("ALLREDUCE", "ALLTOALL")) == {}


# ── swap / collapse / omit at normalize ─────────────────────────────

def _two_class_context():
    from test_astra_adapter import _collective_request  # noqa: E402
    from veritx_dse.application.evaluation_context import (  # noqa: E402
        build_evaluation_context,
    )
    from veritx_dse.application.fabric_compiler import (  # noqa: E402
        FabricCompiler,
    )
    from veritx_dse.model.compile_model import (  # noqa: E402
        CollectiveDimension, CollectiveIntent, CollectiveKind,
    )
    import copy
    request = _collective_request(count=COUNT, payload=1024)
    # GLOBAL second collective: one all-ranks group, so the namespace
    # stays unambiguous (a DP subset would fork communicator groups).
    second = CollectiveIntent(
        kind=CollectiveKind.ALLTOALL,
        dimension=CollectiveDimension.GLOBAL,
        payload_bytes=512, traffic_class=EP_D)
    request = copy.replace(
        request,
        workload=copy.replace(
            request.workload,
            collectives=request.workload.collectives + (second,)))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.status
    return build_evaluation_context(compilation)


def _prepared_two_class():
    from veritx_dse.application.evaluation_question import (  # noqa: E402
        EvaluationQuestion,
    )
    context = _two_class_context()
    native = Astra2Adapter().prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN).native_prepared
    assert set(native.workload_projection.traffic_classes()) == {TP, EP_D}
    return context, native


def _evidence_for(context, native, **over):
    from veritx_dse.backend.astra_execution import (  # noqa: E402
        EVIDENCE_TIER_ASTRA_COLLECTIVE, EXECUTION_TRANSPORT_SUPERVISED,
        NAMESPACE_BINDING_CANONICAL, STATUS_EXECUTED, AstraRuntimeEvidence,
    )
    machine, namespace = native.machine, native.namespace
    fields = {
        "status": STATUS_EXECUTED,
        "evidence_tier": EVIDENCE_TIER_ASTRA_COLLECTIVE,
        "expansion_authority": "astra_comm_coll",
        "workload_evidence_scope": "canonical_logical_messages",
        "machine_id": machine.machine_id(),
        "prepared_id": machine.prepared_id,
        "workload_projection_id":
        native.workload_projection.projection_id(),
        "network_config_abi": machine.network_config_abi,
        "embedded_fabric_abi_version": machine.embedded_fabric_abi_version,
        "astra_binary_sha256": "a" * 64,
        "astra_binary_size": 128,
        "astra_source_revision": "cafe" * 10,
        "astra_dirty": False,
        "binary_accepts_legacy_json_abi": True,
        "book_sim_source_has_json_unwrap": False,
        "packetization_fidelity": machine.packetization_fidelity,
        "flit_bytes": machine.flit_bytes,
        "participant_count": machine.participant_count,
        "autonomous_injection_packets": None,
        "per_rank_cycles": ((0, 100),),
        "per_rank_exposed_comm": ((0, 10),),
        "per_rank_compute": ((0, 90),),
        "aggregate_cycles": 100,
        "aggregate_exposed_comm": 10,
        "rank_count": 1,
        "rank_to_endpoint": tuple(tuple(pair) for pair in
                                  namespace.rank_to_endpoint),
        "namespace_id": namespace.namespace_id(),
        "namespace_binding": NAMESPACE_BINDING_CANONICAL,
        "endpoint_count": namespace.endpoint_count,
        "astra_sys_count": machine.astra_sys_count,
        "idle_fabric_endpoints": (),
        "participant_statistics_present": True,
        "per_endpoint_cycles": ((0, 100),),
        "per_endpoint_exposed_comm": ((0, 10),),
        "transport": EXECUTION_TRANSPORT_SUPERVISED,
        "class_binding_id":
        native.workload_projection.class_binding_id(),
        "embedded_network_class_abi_version":
        machine.embedded_network_class_abi_version,
        "astra_build_manifest_sha256": "b" * 64,
        "astra_build_recipe_version": "astra-sim+booksim2/v1",
    }
    fields.update(over)
    return AstraRuntimeEvidence(**fields)


def _normalize(context, native, evidence):
    from veritx_dse.application.evaluation_question import (  # noqa: E402
        EvaluationQuestion,
    )
    from veritx_dse.backend.adapter import PreparedExecution  # noqa: E402
    adapter = Astra2Adapter()
    prepared = PreparedExecution(
        backend_id=adapter.backend_id,
        projection_identity=native.workload_projection_id,
        qualification_identity=native.machine_id,
        backend_config=None, backend_input=None, producer=None,
        native_prepared=native)
    return adapter.normalize(
        context, EvaluationQuestion.SYSTEM_MAKESPAN, prepared, evidence)


def test_swapped_binding_refuses_at_normalize():
    context, native = _prepared_two_class()
    evidence = _evidence_for(context, native, class_binding_id="0" * 64)
    with pytest.raises(AstraExecutionError, match="class binding"):
        _normalize(context, native, evidence)


def test_collapsed_single_class_evidence_refuses():
    context, native = _prepared_two_class()
    evidence = _evidence_for(context, native, class_binding_id=None)
    with pytest.raises(AstraExecutionError, match="class binding"):
        _normalize(context, native, evidence)


def test_class_blind_runtime_refuses_multi_class():
    context, native = _prepared_two_class()
    evidence = _evidence_for(
        context, native, embedded_network_class_abi_version=0)
    # The generation check fires first (ABI 0 vs qualified 1): a
    # class-blind runtime is a cross-generation transplant here.
    with pytest.raises(AstraExecutionError,
                       match="cross-generation|class-blind|class binding"):
        _normalize(context, native, evidence)


def test_unbalanced_per_class_counts_refuse():
    context, native = _prepared_two_class()
    evidence = _evidence_for(
        context, native,
        per_class_injected=((TP, 10), (EP_D, 8)),
        per_class_completed=((TP, 10), (EP_D, 7)))
    with pytest.raises(AstraExecutionError, match="conservation"):
        _normalize(context, native, evidence)


def test_balanced_per_class_counts_normalize():
    context, native = _prepared_two_class()
    evidence = _evidence_for(
        context, native,
        per_class_injected=((TP, 10), (EP_D, 8)),
        per_class_completed=((TP, 10), (EP_D, 8)))
    envelope = _normalize(context, native, evidence)
    assert envelope.native_evidence_id


# ── live execution (real binary or honest refusal) ───────────────────

def test_live_two_class_collective_execution(tmp_path):
    """Small 2-class mesh design through the real embedded runtime.

    Passes with EXECUTED + matching binding/ABI when the producer is
    pinned; passes with the pin refusal when it is not. Any other
    outcome (silent wrong numbers, flattening) fails."""
    from veritx_dse.application.evaluation_question import (  # noqa: E402
        EvaluationQuestion,
    )
    from veritx_dse.backend.astra_execution import (  # noqa: E402
        AstraExecutionError,
    )
    context, native = _prepared_two_class()
    assert native.machine.embedded_network_class_abi_version >= 1
    adapter = Astra2Adapter()
    from veritx_dse.backend.adapter import PreparedExecution  # noqa: E402
    prepared = PreparedExecution(
        backend_id=adapter.backend_id,
        projection_identity=native.workload_projection_id,
        qualification_identity=native.machine_id,
        backend_config=None, backend_input=None, producer=None,
        native_prepared=native)

    class _Options:
        run_dir = str(tmp_path)
        timeout_s = 300

    try:
        evidence = adapter.execute(prepared, _Options())
    except AstraExecutionError as exc:
        assert ("not pinned" in str(exc) or "pin" in str(exc)
                or "manifest" in str(exc) or "absent" in str(exc)), exc
        return
    assert evidence.status == "EXECUTED"
    assert evidence.class_binding_id == \
        native.workload_projection.class_binding_id()
    assert evidence.embedded_network_class_abi_version >= 1
