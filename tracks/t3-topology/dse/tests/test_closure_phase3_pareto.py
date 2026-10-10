"""Phase-3 Pareto eligibility law (backend-neutral, RC-08).

Every test here drives Optimizer._optimize_core with doubles that carry
explicit federated analyses — no live backend, no proof bypass. A
non-network study is eligible iff: EVALUATED + certified authority +
every objective MEASURED from authentic per-question evidence (EVALUATED
analysis with envelope, qualification and native evidence id) + every
hard constraint SATISFIED under single-source resolution + the
product-requirement leg satisfied under applicability (binding
APPLICABLE/NOT_EVALUATED requirements demand a bound, passing report;
with no such requirements the leg is vacuously satisfied — absence of
a network leg never invalidates a study on its own).
"""
from __future__ import annotations

import dataclasses

import pytest

from test_p2_real_adapter import _base as _real_base

from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import ModelFidelity
from veritx_dse.backend.normalized_evidence import (
    MetricValue,
    NormalizedBackendEvidence,
)
from veritx_dse.model.compile_model import (
    QoSClass,
    RequirementApplicability,
    RequirementV3,
)
from veritx_dse.optimization.definition import (
    Constraint,
    DomainParam,
    Objective,
    OptimizationDefinition,
)
from veritx_dse.optimization.evaluators import (
    AUTHORITY_CERTIFIED_BACKEND,
    CandidateEvaluation,
    ObjectiveProvenance,
)
from veritx_dse.optimization.result import Optimizer

SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN
DRAM = EvaluationQuestion.DRAM_TIMING

def _metric(key, value, unit="cycles"):
    return MetricValue(key=key, value=float(value), unit=unit,
                       source_metric_key=key, dimensions=())

def _row(question, backend, metric, value, *,
         status="EVALUATED", native="sha256:" + "ab" * 32,
         qualification="QUALIFIED-SCRIPTED",
         fidelity=ModelFidelity.SYSTEM_SIMULATION, unit="cycles"):
    from types import SimpleNamespace
    envelope = NormalizedBackendEvidence(
        backend_id=backend, question=question,
        model_fidelity=fidelity,
        canonical_parent_ids=("sha256:" + "cd" * 32,),
        native_evidence_id=native, qualification=qualification,
        producer_identity="scripted-producer",
        metrics=(_metric(metric, value, unit),))
    return SimpleNamespace(
        question=question, backend_id=backend, status=status,
        model_fidelity=fidelity, qualification=qualification,
        normalized_evidence=envelope, native_evidence_id=native,
        reason=None if status == "EVALUATED" else "scripted refusal")

def _prov(metric, question, backend, value, *,
          native="sha256:" + "ab" * 32,
          qualification="QUALIFIED-SCRIPTED",
          fidelity=ModelFidelity.SYSTEM_SIMULATION, unit="cycles"):
    return ObjectiveProvenance(
        metric_key=metric, question=question, backend_id=backend,
        model_fidelity=(fidelity.value if hasattr(fidelity, "value")
                        else fidelity),
        qualification=qualification, native_evidence_id=native,
        unit=unit, value=float(value))

class _FederatedStubPort:
    """Certified double with explicit per-question evidence rows."""

    def __init__(self, values, rows, *, provenance=(),
                 report=None, perf=None):
        self.values = dict(values)
        self.rows = list(rows)
        self.provenance = dict(provenance)
        self.report = report
        self.perf = perf

    def evaluate(self, candidate):
        from veritx_dse.application.requirements import report_identity
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values=dict(self.values),
            locked_consequences={},
            performance_result_id=self.perf,
            requirement_report=self.report,
            requirement_report_id=(
                report_identity(self.report)
                if self.report is not None else None),
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
            federated_analyses=tuple(self.rows),
            objective_provenance=dict(self.provenance))

def _no_binding_base():
    base = _real_base()
    return dataclasses.replace(base, requirements=())

