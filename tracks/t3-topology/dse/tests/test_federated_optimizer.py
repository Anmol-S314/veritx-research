"""PROMPT 4 — candidates evaluated through the federation.

Routing, sharing, provenance and failure-taxonomy laws for
``RealCandidateEvaluator``: compile once, plan once, one execution per
required question (objectives only read), every objective value with
its provenance, and an UNAVAILABLE backend stays unavailable — never
infeasible.

Live-backend honesty: BookSim is BLOCKED on a dirty producer tree and
the Ramulator extension is absent, so live execution legs cannot run
here. Orchestration laws are proven with scripted adapters carrying
the certified backend ids (the established product-federation test
pattern); the one live leg on this tree (ASTRA) is proven live in
test_multi_fidelity_objectives.py. Nothing here executes a real
simulator and then calls it something else.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAssessment, BackendCapability, BackendReadiness, ModelFidelity,
    PreparedExecution, SupportLevel,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence,
)
from veritx_dse.backend.registry import BackendRegistry  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    Agent, AgentKind, CollectiveDimension, CollectiveIntent,
    CollectiveKind, CompileRequestV3, DependencyGraph, ModelFamily,
    NocConfig, QoSClass, RequirementV3, TopologyFamily, WorkloadV3,
)
from veritx_dse.optimization.candidate import make_candidate  # noqa: E402
from veritx_dse.optimization.definition import (  # noqa: E402
    DomainParam, Objective, OptimizationDefinition, required_questions,
)
from veritx_dse.optimization.evaluators import (  # noqa: E402
    AUTHORITY_CERTIFIED_BACKEND, CandidateEvaluation, ObjectiveProvenance,
)
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    RealCandidateEvaluator,
)
from veritx_dse.optimization.result import Optimizer  # noqa: E402
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN
EXPOSURE = EvaluationQuestion.COMMUNICATION_EXPOSURE
DRAM = EvaluationQuestion.DRAM_TIMING

SCRIPTED_METRICS = {
    SYSTEM: (("system_makespan_cycles", 6070.0, "cycles"),),
    EXPOSURE: (("communication_exposure_cycles", 1200.0, "cycles"),),
    DRAM: (("average_read_latency_cycles", 42.0, "cycles"),
           ("row_hits", 900.0, None)),
}

SCRIPTED_FIDELITY = {
    SYSTEM: ModelFidelity.SYSTEM_SIMULATION,
    EXPOSURE: ModelFidelity.SYSTEM_SIMULATION,
    DRAM: ModelFidelity.MEMORY_CYCLE_SIMULATION,
}

SCRIPTED_BACKEND = {
    SYSTEM: "ASTRA2_EMBEDDED_BOOKSIM",
    EXPOSURE: "ASTRA2_EMBEDDED_BOOKSIM",
    DRAM: "RAMULATOR2_HBM3_V1",
}

class _ScriptedFederatedAdapter:
    """Deterministic orchestration double under a certified backend id.

    Answers its questions READY with fixed scalar envelopes so the
    routing/sharing/provenance laws can be proven without live
    simulators. The envelope is openly scripted (qualification
    "SCRIPTED"); no test presents these numbers as measurements.
    """

    def __init__(self, backend_id, questions, *,
                 readiness=BackendReadiness.READY,
                 reason=None):
        self._id = backend_id
        self._questions = tuple(questions)
        self._readiness = readiness
        self._reason = reason
        self.executed: list[EvaluationQuestion] = []

    @property
    def backend_id(self) -> str:
        return self._id

    def capabilities(self):
        return tuple(
            BackendCapability(
                question=q, support=SupportLevel.SUPPORTED,
                fidelity=SCRIPTED_FIDELITY[q])
            for q in self._questions)

    def assess(self, context, question):
        if question not in self._questions:
            return BackendAssessment(
                backend_id=self._id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ModelFidelity.SYSTEM_SIMULATION,
                qualification_profile=None,
                reason=f"{self._id} answers "
                f"{[q.value for q in self._questions]} only",
                required_parents=("design",),
                limitations=())
        return BackendAssessment(
            backend_id=self._id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=self._readiness,
            fidelity=SCRIPTED_FIDELITY[question],
            qualification_profile="SCRIPTED",
            reason=self._reason,
            required_parents=("design",),
            limitations=())

    def prepare(self, context, question, **kwargs):
        return PreparedExecution(
            backend_id=self._id, projection_identity="wp-scripted",
            qualification_identity="m-scripted",
            backend_config=None, backend_input=None, producer=None,
            native_prepared=SimpleNamespace(marker=question))

    def execute(self, prepared, options):
        question = prepared.native_prepared.marker
        self.executed.append(question)
        return SimpleNamespace(
            question=question, status="PASS",
            metrics={}, failure_reason=None,
            evidence_tier="SCRIPTED_TIER",
            expansion_authority="scripted",
            autonomous_injection_packets=0,
            participant_statistics_present=True,
            namespace_binding="SCRIPTED", namespace_id="ns-scripted",
            rank_to_endpoint=((0, 0), (1, 1)),
            aggregate_cycles=1000, aggregate_exposed_comm=100)

    def normalize(self, context, question, prepared, native_result):
        resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = resolved() if callable(resolved) else resolved
        fidelity = SCRIPTED_FIDELITY[question]
        return NormalizedBackendEvidence(
            backend_id=self._id, question=question,
            model_fidelity=fidelity,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id, "wp-scripted"),
            native_evidence_id=f"native-{self._id}-{question.value}",
            qualification="SCRIPTED",
            producer_identity="s" * 64,
            metrics=tuple(
                MetricValue(key=key, value=value, unit=unit,
                            source_metric_key=key)
                for key, value, unit in SCRIPTED_METRICS[question]),
            limitations=())

def _scripted_registry(**overrides):
    astra_kw = dict(overrides.get("astra", {}))
    dram_kw = dict(overrides.get("dram", {}))
    astra = _ScriptedFederatedAdapter(
        "ASTRA2_EMBEDDED_BOOKSIM", (SYSTEM, EXPOSURE), **astra_kw)
    dram = _ScriptedFederatedAdapter(
        "RAMULATOR2_HBM3_V1", (DRAM,), **dram_kw)
    return BackendRegistry((astra, dram)), astra, dram

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

def _port(tmp_path, *, objectives=None, registry=None, **kw):
    kw.setdefault("network_clock_hz", 10 ** 9)
    binary = kw.pop("binary", str(find_booksim_bin(REPO)))
    return RealCandidateEvaluator(
        binary=binary,
        run_root=str(tmp_path / "runs"), timeout_s=120,
        objectives=objectives, registry=registry, **kw)

def test_legacy_bare_objective_means_network_completion_only():
    """A bare Objective keeps its legacy meaning: the study executes
    exactly NETWORK_COMPLETION (BookSim-only study unchanged)."""
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),),
        method="grid")
    objective = definition.objectives[0]
    assert objective.question is NETWORK
    assert objective.backend_id is None
    assert required_questions(definition) == (NETWORK,)

def test_booksim_only_study_plans_one_network_analysis(tmp_path):
    """Routing law without a live binary: a legacy study plans exactly
    one NETWORK_COMPLETION analysis, and with no usable backend the
    candidate keeps the exact refusal taxonomy (never a fabrication,
    never infeasible)."""
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),),
        method="grid")
    port = _port(tmp_path, objectives=definition.objectives,
                 binary="/no-such-booksim")
    assert port._resolve_questions() == (NETWORK,)
    out = port.evaluate(make_candidate(_base(), {"link_width": 64}))
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.evaluation_authority == AUTHORITY_CERTIFIED_BACKEND
    assert len(out.federated_analyses) == 1
    assert out.federated_analyses[0].question is NETWORK
    assert out.objective_values == {}

def test_two_objectives_over_dram_timing_share_one_run(tmp_path):
    """Sharing law: two objectives reading DRAM_TIMING execute the
    Ramulator leg exactly once; both values come from that one
    envelope, each with full provenance."""
    registry, astra, dram = _scripted_registry()
    objectives = (
        Objective("average_read_latency_cycles", "MIN", question=DRAM),
        Objective("row_hits", "MAX", question=DRAM),
        Objective("system_makespan_cycles", "MIN", question=SYSTEM),
    )
    port = _port(tmp_path, objectives=objectives, registry=registry)
    assert port._resolve_questions() == (DRAM, SYSTEM)
    out = port.evaluate(make_candidate(_base(), {"link_width": 64}))
    assert [q for q in dram.executed] == [DRAM]
    assert [q for q in astra.executed] == [SYSTEM]
    assert out.status == "EVALUATED"
    assert out.objective_values == {
        "average_read_latency_cycles": 42.0,
        "row_hits": 900.0,
        "system_makespan_cycles": 6070.0,
    }
    for metric, question, backend, fidelity in (
            ("average_read_latency_cycles", DRAM,
             "RAMULATOR2_HBM3_V1", "MEMORY_CYCLE_SIMULATION"),
            ("row_hits", DRAM,
             "RAMULATOR2_HBM3_V1", "MEMORY_CYCLE_SIMULATION"),
            ("system_makespan_cycles", SYSTEM,
             "ASTRA2_EMBEDDED_BOOKSIM", "SYSTEM_SIMULATION")):
        prov = out.objective_provenance[metric]
        doc = prov.to_dict() if hasattr(prov, "to_dict") else dict(prov)
        assert doc["metric_key"] == metric
        assert doc["question"] == question.value
        assert doc["backend_id"] == backend
        assert doc["model_fidelity"] == fidelity
        assert doc["qualification"] == "SCRIPTED"
        assert doc["native_evidence_id"] == \
            f"native-{backend}-{question.value}"
        assert doc["value"] == out.objective_values[metric]

def test_same_candidate_compiles_once_per_evaluation(tmp_path,
                                                     monkeypatch):
    """The candidate compiles once no matter how many questions or
    objectives the study reads."""
    from veritx_dse.application import fabric_compiler
    calls = []
    real = fabric_compiler.FabricCompiler.compile
    def _count(self, request):
        calls.append(request.design_hash())
        return real(self, request)
    monkeypatch.setattr(
        fabric_compiler.FabricCompiler, "compile", _count)
    registry, _, _ = _scripted_registry()
    objectives = (
        Objective("average_read_latency_cycles", "MIN", question=DRAM),
        Objective("row_hits", "MAX", question=DRAM),
        Objective("system_makespan_cycles", "MIN", question=SYSTEM),
        Objective("communication_exposure_cycles", "MIN",
                  question=EXPOSURE),
    )
    port = _port(tmp_path, objectives=objectives, registry=registry)
    port.evaluate(make_candidate(_base(), {"link_width": 64}))
    assert len(calls) == 1

def test_backend_constraint_mismatch_is_unmeasured_never_substituted(
        tmp_path):
    """An objective constrained to a backend the planner did not
    select is unmeasured with the exact reason — never silently read
    from another backend's evidence."""
    registry, _, _ = _scripted_registry()
    objectives = (
        Objective("system_makespan_cycles", "MIN", question=SYSTEM,
                  backend_id="SOME_OTHER_BACKEND"),
    )
    port = _port(tmp_path, objectives=objectives, registry=registry)
    out = port.evaluate(make_candidate(_base(), {"link_width": 64}))
    assert "system_makespan_cycles" not in out.objective_values
    reason = out.objective_unmeasured_reasons["system_makespan_cycles"]
    assert "SOME_OTHER_BACKEND" in reason
    assert "never substituted" in reason

