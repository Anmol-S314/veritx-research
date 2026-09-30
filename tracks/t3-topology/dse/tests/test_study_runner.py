"""Study runner: multi-scenario execution beside the optimizer.

No backend, no subprocess: the federated execution seam is injected, so
these tests prove build/accounting discipline (aliases, tail, binding,
certified refusal, AUTO-only) with real compiles and a stub executor.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_evaluator import EVALUATED  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    TopologyFamily,
    WorkloadV3,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    ScenarioObjective,
    StudyParam,
)
from veritx_dse.optimization.space_multiscenario import (  # noqa: E402
    MultiScenarioStudy,
    Scenario,
    StudyError,
    build_study_candidates,
)
from veritx_dse.optimization.study_runner import (  # noqa: E402
    RESULT_CLASS_STUDY_GRADE,
    StudyRunConfig,
    evidence_index,
    run_study,
)

def _workload(tp=1, **kw):
    return WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER,
                      tp=tp,
                      collectives=(CollectiveIntent(
                          kind=CollectiveKind.ALLREDUCE,
                          dimension=CollectiveDimension.TP,
                          payload_bytes=2048,
                          traffic_class="tp_collective"),),
                      **kw)

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

def _stub(calls, *, fail_on=()):
    def run(compilation, questions, run_dir):
        key = (compilation.request.workload.tp,
               tuple(q.value for q in questions))
        calls.append(key)
        if key in fail_on:
            raise RuntimeError("backend blew up")
        tag = f"tp{compilation.request.workload.tp}"
        return SimpleNamespace(analyses=tuple(
            SimpleNamespace(question=q, status=EVALUATED,
                            native_evidence_id=f"ev-{tag}-{q.value}",
                            reused_evidence_id=None)
            for q in questions))
    return run

def test_certified_entry_refuses():
    with pytest.raises(StudyError, match="Optimizer-only"):
        run_study(_study(), certified=True)

def test_backend_pinning_refuses_auto_only():
    study = _study(objectives=(
        ScenarioObjective("completion_cycles", "MIN",
                          scenario="s-tp1", backend_id="booksim"),))
    with pytest.raises(StudyError, match="AUTO-only"):
        run_study(study, evaluate=_stub([]))

def test_happy_path_binds_evidence_per_scenario(tmp_path):
    calls: list = []
    result = run_study(_study(), config=StudyRunConfig(run_root=tmp_path),
                       evaluate=_stub(calls))
    assert result.result_class == RESULT_CLASS_STUDY_GRADE
    assert result.result_class != "CERTIFIED_PRODUCT"
    assert result.ledger_valid == 2
    assert result.accounting["evaluated_candidates"] == 2
    assert result.accounting["succeeded_rows"] == 4
    assert len(calls) == 4
    assert all(qs == ("NETWORK_COMPLETION",) for _, qs in calls)
    index = evidence_index(result)
    assert index[(result.rows[0].candidate_id, "s-tp1",
                  "NETWORK_COMPLETION")] == "ev-tp1-NETWORK_COMPLETION"
    assert index[(result.rows[0].candidate_id, "s-tp2",
                  "NETWORK_COMPLETION")] == "ev-tp2-NETWORK_COMPLETION"
    again = run_study(_study(), config=StudyRunConfig(run_root=tmp_path),
                      evaluate=_stub([]))
    assert again.result_id == result.result_id

def test_alias_is_never_reevaluated(tmp_path):
    ledger = build_study_candidates(_study())
    known = frozenset({ledger.valid[0].candidate_id})
    calls: list = []
    result = run_study(_study(), config=StudyRunConfig(run_root=tmp_path),
                       known_ids=known, evaluate=_stub(calls))
    assert result.ledger_aliases == 1
    assert len(calls) == 2
    assert result.accounting["evaluated_candidates"] == 1

def test_tail_is_not_evaluated_not_failed(tmp_path):
    study = _study(budget={"max_candidates": 1})
    calls: list = []
    result = run_study(study, config=StudyRunConfig(run_root=tmp_path),
                       evaluate=_stub(calls))
    assert result.ledger_not_evaluated == 1
    assert len(calls) == 2
    assert result.accounting["failed_rows"] == 0

def test_executor_exception_is_failed_row_not_study_crash(tmp_path):
    calls: list = []
    result = run_study(_study(), config=StudyRunConfig(run_root=tmp_path),
                       evaluate=_stub(calls, fail_on={(2, ("NETWORK_COMPLETION",))}))
    assert result.accounting["succeeded_rows"] == 2
    assert result.accounting["failed_rows"] == 2
    failed = [r for r in result.rows if r.status == "FAILED"]
    assert len(failed) == 2
    assert all(r.scenario_id == "s-tp2" for r in failed)
    assert all("backend blew up" in (r.reason or "") for r in failed)

def test_unasked_scenario_is_not_executed(tmp_path):
    study = _study(objectives=(
        ScenarioObjective("completion_cycles", "MIN", scenario="s-tp1"),))
    with pytest.raises(StudyError, match="no objective"):
        run_study(study, config=StudyRunConfig(run_root=tmp_path),
                  evaluate=_stub([]))
