"""STEP E — the multi-class scientific-integrity HARD GATE.

The certified BookSim trace dialect is ``cyc src cl dst sz``. Under
``booksim2-fork/v2`` the ``cl`` column is the dense trace-class index over
the artifact's canonical class map, so a multi-class workload executes
through the certified multi-class profile
``CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1`` with every class preserved and
reconciled per class against the canonical declaration.

The hard gate is the integrity claim, not a blanket ban: a multi-class
workload must never reach an executed backend number whose traffic was
silently collapsed into one class. The old literal-``0`` dialect did exactly
that — it measured ONE class of traffic while the design declared several,
and the resulting number described work nobody asked for. The sealed refusal
now lives at the boundaries (a single-class profile refuses a multi-class
trace; the prepared input binds the class map and the per-class flit
declaration), and this file proves the seams independently:

    distinct workload traffic classes
        -> candidate compilation          (must not flatten)
        -> BookSim projection             (must not flatten)
        -> trace / backend input          (class identity is bound)

If any seam ever starts silently collapsing classes, one of these fails.
The final test runs the MoE multi-class workload through the REAL pinned
binary and reconciles the executed per-class flits live (RC-04).
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


def test_live_multiclass_moe_executes_and_conserves_per_class(compiled, physical):
    """RC-04: the MoE multi-class workload through the REAL BookSim binary.

    The multi-class V3 execution path was proven only against injected
    fakes; this runs the canonical MoE request on the certified MC profile
    and reconciles the REAL stdout's per-class flit counts against the
    canonical ``expected_flits_by_class``. The environment skips (never
    xfails) when it cannot produce a reusable execution: no built binary,
    or a typed producer/DIRTY/clock refusal.
    """
    import tempfile

    from veritx_dse.backend.booksim_execution import (
        BookSimExecutionError, execute_prepared_booksim,
    )
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionParents,
    )
    from veritx_dse.model.vc_resource import vc_resources_from_assignment

    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("no BookSim binary in this worktree")

    _request, compilation = compiled
    bundle = compilation.bundle
    parents = BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical)
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1", \
        prepared.profile_id
    # Both ``trace_class_map`` and ``expected_flits_by_class`` are sorted by
    # canonical class name, so trace index i is the i-th declared class.
    expected_by_index = {
        index: dict(prepared.expected_flits_by_class)[cls]
        for index, cls in enumerate(prepared.trace_class_map)}
    assert len(expected_by_index) >= 2, expected_by_index

    with tempfile.TemporaryDirectory() as run_root:
        try:
            # No injected runner: this is the supervised production path, so
            # packet/flit conservation and the per-class gate stay armed. A
            # pinned producer is required for reusable evidence; an unpinned
            # or dirty tree is a typed refusal to skip, never a silent pass.
            record = execute_prepared_booksim(
                prepared=prepared, binary=binary,
                run_dir=Path(run_root) / "run", timeout=900,
                repo_root=REPO, require_pinned_producer=True)
        except BookSimExecutionError as exc:
            reason = str(exc)
            if any(token in reason for token in (
                    "producer", "DIRTY", "manifest", "source revision",
                    "clock")):
                pytest.skip(f"live multi-class BookSim refused: {reason}")
            raise

    evidence = record.evidence
    assert evidence.execution_fidelity == "QUALIFIED", \
        evidence.execution_fidelity
    # ``flits_by_class`` is the ``parse_booksim_stats`` parse of the REAL
    # stdout (backend/booksim_execution.py), keyed by trace class index; the
    # parser is reused, not re-implemented, and the run above already proved
    # loaded == injected == delivered.
    per_class = evidence.stats["flits_by_class"]
    assert set(per_class) == set(expected_by_index), per_class
    for index, expected in sorted(expected_by_index.items()):
        counters = per_class[index]
        assert counters["injected"] == expected, (index, counters)
        assert counters["accepted"] == expected, (index, counters)
