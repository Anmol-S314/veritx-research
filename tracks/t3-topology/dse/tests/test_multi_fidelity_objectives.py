"""PROMPT 4 — multi-fidelity objectives: policy, provenance, Pareto.

Step 1 (explicit evaluation policy per objective), Step 2 (provenance
on every value), Step 4 (Pareto comparability never crosses models)
and Step 8 (capability truth derived from the federation).

Live-backend honesty: the ASTRA system-makespan leg is proven live
(the pinned binary is READY on this tree). The Ramulator leg cannot
qualify live (no compiled extension), so its orchestration laws are
proven scripted in test_federated_optimizer.py and its honest
UNAVAILABLE assessment is proven live here. BookSim legs assess
BLOCKED on the dirty producer tree (fail-closed, correct).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import ModelFidelity  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    Agent, AgentKind, CollectiveDimension, CollectiveIntent,
    CollectiveKind, CompileRequestV3, DependencyGraph, ModelFamily,
    NocConfig, QoSClass, RequirementV3, TopologyFamily, WorkloadV3,
)
from veritx_dse.optimization.candidate import make_candidate  # noqa: E402
from veritx_dse.optimization.definition import (  # noqa: E402
    DomainParam, Objective, ObjectiveSource, OptimizationDefinition,
    OptimizationDefinitionError, required_questions,
)
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    RealCandidateEvaluator,
)
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN
EXPOSURE = EvaluationQuestion.COMMUNICATION_EXPOSURE
PER_RANK = EvaluationQuestion.PER_RANK_COMPLETION
DRAM = EvaluationQuestion.DRAM_TIMING

def _base(**kw):
    noc = dict(topology_family=TopologyFamily.MESH, concentration=1)
    noc.update(kw.pop("noc", {}))
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=4, dp=1,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=2048,
                traffic_class="tp_collective"),)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=10 ** 9, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(**noc))

def test_bare_objective_defaults_to_network_completion():
    """Legacy constructions keep their meaning: WHAT metric / FROM
    NETWORK_COMPLETION / WITH planner-adjudicated backend."""
    objective = Objective("completion_cycles", "MIN")
    assert objective.question is NETWORK
    assert objective.backend_id is None
    source = objective.source
    assert isinstance(source, ObjectiveSource)
    assert source.metric_key == "completion_cycles"
    assert source.question is NETWORK
    assert source.backend_id is None

def test_objective_policy_examples():
    """The prompt's canonical bindings: metric <- question <- backend."""
    assert Objective("completion_cycles", "MIN").question is NETWORK
    assert Objective("system_makespan_cycles", "MIN",
                     question=SYSTEM).question is SYSTEM
    assert Objective("average_read_latency_cycles", "MIN",
                     question=DRAM).question is DRAM
    constrained = Objective(
        "system_makespan_cycles", "MIN", question=SYSTEM,
        backend_id="ASTRA2_EMBEDDED_BOOKSIM")
    assert constrained.backend_id == "ASTRA2_EMBEDDED_BOOKSIM"

def test_objective_question_coercion_and_refusal():
    assert Objective("m", "MIN", question="SYSTEM_MAKESPAN").question \
        is SYSTEM
    assert Objective("m", "MIN",
                     question="NETWORK_COMPLETION").question is NETWORK
    with pytest.raises(OptimizationDefinitionError):
        Objective("m", "MIN", question="NO_SUCH_QUESTION")
    with pytest.raises(OptimizationDefinitionError):
        Objective("m", "MIN", question=42)

def test_same_metric_under_two_questions_refuses():
    """One metric, one verdict: the same key under two questions is
    one destination declared twice — fail-closed, never
    last-write-wins, never silently merged across models."""
    with pytest.raises(OptimizationDefinitionError, match="duplicate"):
        OptimizationDefinition(
            domain=(DomainParam("link_width", (64, 128)),),
            objectives=(
                Objective("completion_cycles", "MIN",
                          question=NETWORK),
                Objective("completion_cycles", "MIN",
                          question=PER_RANK),
            ),
            method="grid")

def test_required_questions_yield_each_question_once_in_order():
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(
            Objective("average_read_latency_cycles", "MIN",
                      question=DRAM),
            Objective("row_hits", "MAX", question=DRAM),
            Objective("system_makespan_cycles", "MIN",
                      question=SYSTEM),
        ),
        method="grid")
    assert required_questions(definition) == (DRAM, SYSTEM)

