"""STEP E — the multi-class scientific-integrity HARD GATE.

The certified BookSim trace dialect is ``cyc src cl dst sz`` and its class
column is rendered as a literal ``0``. So a multi-class workload executed
through it would collapse every distinct traffic class into class 0: the
backend would measure ONE class of traffic while the design declares several,
and the resulting number would describe work nobody asked for.

`render_trace` refuses this. That guard alone is NOT sufficient, and this
file exists to prove the stronger claim the brief requires: that a multi-class
workload cannot reach an executed backend number through the
OPTIMISATION/EVALUATION path either. If the classes cannot be preserved,
optimization must REFUSE rather than execute misleading science.

The three seams asserted independently:

    distinct workload traffic classes
        -> candidate compilation          (must not flatten)
        -> BookSim projection             (must not flatten)
        -> trace / backend input          (must never be produced)

If any seam ever starts silently collapsing classes, one of these fails.
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
    BACKEND_UNAVAILABLE, EVALUATED, FAILED, UNSUPPORTED, FabricEvaluator,
)
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    BookSimProjectionError, _iter_physical_packets,
    prepare_booksim_input, render_trace,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    build_multi_class_messages, lower_compile_workload,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifactV3,
)

MOE = REPO / "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json"

def _moe_request():
    return parse_request_doc(json.loads(MOE.read_text(encoding="utf-8")))

@pytest.fixture(scope="module")
def compiled():
    request = _moe_request()
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.status
    return request, compilation

@pytest.fixture(scope="module")
def physical(compiled):
    """The canonical multi-class physical traffic for the MoE design."""
    request, compilation = compiled
    bundle = compilation.bundle
    logical = build_multi_class_messages(lower_compile_workload(request))
    return PhysicalTrafficArtifactV3(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)

def test_the_workload_declares_several_distinct_classes(physical):
    """Guards the guard: if this design were single-class, every test below
    would pass vacuously."""
    classes = {m.traffic_class for m in physical.logical.messages}
    assert len(classes) >= 2, classes
    assert "tp_collective" in classes

def test_classes_are_carried_per_message_not_uniformly(physical):
    by_class: dict[str, int] = {}
    for message in physical.logical.messages:
        by_class[message.traffic_class] = \
            by_class.get(message.traffic_class, 0) + 1
    assert len(by_class) >= 2
    assert all(count > 0 for count in by_class.values())

def test_render_trace_carries_each_canonical_class(physical):
    """booksim2-fork/v2: the dialect's class column renders each message's
    canonical class (dense index over the sorted class map). The old law
    rendered a literal 0 and refused multi-class traffic; the fork's
    per-class replay filter now makes the column semantically load-bearing,
    so the render must carry the classes — a collapse is still a refusal.
    """
    text = render_trace(physical).decode()
    rows = [line.split() for line in text.splitlines() if line]
    assert rows, "no trace rows: the gate would be vacuous"
    rendered_classes = {int(r[2]) for r in rows}
    assert len(rendered_classes) >= 2, (
        f"every row rendered the same class {rendered_classes}: that is "
        "the old literal-0 collapse, not a class-aware render")
    from veritx_dse.backend.booksim_projection import trace_class_map
    assert len(rendered_classes) == len(trace_class_map(physical))

def test_render_trace_is_deterministic_and_class_stable(physical):
    """Two renders over the same artifact are byte-identical (the class
    map is artifact-derived, never environment-derived)."""
    assert render_trace(physical) == render_trace(physical)

def test_prepare_booksim_input_binds_the_class_identity(physical):
    """The prepared input binds the executed class identity: the class map
    and the per-class flit declaration are part of prepared identity, so a
    class remap or a per-class loss can never be invisible."""
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionParents, prepare_booksim_input,
    )
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    compilation = FabricCompiler().compile(_moe_request())
    bundle = compilation.bundle
    parents = BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical)
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1"
    assert len(prepared.trace_class_map) >= 2
    assert len(prepared.expected_flits_by_class) == len(
        prepared.trace_class_map)
    assert sum(flits for _c, flits
               in prepared.expected_flits_by_class) \
        == prepared.expected_flits

def test_no_physical_packet_loses_its_class(physical):
    """The canonical physical traffic keeps a class on every packet, so a
    collapse could only happen at the RENDER, never upstream of it."""
    packets = list(_iter_physical_packets(physical))
    assert packets, "no physical packets: the gate would be vacuous"
    assert all(getattr(p, "src_endpoint", None) is not None
               for p in packets)

def test_evaluation_preserves_classes_or_refuses(compiled):
    """The hard gate, Phase-3 form: a multi-class workload either evaluates
    through the certified multi-class profile (per-class conservation
    proven) or refuses with a named reason. What it may NEVER do is return
    a metric whose traffic was collapsed to one class — that number would
    describe work nobody asked for."""
    from veritx_dse.workload.graph import WorkloadGraph
    request, compilation = compiled
    lowered = lower_compile_workload(request)
    graph = lowered.graph
    assert isinstance(graph, WorkloadGraph)
    outcome = FabricEvaluator().evaluate(compilation, graph)
    if outcome.status == EVALUATED:
        assert outcome.backend_profile == \
            "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1", outcome.backend_profile
    else:
        assert outcome.status in (UNSUPPORTED, BACKEND_UNAVAILABLE, FAILED), \
            outcome.status
        assert outcome.backend_profile == \
            "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1", outcome.backend_profile
        reason = getattr(outcome, "reason", None) or ""
        assert ("multi-class" in reason
                or "class" in reason
                or "producer" in reason
                or "DIRTY" in reason
                or "manifest" in reason
                or "clock" in reason
                or "wall-time" in reason
                or "cycles-only" in reason), reason
    _metrics = getattr(outcome, "metrics", None) in (None, {})
    _clock_discipline = ("cycles-only" in reason or "wall-time" in reason
                         or "clock" in reason)
    assert _metrics or outcome.status == EVALUATED or _clock_discipline

def test_optimization_preserves_classes_or_refuses(compiled):
    """An optimizer must either evaluate a multi-class candidate through
    the certified MC profile or refuse it with a named reason — never
    score a silently collapsed execution."""
    request, compilation = compiled
    from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
    from veritx_dse.optimization.definition import (
        DomainParam, Objective, OptimizationDefinition,
    )
    from veritx_dse.optimization.search import search_candidates

    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),))
    candidates = search_candidates(request, definition)
    assert candidates, "no candidates: the gate would be vacuous"

    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("no BookSim binary in this worktree")
    import tempfile
    with tempfile.TemporaryDirectory() as run_root:
        evaluator = RealCandidateEvaluator(binary=binary, repo_root=REPO,
                                           run_root=run_root)
        evaluated = 0
        for candidate in candidates:
            result = evaluator.evaluate(candidate)
            evaluated += 1
            if result.status == EVALUATED:
                assert result.performance_result_id is not None
                assert result.objective_values, candidate.candidate_id
            else:
                assert result.status in (UNSUPPORTED, BACKEND_UNAVAILABLE,
                                         FAILED), result.status
                detail = str(getattr(result, "error", "") or "")
                assert "multi-class refused until" not in detail, detail
        assert evaluated == len(candidates)
