"""MoE declared-ops lowering and the per-message-class artifact seam.

The MoE closure the product needs is not "delete the dense-only check":
it is (1) a proven lowering that maps exactly the DECLARED collectives
with their declared classes — no invented combine, no expert compute —
and (2) a versioned message artifact that carries a traffic class per
message, so admission can validate each class against the compiled VC
assignment without flattening to one class.

The certified multi-class mesh profile (booksim2-fork/v2) now EXECUTES
both canonical classes through the fork's per-class trace replay; these
tests pin the lowering, the class-aware projection law, and the
per-class conservation that follows it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    _message_class_of, render_trace, trace_class_map,
    verify_trace_conservation,
)
from veritx_dse.core.errors import (  # noqa: E402
    InvalidInput, UnsupportedSemantics,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3,
)
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    build_multi_class_messages, build_single_class_messages,
    lower_compile_workload,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV3,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifactV3,
)

MOE = REPO / "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json"
DENSE = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"


def _request(path: Path) -> CompileRequestV3:
    return parse_request_doc(json.loads(path.read_text(encoding="utf-8")))


def test_moe_lowers_declared_ops_with_per_operation_classes():
    """Exactly the declared collectives: TP allreduce + EP dispatch
    alltoall. No combine is invented and no expert compute appears."""
    lowered = lower_compile_workload(_request(MOE))
    kinds = [op.kind for op in lowered.graph.operations]
    assert set(kinds) == {"COLLECTIVE"}
    # TP=8 over dp=1 expands to 8 TP groups (one per DP rank); EP=8 over
    # tp=8 expands to 8 EP groups (one per TP rank).
    assert len(lowered.graph.operations) == 16
    assert lowered.unified_traffic_class is None
    assert lowered.classes == ("ep_dispatch", "tp_collective")
    collective_kinds = {dict(op.detail)["collective_kind"]
                        for op in lowered.graph.operations}
    assert collective_kinds == {"ALLREDUCE", "ALLTOALL"}
    for op in lowered.graph.operations:
        assert lowered.class_for(op.operation_id) in (
            "ep_dispatch", "tp_collective")
    # Declared order is preserved as a dependency chain.
    lowered.graph.require_total_order()


def test_moe_multi_class_has_no_single_class_representation():
    """V2 is single-class by construction: the multi-class lowering
    refuses it and only V3 can carry the per-message classes."""
    lowered = lower_compile_workload(_request(MOE))
    with pytest.raises(UnsupportedSemantics):
        build_single_class_messages(lowered)
    artifact = build_multi_class_messages(lowered)
    assert isinstance(artifact, LogicalMessageArtifactV3)
    assert artifact.classes == ("ep_dispatch", "tp_collective")


def test_v3_stamps_each_message_with_its_operation_class():
    lowered = lower_compile_workload(_request(MOE))
    artifact = build_multi_class_messages(lowered)
    artifact.validate_conservation()
    by_class: dict[str, set[str]] = {}
    for message in artifact.messages:
        by_class.setdefault(message.traffic_class, set()).add(
            message.operation_id)
    # Each class appears on exactly its own expanded group operations:
    # 8 TP groups (tp_collective) and 8 EP groups (ep_dispatch).
    assert set(by_class) == {"ep_dispatch", "tp_collective"}
    assert all(len(ops) == 8 for ops in by_class.values())
    # Identity is per-class: a V3 id differs from any V2 id over the
    # same graph, and a tampered class map is refused at construction.
    with pytest.raises(InvalidInput):
        LogicalMessageArtifactV3(
            graph=lowered.graph,
            traffic_class_by_operation=(
                (lowered.traffic_class_by_operation[0][0], "made_up"),))


def test_v3_physical_projection_renders_and_conserves_per_class():
    request = _request(MOE)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED"
    lowered = lower_compile_workload(request)
    logical = build_multi_class_messages(lowered)
    bundle = compilation.bundle
    physical = PhysicalTrafficArtifactV3(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    physical.validate_conservation()
    assert physical.logical.message_artifact_id() \
        == logical.message_artifact_id()
    # The class-aware trace dialect (booksim2-fork/v2) renders the class
    # column for every canonical class — never a flattening refusal: the
    # certified MC profile executes multi-class traffic as-is.
    trace = render_trace(physical)
    assert {len(row.split())
            for row in trace.decode().splitlines()} == {5}
    stats = verify_trace_conservation(physical)
    assert trace_class_map(physical) == ("ep_dispatch", "tp_collective")
    assert stats["num_packets"] > 0
    # Each canonical class conserves exactly its own flits (per-class
    # law), under the same class authority the renderer uses.
    expected_by_class: dict[str, int] = {}
    for message in physical.traffic:
        cl = _message_class_of(physical.logical, message)
        for packet in message.packets:
            expected_by_class[cl] = (expected_by_class.get(cl, 0)
                                     + packet.flit_count)
    assert stats["flits_by_class"] == expected_by_class


def test_non_dense_non_moe_families_still_refuse():
    doc = json.loads(MOE.read_text(encoding="utf-8"))
    doc["workload"]["model_family"] = "diffusion"
    with pytest.raises(UnsupportedSemantics):
        lower_compile_workload(parse_request_doc(doc))