def test_definition_identity_and_dict_bind_the_policy():
    """Two definitions differing only in question/backend constraint
    hash differently; to_dict carries the policy losslessly."""
    plain = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("system_makespan_cycles", "MIN",
                              question=SYSTEM),),
        method="grid")
    constrained = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("system_makespan_cycles", "MIN",
                              question=SYSTEM,
                              backend_id="ASTRA2_EMBEDDED_BOOKSIM"),),
        method="grid")
    assert plain.definition_id() != constrained.definition_id()
    doc = constrained.to_dict()["objectives"][0]
    assert doc == {"metric": "system_makespan_cycles",
                   "direction": "MIN", "question": "SYSTEM_MAKESPAN",
                   "backend_id": "ASTRA2_EMBEDDED_BOOKSIM"}

def _live_port(tmp_path, *, objectives):
    return RealCandidateEvaluator(
        binary=str(find_booksim_bin(REPO)),
        run_root=str(tmp_path / "runs"), timeout_s=300,
        network_clock_hz=10 ** 9, objectives=objectives)

def test_live_astra_makespan_objective_is_measured_with_provenance(
        tmp_path):
    """Gate (live-proven): a qualified ASTRA SYSTEM_MAKESPAN leg
    measures the objective with full provenance — metric key,
    question, backend id, model fidelity, qualification, native
    evidence id, unit, value."""
    objectives = (
        Objective("system_makespan_cycles", "MIN", question=SYSTEM),
    )
    out = _live_port(tmp_path, objectives=objectives).evaluate(
        make_candidate(_base(), {"link_width": 64}))
    assert out.status == "EVALUATED"
    assert out.error is None
    value = out.objective_values["system_makespan_cycles"]
    assert isinstance(value, float) and value > 0
    prov = out.objective_provenance["system_makespan_cycles"]
    doc = prov.to_dict() if hasattr(prov, "to_dict") else dict(prov)
    assert doc["metric_key"] == "system_makespan_cycles"
    assert doc["question"] == "SYSTEM_MAKESPAN"
    assert doc["backend_id"] == "ASTRA2_EMBEDDED_BOOKSIM"
    assert doc["model_fidelity"] == \
        ModelFidelity.SYSTEM_SIMULATION.value
    assert doc["qualification"]
    assert doc["native_evidence_id"].startswith("sha256:")
    assert doc["unit"] == "cycles"
    assert doc["value"] == value
    analysis = next(a for a in out.federated_analyses
                    if a.question is SYSTEM)
    assert analysis.status == "EVALUATED"
    assert analysis.native_evidence_id == doc["native_evidence_id"]

def test_live_ramulator_without_memory_demand_is_unsupported_not_failed(
        tmp_path):
    """Gate (live-proven): workloads on this tree carry no resolvable
    COMPUTE memory demand, so the Ramulator leg assesses
    UNSUPPORTED/BLOCKED with the exact semantic reason — and a DRAM
    study keeps status UNSUPPORTED with absent (never zero, never
    failed, never infeasible) values. The UNAVAILABLE leg (demand
    resolves, extension absent) is proven scripted in
    test_federated_optimizer.py; both refusals never collapse into
    infeasible."""
    from veritx_dse.application.evaluation_context import (
        build_evaluation_context,
    )
    from veritx_dse.application.evaluation_plan import EvaluationPlanner
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.backend.adapter import BackendReadiness, SupportLevel
    from veritx_dse.backend.registry import default_backend_registry
    compilation = FabricCompiler().compile(_base())
    context = build_evaluation_context(compilation)
    registry = default_backend_registry(
        booksim_bin=str(find_booksim_bin(REPO)), repo_root=REPO)
    plan = EvaluationPlanner().plan(context, (DRAM,), registry)
    row = plan.analyses[0]
    assert row.support is SupportLevel.UNSUPPORTED
    assert row.readiness is BackendReadiness.BLOCKED
    assert row.backend_id is None
    ramulator = registry.require("RAMULATOR2_HBM3_V1")
    verdict = ramulator.assess(context, DRAM)
    assert verdict.support is SupportLevel.UNSUPPORTED
    assert verdict.readiness is BackendReadiness.BLOCKED
    assert "memory demand" in (verdict.reason or "")

    objectives = (
        Objective("average_read_latency_cycles", "MIN", question=DRAM),
    )
    out = RealCandidateEvaluator(
        binary=str(find_booksim_bin(REPO)),
        run_root=str(tmp_path / "runs"), timeout_s=60,
        network_clock_hz=10 ** 9, objectives=objectives).evaluate(
            make_candidate(_base(), {"link_width": 64}))
    assert out.status == "UNSUPPORTED"
    assert out.objective_values == {}
    assert "average_read_latency_cycles" in \
        out.objective_unmeasured_reasons

