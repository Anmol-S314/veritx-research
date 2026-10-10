"""Phase-3 ASTRA: class-faithful V3 multi-class seam + producer trust.

Proves the ASTRA Python seam accepts the canonical V3 per-operation
artifact without losing class identity (TP allreduce vs EP dispatch vs
EP combine stay separately identifiable), refuses swapped/collapsed/
omitted/relabeled bindings, qualifies multi-class machines only against
a class-aware runtime ABI, binds the pinned producer end to end, and
pins the reproduction binary. Live multi-class execution tests are
marked to run after the C++ class-attribution rebuild; everything here
runs against the current tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from test_astra_projection import (  # noqa: E402  (test-only fixtures)
    _compiled as _compiled16,
)
from test_canonical_compiler import _det, _design  # noqa: E402

from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend import astra  # noqa: E402
from veritx_dse.backend.astra_adapter import (  # noqa: E402
    Astra2Adapter, Astra2SemanticRefusal,
)
from veritx_dse.backend.astra_execution import (  # noqa: E402
    EVIDENCE_TIER_ASTRA_COLLECTIVE, EXECUTION_TRANSPORT_SUPERVISED,
    NAMESPACE_BINDING_CANONICAL, STATUS_EXECUTED, AstraExecutionError,
    AstraRuntimeEvidence,
)
from veritx_dse.backend.astra_machine import (  # noqa: E402
    AstraMachineError,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.workload.graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, collective_detail,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV3,
)

COUNT = 4
TP_CLASS = "tp_collective"
EP_CLASS = "ep_dispatch"

def _graph():
    ops = (
        OperationNode(
            operation_id="ar-tp", kind=KIND_COLLECTIVE,
            detail=collective_detail(
                collective_kind="ALLREDUCE",
                participants=tuple(range(COUNT)),
                payload_bytes=1024, participant_count=COUNT)),
        OperationNode(
            operation_id="a2a-ep", kind=KIND_COLLECTIVE, deps=("ar-tp",),
            detail=collective_detail(
                collective_kind="ALLTOALL",
                participants=tuple(range(COUNT)),
                payload_bytes=512, participant_count=COUNT)),
    )
    compiled = _det(_design(compute=COUNT, tp=COUNT))
    return compiled, WorkloadGraph(
        parallelism=compiled.inventory.parallelism,
        participant_count=COUNT, operations=ops)

def _logical_v3():
    _, graph = _graph()
    return LogicalMessageArtifactV3(
        graph=graph,
        traffic_class_by_operation=(("a2a-ep", EP_CLASS),
                                    ("ar-tp", TP_CLASS)))

def _compiled():
    return _det(_design(compute=COUNT, tp=COUNT))

def _projection_v3(**kwargs):
    compiled = _compiled()
    kwargs.setdefault("resolved_fabric", compiled.resolved_fabric)
    kwargs.setdefault("mapping", compiled.mapping)
    kwargs.setdefault("attachment", compiled.attachment)
    return astra.AstraWorkloadProjection.build(
        logical=_logical_v3(), **kwargs)

def test_v3_projection_preserves_per_operation_classes():
    projection = _projection_v3()
    assert projection.logical_artifact_variant == "V3"
    assert projection.traffic_classes() == (EP_CLASS, TP_CLASS)
    by_op = projection.operation_traffic_classes()
    assert by_op == {"ar-tp": TP_CLASS, "a2a-ep": EP_CLASS}
    assert all(len(entry) == 4
               for entry in projection.collective_operations)
    kinds = {op: kind for op, kind, _, _ in
             projection.collective_operations}
    assert kinds == {"ar-tp": "ALLREDUCE", "a2a-ep": "ALLTOALL"}
    for message in projection.messages:
        assert message.traffic_class == by_op[message.operation_id]

def test_v3_binding_id_is_deterministic_and_class_sensitive():
    first = _projection_v3().class_binding_id()
    second = _projection_v3().class_binding_id()
    assert first == second
    swapped = astra.AstraWorkloadProjection.build(
        logical=LogicalMessageArtifactV3(
            graph=_graph()[1],
            traffic_class_by_operation=(("a2a-ep", TP_CLASS),
                                        ("ar-tp", EP_CLASS))),
        resolved_fabric=_compiled().resolved_fabric,
        mapping=_compiled().mapping, attachment=_compiled().attachment)
    assert swapped.class_binding_id() != first
    assert swapped.projection_id() != _projection_v3().projection_id()

def test_v3_identity_differs_from_v2_and_round_trips():
    v3 = _projection_v3()
    doc = v3.to_dict()
    assert doc["logical_artifact_variant"] == "V3"
    rebuilt = astra.AstraWorkloadProjection.from_dict(doc)
    assert rebuilt.logical_artifact_variant == "V3"
    assert rebuilt.projection_id() == v3.projection_id()
    assert rebuilt.class_binding_id() == v3.class_binding_id()
    legacy = dict(doc)
    legacy.pop("logical_artifact_variant")
    legacy.pop("class_binding_id")
    legacy.pop("traffic_classes")
    back = astra.AstraWorkloadProjection.from_dict(legacy)
    assert back.logical_artifact_variant == "V2"

def test_collapsed_binding_refuses():
    v3 = _projection_v3()
    doc = v3.to_dict()
    tampered = [dict(m) for m in doc["messages"]]
    victim = next(m for m in tampered if m["operation_id"] == "ar-tp")
    victim["traffic_class"] = EP_CLASS
    doc["messages"] = tampered
    rebuilt = astra.AstraWorkloadProjection.from_dict(doc)
    with pytest.raises(astra.AstraError):
        rebuilt.operation_traffic_classes()
    with pytest.raises(astra.AstraError):
        rebuilt.class_binding_id()

def test_omitted_class_refused_at_construction():
    _, graph = _graph()
    from veritx_dse.core.errors import InvalidInput
    with pytest.raises(InvalidInput):
        LogicalMessageArtifactV3(
            graph=graph,
            traffic_class_by_operation=(("ar-tp", TP_CLASS),))

def test_coll_nodes_carry_class_sidecar(tmp_path):
    projection = _projection_v3(et_granularity="collectives")
    plan = dict((node_id, (kind, payload))
                for node_id, kind, payload in projection.node_plan())
    coll = [(node_id, payload) for node_id, (kind, payload)
            in plan.items() if kind == "COLL"]
    assert {payload["operation_id"] for _, payload in coll} == {
        "ar-tp", "a2a-ep"}
    assert {payload["traffic_class"] for _, payload in coll} == {
        TP_CLASS, EP_CLASS}
    written = projection.write_chakra(directory=tmp_path, stem="mc")
    assert written

def _moe_context():
    from veritx_dse.product.service import parse_request_doc
    moe = REPO / "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json"
    compilation = FabricCompiler().compile(
        parse_request_doc(json.loads(moe.read_text(encoding="utf-8"))))
    assert compilation.status == "COMPILED"
    return build_evaluation_context(compilation)

def test_prepare_refuses_eval_time_class_subset_on_v3():
    context = _moe_context()
    adapter = Astra2Adapter()
    with pytest.raises(Astra2SemanticRefusal) as exc:
        adapter.prepare(context, EvaluationQuestion.SYSTEM_MAKESPAN,
                        traffic_class="tp_collective")
    assert "subset" in str(exc.value)

def test_prepare_qualifies_multi_class_at_current_abi_qualification(monkeypatch):
    """Multi-class now qualifies: the two MoE classes survive lowering
    and projection, and the qualified runtime (class ABI 1) attributes
    injections. The old-ABI refusal survives as a monkeypatched variant
    below. No flattening anywhere on the path."""
    context = _moe_context()
    adapter = Astra2Adapter()
    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN).native_prepared
    assert prepared.machine.embedded_network_class_abi_version == 1

def test_prepare_refuses_multi_class_at_old_abi_qualification(monkeypatch):
    """Old runtime still refuses: monkeypatched class ABI 0 cannot
    attribute injections."""
    import veritx_dse.backend.astra_machine as _machine

    monkeypatch.setattr(_machine, "EMBEDDED_NETWORK_CLASS_ABI_VERSION", 0)
    context = _moe_context()
    adapter = Astra2Adapter()
    with pytest.raises(AstraMachineError) as exc:
        adapter.prepare(context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert "class ABI" in str(exc.value)

def test_multi_class_qualifies_when_runtime_proves_class_abi(monkeypatch):
    import veritx_dse.backend.astra_machine as _machine

    monkeypatch.setattr(_machine, "EMBEDDED_NETWORK_CLASS_ABI_VERSION", 1)
    context = _moe_context()
    adapter = Astra2Adapter()
    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN).native_prepared
    assert prepared.machine.embedded_network_class_abi_version == 1
    assert prepared.workload_projection.logical_artifact_variant == "V3"
    assert set(prepared.workload_projection.traffic_classes()) == {
        TP_CLASS, EP_CLASS}

def _single_context():
    from test_astra_adapter import _context
    return _context()

def _prepared_single():
    return Astra2Adapter().prepare(
        _single_context(),
        EvaluationQuestion.SYSTEM_MAKESPAN).native_prepared

def _evidence(native, **over):
    machine = native.machine
    namespace = native.namespace
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
        "embedded_fabric_abi_version":
        machine.embedded_fabric_abi_version,
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
    }
    fields.update(over)
    return AstraRuntimeEvidence(**fields)

def _normalize(native, evidence):
    from veritx_dse.backend.adapter import PreparedExecution
    adapter = Astra2Adapter()
    prepared = PreparedExecution(
        backend_id=adapter.backend_id,
        projection_identity=native.workload_projection_id,
        qualification_identity=native.machine_id,
        backend_config=None, backend_input=None, producer=None,
        native_prepared=native)
    return adapter.normalize(
        _single_context(), EvaluationQuestion.SYSTEM_MAKESPAN,
        prepared, evidence)

def _pinned_evidence(native, **over):
    fields = {
        "astra_build_manifest_sha256": "b" * 64,
        "astra_build_recipe_version": "astra-sim+booksim2/v1",
    }
    fields.update(over)
    return _evidence(native, **fields)

def test_preparation_carries_no_producer_pin():
    assert _prepared_single().producer_pin is None

def test_normalize_refuses_evidence_outside_spawn_gate():
    native = _prepared_single()
    with pytest.raises(AstraExecutionError) as exc:
        _normalize(native, _evidence(native))
    assert "build recipe" in str(exc.value)

def test_normalize_refuses_wrong_recipe():
    native = _prepared_single()
    with pytest.raises(AstraExecutionError):
        _normalize(native, _pinned_evidence(
            native, astra_build_recipe_version="bogus/v9"))

def test_normalize_refuses_missing_manifest_digest():
    native = _prepared_single()
    with pytest.raises(AstraExecutionError):
        _normalize(native, _pinned_evidence(
            native, astra_build_manifest_sha256=None))

def test_normalize_refuses_dirty_producer():
    native = _prepared_single()
    with pytest.raises(AstraExecutionError):
        _normalize(native, _pinned_evidence(native, astra_dirty=True))

def test_normalize_refuses_abi_generation_transplant():
    native = _prepared_single()
    assert native.machine.embedded_network_class_abi_version == 1
    with pytest.raises(AstraExecutionError) as exc:
        _normalize(native, _pinned_evidence(
            native, embedded_network_class_abi_version=0))
    assert "cross-generation" in str(exc.value)

def test_normalize_accepts_pinned_single_class_evidence():
    native = _prepared_single()
    envelope = _normalize(native, _pinned_evidence(
        native, embedded_network_class_abi_version=1))
    assert envelope.native_evidence_id
    assert envelope.producer_identity == "a" * 64

def test_normalize_refuses_swapped_class_binding(monkeypatch):
    import veritx_dse.backend.astra_machine as _machine

    monkeypatch.setattr(_machine, "EMBEDDED_NETWORK_CLASS_ABI_VERSION", 1)
    context = _moe_context()
    native = Astra2Adapter().prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN).native_prepared
    machine = native.machine
    namespace = native.namespace
    evidence = _evidence(
        native,
        machine_id=machine.machine_id(),
        prepared_id=machine.prepared_id,
        workload_projection_id=native.workload_projection.projection_id(),
        rank_to_endpoint=tuple(tuple(pair) for pair in
                               namespace.rank_to_endpoint),
        namespace_id=namespace.namespace_id(),
        class_binding_id="0" * 64,
        embedded_network_class_abi_version=1,
        astra_build_manifest_sha256="b" * 64,
        astra_build_recipe_version="astra-sim+booksim2/v1")
    with pytest.raises(AstraExecutionError) as exc:
        _normalize(native, evidence)
    assert "class binding" in str(exc.value)

def test_execute_refuses_unpinned_spawn(tmp_path):
    """The spawn gate fires before any staging: a fake binary without a
    manifest cannot execute for reusable evidence."""
    from test_astra_adapter import _collective_request
    request = _collective_request()
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED"
    context = build_evaluation_context(compilation)
    native = Astra2Adapter().prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN).native_prepared
    machine = native.machine
    assert machine.expansion_authority == "astra_comm_coll"
    from veritx_dse.backend import astra_execution as _ax
    binary = tmp_path / "AstraSim_BookSim2"
    binary.write_bytes(b"not-a-real-runtime")
    with pytest.raises(AstraExecutionError) as exc:
        _ax.execute_astra_machine(
            machine=machine, binary=binary, run_dir=tmp_path / "run",
            workload_configuration=tmp_path / "workload.et",
            timeout_s=30, write=False, namespace=native.namespace)
    assert "pinned" in str(exc.value)

def test_reproduce_refuses_binary_swap(tmp_path):
    """Archived inputs + evidence naming producer A do not reproduce
    against producer B, even when every structural id matches."""
    import shutil

    from veritx_dse.backend.reproduce_astra import (
        reproduce_astra_run_bundle,
    )
    from veritx_dse.core.run_bundle import RunBundleError
    native = _prepared_single()
    machine = native.machine
    namespace = native.namespace
    projection = native.workload_projection
    root = tmp_path / "analysis"
    inputs = root / "astra-inputs"
    inputs.mkdir(parents=True)
    machine_doc = dict(machine.identity_dict())
    machine_doc.update({
        "system_config_text": machine.system_config_text,
        "network_config_text": machine.network_config_text,
        "logical_topology_text": machine.logical_topology_text,
        "memory_config_text": machine.memory_config_text,
    })
    (inputs / "machine.json").write_text(
        json.dumps(machine_doc), encoding="utf-8")
    (inputs / "workload-projection.json").write_text(
        json.dumps(projection.to_dict()), encoding="utf-8")
    (inputs / "namespace.json").write_text(
        json.dumps(namespace.to_dict()), encoding="utf-8")
    evidence = _pinned_evidence(native)
    astra_dir = root / "astra"
    (astra_dir / "workload").mkdir(parents=True)
    (astra_dir / "astra_evidence.json").write_text(
        json.dumps(evidence.to_dict()), encoding="utf-8")
    (astra_dir / "workload" / "workload.et").write_bytes(b"staged")
    other = tmp_path / "other-binary"
    other.write_bytes(b"a-different-producer")
    with pytest.raises(RunBundleError) as exc:
        reproduce_astra_run_bundle(root, binary=other, timeout=30)
    assert "producer" in str(exc.value).lower()
    shutil.rmtree(root, ignore_errors=True)

def test_required_embedded_classes_covers_collective_kinds():
    from veritx_dse.backend.astra import (
        AstraLoweringRefused, required_embedded_classes,
    )
    assert required_embedded_classes(
        [("op0", "ALLREDUCE", 64, (0, 1))]) == 2
    assert required_embedded_classes(
        [("op0", "ALLREDUCE", 64, (0, 1)),
         ("op1", "ALLTOALL", 64, (0, 1))]) == 5
    assert required_embedded_classes([]) == 1
    with pytest.raises(AstraLoweringRefused, match="BROADCAST"):
        required_embedded_classes([("op9", "BROADCAST", 64, (0, 1))])

def test_embedded_config_declares_class_envelope():
    from types import SimpleNamespace
    from veritx_dse.backend import astra_machine as am
    prepared = SimpleNamespace(
        config_text=("topology = mesh;\nk = 4;\n"
                     "routing_function = dor;\n"))
    assert not hasattr(prepared, "profile_id")
    config = am.embedded_fabric_config(prepared, embedded_classes=5)
    assert "classes = 5;" in config.text
    assert "trace(" not in config.text

def test_serving_class_envelope_covers_ep_kinds():
    from veritx_dse.simulation.serve_canonical import serving_class_envelope
    assert serving_class_envelope(max_ep=1) == 2
    assert serving_class_envelope(max_ep=2) == 4
    assert serving_class_envelope(max_ep=8) == 4
