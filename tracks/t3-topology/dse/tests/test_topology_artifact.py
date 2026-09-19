"""Wave B3.1 tests — materialized TopologyArtifact semantics."""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    TopologyError, materialize_family, materialize_topology,
)


def _cr(agents, family=TopologyFamily.MESH, radix=None, concentration=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[],
        agents=agents,
        dependencies=[],
        noc_config=NocConfig(topology_family=family, radix=radix,
                             concentration=concentration),
    )


def _compute(n):
    return [Agent(kind=AgentKind.COMPUTE_TILE, count=n)]


def _materialized(n=1, **kw):
    cr = _cr(_compute(n), **kw)
    return materialize_topology(build_inventory(cr), cr)


# ── sizing from hardware inventory, not model ranks ─────────────────────────

def test_sixty_four_agents_gives_8x8_mesh():
    t = _materialized(64)
    assert t.router_count == 64
    assert t.family == MaterializedFamily.MESH
    assert t.routers[0].coordinates == (0, 0)
    assert t.routers[63].coordinates == (7, 7)
    # undirected mesh edges = 2*k*(k-1) = 112; directed channels = 224
    assert t.channel_count == 224


def test_sixteen_agents_gives_4x4_mesh():
    t = _materialized(16)
    assert t.router_count == 16 and t.channel_count == 48


def test_non_square_agent_count_rounds_up():
    # 8 agents, k=ceil(sqrt(8))=3 -> 9 routers (9 seats, 1 idle)
    t = _materialized(8)
    assert t.router_count == 9
    assert t.seat_capacity == 9


def test_hardware_agents_include_non_compute():
    cr = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=64),
              Agent(kind=AgentKind.HBM_CONTROLLER, count=8)])
    inv = build_inventory(cr)
    t = materialize_topology(inv, cr)
    assert inv.agent_count == 72 and inv.rank_count == 1
    assert t.router_count == 81  # k=ceil(sqrt(72))=9
    assert t.seat_capacity == 81


def test_concentrated_mesh_default_concentration():
    t = _materialized(64, family=TopologyFamily.CONCENTRATED_MESH)
    assert t.router_count == 16           # 64 endpoints / 4 seats
    assert t.seat_capacity == 64
    assert t.routers[0].seat_capacity == 4


def test_explicit_concentration_overrides_default():
    t = _materialized(64, family=TopologyFamily.CONCENTRATED_MESH,
                      concentration=2)
    # 64/2 = 32 routers needed; a square mesh rounds to k=6 -> 36
    assert t.router_count == 36
    assert t.seat_capacity == 72


def test_radix_pins_k_and_must_provide_seats():
    t = _materialized(64, radix=8)
    assert t.router_count == 64
    with pytest.raises(TopologyError, match="seats"):
        _materialized(64, radix=4)  # 16 seats < 64 agents


def test_torus_wraps_and_has_degree_four():
    t = materialize_family(MaterializedFamily.TORUS, endpoint_count=16)
    assert t.router_count == 16
    assert t.channel_count == 64  # 4 outgoing per router


def test_ring_family():
    t = materialize_family(MaterializedFamily.RING, endpoint_count=5)
    assert t.router_count == 5 and t.channel_count == 10


def test_gec_and_fattree_refused_not_downgraded():
    for fam in (TopologyFamily.GEC, TopologyFamily.FAT_TREE):
        with pytest.raises(TopologyError, match="not materializable"):
            _materialized(16, family=fam)


# ── canonical numbering and structure ───────────────────────────────────────

def test_router_ids_and_coordinates_are_canonical():
    t = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert [r.router_id for r in t.routers] == list(range(16))
    assert t.routers[5].coordinates == (1, 1)  # row-major: id = y*k + x


def test_channel_ids_contiguous_and_sorted():
    t = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert [c.channel_id for c in t.channels] == list(range(t.channel_count))
    keys = [(c.src_router, c.src_port, c.dst_router, c.dst_port)
            for c in t.channels]
    assert keys == sorted(keys)


def test_local_seats_precede_link_ports():
    t = materialize_family(MaterializedFamily.CONCENTRATED_MESH,
                           endpoint_count=8, concentration=2)
    # 8 endpoints / 2 = 4 routers -> k=2; each router has 2 local seats
    r0 = t.routers[0]
    assert r0.seat_capacity == 2
    first = min((c for c in t.channels if c.src_router == 0),
                key=lambda c: c.src_port)
    assert first.src_port >= 2


def test_channels_carry_width_and_latency_from_noc():
    t = materialize_topology(
        build_inventory(_cr(_compute(16))),
        NocConfig(topology_family=TopologyFamily.MESH, link_width=512))
    assert all(c.width_bits == 512 for c in t.channels)
    assert all(c.latency_cycles >= 1 for c in t.channels)


# ── identity ────────────────────────────────────────────────────────────────

def test_topology_hash_stable_and_size_sensitive():
    a = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    b = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    c = materialize_family(MaterializedFamily.MESH, endpoint_count=64)
    assert a.topology_hash() == b.topology_hash()
    assert a.topology_hash() != c.topology_hash()
    assert len(a.topology_hash()) == 64


def test_round_trip_and_tamper_detection():
    t = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    d = t.to_dict()
    assert TopologyArtifact.from_dict(d).topology_hash() == t.topology_hash()
    d["routers"][0]["seat_capacity"] = 99
    with pytest.raises(TopologyError, match="does not match content"):
        TopologyArtifact.from_dict(d)


def test_unknown_fields_refused():
    t = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    d = t.to_dict()
    d["extra"] = 1
    with pytest.raises(TopologyError, match="unknown fields"):
        TopologyArtifact.from_dict(d)


def test_self_loop_channel_refused():
    with pytest.raises(TopologyError, match="self-loop"):
        DirectedChannel(channel_id=0, src_router=0, src_port=1,
                        dst_router=0, dst_port=1, width_bits=64,
                        latency_cycles=1)


def test_contiguous_router_ids_enforced():
    with pytest.raises(TopologyError, match="contiguous"):
        TopologyArtifact(family=MaterializedFamily.MESH,
                         routers=(Router(1, (0, 0), 1),), channels=())
