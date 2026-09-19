"""Wave B2.2 tests — MappingArtifact: explicit, content-addressed placement."""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.mapping import (
    MappingArtifact, MappingError, RankPlacement, derive_mapping,
)
from veritx_dse.model.placement import AgentInstance, Endpoint


def _cr(tp=1, pp=1, ep=1, dp=1, compute=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=pp,
                          ep=ep, dp=dp),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE,
                      count=compute or tp * pp * ep * dp)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )


def test_derive_binds_every_rank_to_a_distinct_instance():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    assert m.rank_count == 4
    assert [p.rank for p in m.placements] == [0, 1, 2, 3]
    assert [p.agent.instance_id for p in m.placements] == [
        "compute_tile[0]", "compute_tile[1]",
        "compute_tile[2]", "compute_tile[3]"]
    assert all(p.endpoint_id is None and p.router is None
               for p in m.placements)


def test_more_ranks_than_compute_instances_is_refused():
    with pytest.raises(MappingError, match="only 2 compute instances"):
        derive_mapping(_cr(tp=2, pp=2, ep=1, dp=1, compute=2))


def test_idle_instances_do_not_become_active_ranks():
    """4 active ranks on 64 compute instances: mapping has exactly 4 entries."""
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1, compute=64))
    assert m.rank_count == 4
    assert len(m.placements) == 4


def test_mapping_hash_is_content_addressed_and_stable():
    a = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    b = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    assert a.mapping_hash() == b.mapping_hash()
    assert len(a.mapping_hash()) == 64


def test_mapping_hash_tracks_placement_not_parallelism_coords():
    """tp*ep=4 and tp*ep=4 place identically, so mapping identity is equal.

    The parallelism layout is design intent (design_hash); the mapping
    answers only where those ranks live.
    """
    a = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    c = derive_mapping(_cr(tp=4, pp=1, ep=1, dp=1))
    assert a.mapping_hash() == c.mapping_hash()


def test_endpoint_attachment_changes_mapping_hash():
    plain = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1))
    endpoints = tuple(Endpoint(endpoint_id=r, rank=r, router=r)
                      for r in range(2))
    attached = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1),
                              endpoints=endpoints)
    assert plain.mapping_hash() != attached.mapping_hash()


def test_placement_change_changes_hash():
    base = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1))
    moved = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=AgentInstance(AgentKind.COMPUTE_TILE, 1)),
        RankPlacement(rank=1, agent=AgentInstance(AgentKind.COMPUTE_TILE, 0)),
    ))
    assert base.mapping_hash() != moved.mapping_hash()


def test_router_assignment_is_never_inferred_from_rank():
    """Without a fabric attachment the mapping must not invent routers."""
    m = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1))
    assert all(p.endpoint_id is None and p.router is None
               for p in m.placements)


def test_endpoint_attachment_is_recorded_verbatim():
    endpoints = tuple(
        Endpoint(endpoint_id=100 + r, rank=r, router=7 - r) for r in range(4))
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1), endpoints=endpoints)
    assert [(p.rank, p.endpoint_id, p.router) for p in m.placements] == [
        (0, 100, 7), (1, 101, 6), (2, 102, 5), (3, 103, 4)]


def test_partial_endpoint_attachment_is_refused():
    endpoints = (Endpoint(endpoint_id=0, rank=0, router=0),)
    with pytest.raises(MappingError, match="cover every rank"):
        derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1), endpoints=endpoints)


def test_endpoints_must_be_tuple():
    with pytest.raises(MappingError, match="tuple"):
        derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1),
                       endpoints=[Endpoint(endpoint_id=0, rank=0, router=0)])


def test_duplicate_endpoint_rank_refused():
    endpoints = (Endpoint(endpoint_id=0, rank=0, router=0),
                 Endpoint(endpoint_id=1, rank=0, router=1))
    with pytest.raises(MappingError, match="duplicate"):
        derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1), endpoints=endpoints)


def test_placement_requires_endpoint_and_router_together():
    with pytest.raises(MappingError, match="both present or both absent"):
        RankPlacement(rank=0, agent=AgentInstance(AgentKind.COMPUTE_TILE, 0),
                      endpoint_id=3, router=None)


def test_artifact_rejects_non_contiguous_ranks():
    with pytest.raises(MappingError, match="contiguous"):
        MappingArtifact(placements=(
            RankPlacement(rank=1,
                          agent=AgentInstance(AgentKind.COMPUTE_TILE, 0)),))


def test_artifact_requires_tuple_placements():
    p = RankPlacement(rank=0, agent=AgentInstance(AgentKind.COMPUTE_TILE, 0))
    with pytest.raises(MappingError, match="tuple"):
        MappingArtifact(placements=[p])


def test_round_trip_and_tamper_detection():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    d = m.to_dict()
    assert MappingArtifact.from_dict(d).mapping_hash() == m.mapping_hash()
    d["placements"][0]["agent"]["index"] = 9
    with pytest.raises(MappingError, match="does not match content"):
        MappingArtifact.from_dict(d)


def test_from_dict_rejects_unknown_fields():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    d = m.to_dict()
    d["extra"] = 1
    with pytest.raises(MappingError, match="unknown fields"):
        MappingArtifact.from_dict(d)