def _record(candidate_id, metric, *, question, backend, fidelity,
            qualification, unit, value, eligible=True,
            native_evidence_id="sha256:abc"):
    from veritx_dse.optimization.result import CandidateRecord
    return CandidateRecord(
        candidate_id=candidate_id, guided_patch={}, design_hash="d",
        locked_consequences={}, evaluation_status="EVALUATED",
        objective_values={metric: value},
        objective_availability={metric: "MEASURED"},
        constraint_verdicts={}, pareto_eligible=eligible,
        pareto_member=False,
        objective_provenance=({
            "metric_key": metric, "question": question,
            "backend_id": backend, "model_fidelity": fidelity,
            "qualification": qualification,
            "native_evidence_id": native_evidence_id,
            "unit": unit, "value": value},),
        eligibility_reason=None)

def _definition_for(metric, question):
    return OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective(metric, "MIN", question=question),),
        method="grid")

def test_booksim_completion_vs_astra_makespan_never_share_an_axis():
    """Different semantic families never compare merely because both
    use cycles: a divergent question demotes with a MODEL DIFFERENCE
    reason instead of a delta."""
    from veritx_dse.optimization.result import (
        _enforce_federated_comparability,
    )
    definition = _definition_for("completion_cycles", NETWORK)
    records = [
        _record("c1", "completion_cycles", question="NETWORK_COMPLETION",
                backend="BOOKSIM_STANDALONE",
                fidelity="NETWORK_PACKET_SIMULATION",
                qualification="QUALIFIED", unit=None, value=100.0),
        _record("c2", "completion_cycles", question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="SYSTEM_SIMULATION",
                qualification="ASTRA_OWNED_COLLECTIVE_EXECUTION",
                unit="cycles", value=90.0),
    ]
    out = {r.candidate_id: r for r in
           _enforce_federated_comparability(records, definition)}
    assert out["c1"].pareto_eligible is True
    assert out["c2"].pareto_eligible is False
    assert "SYSTEM_MAKESPAN" in (out["c2"].eligibility_reason or "")
    assert "NETWORK_COMPLETION" in (out["c2"].eligibility_reason or "")

def test_fidelity_divergence_demotes_with_model_difference():
    from veritx_dse.optimization.result import (
        _enforce_federated_comparability,
    )
    definition = _definition_for("system_makespan_cycles", SYSTEM)
    records = [
        _record("c1", "system_makespan_cycles",
                question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="SYSTEM_SIMULATION",
                qualification="Q", unit="cycles", value=100.0),
        _record("c2", "system_makespan_cycles",
                question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="FULL_SYSTEM_SIMULATION",
                qualification="Q", unit="cycles", value=90.0),
    ]
    out = {r.candidate_id: r for r in
           _enforce_federated_comparability(records, definition)}
    assert out["c1"].pareto_eligible is True
    assert out["c2"].pareto_eligible is False
    assert "MODEL DIFFERENCE" in (out["c2"].eligibility_reason or "")

def test_qualification_and_unit_divergence_demotes():
    from veritx_dse.optimization.result import (
        _enforce_federated_comparability,
    )
    definition = _definition_for("system_makespan_cycles", SYSTEM)
    records = [
        _record("c1", "system_makespan_cycles",
                question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="SYSTEM_SIMULATION",
                qualification="QUALIFIED-A", unit="cycles",
                value=100.0),
        _record("c2", "system_makespan_cycles",
                question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="SYSTEM_SIMULATION",
                qualification="QUALIFIED-B", unit="cycles",
                value=90.0),
    ]
    out = {r.candidate_id: r for r in
           _enforce_federated_comparability(records, definition)}
    assert out["c2"].pareto_eligible is False
    assert out["c2"].eligibility_reason

