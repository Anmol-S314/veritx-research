"""SROTA's two-shape policy, proved as a UNION of runtime choices.

SROTA with ``vc_policy=shape`` does NOT have a deterministic route. The FIU
picks the shape per flow from live telemetry load:

    int const row_load = gSrTel.ColLoad( dx );
    int const col_load = gSrTel.RowLoad( dy );
    if ( row_load < col_load ) return SROTA_ROW_FIRST;
    if ( col_load < row_load ) return SROTA_COL_FIRST;

so ``(src, dst) -> one decision`` is not a function and no single decision
table can hold it. The obligation is therefore over the UNION of both
shapes, separated by VC — which is exactly the static check the fork runs on
its own abstraction.

The negative control is the point of this file: collapsing the two shapes
onto ONE partition must reproduce RT-R7. Without that, "acyclic" would be a
claim about a graph nothing could have made cyclic.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.route_artifact_v3 import (  # noqa: E402
    RouteArtifactV3Error,
    ShapePolicyRoute,
    shape_policy_route_for_srota,
)
from veritx_dse.model.srota_rowfirst_route import (  # noqa: E402
    SrotaRowFirstParams,
)
from veritx_dse.verification.shared_resource_cdg import (  # noqa: E402
    build_shared_resource_cdg,
)
from veritx_dse.model.srota_shape_vc_policy import (  # noqa: E402
    SrotaShapeVCPartitionPolicy,
)

_SHAPE = SrotaRowFirstParams(k=4, c=2, num_vcs=2)


def _union() -> ShapePolicyRoute:
    return shape_policy_route_for_srota(_SHAPE, topology_hash="sha256:test")


def test_the_two_shapes_differ_on_the_same_flow():
    """Same fabric, same wires, opposite first hop — the reason for VCs."""
    union = _union()
    options = union.choices[(0, 15)]
    assert len(options) == 2, options
    partitions = {d.vc_partition for d in options}
    assert partitions == {0, 1}
    first_hops = {d.next_router for d in options}
    assert len(first_hops) == 2, (
        "row-first and column-first must land on DIFFERENT routers for a "
        "diagonal flow, or the two shapes would be the same route")


def test_the_union_is_acyclic_under_the_shape_partition():
    union = _union()
    cdg = union.shared_resource_cdg()
    assert cdg.find_cycle() is None, cdg.find_cycle()
    assert cdg.node_count > 0 and cdg.edge_count > 0, (
        "an acyclic verdict over an empty graph would be vacuous")
    assert union.shape_count == 2
    # The union names every wire the materializer built: 4k(k-1) at k=4.
    assert union.shared_resource_count == 48


def test_shape_union_rejects_lost_adaptive_partition_correlation():
    union = _union()
    with pytest.raises(RouteArtifactV3Error, match="repeats partition"):
        replace(
            union,
            choices={key: tuple(replace(d, vc_partition=0)
                                for d in options)
                     for key, options in union.choices.items()})

    with pytest.raises(RouteArtifactV3Error, match="label every VC partition"):
        replace(union, shape_of_partition={0: "row"})
    with pytest.raises(RouteArtifactV3Error, match="crosses adaptive shape"):
        replace(union, allowed_transitions=((0, 1),))

def test_collapsing_the_shapes_reproduces_rt_r7():
    """THE negative control: without separation the hazard must reappear."""
    union = _union()
    collapsed_choices = {
        key: tuple(replace(d, vc_partition=0) for d in options)
        for key, options in union.choices.items()}
    cycle = build_shared_resource_cdg(
        decisions=collapsed_choices,
        partition_to_vcs={0: (0,)}, allowed_transitions=((0, 0),),
        routers=union.routers,
        node_to_router=union.terminal_to_router).find_cycle()
    assert cycle is not None, (
        "one partition for both shapes must close a cycle; if it does not, "
        "the acyclic result above proves nothing")
    # SROTA.md documents this as a FOUR-resource cycle, not a two-node one:
    # a channel is a driven segment, so the shortest cycle goes round a 2x2
    # square of routers.
    distinct = list(dict.fromkeys(cycle))
    assert len(distinct) == 4, cycle


def test_the_partition_map_comes_from_the_policy_artifact():
    union = _union()
    policy = SrotaShapeVCPartitionPolicy.derive(2)
    assert dict(union.partition_to_vcs) == policy.partition_to_vcs
    assert union.allowed_transitions == policy.allowed_transitions
    assert union.shape_of_partition == {0: "row", 1: "column"}
    # No transition crosses between the two shapes.
    row_vcs = dict(policy.shape_to_vcs)["row"]
    col_vcs = dict(policy.shape_to_vcs)["column"]
    for vc_in, vc_out in union.allowed_transitions:
        assert (vc_in in row_vcs) == (vc_out in row_vcs), (
            "a transition that changes shape would re-open RT-R7")


def test_an_odd_vc_count_leaves_the_remainder_unused_and_says_so():
    """The source integer-divides; a floored slice strands VCs."""
    policy = SrotaShapeVCPartitionPolicy.derive(3)
    assert policy.unused_vcs == (2,), policy
    assert dict(policy.shape_to_vcs) == {"row": (0,), "column": (1,)}


def test_the_union_identity_moves_with_content():
    a = _union()
    b = shape_policy_route_for_srota(_SHAPE, topology_hash="sha256:test")
    c = shape_policy_route_for_srota(SrotaRowFirstParams(k=6, c=1, num_vcs=2),
                                     topology_hash="sha256:test")
    assert a.route_artifact_id() == b.route_artifact_id()
    assert a.route_artifact_id() != c.route_artifact_id()
    altered_terminal_map = dict(a.terminal_to_router)
    altered_terminal_map[0] = 1
    assert replace(a, terminal_to_router=altered_terminal_map).route_artifact_id() \
        != a.route_artifact_id()