def test_unavailable_memory_backend_is_unavailable_not_infeasible(
        tmp_path):
    """An UNAVAILABLE Ramulator leg keeps BACKEND_UNAVAILABLE through
    the port and the Optimizer: visible, out of Pareto, with a typed
    reason — never collapsed into infeasible/failed/unsupported."""
    registry, _, _ = _scripted_registry(
        dram={"readiness": BackendReadiness.UNAVAILABLE,
              "reason": "scripted extension absent"})
    objectives = (
        Objective("average_read_latency_cycles", "MIN", question=DRAM),
    )
    port = _port(tmp_path, objectives=objectives, registry=registry)
    out = port.evaluate(make_candidate(_base(), {"link_width": 64}))
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.objective_values == {}
    assert "average_read_latency_cycles" in \
        out.objective_unmeasured_reasons

    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=objectives, method="grid")
    result = Optimizer().optimize_with_port(_base(), definition, port)
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    for record in result.records:
        assert record.evaluation_status == "BACKEND_UNAVAILABLE"
        assert record.pareto_eligible is False
        assert "BACKEND_UNAVAILABLE" in (record.eligibility_reason or "")
        assert record.constraint_verdicts == {}
        assert record.objective_availability[
            "average_read_latency_cycles"] == "UNMEASURABLE"