def test_matching_provenance_compares():
    """The control: identical question/backend/fidelity/qualification/
    unit/native-evidence across the eligible set demotes nothing."""
    from veritx_dse.optimization.result import (
        _enforce_federated_comparability,
    )
    definition = _definition_for("system_makespan_cycles", SYSTEM)
    records = [
        _record("c1", "system_makespan_cycles",
                question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="SYSTEM_SIMULATION",
                qualification="Q", unit="cycles", value=100.0),
        _record("c2", "system_makespan_cycles",
                question="SYSTEM_MAKESPAN",
                backend="ASTRA2_EMBEDDED_BOOKSIM",
                fidelity="SYSTEM_SIMULATION",
                qualification="Q", unit="cycles", value=90.0),
    ]
    out = list(_enforce_federated_comparability(records, definition))
    assert all(r.pareto_eligible for r in out)

def test_catalog_backends_come_from_the_registry():
    """Available backends per question are read from the registry's
    own adapters — a scripted registry changes the answer, proving
    no second handwritten matrix."""
    from veritx_dse.backend.registry import BackendRegistry
    from veritx_dse.optimization.metric_registry import (
        federated_metric_catalog,
    )

    class _OnlyDram:
        backend_id = "SCRIPTED_DRAM"
        def capabilities(self):
            from veritx_dse.backend.adapter import (
                BackendCapability, SupportLevel,
            )
            return (BackendCapability(
                question=DRAM, support=SupportLevel.SUPPORTED,
                fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION),)

    rows = federated_metric_catalog(
        registry=BackendRegistry((_OnlyDram(),)))
    by_question = {}
    for row in rows:
        by_question.setdefault(row.question, set()).update(
            row.backends)
    assert by_question["DRAM_TIMING"] == {"SCRIPTED_DRAM"}
    assert by_question["NETWORK_COMPLETION"] == set()
    assert by_question["SYSTEM_MAKESPAN"] == set()

def test_catalog_mirrors_producer_tables():
    """Metric rows mirror the producers' single-source tables: every
    ASTRA table entry and every Ramulator key appears exactly once
    for its question."""
    from veritx_dse.backend.astra_adapter import (
        ASTRA_NORMALIZED_METRICS,
    )
    from veritx_dse.backend.ramulator_adapter import (
        RAMULATOR_NORMALIZED_METRICS,
    )
    from veritx_dse.optimization.metric_registry import (
        federated_metric_catalog,
    )
    rows = federated_metric_catalog()
    for question in (EvaluationQuestion.SYSTEM_MAKESPAN,
                     EvaluationQuestion.COMMUNICATION_EXPOSURE,
                     EvaluationQuestion.PER_RANK_COMPLETION):
        expected = {key for key, _, _ in
                    ASTRA_NORMALIZED_METRICS[question]}
        got = {r.metric for r in rows
               if r.question == question.value}
        assert got == expected, question.value
    got_dram = {r.metric for r in rows
                if r.question == DRAM.value}
    assert got_dram == set(RAMULATOR_NORMALIZED_METRICS)

def test_dimensioned_rows_are_honestly_ineligible():
    """Per-rank / per-request rows can never be scalar objectives —
    the catalog says so instead of inventing key suffixes."""
    from veritx_dse.optimization.metric_registry import (
        federated_metric_catalog,
    )
    rows = {(r.question, r.metric): r
            for r in federated_metric_catalog()}
    per_rank = rows[("PER_RANK_COMPLETION", "completion_cycles")]
    assert per_rank.scalar_bindable is False
    assert per_rank.optimization_eligible is False
    assert per_rank.reason
    serving = rows[("SERVING_TTFT", "ttft_cycles")]
    assert serving.optimization_eligible is False
    assert serving.backends == ("CANONICAL_SERVING",)

def test_capabilities_publish_the_federated_truth():
    """The product capability payload carries the federated rows with
    metric, family, question, backends, fidelity, unit, eligibility."""
    from veritx_dse.optimization.capabilities import (
        optimization_capabilities,
    )
    payload = optimization_capabilities()
    rows = payload["federated_metrics"]
    assert rows
    makespan = next(r for r in rows
                    if r["metric"] == "system_makespan_cycles")
    assert makespan["question"] == "SYSTEM_MAKESPAN"
    assert makespan["backends"] == ["ASTRA2_EMBEDDED_BOOKSIM"]
    assert makespan["fidelity"] == "SYSTEM_SIMULATION"
    assert makespan["unit"] == "cycles"
    assert makespan["optimization_eligible"] is True
    assert makespan["semantic_family"] == \
        "SYSTEM_MAKESPAN:system_makespan_cycles"