def _defn(*objectives, constraints=()):
    return OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=tuple(objectives), constraints=tuple(constraints),
        method="grid")

def _run(base, definition, port):
    return Optimizer()._optimize_core(
        base, definition, port, accept_certified_claims=True)

def test_astra_only_study_is_eligible_without_network_proof():
    """ASTRA-only: no performance_result_id, no report, no network leg
    — eligible on authentic SYSTEM_MAKESPAN evidence alone."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                 "system_makespan_cycles", 150.0)]
    port = _FederatedStubPort(
        {"system_makespan_cycles": 150.0}, rows,
        provenance={"system_makespan_cycles": _prov(
            "system_makespan_cycles", SYSTEM,
            "ASTRA2_EMBEDDED_BOOKSIM", 150.0)})
    result = _run(_no_binding_base(), definition, port)
    assert result.pareto_ids
    record = result.records[0]
    assert record.pareto_eligible is True
    assert record.eligibility_reason is None
    assert "performance_result_id" not in \
        (record.eligibility_reason or "")
    docs = {d["metric_key"]: d for d in record.objective_provenance}
    assert docs["system_makespan_cycles"]["native_evidence_id"] == \
        "sha256:" + "ab" * 32

def test_ramulator_only_study_is_eligible_without_network_proof():
    """Ramulator-only: eligible on authentic DRAM_TIMING evidence."""
    definition = _defn(Objective("average_read_latency_cycles", "MIN",
                                 question=DRAM))
    rows = [_row(DRAM, "RAMULATOR2_HBM3_V1",
                 "average_read_latency_cycles", 42.0,
                 fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION)]
    port = _FederatedStubPort(
        {"average_read_latency_cycles": 42.0}, rows,
        provenance={"average_read_latency_cycles": _prov(
            "average_read_latency_cycles", DRAM,
            "RAMULATOR2_HBM3_V1", 42.0,
            fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION)})
    result = _run(_no_binding_base(), definition, port)
    assert result.pareto_ids
    assert result.records[0].pareto_eligible is True

def test_binding_network_requirement_blocks_unevaluated_astra_study():
    """A network binding requirement the study never asks about stays
    visibly unevaluated WITHOUT poisoning Pareto eligibility: the ASTRA
    leg carries authentic evidence, so the candidate is eligible while
    product_requirements_satisfied stays None (never True) and the
    reason never blames a missing network id."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                 "system_makespan_cycles", 150.0)]
    port = _FederatedStubPort({"system_makespan_cycles": 150.0}, rows)
    result = _run(_real_base(), definition, port)
    assert result.pareto_ids != ()
    assert result.records[0].product_requirements_satisfied is None
    reason = result.records[0].eligibility_reason or ""
    assert "performance_result_id" not in reason

def test_out_of_scope_binding_requirement_is_recorded_not_absent():
    """RC-08(ii): an ASTRA-only study whose only applicable binding
    requirement answers NETWORK_COMPLETION passes the requirement leg —
    but the out-of-scope requirement is RECORDED on the candidate record
    (position + scope + QoS), never silently absent, while the candidate
    stays Pareto-eligible."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                 "system_makespan_cycles", 150.0)]
    port = _FederatedStubPort({"system_makespan_cycles": 150.0}, rows)
    result = _run(_real_base(), definition, port)
    record = result.records[0]
    assert record.pareto_eligible is True
    assert result.pareto_ids != ()
    assert record.out_of_scope_requirement_ids == (
        "requirements[0]:tp_collective/latency_critical",)

def test_no_binding_requirement_is_recorded_as_empty_scope():
    """The companion fact: a study with no applicable binding
    requirement records an empty (never omitted) out-of-scope set, so
    "nothing was required" and "everything was out of scope" are
    distinguishable recorded states."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                 "system_makespan_cycles", 150.0)]
    port = _FederatedStubPort({"system_makespan_cycles": 150.0}, rows)
    result = _run(_no_binding_base(), definition, port)
    assert result.pareto_ids != ()
    assert result.records[0].out_of_scope_requirement_ids == ()

