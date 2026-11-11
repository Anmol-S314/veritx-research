"""Canonical ASTRA class envelope: dense identity, not collective kinds.

Two canonical traffic classes may lower to the same collective kind. The
embedded ABI must still hand each class its own dense index so the runtime's
per-class conservation ledger can keep them apart.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend import astra  # noqa: E402
from veritx_dse.backend import astra_machine as am  # noqa: E402
from veritx_dse.backend.astra_execution import (  # noqa: E402
    AstraExecutionError, class_conservation_by_name,
    parse_class_conservation,
)
from veritx_dse.workload.graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, collective_detail,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV3,
)

COUNT = 4
FAST = "fast_class"
SLOW = "slow_class"


def _compiled():
    from test_canonical_compiler import _det, _design  # noqa: E402
    return _det(_design(compute=COUNT, tp=COUNT))


def _logical():
    graph = WorkloadGraph(
        parallelism=_compiled().inventory.parallelism,
        participant_count=COUNT,
        operations=(
            OperationNode(
                operation_id="ar-fast", kind=KIND_COLLECTIVE,
                detail=collective_detail(
                    collective_kind="ALLREDUCE",
                    participants=tuple(range(COUNT)),
                    payload_bytes=1024, participant_count=COUNT)),
            OperationNode(
                operation_id="ar-slow", kind=KIND_COLLECTIVE,
                deps=("ar-fast",),
                detail=collective_detail(
                    collective_kind="ALLREDUCE",
                    participants=tuple(range(COUNT)),
                    payload_bytes=2048, participant_count=COUNT)),
        ))
    return LogicalMessageArtifactV3(
        graph=graph,
        traffic_class_by_operation=(
            ("ar-fast", FAST), ("ar-slow", SLOW)))


def _projection(**kwargs):
    compiled = _compiled()
    kwargs.setdefault("resolved_fabric", compiled.resolved_fabric)
    kwargs.setdefault("mapping", compiled.mapping)
    kwargs.setdefault("attachment", compiled.attachment)
    return astra.AstraWorkloadProjection.build(
        logical=_logical(), et_granularity="collectives", **kwargs)


def test_same_kind_classes_keep_distinct_dense_indices():
    projection = _projection()
    assert projection.traffic_classes() == (FAST, SLOW)
    assert projection.canonical_class_index() == ((FAST, 0), (SLOW, 1))
    assert projection.embedded_class_count() == 2
    by_op = projection.operation_traffic_classes()
    assert by_op == {"ar-fast": FAST, "ar-slow": SLOW}
    kinds = {op: kind for op, kind, _payload, _parts
             in projection.collective_operations}
    assert kinds == {"ar-fast": "ALLREDUCE", "ar-slow": "ALLREDUCE"}
    indices = {payload["operation_id"]: payload["traffic_class_index"]
               for _node, kind, payload in projection.node_plan()
               if kind == "COLL"}
    assert indices == {"ar-fast": 0, "ar-slow": 1}


def test_chakra_collective_nodes_carry_the_dense_class_index(tmp_path):
    projection = _projection()
    projection.write_chakra(directory=tmp_path, stem="classes")
    from chakra.schema.protobuf import et_def_pb2 as pb
    from chakra.src.third_party.utils import protolib

    attrs = {}
    with (tmp_path / "classes.et.0.et").open("rb") as handle:
        metadata = pb.GlobalMetadata()
        assert protolib.decodeMessage(handle, metadata)
        while True:
            node = pb.Node()
            if not protolib.decodeMessage(handle, node):
                break
            if node.type != pb.COMM_COLL_NODE:
                continue
            values = {attr.name: attr for attr in node.attr}
            attrs[node.name] = (
                values["veritx_traffic_class"].string_val,
                values["veritx_traffic_class_index"].uint32_val)
    assert attrs == {"ar-fast": (FAST, 0), "ar-slow": (SLOW, 1)}


def test_embedded_config_preserves_distinct_canonical_class_vcs():
    prepared = SimpleNamespace(
        config_text=("topology = mesh;\nk = 2;\nrouting_function = dor;\n"
                     "classes = 2;\nnum_vcs = 4;\n"
                     "mesh_class_vc_begin = {0,2};\n"
                     "mesh_class_vc_end = {1,3};\n"))
    embedded = am.embedded_fabric_config(
        prepared, embedded_classes=2,
        canonical_class_index=((FAST, 0), (SLOW, 1)))
    assert "classes = 2;" in embedded.text
    assert "mesh_class_vc_begin = {0,2};" in embedded.text
    assert "mesh_class_vc_end = {1,3};" in embedded.text


def test_embedded_config_refuses_a_truncated_class_envelope():
    prepared = SimpleNamespace(
        config_text=("topology = mesh;\nk = 2;\nrouting_function = dor;\n"
                     "classes = 2;\nnum_vcs = 4;\n"
                     "mesh_class_vc_begin = {0,2};\n"
                     "mesh_class_vc_end = {1,3};\n"))
    with pytest.raises(am.AstraMachineError, match="embedded envelope"):
        am.embedded_fabric_config(
            prepared, embedded_classes=1,
            canonical_class_index=((FAST, 0), (SLOW, 1)))


def test_class_conservation_is_keyed_by_canonical_names():
    stdout = (
        "VeritX: class 0 injected flits = 100, accepted flits = 100\n"
        "VeritX: class 1 injected flits = 40, accepted flits = 40\n")
    counts = parse_class_conservation(stdout)
    assert counts == {0: (100, 100), 1: (40, 40)}
    injected, completed = class_conservation_by_name(
        counts, ((FAST, 0), (SLOW, 1)))
    assert injected == ((FAST, 100), (SLOW, 40))
    assert completed == injected


def test_class_conservation_refuses_an_unmapped_runtime_class():
    with pytest.raises(AstraExecutionError, match="unmapped"):
        class_conservation_by_name(
            {0: (10, 10), 2: (5, 5)}, ((FAST, 0), (SLOW, 1)))


def test_class_conservation_refuses_a_missing_canonical_class():
    with pytest.raises(AstraExecutionError, match="no per-class"):
        class_conservation_by_name({0: (10, 10)}, ((FAST, 0), (SLOW, 1)))


def test_real_runtime_emits_per_canonical_class_conservation(tmp_path):
    """The real embedded runtime proves both canonical classes separately.

    Uses the unpinned test runner so a locally rebuilt producer can be
    exercised; production normalization still requires the pinned spawn gate.
    """
    from veritx_dse.backend.astra import resolve_runtime_binary
    from veritx_dse.backend.astra_execution import (
        AstraOutcome, execute_astra_machine,
    )
    from veritx_dse.backend.astra_namespace import stage_endpoint_workload

    binary = resolve_runtime_binary()
    if binary is None:
        pytest.skip("no AstraSim_BookSim2 binary available")
    from veritx_dse.backend.astra_adapter import (  # noqa: E402
        _chakra_staging_available,
    )
    if not _chakra_staging_available():
        pytest.skip("Chakra protobuf bindings unavailable")
    from test_astra_multiclass_bridge import _prepared_two_class  # noqa: E402

    _context, native = _prepared_two_class()
    projection = native.workload_projection
    assert len(projection.traffic_classes()) == 2
    astra_dir = tmp_path / "astra"
    canonical = astra_dir / "workload-canonical"
    workload = astra_dir / "workload"
    projection.write_chakra(directory=canonical, stem="workload")
    staged = stage_endpoint_workload(
        workload=projection, namespace=native.namespace,
        source_directory=canonical, target_directory=workload,
        stem="workload", collective_binding=native.collective_binding)

    def runner(command, cwd, timeout):
        import subprocess
        proc = subprocess.run(
            command, cwd=str(cwd), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout)
        return AstraOutcome(proc.returncode, proc.stdout or "",
                            proc.stderr or "")

    evidence = execute_astra_machine(
        machine=native.machine, binary=str(binary), run_dir=astra_dir,
        workload_configuration=staged.base, timeout_s=180, runner=runner,
        write=False, namespace=native.namespace,
        class_binding_id=projection.class_binding_id(),
        expected_collective_kinds=tuple(
            kind for _op, kind, _payload, _parts
            in projection.collective_operations),
        canonical_class_index=tuple(projection.canonical_class_index()))
    assert evidence.status == "EXECUTED"
    assert evidence.embedded_traffic_class_abi_version >= 1
    assert evidence.embedded_class_count == 2
    expected = set(projection.traffic_classes())
    injected = dict(evidence.per_class_injected)
    completed = dict(evidence.per_class_completed)
    assert set(injected) == expected
    assert set(completed) == expected
    assert all(injected[cls] > 0 for cls in expected)
    assert injected == completed

    from veritx_dse.backend.astra_execution import AstraRuntimeEvidence
    reread = AstraRuntimeEvidence.from_dict(evidence.to_dict())
    assert reread.evidence_id() == evidence.evidence_id()
    assert dict(reread.per_class_injected) == injected
    assert reread.embedded_class_count == 2
