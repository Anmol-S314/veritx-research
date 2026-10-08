"""SROTA materialization: MECS is a SHARED (multidrop) resource, never flattened.

These pin the properties that decide whether the artifact is a faithful
description of the SROTA Plane D:

  * the source's port order (XNEG, XPOS, YNEG, YPOS, skipping absent
    directions) is the single contract between builder and router;
  * MECS express channels are one driver feeding many taps, so they are
    SharedLink objects — flattening them to independent directed channels
    would model N wires where the hardware has one;
  * tap in-degree is 2(k-1) with both dimensions express, which is the
    "cheap passive taps, expensive active drivers" asymmetry the design
    exists for;
  * island columns materialize as PLACEMENT (the colfirst rule is
    proved by the shape union); the control plane still refuses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    TopologyError,
    materialize_srota,
    materialize_topology_intent,
)
from veritx_dse.model.srota_intent import SrotaIntent  # noqa: E402


def _intent(**over):
    base = {
        "kind": "srota", "side_length": 4, "concentration": 2,
        "mecs_row": True, "mecs_col": True, "drop_latency": 1,
        "planes": ["d", "t"], "island_columns": [], "path_shapes": ["row"],
        "vc_policy": "none", "sidebuf_enable": True, "sidebuf_watermark": 6,
        "tel_period": 4, "tel_latency": 8,
    }
    base.update(over)
    return SrotaIntent.from_dict(base)


def _inventory(count: int):
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, Workload,
    )
    from veritx_dse.model.placement import build_inventory
    return build_inventory(CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1,
                          dp=1),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=count)],
        dependencies=[], noc_config=NocConfig()))


def test_full_mecs_is_all_shared_links_and_no_flattening():
    art = materialize_srota(k=4, concentration=2, mecs_row=True,
                            mecs_col=True)
    assert art.family == MaterializedFamily.SROTA
    assert art.router_count == 16
    assert art.channel_count == 0, (
        "both dimensions are express, so every direction port is a shared "
        "segment; any point-to-point channel here would be a flattening")
    # Every router drives one segment per present direction: 4k(k-1).
    assert len(art.shared_links) == 4 * 4 * 3


def test_tap_indegree_is_two_k_minus_one():
    """TOPO-003 3.2: cheap passive taps are the point of MECS."""
    k, c = 4, 2
    art = materialize_srota(k=k, concentration=c, mecs_row=True,
                            mecs_col=True)
    taps = {r: 0 for r in range(k * k)}
    for link in art.shared_links:
        for tap in link.taps:
            taps[tap] += 1
    assert set(taps.values()) == {2 * (k - 1)}


def test_mecs_off_falls_back_to_point_to_point_links():
    art = materialize_srota(k=4, concentration=1, mecs_row=False,
                            mecs_col=False)
    assert art.shared_links == ()
    # 2*k*(k-1) undirected mesh edges, each realized as two directed channels.
    k = 4
    assert art.channel_count == 4 * k * (k - 1)


def test_one_dimension_express_one_plain():
    art = materialize_srota(k=4, concentration=1, mecs_row=True,
                            mecs_col=False)
    # Only the Y direction is a shared segment now: 2k(k-1) of them.
    assert len(art.shared_links) == 2 * 4 * 3
    assert art.channel_count > 0


def test_shared_links_are_canonically_ordered_and_contiguous():
    art = materialize_srota(k=4, concentration=2, mecs_row=True,
                            mecs_col=True)
    ids = [s.shared_link_id for s in art.shared_links]
    assert ids == list(range(len(ids)))
    assert art.router_count == len(art.routers)
    assert [r.router_id for r in art.routers] == list(range(16))


def test_identity_is_content_addressed_and_moves_with_the_design():
    a = materialize_srota(k=4, concentration=2, mecs_row=True, mecs_col=True)
    b = materialize_srota(k=4, concentration=2, mecs_row=True, mecs_col=True)
    c = materialize_srota(k=4, concentration=1, mecs_row=True, mecs_col=True)
    assert a.topology_hash() == b.topology_hash()
    assert a.topology_hash() != c.topology_hash()


def test_islands_materialize_as_placement_not_an_unwrapped_fabric():
    art = materialize_topology_intent(
        _inventory(32), _intent(island_columns=[1]))
    assert art.island_columns == (1,)
    # The placement is identity: an island fabric is a different artifact.
    assert art.topology_hash() != materialize_topology_intent(
        _inventory(32), _intent()).topology_hash()


def test_valiant_materializes_the_same_fabric_it_routes_over():
    """Valiant is a ROUTING shape over the same Plane D wires (both legs
    are row-first), so it must NOT be refused at materialization — it
    changes the route, never the topology. The rank VC policy is what
    proves it (test_srota_rank_valiant.py)."""
    art = materialize_topology_intent(
        _inventory(32), _intent(path_shapes=["row", "valiant"],
                                vc_policy="rank"))
    assert art.family is MaterializedFamily.SROTA
    assert art.channel_count == 0
    assert art.shared_links


def test_control_plane_materializes_as_a_second_plane():
    art = materialize_topology_intent(
        _inventory(32), _intent(planes=["d", "c", "t"]))
    assert "c" in art.planes
    assert art.planes == ("c", "d", "t")
    # A single-plane fabric is unchanged.
    plain = materialize_topology_intent(_inventory(32), _intent())
    assert plain.planes == ("d", "t")
    assert art.topology_hash() != plain.topology_hash()


def test_direct_planes_materialize_through_the_intent_seam():
    art = materialize_topology_intent(_inventory(32), _intent())
    assert art.family == MaterializedFamily.SROTA
    assert art.seat_capacity == 32
