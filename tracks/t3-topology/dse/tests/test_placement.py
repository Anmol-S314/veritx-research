"""Wave B2.1 tests — node semantics: explicit universes, full 4D ranks."""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import (
    AgentInstance, LogicalRank, NodeInventory, build_inventory, coords_of,
    rank_of,
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


# ── rank coordinate conversions ────────────────────────────────────────────

def test_rank_of_and_coords_of_roundtrip():
    world = dict(tp=2, pp=3, ep=2, dp=2)
    n = 2 * 3 * 2 * 2
    seen = set()
    for tp_i in range(2):
        for pp_i in range(3):
            for ep_i in range(2):
                for dp_i in range(2):
                    r = rank_of(tp_i, pp_i, ep_i, dp_i, **world)
                    assert 0 <= r < n
                    seen.add(r)
                    assert coords_of(r, **world) == {
                        "tp": tp_i, "pp": pp_i, "ep": ep_i, "dp": dp_i}
    assert seen == set(range(n))


def test_coords_of_rejects_out_of_range_rank():
    with pytest.raises(ValueError):
        coords_of(4, tp=2, pp=2, ep=1, dp=1)


# ── explicit universes ─────────────────────────────────────────────────────

def test_workload_world_size_is_full_4d_product():
    w = Workload(model_family=ModelFamily.MOE, tp=2, pp=3, ep=4, dp=5)
    assert w.world_size == 120


def test_total_npus_is_deprecated_alias_for_world_size():
    w = Workload(model_family=ModelFamily.MOE, tp=2, pp=3, ep=4, dp=5)
    assert w.total_npus == w.world_size == 120


def test_build_inventory_expands_agents_and_ranks():
    cr = _cr(tp=2, pp=2, ep=2, dp=2)
    inv = build_inventory(cr)
    assert inv.agent_count == 16
    assert inv.rank_count == 16
    assert len(inv.compute_instances) == 16
    assert [r.rank for r in inv.ranks] == list(range(16))


def test_inventory_keeps_fabric_agents_separate_from_ranks():
    """The 4-active-ranks-on-64-compute-instances case must be explicit."""
    cr = _cr(tp=2, pp=1, ep=2, dp=1,
             agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64),
                     Agent(kind=AgentKind.HBM_CONTROLLER, count=8)])
    inv = build_inventory(cr)
    assert inv.rank_count == 4
    assert inv.agent_count == 72
    assert len(inv.compute_instances) == 64
    assert len(inv.instances_of(AgentKind.HBM_CONTROLLER)) == 8


def test_agent_instance_id_is_stable():
    a = AgentInstance(kind=AgentKind.NIC, index=3)
    assert a.instance_id == "nic[3]"


# ── sealing (B1.2 rigor) ───────────────────────────────────────────────────

def test_inventory_requires_tuple_containers():
    a = AgentInstance(kind=AgentKind.COMPUTE_TILE, index=0)
    r = LogicalRank(rank=0, tp=0, pp=0, ep=0, dp=0)
    with pytest.raises(ValueError, match="agents"):
        NodeInventory(agents=[a], ranks=(r,))
    with pytest.raises(ValueError, match="ranks"):
        NodeInventory(agents=(a,), ranks=[r])


def test_inventory_rejects_wrong_element_types():
    with pytest.raises(ValueError):
        NodeInventory(agents=("nope",), ranks=())
    with pytest.raises(ValueError):
        NodeInventory(agents=(), ranks=("nope",))


def test_inventory_rejects_non_contiguous_ranks():
    r0 = LogicalRank(rank=0, tp=0, pp=0, ep=0, dp=0)
    r2 = LogicalRank(rank=2, tp=0, pp=0, ep=0, dp=0)
    with pytest.raises(ValueError, match="contiguous"):
        NodeInventory(agents=(), ranks=(r0, r2))


def test_agent_instance_validates_kind_and_index():
    with pytest.raises(ValueError):
        AgentInstance(kind="compute_tile", index=0)
    with pytest.raises(ValueError):
        AgentInstance(kind=AgentKind.COMPUTE_TILE, index=-1)


def test_logical_rank_rejects_negative_coords():
    with pytest.raises(ValueError):
        LogicalRank(rank=0, tp=-1, pp=0, ep=0, dp=0)


def test_inventory_round_trips_through_dict():
    inv = build_inventory(_cr(tp=2, pp=1, ep=2, dp=1))
    d = inv.to_dict()
    assert d["agents"][0] == {"kind": "compute_tile", "index": 0}
    assert d["ranks"][0] == {"rank": 0, "tp": 0, "pp": 0, "ep": 0, "dp": 0}