def test_non_network_value_without_qualification_never_reaches_pareto():
    """RC-08/RC-12: an EVALUATED non-network candidate whose analysis
    carries an envelope but no qualification / native evidence id is
    ineligible with a typed reason naming the missing evidence — a
    finite value without bound evidence is never an objective."""
    from types import SimpleNamespace
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    evidenced = _row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                     "system_makespan_cycles", 150.0)
    unbound = SimpleNamespace(
        question=evidenced.question, backend_id=evidenced.backend_id,
        status="EVALUATED", model_fidelity=evidenced.model_fidelity,
        qualification=None,
        normalized_evidence=evidenced.normalized_evidence,
        native_evidence_id=None, reason=None)
    port = _FederatedStubPort({"system_makespan_cycles": 150.0},
                              [unbound])
    result = _run(_no_binding_base(), definition, port)
    assert result.pareto_ids == ()
    record = result.records[0]
    assert record.pareto_eligible is False
    reason = record.eligibility_reason or ""
    assert "no authentic" in reason
    assert "qualification" in reason
    assert "native evidence id" in reason

def test_explicit_not_evaluated_mark_never_passes():
    """A binding requirement marked NOT_EVALUATED keeps the candidate
    out of Pareto even when every measurement exists."""
    base = _real_base()
    req = RequirementV3(
        qos_class=QoSClass.LATENCY_CRITICAL,
        traffic_class="tp_collective",
        latency_ceiling_cycles=10 ** 9, binding=True,
        applicability=RequirementApplicability.NOT_EVALUATED)
    base = dataclasses.replace(base, requirements=(req,))
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                 "system_makespan_cycles", 150.0)]
    port = _FederatedStubPort({"system_makespan_cycles": 150.0}, rows)
    result = _run(base, definition, port)
    assert result.pareto_ids == ()
    assert "NOT_EVALUATED" in (result.records[0].eligibility_reason or "")

def test_binding_without_bound_refuses_at_construction():
    """A binding requirement that binds nothing is refused, and a
    declared bound cannot be waived via NOT_APPLICABLE."""
    with pytest.raises(ValueError):
        RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL, binding=True)
    with pytest.raises(ValueError):
        RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                      latency_ceiling_cycles=100.0, binding=True,
                      applicability="NOT_APPLICABLE")
    with pytest.raises(ValueError):
        RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                      latency_ceiling_cycles=100.0,
                      applicability="BOGUS")
    waived = RequirementV3(qos_class=QoSClass.BEST_EFFORT,
                           applicability="NOT_APPLICABLE")
    assert waived.applicability is RequirementApplicability.NOT_APPLICABLE
    assert "applicability" not in _real_base().requirements[0].to_dict()
    assert waived.to_dict()["applicability"] == "NOT_APPLICABLE"

def test_mixed_study_needs_every_evidence_family():
    """SYSTEM + DRAM objectives: one family evidenced is not enough —
    the missing family stays UNMEASURABLE and blocks Pareto."""
    definition = _defn(
        Objective("system_makespan_cycles", "MIN", question=SYSTEM),
        Objective("average_read_latency_cycles", "MIN", question=DRAM))
    partial = _FederatedStubPort(
        {"system_makespan_cycles": 150.0},
        [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
              "system_makespan_cycles", 150.0)])
    result = _run(_no_binding_base(), definition, partial)
    assert result.pareto_ids == ()
    availability = result.records[0].objective_availability
    assert availability["average_read_latency_cycles"] == "UNMEASURABLE"
    assert "average_read_latency_cycles" not in \
        result.records[0].objective_values
    full = _FederatedStubPort(
        {"system_makespan_cycles": 150.0,
         "average_read_latency_cycles": 42.0},
        [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
              "system_makespan_cycles", 150.0),
         _row(DRAM, "RAMULATOR2_HBM3_V1",
              "average_read_latency_cycles", 42.0,
              fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION)],
        provenance={
            "system_makespan_cycles": _prov(
                "system_makespan_cycles", SYSTEM,
                "ASTRA2_EMBEDDED_BOOKSIM", 150.0),
            "average_read_latency_cycles": _prov(
                "average_read_latency_cycles", DRAM,
                "RAMULATOR2_HBM3_V1", 42.0,
                fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION)})
    result = _run(_no_binding_base(), definition, full)
    assert result.pareto_ids
    assert result.records[0].pareto_eligible is True

