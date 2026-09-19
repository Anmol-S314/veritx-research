"""Wave B2 mapping tests — one-to-one rank→agent, no fabric attachment."""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.mapping import (
    MappingArtifact, MappingError, RankPlacement, derive_mapping,
)
from veritx_dse.model.placement import AgentInstance

_FABRIC_KEYS = {"router", "router_id", "endpoint", "endpoint_id", "port",
                "link", "topology", "routing", "vc"}


def _cr(tp=1, pp=1, ep=1, dp=1, agents=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=pp,
                          ep=ep, dp=dp),
        requirements=[],
        agents=agents or [Agent(kind=AgentKind.COMPUTE_TILE,
                                count=tp * pp * ep * dp)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )


def _keys(node, acc=None):
    acc = acc if acc is not None else set()
    if isinstance(node, dict):
        acc.update(node.keys())
        for v in node.values():
            _keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            _keys(v, acc)
    return acc


def _swap_placement():
    return MappingArtifact(placements=(
        RankPlacement(rank=0, agent=AgentInstance(0, 1, AgentKind.COMPUTE_TILE)),
        RankPlacement(rank=1, agent=AgentInstance(0, 0, AgentKind.COMPUTE_TILE)),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# baseline placement
# ══════════════════════════════════════════════════════════════════════════════

def test_derive_binds_every_rank_to_a_distinct_instance():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    assert m.rank_count == 4
    assert [p.rank for p in m.placements] == [0, 1, 2, 3]
    assert [p.agent.instance_id for p in m.placements] == [
        "agent_group[0]/compute_tile[0]",
        "agent_group[0]/compute_tile[1]",
        "agent_group[0]/compute_tile[2]",
        "agent_group[0]/compute_tile[3]",
    ]


def test_more_ranks_than_compute_instances_is_refused():
    with pytest.raises(MappingError, match="needs 4 ranks but design has only 2"):
        derive_mapping(_cr(tp=2, pp=2, ep=1, dp=1,
                           agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=2)]))


def test_four_active_ranks_on_64_compute_instances():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1, agents=[
        Agent(kind=AgentKind.COMPUTE_TILE, count=64),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=8),
    ]))
    assert m.rank_count == 4
    assert len(m.placements) == 4
    assert all(p.agent.kind == AgentKind.COMPUTE_TILE for p in m.placements)


# ══════════════════════════════════════════════════════════════════════════════
# content addressing
# ══════════════════════════════════════════════════════════════════════════════

def test_mapping_hash_is_stable():
    a = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    b = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    assert a.mapping_hash() == b.mapping_hash()
    assert len(a.mapping_hash()) == 64


def test_mapping_hash_changes_on_placement():
    assert derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).mapping_hash() \
        != _swap_placement().mapping_hash()


def test_same_placement_different_design_hash():
    a = _cr(tp=2, pp=1, ep=2, dp=1)
    b = _cr(tp=4, pp=1, ep=1, dp=1)
    assert a.design_hash() != b.design_hash()
    assert derive_mapping(a).mapping_hash() == derive_mapping(b).mapping_hash()


def test_serialize_deserialize_hash_stable():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    assert MappingArtifact.from_dict(m.to_dict()).mapping_hash() == m.mapping_hash()


# ══════════════════════════════════════════════════════════════════════════════
# §43 — sentinel: no fabric attachment in B2 mapping
# ══════════════════════════════════════════════════════════════════════════════

def test_mapping_contains_no_fabric_fields():
    m = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1))
    assert _keys(m.to_dict()) & _FABRIC_KEYS == set()


def test_placement_with_router_field_refused():
    with pytest.raises(MappingError, match="unknown fields"):
        RankPlacement.from_dict(
            {"rank": 0, "router": 3,
             "agent": {"group_index": 0, "instance_index": 0,
                       "kind": "compute_tile"}})


# ══════════════════════════════════════════════════════════════════════════════
# §22/23/33/34 — schema and tamper
# ══════════════════════════════════════════════════════════════════════════════

def test_to_dict_persists_schema_version():
    d = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1)).to_dict()
    assert d["schema_version"] == 1


