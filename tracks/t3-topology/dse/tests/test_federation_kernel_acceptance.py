"""PROMPT 1 — the federation-kernel acceptance gate.

ONE real PASS compilation, BOTH backends, planned through the
registry, executed through the generic seam (prepare -> execute ->
normalize), every identity bound, no cross-backend numeric equivalence
ever claimed, no silent substitution ever performed.

Offline part (always): selection, identity binding, endpoint-mapping
preservation, no-execution-during-planning, no-substitution.

Live part (VERITX_LIVE_FEDERATION=1 only): both backends actually
spawn, both normalize authentic native evidence over the same canonical
parents, ASTRA proves zero autonomous injection at the qualified
collective tier, BookSim route/conservation gates pass, and a repeat
run yields a stable scientific evidence identity. Under the marker
nothing skips: a missing backend is FAILURE.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_plan import EvaluationPlanner  # noqa: E402
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendReadiness, ModelFidelity, PreparedExecution, SupportLevel,
)
from veritx_dse.backend.registry import default_backend_registry  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402

DENSE = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
SYSTEM_QUESTIONS = (
    EvaluationQuestion.SYSTEM_MAKESPAN,
    EvaluationQuestion.COMMUNICATION_EXPOSURE,
    EvaluationQuestion.PER_RANK_COMPLETION,
)
ALL_QUESTIONS = (NETWORK, *SYSTEM_QUESTIONS)

LIVE = os.environ.get("VERITX_LIVE_FEDERATION") == "1"

def _context():
    compilation = FabricCompiler().compile(
        parse_request_doc(json.loads(DENSE.read_text(encoding="utf-8"))))
    assert compilation.status == "COMPILED", compilation.status
    assert compilation.certificate is not None \
        and compilation.certificate.overall == "PASS"
    return build_evaluation_context(compilation)

def test_planner_selects_booksim_for_network_completion():
    context = _context()
    plan = EvaluationPlanner().plan(
        context, (NETWORK,), default_backend_registry())
    row = plan.analyses[0]
    assert row.backend_id == "BOOKSIM_STANDALONE"
    assert row.support is not SupportLevel.UNSUPPORTED

def test_planner_selects_astra_for_system_questions():
    context = _context()
    plan = EvaluationPlanner().plan(
        context, SYSTEM_QUESTIONS, default_backend_registry())
    rows = {row.question: row for row in plan.analyses}
    assert set(rows) == set(SYSTEM_QUESTIONS)
    for question in SYSTEM_QUESTIONS:
        assert rows[question].backend_id == "ASTRA2_EMBEDDED_BOOKSIM"

def test_all_plan_rows_bind_the_same_canonical_parents():
    context = _context()
    plan = EvaluationPlanner().plan(
        context, ALL_QUESTIONS, default_backend_registry())
    assert plan.design_hash == context.design_hash
    resolved = context.bundle.resolved_fabric.resolved_fabric_hash
    resolved_hash = resolved() if callable(resolved) else resolved
    assert plan.resolved_fabric_hash == resolved_hash
    assert len(plan.analyses) == len(ALL_QUESTIONS)

def test_astra_preserves_the_canonical_endpoint_mapping():
    """No identity assumption: the prepared binding IS the canonical
    ParticipantEndpointMapping, and the namespace uses the same one."""
    from veritx_dse.workload.traffic import bind_participants
    context = _context()
    registry = default_backend_registry()
    adapter = registry.require("ASTRA2_EMBEDDED_BOOKSIM")
    prepared = adapter.prepare(context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert isinstance(prepared, PreparedExecution)
    native = prepared.native_prepared
    canonical = bind_participants(
        participant_count=native.workload_projection.participant_count,
        mapping=context.bundle.mapping,
        attachment=context.bundle.attachment,
        resolved_fabric=context.bundle.resolved_fabric)
    assert native.rank_to_endpoint == canonical.rank_to_endpoint
    assert native.namespace.rank_to_endpoint == canonical.rank_to_endpoint
    assert native.namespace.participant_mapping_id == \
        canonical.binding_id()

def test_planning_executes_nothing():
    """The planner may project (assess) but must never execute."""
    context = _context()
    registry = default_backend_registry()
    for adapter in registry.adapters():
        adapter.execute = _refuse_execute  # type: ignore[method-assign]
    plan = EvaluationPlanner().plan(
        context, ALL_QUESTIONS, registry)
    assert len(plan.analyses) == len(ALL_QUESTIONS)

def _refuse_execute(prepared, options):
    raise AssertionError("the planner must never execute a backend")

def test_no_silent_backend_substitution():
    """An explicit ASTRA request for the network question refuses — it
    must never secretly receive BookSim (and vice versa)."""
    context = _context()
    registry = default_backend_registry()
    plan = EvaluationPlanner().plan(
        context, (NETWORK,), registry,
        requested_backend="ASTRA2_EMBEDDED_BOOKSIM")
    row = plan.analyses[0]
    assert row.backend_id is None
    assert row.support is SupportLevel.UNSUPPORTED

    plan = EvaluationPlanner().plan(
        context, (EvaluationQuestion.SYSTEM_MAKESPAN,), registry,
        requested_backend="BOOKSIM_STANDALONE")
    row = plan.analyses[0]
    assert row.backend_id is None
    assert row.support is SupportLevel.UNSUPPORTED

def test_explicit_ready_backend_is_selected():
    context = _context()
    registry = default_backend_registry()
    plan = EvaluationPlanner().plan(
        context, (NETWORK,), registry,
        requested_backend="BOOKSIM_STANDALONE")
    assert plan.analyses[0].backend_id == "BOOKSIM_STANDALONE"

def _require_live_ready(plan):
    not_ready = [
        (row.question.value, row.backend_id, row.readiness.value,
         row.reason)
        for row in plan.analyses
        if row.readiness is not BackendReadiness.READY]
    assert not not_ready, \
        f"live federation requires READY rows, got refusals: {not_ready}"

@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_FEDERATION=1")
def test_live_booksim_spawns_and_normalizes(tmp_path):
    from veritx_dse.application.evaluation_question import (
        EvaluationQuestion as _Q,
    )
    context = _context()
    registry = default_backend_registry()
    plan = EvaluationPlanner().plan(context, (NETWORK,), registry)
    _require_live_ready(plan)
    adapter = registry.require("BOOKSIM_STANDALONE")

    def _run(seed_dir: Path):
        prepared = adapter.prepare(
            context, _Q.NETWORK_COMPLETION,
            traffic_class=context.unified_traffic_class)
        assert isinstance(prepared, PreparedExecution)
        result = adapter.execute(prepared, SimpleNamespace(
            binary=None, repo_root=None, run_dir=seed_dir,
            timeout=900, seed=0))
        envelope = adapter.normalize(
            context, _Q.NETWORK_COMPLETION, prepared, result)
        return prepared, result, envelope

    prepared, result, envelope = _run(tmp_path / "run-a")
    evidence = result.record.evidence
    stats = evidence.stats
    expected = prepared.native_prepared.prepared.expected_packets
    assert stats["loaded_trace_packets"] == expected
    assert stats["injected_trace_packets"] == expected
    assert envelope.backend_id == "BOOKSIM_STANDALONE"
    assert envelope.question is _Q.NETWORK_COMPLETION
    assert envelope.model_fidelity is \
        ModelFidelity.NETWORK_PACKET_SIMULATION
    assert envelope.native_evidence_id == evidence.evidence_id()
    assert envelope.qualification == evidence.execution_fidelity
    assert envelope.producer_identity == evidence.binary_sha256
    assert envelope.backend_config_hash == \
        prepared.native_prepared.config_hash
    assert envelope.backend_input_hash == \
        prepared.native_prepared.input_hash
    assert context.design_hash in envelope.canonical_parent_ids
    assert context.workload_id in envelope.canonical_parent_ids
    assert prepared.native_prepared.message_artifact_id in \
        envelope.canonical_parent_ids
    assert envelope.metric("completion_cycles") is not None or \
        envelope.metric("completion_time") is not None
    _, repeat_result, _ = _run(tmp_path / "run-b")
    assert repeat_result.record.evidence.evidence_id() == \
        evidence.evidence_id()

@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_FEDERATION=1")
def test_live_astra_spawns_and_normalizes(tmp_path):
    from veritx_dse.backend.astra_execution import (
        EVIDENCE_TIER_ASTRA_COLLECTIVE,
    )
    context = _context()
    registry = default_backend_registry()
    plan = EvaluationPlanner().plan(context, SYSTEM_QUESTIONS, registry)
    _require_live_ready(plan)
    adapter = registry.require("ASTRA2_EMBEDDED_BOOKSIM")

    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert isinstance(prepared, PreparedExecution)
    native = prepared.native_prepared
    evidence = adapter.execute(prepared, SimpleNamespace(
        run_dir=tmp_path / "run", timeout_s=900))
    assert evidence.status == "EXECUTED"
    assert evidence.evidence_tier == EVIDENCE_TIER_ASTRA_COLLECTIVE
    assert evidence.autonomous_injection_packets in (None, 0)
    assert evidence.machine_id == native.machine_id
    assert evidence.workload_projection_id == \
        native.workload_projection_id
    assert evidence.rank_to_endpoint == native.rank_to_endpoint

    envelopes = {
        question: adapter.normalize(
            context, question, prepared, evidence)
        for question in SYSTEM_QUESTIONS
    }
    makespan = envelopes[EvaluationQuestion.SYSTEM_MAKESPAN]
    assert makespan.metric("system_makespan_cycles").value == \
        float(evidence.aggregate_cycles)
    exposure = envelopes[EvaluationQuestion.COMMUNICATION_EXPOSURE]
    assert exposure.metric("communication_exposure_cycles").value == \
        float(evidence.aggregate_exposed_comm)
    per_rank = envelopes[EvaluationQuestion.PER_RANK_COMPLETION]
    ranks = sorted(
        int(m.dimensions[0][1]) for m in per_rank.metrics
        if m.key == "completion_cycles")
    assert ranks == sorted(
        rank for rank, _ in evidence.per_rank_cycles)
    for envelope in envelopes.values():
        assert envelope.native_evidence_id == evidence.evidence_id()
        assert envelope.producer_identity == \
            evidence.astra_binary_sha256
        assert context.design_hash in envelope.canonical_parent_ids
        assert context.workload_id in envelope.canonical_parent_ids

@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_FEDERATION=1")
def test_live_both_backends_share_canonical_parents(tmp_path):
    """Two simulators, one truth: both evidence sets bind the same
    design/fabric/workload parents. No numeric equivalence claimed."""
    from veritx_dse.application.evaluation_question import (
        EvaluationQuestion as _Q,
    )
    context = _context()
    registry = default_backend_registry()
    plan = EvaluationPlanner().plan(context, ALL_QUESTIONS, registry)
    _require_live_ready(plan)

    booksim = registry.require("BOOKSIM_STANDALONE")
    bs_prepared = booksim.prepare(
        context, _Q.NETWORK_COMPLETION,
        traffic_class=context.unified_traffic_class)
    bs_result = booksim.execute(bs_prepared, SimpleNamespace(
        binary=None, repo_root=None, run_dir=tmp_path / "booksim",
        timeout=900, seed=0))
    bs_envelope = booksim.normalize(
        context, _Q.NETWORK_COMPLETION, bs_prepared, bs_result)

    astra = registry.require("ASTRA2_EMBEDDED_BOOKSIM")
    a_prepared = astra.prepare(context, _Q.SYSTEM_MAKESPAN)
    a_evidence = astra.execute(a_prepared, SimpleNamespace(
        run_dir=tmp_path / "astra", timeout_s=900))
    a_envelope = astra.normalize(
        context, _Q.SYSTEM_MAKESPAN, a_prepared, a_evidence)

    shared = set(bs_envelope.canonical_parent_ids) & \
        set(a_envelope.canonical_parent_ids)
    assert context.design_hash in shared
    assert context.workload_id in shared
    assert bs_envelope.model_fidelity is \
        ModelFidelity.NETWORK_PACKET_SIMULATION
    assert a_envelope.model_fidelity is ModelFidelity.SYSTEM_SIMULATION