def test_missing_objective_is_never_zero_filled():
    """An objective the evidence does not carry is UNMEASURABLE with a
    typed reason — absent metrics remain absent."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    port = _FederatedStubPort({}, [])
    result = _run(_no_binding_base(), definition, port)
    record = result.records[0]
    assert record.pareto_eligible is False
    assert record.objective_availability["system_makespan_cycles"] == \
        "UNMEASURABLE"
    assert "system_makespan_cycles" not in record.objective_values
    assert "no authentic" in (record.eligibility_reason or "")

def test_fidelity_mismatch_demotes_the_axis():
    """Two candidates with different fidelity signatures for one axis
    do not share Pareto: the divergent one demotes with the exact
    MODEL DIFFERENCE."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))

    def port_for(fidelity, qualification, value):
        rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                     "system_makespan_cycles", value,
                     qualification=qualification, fidelity=fidelity)]
        return _FederatedStubPort(
            {"system_makespan_cycles": value}, rows,
            provenance={"system_makespan_cycles": _prov(
                "system_makespan_cycles", SYSTEM,
                "ASTRA2_EMBEDDED_BOOKSIM", value,
                qualification=qualification, fidelity=fidelity)})

    from veritx_dse.optimization.result import (
        _enforce_federated_comparability,
    )
    import dataclasses as _dc
    base = _no_binding_base()
    records = []
    for ident, cand_value, fidelity in (
            ("c1", 150.0, ModelFidelity.SYSTEM_SIMULATION),
            ("c2", 140.0, ModelFidelity.MEMORY_CYCLE_SIMULATION)):
        result = _run(base, definition,
                      port_for(fidelity, "QUALIFIED-SCRIPTED",
                               cand_value))
        assert result.records[0].pareto_eligible is True
        records.append(_dc.replace(result.records[0],
                                   candidate_id=ident))
    out = {r.candidate_id: r for r in
           _enforce_federated_comparability(list(records), definition)}
    demoted = [r for r in out.values() if not r.pareto_eligible]
    assert len(demoted) == 1
    assert "MODEL DIFFERENCE" in (demoted[0].eligibility_reason or "")

def test_fake_native_evidence_is_refused():
    """A fake: native evidence id never reaches Pareto, and a fake
    network result id is refused where a network leg ran."""
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                 "system_makespan_cycles", 150.0,
                 native="fake:scripted")]
    port = _FederatedStubPort({"system_makespan_cycles": 150.0}, rows)
    result = _run(_no_binding_base(), definition, port)
    assert result.pareto_ids == ()
    assert "fake" in (result.records[0].eligibility_reason or "")

def test_transplanted_report_is_refused_not_bound():
    """A report naming another design is a forgery refusal, not an
    eligibility verdict."""
    from veritx_dse.optimization.result import OptimizationResultError
    definition = _defn(Objective("system_makespan_cycles", "MIN",
                                 question=SYSTEM))
    foreign = "ab" * 32
    report = {
        "contract_version": 1,
        "design_hash": "sha256:" + foreign,
        "performance_result_id": "perf:x",
        "entries": [{
            "requirement_index": 0,
            "traffic_class": "tp_collective",
            "qos_class": "latency_critical",
            "verdict": "SATISFIED",
            "binding": True,
            "required": 600.0,
            "measured": 10.0,
            "metric_authority": "test",
            "performance_result_id": "perf:x",
            "reason": "forged",
        }],
    }
    port = _FederatedStubPort({"system_makespan_cycles": 150.0},
                              [], report=report, perf="perf:x")
    with pytest.raises(OptimizationResultError):
        _run(_no_binding_base(), definition, port)

