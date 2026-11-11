"""Multi-class projection and real execution across the catalog families.

The catalog's mesh-only multi-class profile was a coverage gap, not a
BookSim limitation: the trace dialect carries a class column and the fork's
traffic manager replays it per class. These tests prove the same canonical
class map survives projection and a real execution on every catalog family
whose native topology can seat the workload, and that the three 64-terminal
native trees/fly keep their exact seating refusal instead of being faked.

The workload is the canonical V4 Qwen3-MoE request: three traffic classes
(``tp_collective``, ``ep_dispatch``, ``ep_combine``) over 22 attached
endpoints. The 64-terminal QTree/Tree4/fly cannot seat 22 endpoints without
padding, so their refusal is a topology-size boundary, not a class collapse.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    EVALUATED, EvaluationOptions, FabricEvaluator,
)
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    BookSimProjectionParents, SemanticLoss, parse_config_values,
    prepare_booksim_input, select_booksim_profile, trace_class_map,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.vc_resource import (  # noqa: E402
    vc_resources_from_assignment,
)
from veritx_dse.product.catalog_evaluation import (  # noqa: E402
    catalog_for, candidate_for,
)
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    build_multi_class_messages, lower_compile_workload,
)
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV3  # noqa: E402

MOE_V4 = (
    REPO / "tracks/t3-topology/examples/"
    "qwen3_moe_tp2_ep4_16tiles-v4.json")
MOE_V3 = REPO / "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json"

#: Every catalog family with a native point-to-point/shared-wire renderer
#: that can seat 22 endpoints. The 64-terminal trees/fly are covered by the
#: explicit seating-refusal test below.
EXECUTABLE = (
    "mesh",
    "concentrated_mesh",
    "torus",
    "fattree",
    "flatfly",
    "srota",
    "gec_mecs",
    "gec_hybrid",
    "ring_native",
)

#: The profile each family must reach. Concentrated mesh shares the native
#: DOR envelope; fat-tree is the explicit AnyNet graph; the shared-wire
#: families keep their native v3 route.
EXPECTED_PROFILE = {
    "mesh": "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1",
    "concentrated_mesh": "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1",
    "torus": "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1",
    "fattree": "CERTIFIED_BOOKSIM_ANYNET_MC_V1",
    "flatfly": "CERTIFIED_BOOKSIM_FLATFLY_MIN_V1",
    "srota": "CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1",
    "gec_mecs": "CERTIFIED_BOOKSIM_GEC_MECS_V1",
    "gec_hybrid": "CERTIFIED_BOOKSIM_GEC_HYBRID_V1",
    "ring_native": "CERTIFIED_BOOKSIM_RING_DATELINE_V1",
    "qtree_native": "CERTIFIED_BOOKSIM_QTREE_NCA_V1",
    "tree4_native": "CERTIFIED_BOOKSIM_TREE4_NCA_V1",
    "fly_native": "CERTIFIED_BOOKSIM_FLY_DEST_TAG_V1",
}

#: Complete 64-terminal native constructions. They need an exactly-64
#: attachment; the same multi-class workload is re-scaled to that inventory.
EXECUTABLE_64 = ("qtree_native", "tree4_native", "fly_native")


def _request(path: Path = MOE_V4):
    return parse_request_doc(json.loads(path.read_text(encoding="utf-8")))


def _request_64():
    """The same multi-class workload scaled to exactly 64 attached agents.

    The native QTree/Tree4/fly are complete 64-terminal constructions; they
    cannot seat a 22-terminal subset without padding. This fixture keeps the
    inventory unchanged at 64 and drops only the HBM/NIC agents, which is the
    shape those three fabrics are certified for.
    """
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    base = json.loads(MOE_V4.read_text(encoding="utf-8"))
    scaled = json.loads(MOE_V3.read_text(encoding="utf-8"))
    base["workload"] = scaled["workload"]
    base["requirements"] = scaled["requirements"]
    base["agents"] = [{
        "kind": "compute_tile", "count": 64, "data_width": 256,
        "addr_width": 64, "protocol": "AXI",
        "clock_domain": None, "power_domain": None,
    }]
    for key in ("design_hash", "guardrail_hash"):
        base.pop(key, None)
    return CompileRequestV4.from_dict(base)


def _row(request, topology_id: str):
    return next(r for r in catalog_for(request)
                if r["topology_id"] == topology_id)


def _compiled(request, topology_id: str):
    row = _row(request, topology_id)
    assert row.get("reason") is None, row
    candidate = candidate_for(request, row)
    compilation = FabricCompiler().compile(candidate.request)
    assert compilation.status == "COMPILED", compilation.error
    return candidate, compilation


def _parents(candidate, compilation):
    bundle = compilation.bundle
    lowered = lower_compile_workload(candidate.request)
    logical = build_multi_class_messages(lowered)
    physical = PhysicalTrafficArtifactV3(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    return BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical), lowered


@pytest.mark.parametrize("topology_id", EXECUTABLE)
def test_every_catalog_family_preserves_the_class_map(topology_id):
    request = _request()
    candidate, compilation = _compiled(request, topology_id)
    parents, _lowered = _parents(candidate, compilation)
    classes = trace_class_map(parents.physical_traffic)
    assert len(classes) >= 2, classes
    profile = select_booksim_profile(parents)
    assert profile.profile_id == EXPECTED_PROFILE[topology_id]
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == profile.profile_id
    assert prepared.trace_class_map == classes
    assert len(prepared.expected_flits_by_class) == len(classes)
    assert sum(flits for _cls, flits
               in prepared.expected_flits_by_class) == prepared.expected_flits
    assert parse_config_values(prepared.config_text)["classes"] == str(
        len(classes))
    # The class column is load-bearing, not a literal zero.
    rendered = {int(line.split()[2])
                for line in prepared.trace_text.splitlines() if line}
    assert rendered == set(range(len(classes)))


@pytest.mark.parametrize("topology_id", EXECUTABLE)
def test_every_catalog_family_executes_every_class(topology_id):
    """Real pinned BookSim execution, not a projection-only claim."""
    request = _request()
    candidate, compilation = _compiled(request, topology_id)
    parents, lowered = _parents(candidate, compilation)
    prepared = prepare_booksim_input(parents)
    outcome = FabricEvaluator().evaluate(
        compilation, lowered.graph,
        EvaluationOptions(network_clock_hz=1_000_000_000))
    assert outcome.status == EVALUATED, outcome.reason
    assert outcome.backend_profile == EXPECTED_PROFILE[topology_id]
    metrics = outcome.metrics or {}
    assert metrics["loaded_trace_packets"] == prepared.expected_packets
    assert metrics["flits_injected"] == prepared.expected_flits
    assert metrics["flits_accepted"] == metrics["flits_injected"]


@pytest.mark.parametrize("topology_id", EXECUTABLE_64)
def test_every_64_terminal_native_fabric_executes_multiclass(topology_id):
    request = _request_64()
    candidate, compilation = _compiled(request, topology_id)
    parents, lowered = _parents(candidate, compilation)
    classes = trace_class_map(parents.physical_traffic)
    assert len(classes) >= 2, classes
    prepared = prepare_booksim_input(parents)
    assert prepared.trace_class_map == classes
    assert parse_config_values(prepared.config_text)["classes"] == str(
        len(classes))
    outcome = FabricEvaluator().evaluate(
        compilation, lowered.graph,
        EvaluationOptions(network_clock_hz=1_000_000_000))
    assert outcome.status == EVALUATED, outcome.reason
    assert outcome.backend_profile == EXPECTED_PROFILE[topology_id]
    metrics = outcome.metrics or {}
    assert metrics["loaded_trace_packets"] == prepared.expected_packets
    assert metrics["flits_injected"] == prepared.expected_flits
    assert metrics["flits_accepted"] == metrics["flits_injected"]


@pytest.mark.parametrize("topology_id", ("qtree_native", "tree4_native",
                                         "fly_native"))
def test_native_64_terminal_fabrics_refuse_a_sparse_workload_by_name(
        topology_id):
    """22 attached endpoints cannot fill a 64-terminal native tree/fly.

    Padding the attachment would change the workload, so the exact seating
    refusal is retained. This is a topology-size boundary, not a class loss.
    """
    request = _request()
    candidate, compilation = _compiled(request, topology_id)
    parents, _lowered = _parents(candidate, compilation)
    with pytest.raises(SemanticLoss, match="64-terminal"):
        select_booksim_profile(parents)


def test_catalog_preflight_keeps_the_64_terminal_reason_for_a_larger_workload():
    request = _request(MOE_V3)
    rows = {row["topology_id"]: row for row in catalog_for(request)}
    assert sum(agent.count for agent in request.agents) > 64
    for topology_id in ("qtree_native", "tree4_native", "fly_native"):
        assert "64" in (rows[topology_id].get("reason") or "")