def test_inconclusive_native_drain_is_inconclusive(tmp_path):
    """A native verdict that drained without deciding (Ramulator
    INCONCLUSIVE) surfaces as INCONCLUSIVE — never a crash, never a
    refusal, never infeasible."""
    class _InconclusiveDram(_ScriptedFederatedAdapter):
        def execute(self, prepared, options):
            question = prepared.native_prepared.marker
            self.executed.append(question)
            return SimpleNamespace(
                question=question, status="INCONCLUSIVE",
                producer="scripted",
                fidelity="MEMORY_CYCLE_SIMULATION",
                memory_artifact_hash="m", lowering_manifest_hash="l",
                backend_input_hash="i", backend_config_hash="c",
                metrics={}, assumptions=[], semantic_losses=[],
                failure_reason="drained without deciding")
    dram = _InconclusiveDram("RAMULATOR2_HBM3_V1", (DRAM,))
    registry = BackendRegistry((dram,))
    objectives = (
        Objective("average_read_latency_cycles", "MIN", question=DRAM),
    )
    port = _port(tmp_path, objectives=objectives, registry=registry)
    out = port.evaluate(make_candidate(_base(), {"link_width": 64}))
    assert out.status == "INCONCLUSIVE"
    assert "INCONCLUSIVE" in (out.error or "")
    assert out.objective_values == {}