@pytest.mark.parametrize("bad", [0, 2, 1.0, True])
def test_from_dict_rejects_bad_schema_version(bad):
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    d["schema_version"] = bad
    with pytest.raises(MappingError):
        MappingArtifact.from_dict(d)


def test_from_dict_requires_schema_version():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    del d["schema_version"]
    with pytest.raises(MappingError, match="schema_version"):
        MappingArtifact.from_dict(d)


def test_from_dict_requires_mapping_hash():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    del d["mapping_hash"]
    with pytest.raises(MappingError, match="mapping_hash"):
        MappingArtifact.from_dict(d)


def test_from_dict_detects_tampered_placement():
    d = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1)).to_dict()
    d["placements"][0]["agent"]["instance_index"] = 9
    with pytest.raises(MappingError, match="does not match content"):
        MappingArtifact.from_dict(d)


def test_from_dict_detects_tampered_hash():
    d = derive_mapping(_cr(tp=2, pp=1, ep=2, dp=1)).to_dict()
    d["mapping_hash"] = "0" * 64
    with pytest.raises(MappingError, match="does not match content"):
        MappingArtifact.from_dict(d)


# ══════════════════════════════════════════════════════════════════════════════
# §35 — unknown fields
# ══════════════════════════════════════════════════════════════════════════════

def test_from_dict_rejects_unknown_root_field():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    d["foo"] = 1
    with pytest.raises(MappingError, match="unknown fields"):
        MappingArtifact.from_dict(d)


def test_from_dict_rejects_unknown_placement_field():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    d["placements"][0]["link"] = 1
    with pytest.raises(MappingError, match="unknown fields"):
        MappingArtifact.from_dict(d)


def test_from_dict_rejects_unknown_agent_field():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    d["placements"][0]["agent"]["clock_domain"] = "clk"
    with pytest.raises(MappingError, match="unknown fields"):
        MappingArtifact.from_dict(d)


def test_from_dict_rejects_missing_placement_fields():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    del d["placements"][0]["agent"]
    with pytest.raises(MappingError, match="agent"):
        MappingArtifact.from_dict(d)


# ══════════════════════════════════════════════════════════════════════════════
# §21/32/47 — one-to-one, compute-only
# ══════════════════════════════════════════════════════════════════════════════

def test_duplicate_agent_placement_refused():
    with pytest.raises(MappingError, match="duplicate agent placement"):
        MappingArtifact(placements=(
            RankPlacement(rank=0, agent=AgentInstance(0, 0, AgentKind.COMPUTE_TILE)),
            RankPlacement(rank=1, agent=AgentInstance(0, 0, AgentKind.COMPUTE_TILE)),
        ))


def test_duplicate_agent_placement_refused_via_from_dict():
    d = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).to_dict()
    d["placements"][1]["agent"] = dict(d["placements"][0]["agent"])
    d["mapping_hash"] = derive_mapping(_cr(tp=2, pp=1, ep=1, dp=1)).mapping_hash()
    with pytest.raises(MappingError, match="duplicate agent placement"):
        MappingArtifact.from_dict(d)


@pytest.mark.parametrize("kind", [AgentKind.HBM_CONTROLLER, AgentKind.NIC,
                                  AgentKind.PERIPHERAL, AgentKind.UCIE_PORT])
def test_non_compute_agent_cannot_host_rank(kind):
    with pytest.raises(MappingError, match="only compute instances"):
        MappingArtifact(placements=(
            RankPlacement(rank=0, agent=AgentInstance(0, 0, kind)),
        ))


def test_contiguous_ranks_enforced():
    with pytest.raises(MappingError, match="contiguous"):
        MappingArtifact(placements=(
            RankPlacement(rank=1, agent=AgentInstance(0, 0, AgentKind.COMPUTE_TILE)),
        ))


def test_artifact_requires_tuple_placements():
    p = RankPlacement(rank=0, agent=AgentInstance(0, 0, AgentKind.COMPUTE_TILE))
    with pytest.raises(MappingError, match="tuple"):
        MappingArtifact(placements=[p])
