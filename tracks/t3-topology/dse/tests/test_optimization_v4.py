"""V4 optimization preserves canonical intent; scripted runs prove orchestration only."""
from __future__ import annotations

import dataclasses

import pytest

from veritx_dse.model.compile_request_v4 import migrate_v3_to_v4
from veritx_dse.model.topology_intent import (
    ExplicitTopologyIntent, FatTreeIntent, FlatFlyIntent, GecMode,
    GecTopologyIntent, MeshIntent, TorusIntent,
)
from veritx_dse.optimization.candidate import CandidateError, apply_patch, make_candidate
from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
from test_federated_optimizer import _base, _scripted_registry
from test_product_federation import _service, _wait_job, WORKLOAD


def _v4():
    return migrate_v3_to_v4(_base())


@pytest.mark.parametrize("patch,expected_topology", [
    ({"link_width": 128}, MeshIntent(2, 1)),
    ({"concentration": 2}, MeshIntent(2, 2)),
    ({"radix": 3}, MeshIntent(3, 1)),
    ({"topology_family": "torus"}, TorusIntent(2, 1)),
    ({"topology_family": "torus", "radix": 3, "concentration": 2,
      "link_width": 128}, TorusIntent(3, 2)),
])
def test_v4_guided_patch_preserves_other_intent(patch, expected_topology):
    base = _v4()
    before = base.to_dict()
    candidate = make_candidate(base, patch)
    expected_controls = dataclasses.replace(
        base.noc_controls, **{k: v for k, v in patch.items() if k == "link_width"})
    expected = dataclasses.replace(base, topology=expected_topology,
                                   noc_controls=expected_controls)
    assert candidate.request == expected
    assert candidate.request.schema_version == 4
    assert candidate.request.design_hash() == expected.design_hash()
    assert candidate.base_design_hash == base.design_hash()
    assert base.to_dict() == before


@pytest.mark.parametrize("topology,patch,expected", [
    (FlatFlyIntent(2, 2, 1), {"radix": 3}, FlatFlyIntent(3, 2, 1)),
    (FatTreeIntent(2, 2), {"radix": 4}, FatTreeIntent(4, 2)),
    (GecTopologyIntent(GecMode.MESH, 2, 1), {"radix": 3, "concentration": 2},
     GecTopologyIntent(GecMode.MESH, 3, 2)),
])
def test_v4_family_specific_dimensions_are_preserved(topology, patch, expected):
    base = dataclasses.replace(_v4(), topology=topology)
    assert apply_patch(base, patch).topology == expected


def test_v4_gec_shape_patch_does_not_relax_partition_law():
    base = dataclasses.replace(_v4(), topology=GecTopologyIntent(
        GecMode.EXPRESS, 3, 1, 2, 1))
    with pytest.raises(ValueError, match="span the grid exactly once"):
        apply_patch(base, {"radix": 4})


def test_v4_patch_retains_all_extended_router_controls():
    base = _v4()
    base = dataclasses.replace(base, noc_controls=dataclasses.replace(
        base.noc_controls, input_buffer_depth_flits_per_vc=8,
        credit_return_latency_cycles=2, allocator_iterations=3))
    patched = apply_patch(base, {"link_width": 64})
    assert patched.noc_controls == dataclasses.replace(base.noc_controls, link_width=64)


@pytest.mark.parametrize("patch", [{"link_width": True}, {"radix": 0},
                                   {"concentration": -1}, {"vc_count": 5}])
def test_v4_invalid_and_locked_knobs_still_refuse(patch):
    with pytest.raises(ValueError):
        apply_patch(_v4(), patch)


def test_v4_explicit_graph_survives_control_patch_and_refuses_shape_guessing():
    from veritx_dse.model.topology_ir import TopologyIR
    base = _v4()
    graph = TopologyIR(name="authored", kind="custom", nodes=4,
                       links=[[0, 1], [1, 2], [2, 3]],
                       link_attrs={"bandwidth_GBs": 50.0, "latency_ns": 500.0})
    base = dataclasses.replace(base, topology=ExplicitTopologyIntent(graph))
    assert apply_patch(base, {"link_width": 64}).topology == base.topology
    for patch in ({"radix": 3}, {"concentration": 2}, {"topology_family": "mesh"}):
        with pytest.raises(CandidateError):
            apply_patch(base, patch)


@pytest.mark.parametrize("unavailable", [False, True])
def test_product_v4_optimization_uses_real_pipeline_without_downgrade(
        tmp_path, monkeypatch, unavailable):
    from veritx_dse.backend.adapter import BackendReadiness
    registry, astra, _ = _scripted_registry(**(
        {"astra": {"readiness": BackendReadiness.UNAVAILABLE,
                   "reason": "test producer unavailable"}} if unavailable else {}))
    monkeypatch.setattr(RealCandidateEvaluator, "_resolve_registry", lambda self: registry)
    svc = _service(tmp_path)
    pid = svc.create_project(name="v4 optimizer", workload_id=WORKLOAD)["project"]["project_id"]
    base = _v4()
    svc.put_draft(pid, base.to_dict())
    before = svc.draft_view(pid)["request"]
    revision = svc.compile_draft(pid)
    assert revision["compilation"]["status"] == "COMPILED"
    submitted = svc.submit_optimization(revision["revision_id"], {
        "domain": [{"name": "link_width", "values": [32, 64]}],
        "objectives": [{"metric": "system_makespan_cycles", "direction": "MIN",
                        "question": "SYSTEM_MAKESPAN"}],
    })
    job = _wait_job(svc, submitted["job_id"])
    assert job["state"] == "COMPLETED", job
    optimization = svc.get_optimization(job["result"]["optimization_id"])
    study = optimization["study"]
    assert len(study["candidates"]) == 2
    expected_status = "BACKEND_UNAVAILABLE" if unavailable else "EVALUATED"
    assert {c["evaluation_status"] for c in study["candidates"]} == {expected_status}
    assert len(astra.executed) == (0 if unavailable else 2)
    if unavailable:
        assert study["selected_candidate_id"] is None
        assert all(not c["objective_values"] for c in study["candidates"])
    else:
        assert study["selected_candidate_id"] is not None
        for c in study["candidates"]:
            assert c["objective_values"]["system_makespan_cycles"] == 6070.0
            provenance = {p["metric_key"]: p for p in c["objective_provenance"]}
            assert provenance["system_makespan_cycles"]["qualification"] == "SCRIPTED"
    assert svc.draft_view(pid)["request"] == before
    if not unavailable:
        selected = next(c for c in study["candidates"]
                        if c["candidate_id"] == study["selected_candidate_id"])
        adopted = svc.use_candidate(optimization["optimization_id"], selected["candidate_id"])
        assert adopted["request"]["schema_version"] == 4
        from veritx_dse.product.service import parse_request_doc
        assert parse_request_doc(adopted["request"]) == apply_patch(base, selected["guided_patch"])
        assert svc.compile_draft(pid)["compilation"]["status"] == "COMPILED"