class _ProvenanceStubPort:
    """Analytic port carrying real ObjectiveProvenance rows (no
    certified claims, so the analytic entry point accepts it)."""

    def __init__(self, values, provenance):
        self.values = values
        self.provenance = provenance

    def evaluate(self, candidate):
        from veritx_dse.optimization.evaluators import (
            AUTHORITY_ANALYTIC_FAKE,
        )
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values=dict(self.values),
            locked_consequences={},
            evaluation_authority=AUTHORITY_ANALYTIC_FAKE,
            objective_provenance=dict(self.provenance))

def test_objective_provenance_survives_into_study_view():
    """A float without provenance is not an optimizer objective: bound
    values carry their provenance rows through to the study view."""
    provenance = {
        "system_makespan_cycles": ObjectiveProvenance(
            metric_key="system_makespan_cycles", question=SYSTEM,
            backend_id="ASTRA2_EMBEDDED_BOOKSIM",
            model_fidelity="SYSTEM_SIMULATION",
            qualification="SCRIPTED",
            native_evidence_id="native-ASTRA2_EMBEDDED_BOOKSIM-"
            "SYSTEM_MAKESPAN",
            unit="cycles", value=6070.0),
    }
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("system_makespan_cycles", "MIN",
                              question=SYSTEM),),
        method="grid")
    result = Optimizer().optimize_with_port(
        _base(), definition,
        _ProvenanceStubPort({"system_makespan_cycles": 6070.0},
                            provenance))
    view = result.to_study_view()
    assert view["contract_version"] == 2
    for candidate in view["candidates"]:
        rows = candidate["objective_provenance"]
        assert rows == [{
            "metric_key": "system_makespan_cycles",
            "question": "SYSTEM_MAKESPAN",
            "backend_id": "ASTRA2_EMBEDDED_BOOKSIM",
            "model_fidelity": "SYSTEM_SIMULATION",
            "qualification": "SCRIPTED",
            "native_evidence_id":
                "native-ASTRA2_EMBEDDED_BOOKSIM-SYSTEM_MAKESPAN",
            "unit": "cycles",
            "value": 6070.0,
        }]
    assert view["definition"]["objectives"] == [{
        "metric": "system_makespan_cycles", "direction": "MIN",
        "question": "SYSTEM_MAKESPAN", "backend_id": None}]
