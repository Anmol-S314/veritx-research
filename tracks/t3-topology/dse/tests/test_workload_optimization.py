"""Canonical decomposition sweeps preserve authored demand, never rewrite replay traces."""
from dataclasses import replace

import pytest

from test_federated_optimizer import _base
from test_product_federation import _service, _wait_job, WORKLOAD
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.compile_model import CollectiveDimension, CollectiveIntent, CollectiveKind, ModelFamily
from veritx_dse.model.compile_request_v4 import migrate_v3_to_v4
from veritx_dse.model.compute_intent import ComputeIntent, ComputeStage
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.optimization.candidate import CandidateError, apply_patch, apply_study_patch, make_candidate
from veritx_dse.optimization.definition import DomainParam, OptimizationDefinitionError
from veritx_dse.workload.intent_lowering import lower_compile_workload


def request():
    base = migrate_v3_to_v4(_base())
    return replace(base, topology=MeshIntent(4, 1),
        agents=(replace(base.agents[0], count=16),), workload=replace(
        base.workload, model_family=ModelFamily('mixture_of_experts'), tp=2, ep=4,
        collectives=(
            CollectiveIntent(CollectiveKind.ALLREDUCE, CollectiveDimension.TP, 64, 'tp_collective'),
            CollectiveIntent(CollectiveKind.ALLTOALL, CollectiveDimension.EP, 64, 'tp_collective'),
        )), compute=ComputeIntent(stages=(ComputeStage('authored', 100, 64, 128, 32, owner=0),)))


@pytest.mark.parametrize('dimension', ['tp', 'ep', 'pp', 'dp'])
@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '2'])
def test_bad_parallelism_refused(dimension, value):
    with pytest.raises(OptimizationDefinitionError):
        DomainParam(dimension, (value,))
    with pytest.raises(CandidateError):
        apply_patch(request(), {dimension: value})


def test_decomposition_relowers_collectives_without_inventing_compute():
    base = request()
    before = base.to_dict()
    patched = make_candidate(base, {'workload.tp': 4, 'workload.ep': 2})
    assert patched.request.topology == base.topology
    assert patched.request.compute == base.compute
    assert patched.request.agents == base.agents
    assert patched.request.design_hash() != base.design_hash()
    assert patched.request.workload.world_size == base.workload.world_size == 8
    old = lower_compile_workload(base)
    new = lower_compile_workload(patched.request)
    assert old.graph.workload_id() != new.graph.workload_id()
    assert [op.detail for op in old.graph.operations if op.kind == 'COMPUTE'] == [
        op.detail for op in new.graph.operations if op.kind == 'COMPUTE']
    assert FabricCompiler().compile(patched.request).certificate.overall == 'PASS'
    assert base.to_dict() == before


def test_study_and_product_paths_share_v4_typed_patch():
    base = request()
    patch = {'tp': 1, 'ep': 2, 'link_width': 64}
    assert apply_study_patch(base, patch) == apply_patch(base, patch)
    assert apply_study_patch(base, patch).compute == base.compute


def test_imported_source_cannot_be_repartitioned():
    # Source contents are deliberately not needed: refusing to reinterpret them
    # must happen before fetching an imported trace.
    from veritx_dse.model.compile_model import WorkloadSourceRef
    source = WorkloadSourceRef(content_digest='sha256:' + 'a' * 64, format='chakra')
    base = replace(request(), workload=replace(request().workload, source_ref=source))
    for patcher in (apply_patch, apply_study_patch):
        with pytest.raises(CandidateError, match='imported workload source'):
            patcher(base, {'tp': 1})


def test_product_job_preserves_draft_and_declared_demand(tmp_path, monkeypatch):
    from test_federated_optimizer import _scripted_registry
    from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
    registry, astra, _ = _scripted_registry()
    monkeypatch.setattr(RealCandidateEvaluator, '_resolve_registry', lambda self: registry)
    svc = _service(tmp_path)
    pid = svc.create_project(name='decomposition', workload_id=WORKLOAD)['project']['project_id']
    base = request()
    svc.put_draft(pid, base.to_dict())
    revision = svc.compile_draft(pid)
    assert revision['compilation']['status'] == 'COMPILED'
    before = svc.draft_view(pid)['request']
    submitted = svc.submit_optimization(revision['revision_id'], {
        'domain': [{'name': 'tp', 'values': [2, 4]}, {'name': 'ep', 'values': [2, 4]}],
        'objectives': [{'metric': 'system_makespan_cycles', 'direction': 'MIN', 'question': 'SYSTEM_MAKESPAN'}],
        'budget': {'max_evaluations': 4},
    })
    job = _wait_job(svc, submitted['job_id'])
    assert job['state'] == 'COMPLETED', job
    study = svc.get_optimization(job['result']['optimization_id'])['study']
    assert len(study['candidates']) == 4
    assert len(astra.executed) == 4
    assert svc.draft_view(pid)['request'] == before
    assert all(row['objective_provenance'][0]['qualification'] == 'SCRIPTED' for row in study['candidates'])
    selected = next(row for row in study['candidates'] if row['candidate_id'] == study['selected_candidate_id'])
    adopted = svc.use_candidate(job['result']['optimization_id'], selected['candidate_id'])
    from veritx_dse.product.service import parse_request_doc
    assert parse_request_doc(adopted['request']) == apply_patch(base, selected['guided_patch'])
    assert adopted['request']['compute'] == base.to_dict()['compute']
