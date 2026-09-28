"""Wave-F re-expression: multi-scenario studies on CompileRequest authority.

No fabric_overrides, no BookSim, no subprocess. Pure build/accounting
semantics: scenario scoping, aliasing, INVALID/FAILED/NOT_EVALUATED,
budget-tail agreement, hardware consistency, scenario binding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    Agent,
    AgentKind,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    TopologyFamily,
    WorkloadV3,
)
from veritx_dse.optimization.candidate import (  # noqa: E402
    CandidateError,
    make_study_candidate,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    OptimizationDefinitionError,
    ScenarioConstraint,
    ScenarioObjective,
    StudyParam,
    assess_effectiveness,
)
from veritx_dse.optimization.space_multiscenario import (  # noqa: E402
    ALIAS,
    INVALID,
    NOT_EVALUATED,
    VALID,
    BuildLedger,
    EvaluationRow,
    MultiScenarioStudy,
    Scenario,
    StudyError,
    accounting_summary,
    assert_scenario_binding,
    build_study_candidates,
    check_hardware_consistent,
    evaluate_constraints_per_scenario,
    scenario_request_for,
    study_structure,
    verify_tail_agreement,
    workload_fingerprint,
)


def _workload(tp=1, **kw):
    return WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER,
                      tp=tp, **kw)


def _base():
    return CompileRequestV3(
        workload=_workload(tp=1),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _study(**kw):
    base = dict(
        base=_base(),
        scenarios=(Scenario("s-tp1", _workload(tp=1)),
                   Scenario("s-tp2", _workload(tp=2))),
        objectives=(ScenarioObjective("completion_cycles", "MIN",
                                      scenario="s-tp1"),
                    ScenarioObjective("completion_cycles", "MIN",
                                      scenario="s-tp2")),
        domain=(StudyParam("link_width", (64, 128)),),
        method="grid",
    )
    base.update(kw)
    return MultiScenarioStudy(**base)


# ── scenario scoping ────────────────────────────────────────────────

def test_duplicate_metric_scenario_objectives_refuse():
    with pytest.raises(StudyError, match="duplicate"):
        _study(objectives=(
            ScenarioObjective("completion_cycles", "MIN", scenario="s-tp1"),
            ScenarioObjective("completion_cycles", "MIN", scenario="s-tp1")))


def test_unknown_scenario_scope_refuses():
    with pytest.raises(StudyError, match="unknown scenario"):
        _study(objectives=(
            ScenarioObjective("completion_cycles", "MIN", scenario="nope"),))
    with pytest.raises(StudyError, match="unknown scenario"):
        _study(constraints=(
            ScenarioConstraint("completion_cycles", "<=", 5.0,
                               scenario="nope"),))


def test_duplicate_scenario_ids_refuse():
    with pytest.raises(StudyError, match="duplicate scenario"):
        _study(scenarios=(Scenario("s", _workload()),
                          Scenario("s", _workload())))


def test_scenario_needs_canonical_workload():
    with pytest.raises(StudyError):
        Scenario("s", object())
    with pytest.raises(StudyError):
        Scenario("", _workload())


# ── dead knobs and LOCKED properties ─────────────────────────────────

@pytest.mark.parametrize("knob", [
    "rcu_enabled", "mcast_groups", "mcast_setup_cycles",
    "output_formats", "obfuscation_level"])
def test_dead_knobs_refuse_with_reasons(knob):
    with pytest.raises(OptimizationDefinitionError) as exc:
        StudyParam(knob, (1, 2))
    assert "not a physical-performance dimension" in str(exc.value) \
        or "removed from v4" in str(exc.value) or "no execution" in str(
            exc.value)


@pytest.mark.parametrize("knob", [
    "vc_count", "vc_map", "routing_function", "escape_vc",
    "turn_restrictions"])
def test_locked_properties_refuse(knob):
    with pytest.raises(OptimizationDefinitionError, match="LOCKED"):
        StudyParam(knob, (1, 2))


def test_unknown_dimension_refuses():
    with pytest.raises(OptimizationDefinitionError, match="unknown study"):
        StudyParam("flux_capacitor", (1,))


# ── aliasing / INVALID / tail ────────────────────────────────────────

def test_dotted_and_short_names_share_identity():
    base = _base()
    a = make_study_candidate(base, {"noc_config.link_width": 64})
    b = make_study_candidate(base, {"link_width": 64})
    assert a.candidate_id == b.candidate_id


def test_known_ids_surface_as_alias_never_reevaluated():
    first = build_study_candidates(_study())
    known = frozenset(c.candidate_id for c in first.valid)
    second = build_study_candidates(_study(), known_ids=known)
    assert second.valid == []
    assert len(second.aliases) == len(first.valid)
    assert all(a.status == ALIAS for a in second.aliases)
    assert {a.canonical_of for a in second.aliases} == known


def test_budget_tail_is_not_evaluated_not_failed():
    study = _study(domain=(StudyParam("link_width", (32, 64, 128, 256)),),
                   budget={"max_candidates": 2})
    ledger = build_study_candidates(study)
    assert len(ledger.valid) == 4
    assert len(ledger.not_evaluated) == 2
    assert ledger.invalid == [] and ledger.aliases == []
    # tail is the canonical-prefix cut: last two in canonical order
    assert ledger.not_evaluated == \
        [c.candidate_id for c in ledger.valid[2:]]
    from veritx_dse.optimization.space_multiscenario import eligible_ids
    assert eligible_ids(ledger) == \
        [c.candidate_id for c in ledger.valid[:2]]
    verify_tail_agreement([c.candidate_id for c in ledger.valid],
                          [], ledger.not_evaluated)
    # evaluating a tail identity without re-budgeting refuses
    with pytest.raises(StudyError, match="without re-budgeting"):
        verify_tail_agreement([c.candidate_id for c in ledger.valid],
                              ledger.not_evaluated, ledger.not_evaluated)


def test_tail_disagreement_refuses():
    study = _study()
    ledger = build_study_candidates(study)
    ids = [c.candidate_id for c in ledger.valid]
    with pytest.raises(StudyError, match="tail disagreement"):
        verify_tail_agreement(ids, [], ["forged-id"])
    with pytest.raises(StudyError, match="duplicates"):
        verify_tail_agreement(ids, [ids[0], ids[0]], [])


def test_invalid_patch_values_are_invalid_not_failed():
    study = _study(domain=(StudyParam("tp", (1, 64)),))
    ledger = build_study_candidates(study)
    # tp=64 -> 64 ranks over 4 compute instances: mapping infeasible by
    # canonical constructor -> INVALID at build, never an evaluation.
    assert len(ledger.valid) == 1
    assert len(ledger.invalid) == 1
    assert ledger.invalid[0].status == INVALID
    assert "mapping infeasible" in ledger.invalid[0].reason


# ── scenario binding + hardware consistency ──────────────────────────

def test_candidate_evaluated_against_exact_scenario_intent():
    study = _study()
    ledger = build_study_candidates(study)
    cand = ledger.valid[0]
    for scenario in study.scenarios:
        req = scenario_request_for(cand, scenario)
        assert workload_fingerprint(req.workload) == scenario.fingerprint()


def test_transplanted_scenario_binding_refuses():
    import dataclasses
    study = _study()
    ledger = build_study_candidates(study)
    cand = ledger.valid[0]
    other = study.scenarios[1]
    tampered = dataclasses.replace(
        scenario_request_for(cand, study.scenarios[0]),
        workload=other.workload)
    with pytest.raises(StudyError, match="exactly the scenario intent"):
        assert_scenario_binding(tampered, cand, study.scenarios[0])


def test_hardware_consistent_across_scenarios():
    study = _study()
    ledger = build_study_candidates(study)
    cand = ledger.valid[0]
    reqs = [scenario_request_for(cand, s) for s in study.scenarios]
    check_hardware_consistent(reqs)


def test_fabric_mutation_breaks_hardware_consistency():
    import dataclasses
    study = _study()
    ledger = build_study_candidates(study)
    cand = ledger.valid[0]
    reqs = [scenario_request_for(cand, s) for s in study.scenarios]
    mutated = dataclasses.replace(
        reqs[1], noc_config=dataclasses.replace(
            reqs[1].noc_config, link_width=999))
    with pytest.raises(StudyError, match="differ only in workload"):
        check_hardware_consistent([reqs[0], mutated])


# ── accounting: INVALID vs FAILED vs NOT_EVALUATED ───────────────────

def test_accounting_summary_separates_bins():
    study = _study(budget={"max_candidates": 1})
    ledger = build_study_candidates(study)
    assert len(ledger.valid) == 2
    assert len(ledger.not_evaluated) == 1
    cand = ledger.valid[0]
    rows = [EvaluationRow(cand.candidate_id, "s-tp1", "SUCCEEDED"),
            EvaluationRow(cand.candidate_id, "s-tp2", "FAILED",
                          reason="backend timeout")]
    summary = accounting_summary(ledger, rows)
    assert summary["valid"] == 2
    assert summary["not_evaluated"] == 1
    assert summary["evaluated_candidates"] == 1
    assert summary["succeeded_rows"] == 1
    assert summary["failed_rows"] == 1
    assert summary["failed"][0][1] == "s-tp2"


def test_evaluation_row_for_unknown_candidate_refuses():
    study = _study()
    ledger = build_study_candidates(study)
    with pytest.raises(StudyError, match="unknown candidate"):
        accounting_summary(ledger, [EvaluationRow("scand_" + "0" * 64,
                                                 "s-tp1", "SUCCEEDED")])


def test_constraint_violations_reported_per_scenario():
    study = _study(constraints=(
        ScenarioConstraint("completion_cycles", "<=", 100.0,
                           scenario="s-tp1"),
        ScenarioConstraint("completion_cycles", "<=", 100.0,
                           scenario="s-tp2"),))
    report = evaluate_constraints_per_scenario(
        study, {"s-tp1": {"completion_cycles": 50.0},
                "s-tp2": {"completion_cycles": 500.0}})
    assert report["s-tp1"]["violated"] == []
    assert report["s-tp2"]["violated"] == ["completion_cycles"]
    missing = evaluate_constraints_per_scenario(study, {})
    assert missing["s-tp1"]["verdicts"]["completion_cycles"]["verdict"] == \
        "UNMEASURABLE"


# ── effectiveness ────────────────────────────────────────────────────

def test_link_width_critical_path_has_no_direct_effect():
    verdict, rationale = assess_effectiveness("link_width", "critical_path")
    assert verdict == "NO_DIRECT_EFFECT"
    assert "serialization" in rationale


def test_link_width_completion_effective():
    verdict, _ = assess_effectiveness("link_width", "completion_cycles")
    assert verdict == "EFFECTIVE"


def test_unknown_combination_warns():
    verdict, rationale = assess_effectiveness("arbitration", "critical_path")
    assert verdict == "UNKNOWN"
    assert "warn" in rationale


# ── structure ────────────────────────────────────────────────────────

def test_study_structure_and_identity():
    a, b = _study(), _study()
    assert a.study_id() == b.study_id()
    ledger = build_study_candidates(a)
    struct = study_structure(a, ledger)
    assert struct["raw_cardinality"] == 2
    assert struct["scenarios"] == ["s-tp1", "s-tp2"]
    assert struct["study_id"] == a.study_id()


def test_make_study_candidate_identity_and_transplant():
    from veritx_dse.optimization.candidate import StudyCandidate
    base = _base()
    c1 = make_study_candidate(base, {"tp": 2})
    c2 = make_study_candidate(base, {"workload.tp": 2})
    assert c1.candidate_id == c2.candidate_id
    with pytest.raises(CandidateError, match="transplanted id"):
        StudyCandidate(candidate_id="scand_" + "f" * 64,
                       base_design_hash=c1.base_design_hash,
                       study_patch=c1.study_patch, request=c1.request,
                       mapping_hash=c1.mapping_hash,
                       placement_policy=c1.placement_policy)
