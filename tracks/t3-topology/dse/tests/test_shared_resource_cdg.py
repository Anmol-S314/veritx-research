"""The shared-resource deadlock graph, checked against hand-computed answers.

This fabric exists for one reason: to be small enough that the expected
dependency graph can be written down by hand, independently of the code that
builds it. Every edge assertion below is derived on paper first, so a
disagreement is a real defect rather than a restatement of the implementation.

Topology (one VC, deterministic routing):

    R0 ── bus A ──> R1
        └─────────> R2
    R1 ── bus B ──> R3
    R2 ── bus C ──> R3

    R0 → R3 takes bus A (tap 0, lands at R1), then bus B.

and the triangular fabric, which is the smallest case that MUST be reported
as a cycle:

    R0 ── A ──> R1 ── B ──> R2 ── C ──> R0
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.shared_resource import (  # noqa: E402
    ResourceKind,
    ResourceRef,
    RouteDecision,
    SharedResourceError,
)
from veritx_dse.model.srota_shape_vc_policy import (  # noqa: E402
    SrotaShapeVCPartitionPolicy,
)
from veritx_dse.verification.shared_resource_cdg import (  # noqa: E402
    SharedResourceCDGError,
    build_shared_resource_cdg,
    shared_resources_of,
)

A = ResourceRef(ResourceKind.SHARED_LINK, 0)
B = ResourceRef(ResourceKind.SHARED_LINK, 1)
C = ResourceRef(ResourceKind.SHARED_LINK, 2)


def _bus(resource, next_router, tap=0, partition=0):
    return RouteDecision(resource=resource, next_router=next_router,
                         vc_partition=partition, tap=tap)


def _chain_decisions():
    # 0→1 is a one-bus trip; 0→2 leaves bus A at tap 1; 0→3 rides A then B.
    return {
        (0, 1): _bus(A, 1, tap=0),
        (0, 2): _bus(A, 2, tap=1),
        (0, 3): _bus(A, 1, tap=0),
        (1, 3): _bus(B, 3, tap=0),
        (2, 3): _bus(C, 3, tap=0),
    }


def _triangle_decisions():
    return {
        (0, 1): _bus(A, 1),
        (0, 2): _bus(A, 1),
        (1, 2): _bus(B, 2),
        (1, 0): _bus(B, 2),
        (2, 0): _bus(C, 0),
        (2, 1): _bus(C, 0),
    }


def test_chain_has_exactly_the_hand_derived_edge():
    cdg = build_shared_resource_cdg(
        decisions=_chain_decisions(), partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))
    # Hand derivation: only 0→3 spans two buses, so A→B is the single edge.
    assert cdg.edges == (((A, 0), (B, 0)),)
    assert cdg.nodes == ((A, 0), (B, 0), (C, 0))
    assert cdg.find_cycle() is None
    assert cdg.unused_transitions == ()


def test_chain_resources_are_named_individually_not_collapsed():
    decisions = _chain_decisions()
    assert shared_resources_of(decisions) == (A, B, C)
    # Every shared hop must carry a tap; there is no tap-free shared hop.
    assert all(d.tap is not None for d in decisions.values())


def test_triangle_is_reported_as_the_exact_hand_derived_cycle():
    cdg = build_shared_resource_cdg(
        decisions=_triangle_decisions(), partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2))
    assert set(cdg.edges) == {((A, 0), (B, 0)), ((B, 0), (C, 0)),
                              ((C, 0), (A, 0))}
    cycle = cdg.find_cycle()
    assert cycle is not None, "the triangular bus fabric must be a cycle"
    assert cycle[0] == cycle[-1], "a reported cycle must close on itself"
    assert set(cycle) == {(A, 0), (B, 0), (C, 0)}


def test_a_private_channel_hop_is_not_a_tap_hop():
    """The two resource kinds must not be interchangeable."""
    with pytest.raises(SharedResourceError, match="MUST name the tap"):
        RouteDecision(resource=A, next_router=1)
    with pytest.raises(SharedResourceError, match="cannot name tap"):
        RouteDecision(resource=ResourceRef(ResourceKind.CHANNEL, 3),
                      next_router=1, tap=0)
    # The same id in two kinds is two different resources, not one.
    assert ResourceRef(ResourceKind.CHANNEL, 7) != \
        ResourceRef(ResourceKind.SHARED_LINK, 7)


def test_overlapping_partitions_are_refused_not_reasoned_about():
    with pytest.raises(SharedResourceCDGError, match="disjoint"):
        build_shared_resource_cdg(
            decisions=_chain_decisions(),
            partition_to_vcs={0: (0, 1), 1: (1, 2)},
            allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))


def test_an_unrealizable_hop_is_a_declaration_error_not_a_cycle():
    decisions = _chain_decisions()
    del decisions[(1, 3)]
    with pytest.raises(SharedResourceCDGError, match="not realizable"):
        build_shared_resource_cdg(
            decisions=decisions, partition_to_vcs={0: (0,)},
            allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))


def test_ineligible_transition_adds_no_edge_and_is_reported():
    """Eligibility is what the partition actually buys.

    The 0->3 route is two TRANSIT hops, the first requiring partition 0 and
    the second partition 1. The only permitted transition leaves on VC 0,
    which partition 1 does not own, so the second hop is unreachable on that
    VC and no edge may be invented. (A terminal hop is exempt — see
    test_terminal_ejection_is_not_a_partition_member — which is why this
    case needs a two-hop route rather than a one-hop one.)
    """
    decisions = {
        (0, 3): _bus(A, 1, tap=0, partition=0),
        (1, 3): _bus(B, 2, tap=0, partition=1),
        (2, 3): _bus(C, 3, tap=0, partition=1),
    }
    cdg = build_shared_resource_cdg(
        decisions=decisions,
        partition_to_vcs={0: (0,), 1: (1,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))
    assert cdg.edges == ()
    assert cdg.unused_transitions == ((0, 0),)
    assert cdg.find_cycle() is None

def test_terminal_ejection_is_not_a_partition_member():
    """A hop that ENDS the route accepts whatever VC arrived on.

    Modelling the eject port as a partition member would pretend only one
    tap's VCs may eject, which is wrong: the destination imposes nothing on
    a successor because it has none.
    """
    decisions = {
        (0, 2): _bus(A, 1, tap=0, partition=0),
        (1, 2): _bus(B, 2, tap=0, partition=1),
    }
    # Ejecting is not an allocation step, so the arriving VC is the one the
    # flit leaves on: the only realizable transition here is identity.
    identity = build_shared_resource_cdg(
        decisions=decisions,
        partition_to_vcs={0: (0,), 1: (1,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2))
    assert identity.edges == (((A, 0), (B, 0)),)
    assert identity.find_cycle() is None

    # A transition that tries to CHANGE VC on the eject hop is not something
    # the hardware does, so it yields no edge instead of a fictitious one.
    changed = build_shared_resource_cdg(
        decisions=decisions,
        partition_to_vcs={0: (0,), 1: (1,)},
        allowed_transitions=((0, 1),), routers=(0, 1, 2))
    assert changed.edges == ()
    assert changed.unused_transitions == ((0, 1),)


def test_unknown_partition_refuses():
    decisions = _chain_decisions()
    decisions[(0, 3)] = _bus(A, 1, tap=0, partition=9)
    with pytest.raises(SharedResourceCDGError, match="no VC mapping"):
        build_shared_resource_cdg(
            decisions=decisions, partition_to_vcs={0: (0,)},
            allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))


def test_decisions_round_trip_and_identity_is_content_addressed():
    decision = RouteDecision(resource=A, next_router=2, vc_partition=1, tap=3)
    assert RouteDecision.from_dict(decision.to_dict()) == decision
    assert ResourceRef.from_dict(A.to_dict()) == A

    base = build_shared_resource_cdg(
        decisions=_chain_decisions(), partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))
    same = build_shared_resource_cdg(
        decisions=_chain_decisions(), partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))
    other = build_shared_resource_cdg(
        decisions=_triangle_decisions(), partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2))
    assert base.cdg_id() == same.cdg_id()
    assert base.cdg_id() != other.cdg_id()


def test_a_self_keyed_row_is_a_local_route_at_concentration_one():
    """With c == 1 a terminal id IS a router id, so (r, r) is a zero-hop
    route that only ejects. It must be legal, and it must be a sink."""
    legal = {**_chain_decisions(), (2, 2): _bus(C, 2)}
    cdg = build_shared_resource_cdg(
        decisions=legal, partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1, 2, 3))
    assert cdg.find_cycle() is None
    assert ((C, 0), (C, 0)) not in cdg.edges, "an eject must not self-depend"

def test_a_terminal_is_not_its_own_router_when_concentrated():
    """The bug this guards: with c > 1, terminal n belongs to router n//c.

    Router 1 has terminals 2 and 3. A row keyed (1, 3) is therefore a route
    from router 1 to router 1 -- a zero-hop local delivery -- and must be
    recognized as terminal, not as a hop to router 3.
    """
    a = ResourceRef(ResourceKind.SHARED_LINK, 10)
    decisions = {
        (1, 3): _bus(a, 1, tap=0),      # router 1 -> its OWN terminal 3
        (0, 3): _bus(ResourceRef(ResourceKind.SHARED_LINK, 11), 1, tap=0),
    }
    node_to_router = {0: 0, 1: 0, 2: 1, 3: 1}
    cdg = build_shared_resource_cdg(
        decisions=decisions, partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1),
        node_to_router=node_to_router)
    # (1,3) is local delivery, so it contributes no edge from the shared wire.
    assert cdg.edges == ()
    # Without the terminal map, (1,3) is mis-read as a hop TOWARD router 3,
    # so the graph gains an edge that does not exist. That is the failure the
    # map exists to prevent, and it is silent: no exception, just a wrong
    # dependency graph.
    misread = build_shared_resource_cdg(
        decisions=decisions, partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=(0, 1))
    assert misread.edges != (), (
        "the fixture must actually expose the mis-read it guards against")


# ---------------------------------------------------------------------------
# The RT-R7 hazard, on a fixture.
#
# SROTA.md records the real hazard: with both direct shapes live and no VC
# separation, the MECS dependency graph closes a FOUR-resource cycle. The
# four resources below are exactly the four segments that cycle names, and
# the two tables differ ONLY in whether each hop declares which shape it
# belongs to.
#
#     2x2 router grid, unidirectional buses
#       a = R0C0, b = R0C1, c = R1C1, d = R1C0
#       R0P a->b   R1N c->d      (row buses)
#       C1P b->c   C0N d->a      (column buses)
#
#     row-first  a -> c : R0P then C1P
#     column-first b -> d : C1P then R1N
#     row-first  c -> a : R1N then C0N
#     column-first d -> b : C0N then R0P
# ---------------------------------------------------------------------------
A_, B_, C_, D_ = 0, 1, 2, 3
R0P = ResourceRef(ResourceKind.SHARED_LINK, 0)
R1N = ResourceRef(ResourceKind.SHARED_LINK, 1)
C1P = ResourceRef(ResourceKind.SHARED_LINK, 2)
C0N = ResourceRef(ResourceKind.SHARED_LINK, 3)

ROW_FIRST, COLUMN_FIRST = 0, 1

_RTR7_HOPS = {
    # (src, dst): (resource, landing router, which shape's hops these are)
    (A_, C_): (R0P, B_, ROW_FIRST),
    (B_, C_): (C1P, C_, ROW_FIRST),
    (A_, B_): (R0P, B_, COLUMN_FIRST),
    (B_, D_): (C1P, C_, COLUMN_FIRST),
    (C_, D_): (R1N, D_, COLUMN_FIRST),
    (D_, B_): (C0N, A_, COLUMN_FIRST),
    (C_, A_): (R1N, D_, ROW_FIRST),
    (D_, A_): (C0N, A_, ROW_FIRST),
}


def _rtr7_decisions(*, shape_partition: bool):
    return {
        key: _bus(resource, nxt, tap=0,
                  partition=(shape if shape_partition else 0))
        for key, (resource, nxt, shape) in _RTR7_HOPS.items()
    }

_RTR7_ROUTERS = (A_, B_, C_, D_)

def test_rt_r7_hazard_is_reproduced_on_the_fixture():
    """No shape separation: the documented four-resource cycle must appear."""
    cdg = build_shared_resource_cdg(
        decisions=_rtr7_decisions(shape_partition=False),
        partition_to_vcs={0: (0,)},
        allowed_transitions=((0, 0),), routers=_RTR7_ROUTERS)
    assert set(cdg.edges) == {
        ((R0P, 0), (C1P, 0)),
        ((C1P, 0), (R1N, 0)),
        ((R1N, 0), (C0N, 0)),
        ((C0N, 0), (R0P, 0)),
    }
    cycle = cdg.find_cycle()
    assert cycle is not None, (
        "the mixed-shape MECS fabric must reproduce the RT-R7 hazard")
    assert set(cycle) == {(R0P, 0), (C1P, 0), (R1N, 0), (C0N, 0)}

def test_shape_partition_separation_breaks_the_rt_r7_cycle():
    """Same four resources, same hops, same order — only eligibility differs.

    This is the whole claim of the shared-resource design under test: giving
    each shape its own VC partition makes the four-hop cycle unrealizable,
    because a hop may only continue on a VC its own shape owns.
    """
    policy = SrotaShapeVCPartitionPolicy.derive(2)
    cdg = build_shared_resource_cdg(
        decisions=_rtr7_decisions(shape_partition=True),
        partition_to_vcs=policy.partition_to_vcs,
        allowed_transitions=policy.allowed_transitions,
        routers=_RTR7_ROUTERS)
    assert cdg.find_cycle() is None, (
        f"shape separation must break RT-R7, got {cdg.find_cycle()}")
    # The edges that survive are exactly the two-shape chains, never a turn
    # back across shapes.
    assert set(cdg.edges) == {
        ((R0P, 0), (C1P, 0)),
        ((R1N, 0), (C0N, 0)),
        ((C1P, 1), (R1N, 1)),
        ((C0N, 1), (R0P, 1)),
    }
    # And no resource is reached under one shape and left under the other.
    for (resource_in, vc_in), (resource_out, vc_out) in cdg.edges:
        assert vc_in == vc_out