def test_analytical_only_study_is_ineligible_for_certified_pareto():
    """A makespan-only study exercises the analytical (non-measured)
    registry path: UNMEASURABLE with the model-output reason, never
    Pareto — zero backend measurement cannot mint certification."""
    from p2_verified_support import certified_evaluation
    from veritx_dse.optimization.evaluators import AUTHORITY_CERTIFIED_BACKEND
    definition = _defn(Objective("makespan", "MIN"))

    class _MakespanPort:
        certified_pipeline = True

        def evaluate(self, candidate):
            return certified_evaluation(candidate, cycles=100,
                                        objective_values={})

    from p2_verified_support import run_certified_mechanics_for_tests
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY,
    )
    result = run_certified_mechanics_for_tests(
        _real_base(), definition, _MakespanPort(),
        CERTIFIED_METRIC_REGISTRY)
    assert result.pareto_ids == ()
    record = result.records[0]
    assert record.objective_availability["makespan"] == "UNMEASURABLE"
    assert "analytical" in (record.objective_details[0]["reason"] or "")
    assert AUTHORITY_CERTIFIED_BACKEND == record.evaluation_authority

def test_cross_model_same_key_constraint_is_unmeasured():
    """A constraint metric evidenced by both the verified proof and a
    federated envelope binds nothing — refusing to guess across
    models — while a single-source constraint still satisfies."""
    from p2_verified_support import certified_evaluation

    class _DualSourcePort:
        certified_pipeline = True

        def evaluate(self, candidate):
            ev = certified_evaluation(
                candidate, cycles=100,
                objective_values={"latency": 10.0})
            rows = [_row(SYSTEM, "ASTRA2_EMBEDDED_BOOKSIM",
                         "completion_cycles", 100.0)]
            return dataclasses.replace(ev, federated_analyses=tuple(rows))

    from p2_verified_support import (
        TEST_METRIC_REGISTRY,
        run_certified_mechanics_for_tests,
    )
    definition = _defn(
        Objective("latency", "MIN"),
        constraints=(Constraint("completion_cycles", "<=", 1000.0),
                     Constraint("latency", "<=", 600.0)))
    result = run_certified_mechanics_for_tests(
        _real_base(), definition, _DualSourcePort(), TEST_METRIC_REGISTRY)
    record = result.records[0]
    details = {d["metric"]: d for d in record.constraint_details}
    assert details["completion_cycles"]["verdict"] == "UNMEASURABLE"
    assert "across models" in details["completion_cycles"]["reason"]
    assert details["latency"]["verdict"] == "SATISFIED"

def test_single_source_constraint_still_satisfies():
    """Control: a proof-only constraint metric keeps its verdict —
    the union rule changes nothing for unambiguous sourcing."""
    from p2_verified_support import certified_evaluation

    class _ProofOnlyPort:
        certified_pipeline = True

        def evaluate(self, candidate):
            return certified_evaluation(
                candidate, cycles=100,
                objective_values={"latency": 10.0})

    from p2_verified_support import (
        TEST_METRIC_REGISTRY,
        run_certified_mechanics_for_tests,
    )
    definition = _defn(
        Objective("latency", "MIN"),
        constraints=(Constraint("latency", "<=", 600.0),))
    result = run_certified_mechanics_for_tests(
        _real_base(), definition, _ProofOnlyPort(), TEST_METRIC_REGISTRY)
    record = result.records[0]
    assert record.constraint_verdicts["latency"] == "SATISFIED"
    assert record.pareto_eligible is True
