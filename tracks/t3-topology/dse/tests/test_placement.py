"""Wave B2 placement tests — global agent identity + canonical rank space."""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import (
    AgentInstance, LogicalRank, NodeInventory, ParallelismShape, build_inventory,
    coords_of, rank_of,
)


def _cr(tp=1, pp=1, ep=1, dp=1, agents=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=pp,
                          ep=ep, dp=dp),
        requirements=[],
        agents=agents or [Agent(kind=AgentKind.COMPUTE_TILE, count=tp * pp * ep * dp)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )


def _ranks(shape):
    return tuple(LogicalRank(
        rank=r, **coords_of(r, tp=shape.tp, pp=shape.pp,
                            ep=shape.ep, dp=shape.dp))
        for r in range(shape.world_size))


SHAPES = [ParallelismShape(*d) for d in (
    (1, 1, 1, 1), (2, 1, 1, 1), (2, 2, 1, 1),
    (2, 2, 2, 1), (2, 2, 2, 2), (3, 2, 2, 2),
)]


# ══════════════════════════════════════════════════════════════════════════════
# §30/31 — global agent identity
# ══════════════════════════════════════════════════════════════════════════════

def test_duplicate_kind_groups_produce_distinct_instances():
    cr = _cr(agents=[
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, protocol="CHI",
              clock_domain="clk_fast"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, protocol="AXI",
              clock_domain="clk_slow"),
    ])
    inv = build_inventory(cr)
    ids = [a.instance_id for a in inv.agents]
    assert ids == [
        "agent_group[0]/compute_tile[0]",
        "agent_group[0]/compute_tile[1]",
        "agent_group[1]/compute_tile[0]",
        "agent_group[1]/compute_tile[1]",
    ]
    assert len(ids) == len(set(ids))


def test_group_swap_changes_design_hash():
    fast = Agent(kind=AgentKind.COMPUTE_TILE, count=2, protocol="CHI")
    slow = Agent(kind=AgentKind.COMPUTE_TILE, count=2, protocol="AXI")
    a = _cr(agents=[fast, slow])
    b = _cr(agents=[slow, fast])
    assert a.design_hash() != b.design_hash()
    assert [x.instance_id for x in build_inventory(a).agents] == [
        x.instance_id for x in build_inventory(b).agents]


def test_agent_instance_id_format():
    a = AgentInstance(group_index=2, instance_index=3,
                      kind=AgentKind.HBM_CONTROLLER)
    assert a.instance_id == "agent_group[2]/hbm_controller[3]"


def test_agent_instance_to_dict_has_explicit_fields():
    a = AgentInstance(group_index=0, instance_index=2, kind=AgentKind.COMPUTE_TILE)
    assert a.to_dict() == {"group_index": 0, "instance_index": 2,
                           "kind": "compute_tile"}


@pytest.mark.parametrize("kwargs", [
    {"group_index": True, "instance_index": 0, "kind": AgentKind.COMPUTE_TILE},
    {"group_index": 0, "instance_index": 0.0, "kind": AgentKind.COMPUTE_TILE},
    {"group_index": 0, "instance_index": 0, "kind": "compute_tile"},
    {"group_index": -1, "instance_index": 0, "kind": AgentKind.COMPUTE_TILE},
    {"group_index": 0, "instance_index": -1, "kind": AgentKind.COMPUTE_TILE},
])
def test_agent_instance_strict_validation(kwargs):
    with pytest.raises(ValueError):
        AgentInstance(**kwargs)


def test_inventory_rejects_duplicate_agent_identity():
    a = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    with pytest.raises(ValueError, match="duplicate source-instance coordinate"):
        NodeInventory(parallelism=ParallelismShape(1, 1, 1, 1),
                      agents=(a, a),
                      ranks=_ranks(ParallelismShape(1, 1, 1, 1)))


def test_inventory_rejects_duplicate_source_instance_coordinate():
    """Same (group, instance) with differing kind still collides."""
    a = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    b = AgentInstance(0, 0, AgentKind.HBM_CONTROLLER)
    with pytest.raises(ValueError, match="duplicate source-instance coordinate"):
        NodeInventory(parallelism=ParallelismShape(1, 1, 1, 1),
                      agents=(a, b),
                      ranks=_ranks(ParallelismShape(1, 1, 1, 1)))


def test_inventory_allows_same_instance_index_in_different_groups():
    shape = ParallelismShape(1, 1, 1, 1)
    inv = NodeInventory(
        parallelism=shape,
        agents=(AgentInstance(0, 0, AgentKind.COMPUTE_TILE),
                AgentInstance(1, 0, AgentKind.COMPUTE_TILE)),
        ranks=_ranks(shape))
    assert inv.agent_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# §36 — exhaustive rank space
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: f"{s.tp}x{s.pp}x{s.ep}x{s.dp}")
def test_rank_space_round_trips(shape):
    seen = set()
    for tp_i in range(shape.tp):
        for pp_i in range(shape.pp):
            for ep_i in range(shape.ep):
                for dp_i in range(shape.dp):
                    r = rank_of(tp_i, pp_i, ep_i, dp_i, tp=shape.tp,
                                pp=shape.pp, ep=shape.ep, dp=shape.dp)
                    seen.add(r)
                    assert coords_of(r, tp=shape.tp, pp=shape.pp,
                                     ep=shape.ep, dp=shape.dp) == {
                        "tp": tp_i, "pp": pp_i, "ep": ep_i, "dp": dp_i}
    assert seen == set(range(shape.world_size))


