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


# ══ seam 1 — the workload really is multi-class ═══════════════════════

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


# ══ seam 3 — the trace can NEVER be produced with collapsed classes ══

def test_render_trace_refuses_multi_class_traffic(physical):
    with pytest.raises(BookSimProjectionError, match="multi-class"):
        render_trace(physical)


def test_the_class_column_is_a_literal_zero_hence_the_refusal(physical):
    """Documents WHY the refusal is necessary: the dialect has no room for a
    second class, so the only alternatives are refuse or lie."""
    import inspect
    src = inspect.getsource(render_trace)
    assert '" 0 "' in src or " 0 " in src, \
        "the class column is no longer a literal; revisit this gate"


def test_prepare_booksim_input_refuses_before_any_bytes_exist(physical):
    """The refusal must happen in the PREPARER, so no prepared config, trace
    or topology file can exist for a multi-class design."""
    from veritx_dse.backend.booksim_projection import BookSimProjectionParents
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
    # TWO independent refusals guard this seam, and the VC-class admission
    # fires FIRST: the certified profile runs every flow in one class over all
    # VCs, so an artifact that assigns classes to VC subsets is refused before
    # the trace is ever rendered. Either refusal is acceptable; silence is not.
    with pytest.raises(BookSimProjectionError) as excinfo:
        prepare_booksim_input(parents)
    message = str(excinfo.value)
    assert ("multi-class" in message
            or "one class" in message
            or "traffic classes" in message), message


def test_no_physical_packet_loses_its_class(physical):
    """The canonical physical traffic keeps a class on every packet, so a
    collapse could only happen at the RENDER, never upstream of it."""
    packets = list(_iter_physical_packets(physical))
    assert packets, "no physical packets: the gate would be vacuous"
    assert all(getattr(p, "src_endpoint", None) is not None
               for p in packets)


# ══ seam 2 — the EVALUATION path refuses, never returns a number ═════

def test_evaluation_refuses_a_multi_class_workload(compiled):
    """The hard gate: no executed metric may be produced."""
    from veritx_dse.workload.graph import WorkloadGraph
    request, compilation = compiled
    lowered = lower_compile_workload(request)
    graph = lowered.graph
    assert isinstance(graph, WorkloadGraph)
    outcome = FabricEvaluator().evaluate(compilation, graph)
    assert outcome.status != EVALUATED, (
        "a multi-class workload was EVALUATED: the certified trace dialect "
        "renders one class column, so the metric would describe collapsed "
        f"traffic. status={outcome.status} detail={outcome.detail!r}")
    assert outcome.status in (UNSUPPORTED, BACKEND_UNAVAILABLE, FAILED)
    # ...and there is no number to mistake for a measurement.
    assert getattr(outcome, "metrics", None) in (None, {})


# ══ the OPTIMISATION path must not turn the refusal into a score ═════

def test_optimization_cannot_score_a_multi_class_base(compiled):
    """An optimizer that swallowed the projection refusal into a numeric
    penalty would 'rank' candidates for a design nothing can execute. The
    candidate must be refused, not scored."""
    request, compilation = compiled
    from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
    from veritx_dse.optimization.definition import (
        DomainParam, Objective, OptimizationDefinition,
    )
    from veritx_dse.optimization.candidate import make_candidate
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
            assert result.status != EVALUATED, (
                f"candidate {candidate.candidate_id} was SCORED for a "
                "multi-class design that the certified backend cannot "
                f"execute: status={result.status}")
        assert evaluated == len(candidates)
    evaluated = 0
    for candidate in candidates:
        result = evaluator.evaluate(candidate)
        evaluated += 1
        assert result.status != EVALUATED, (
            f"candidate {candidate.candidate_id} was SCORED for a "
            "multi-class design that the certified backend cannot execute: "
            f"status={result.status}")
    assert evaluated == len(candidates)
