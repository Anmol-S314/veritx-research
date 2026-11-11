"""Bounded live execution: authored demand, canonical TP/EP, three separate models."""
from dataclasses import replace
import pytest

from test_workload_optimization import request
from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_model import Agent, AgentKind
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.optimization.candidate import make_candidate
from veritx_dse.optimization.definition import Objective
from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator


def test_native_decomposition_with_authored_compute_and_memory(tmp_path):
    binary = REPO / 'third_party/booksim2/src/booksim'
    python = REPO / 'apps/studio/prototype/.desktop-venv/bin/python'
    if not binary.is_file() or not python.is_file():
        pytest.skip('requires built BookSim and the desktop Python/Ramulator environment')
    base = request()
    base = replace(base, topology=MeshIntent(5, 1), agents=base.agents + (
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1),))
    objectives = (
        Objective('completion_cycles', 'MIN'),
        Objective('system_makespan_cycles', 'MIN', question='SYSTEM_MAKESPAN'),
        Objective('average_read_latency_cycles', 'MIN', question='DRAM_TIMING'),
    )
    port = RealCandidateEvaluator(binary=binary, network_clock_hz=10**9,
        timeout_s=60, run_root=tmp_path, repo_root=REPO, objectives=objectives,
        ramulator_python=str(python))
    results = [port.evaluate(make_candidate(base, patch)) for patch in (
        {'tp': 2, 'ep': 4}, {'tp': 4, 'ep': 2})]
    for result in results:
        assert result.status == 'EVALUATED', result.error
        assert all(row.status == 'EVALUATED' for row in result.federated_analyses)
        for objective in objectives:
            assert result.objective_values[objective.metric] > 0
            provenance = result.objective_provenance[objective.metric]
            assert provenance.native_evidence_id.startswith('sha256:')
            assert provenance.qualification != 'SCRIPTED'
        assert len({p.backend_id for p in result.objective_provenance.values()}) == 3
    assert results[0].objective_values['completion_cycles'] != results[1].objective_values['completion_cycles']
    assert results[0].objective_values['system_makespan_cycles'] != results[1].objective_values['system_makespan_cycles']
    # Memory demand is deliberately unchanged: no inferred tensor sharding.
    assert results[0].objective_values['average_read_latency_cycles'] == results[1].objective_values['average_read_latency_cycles']
    slower = replace(base, compute=replace(base.compute, stages=(
        replace(base.compute.stages[0], duration_ns=1000),)))
    changed = port.evaluate(make_candidate(slower, {'tp': 2, 'ep': 4}))
    assert changed.status == 'EVALUATED', changed.error
    assert changed.objective_values['completion_cycles'] == results[0].objective_values['completion_cycles']
    # Native rank scheduling can overlap work: prove compute affects the
    # system result, not an invented additive compute+communication formula.
    assert changed.objective_values['system_makespan_cycles'] > results[0].objective_values['system_makespan_cycles']

    # Exercise the actual product job and archived candidate evidence too,
    # without mutating any existing user's project or automatically adopting.
    from test_product_federation import _service, _wait_job, WORKLOAD
    svc = _service(tmp_path / 'product', booksim_bin=binary,
        network_clock_hz=10**9, timeout_s=60, ramulator_python=str(python))
    try:
        pid = svc.create_project(name='native TP/EP smoke', workload_id=WORKLOAD)['project']['project_id']
        svc.put_draft(pid, base.to_dict())
        revision = svc.compile_draft(pid)
        before = svc.draft_view(pid)['request']
        submitted = svc.submit_optimization(revision['revision_id'], {
            'domain': [{'name': 'tp', 'values': [2, 4]}, {'name': 'ep', 'values': [2, 4]}],
            'objectives': [{'metric': o.metric, 'direction': o.direction, 'question': o.question.value} for o in objectives],
            'budget': {'max_evaluations': 4},
        })
        job = _wait_job(svc, submitted['job_id'], timeout_s=60)
        assert job['state'] == 'COMPLETED', job
        study = svc.get_optimization(job['result']['optimization_id'])['study']
        assert len(study['candidates']) == 4
        assert study['selected_candidate_id'] is not None
        for candidate in study['candidates']:
            assert candidate['evaluation_status'] == 'EVALUATED'
            assert {o.metric for o in objectives} <= candidate['objective_values'].keys()
            assert all(p['qualification'] != 'SCRIPTED' for p in candidate['objective_provenance'])
        assert svc.draft_view(pid)['request'] == before
    finally:
        svc.jobs.shutdown()