# ══════════════════════════════════════════════════════════════════════════════
# §37/38/39 — invalid dimensions, coordinates, ranks
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [0, -1, 1.0, True])
@pytest.mark.parametrize("dim", ["tp", "pp", "ep", "dp"])
def test_parallelism_shape_rejects_bad_dimensions(dim, bad):
    dims = {"tp": 1, "pp": 1, "ep": 1, "dp": 1}
    dims[dim] = bad
    with pytest.raises(ValueError):
        ParallelismShape(**dims)


@pytest.mark.parametrize("bad", [0, -1, 1.0, True])
@pytest.mark.parametrize("dim", ["tp", "pp", "ep", "dp"])
def test_rank_of_rejects_bad_dimensions(dim, bad):
    dims = {"tp": 1, "pp": 1, "ep": 1, "dp": 1}
    dims[dim] = bad
    with pytest.raises(ValueError):
        rank_of(0, 0, 0, 0, **dims)


@pytest.mark.parametrize("bad", [0, -1, 1.0, True])
@pytest.mark.parametrize("dim", ["tp", "pp", "ep", "dp"])
def test_coords_of_rejects_bad_dimensions(dim, bad):
    dims = {"tp": 1, "pp": 1, "ep": 1, "dp": 1}
    dims[dim] = bad
    with pytest.raises(ValueError):
        coords_of(0, **dims)


@pytest.mark.parametrize("axis,val", [("tp", -1), ("tp", 2), ("pp", -1),
                                      ("pp", 2), ("ep", -1), ("ep", 2),
                                      ("dp", -1), ("dp", 2)])
def test_rank_of_rejects_bad_coordinates(axis, val):
    coords = {"tp": 0, "pp": 0, "ep": 0, "dp": 0}
    coords[axis] = val
    with pytest.raises(ValueError):
        rank_of(tp_i=coords["tp"], pp_i=coords["pp"], ep_i=coords["ep"],
                dp_i=coords["dp"], tp=2, pp=2, ep=2, dp=2)


@pytest.mark.parametrize("axis,val", [("tp", 0.0), ("pp", True),
                                      ("ep", -1), ("dp", 2)])
def test_rank_of_rejects_non_integer_coordinates(axis, val):
    coords = {"tp": 0, "pp": 0, "ep": 0, "dp": 0}
    coords[axis] = val
    with pytest.raises(ValueError):
        rank_of(tp_i=coords["tp"], pp_i=coords["pp"], ep_i=coords["ep"],
                dp_i=coords["dp"], tp=2, pp=2, ep=2, dp=2)


@pytest.mark.parametrize("rank", [-1, 16, 100, 1.0, True])
def test_coords_of_rejects_out_of_range_rank(rank):
    with pytest.raises(ValueError):
        coords_of(rank, tp=2, pp=2, ep=2, dp=2)


# ══════════════════════════════════════════════════════════════════════════════
# §40/41 — NodeInventory proves rank coherence
# ══════════════════════════════════════════════════════════════════════════════

def test_inventory_rejects_bogus_coordinates():
    shape = ParallelismShape(2, 1, 1, 1)
    ranks = (LogicalRank(rank=0, tp=1, pp=0, ep=0, dp=0),
             LogicalRank(rank=1, tp=1, pp=0, ep=0, dp=0))
    with pytest.raises(ValueError, match="canonical coordinates"):
        NodeInventory(parallelism=shape, agents=(), ranks=ranks)


@pytest.mark.parametrize("ranks", [
    (LogicalRank(0, 0, 0, 0, 0), LogicalRank(1, 1, 0, 0, 0),
     LogicalRank(2, 0, 0, 1, 0)),  # 3 != world 4
    tuple(LogicalRank(r, r % 2, 0, (r // 2) % 2, 0) for r in range(5)),  # 5
    (LogicalRank(0, 0, 0, 0, 0), LogicalRank(1, 1, 0, 0, 0),
     LogicalRank(2, 0, 0, 1, 0), LogicalRank(4, 1, 0, 1, 0)),  # gap
])
def test_inventory_rejects_bad_rank_namespace(ranks):
    with pytest.raises(ValueError):
        NodeInventory(parallelism=ParallelismShape(2, 1, 2, 1), agents=(),
                      ranks=ranks)


def test_inventory_requires_parallelism_shape():
    with pytest.raises(ValueError, match="ParallelismShape"):
        NodeInventory(parallelism=(2, 1, 1, 1), agents=(), ranks=())


# ══════════════════════════════════════════════════════════════════════════════
# §42 — hardware inventory stays separate from active ranks
# ══════════════════════════════════════════════════════════════════════════════

def test_hardware_agents_remain_separate_from_active_ranks():
    cr = _cr(tp=2, pp=1, ep=2, dp=1, agents=[
        Agent(kind=AgentKind.COMPUTE_TILE, count=64),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=8),
    ])
    inv = build_inventory(cr)
    assert inv.agent_count == 72
    assert len(inv.compute_instances) == 64
    assert inv.rank_count == 4
    assert inv.parallelism.world_size == 4


def test_parallelism_shapeto_dict_round_trips():
    assert ParallelismShape(8, 2, 4, 1).to_dict() == {
        "tp": 8, "pp": 2, "ep": 4, "dp": 1}


def test_build_inventory_to_dict_shape():
    inv = build_inventory(_cr(tp=2, pp=1, ep=2, dp=1))
    d = inv.to_dict()
    assert d["parallelism"] == {"tp": 2, "pp": 1, "ep": 2, "dp": 1}
    assert d["agents"][0] == {"group_index": 0, "instance_index": 0,
                              "kind": "compute_tile"}
    assert d["ranks"][0] == {"rank": 0, "tp": 0, "pp": 0, "ep": 0, "dp": 0}
