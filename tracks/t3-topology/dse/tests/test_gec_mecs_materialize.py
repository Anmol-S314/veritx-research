"""GEC-MECS materializes as shared wires — and agrees with its own route rule.

Two independent constructions of the same fabric: the MATERIALIZER builds the
wire set from the topology rule, and the ROUTE derivation builds it from the
first-hop rule. They must name the same number of wires, or one of them
describes a network that was never built.

The tap order is the thing to get right, and it is NOT SROTA's: GEC's express
wires are non-directional (one per dimension per group) with taps ordered by
``GEC::_PeerIndex`` — ascending, self skipped. Deriving them per-direction
would put the tap on the wrong router.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.gec_mecs_route import GecMecsParams  # noqa: E402
from veritx_dse.model.route_artifact_v3 import (  # noqa: E402
    route_artifact_v3_for_gec_mecs,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    TopologyError,
    materialize_gec_mecs,
)


@pytest.mark.parametrize("k,c,o,d", [(4, 1, 1, 3), (6, 1, 1, 5), (4, 2, 1, 3)])
def test_wire_count_matches_the_route_rule(k, c, o, d):
    topology = materialize_gec_mecs(k=k, concentration=c, o=o, d=d)
    assert topology.family is MaterializedFamily.GEC_MECS
    assert topology.channel_count == 0, (
        "MECS has no point-to-point channels at all; any channel here would "
        "be a flattened tap")
    # One wire per (router, dimension, group): 2 * o * k^2.
    assert len(topology.shared_links) == 2 * o * k * k
    route = route_artifact_v3_for_gec_mecs(
        GecMecsParams(k=k, c=c, o=o, d=d, num_vcs=d),
        topology_hash=topology.topology_hash())
    assert route.shared_resource_count == len(topology.shared_links)
    route.validate_against(topology)


def test_every_router_drives_two_wires_per_group():
    k, o, d = 4, 1, 3
    topology = materialize_gec_mecs(k=k, concentration=1, o=o, d=d)
    driven = Counter(link.src_router for link in topology.shared_links)
    assert set(driven.values()) == {2 * o}, sorted(driven.items())
    # Every wire taps exactly d destinations, and a router is never its own tap.
    for link in topology.shared_links:
        assert len(link.taps) == d
        assert link.src_router not in link.taps


def test_tap_in_degree_is_two_k_minus_one():
    """Each router is a passive tap on every peer's wire in its row/column."""
    k = 4
    topology = materialize_gec_mecs(k=k, concentration=1, o=1, d=k - 1)
    taps = Counter()
    for link in topology.shared_links:
        for tap in link.taps:
            taps[tap] += 1
    assert set(taps.values()) == {2 * (k - 1)}


def test_tap_order_is_gec_not_srota():
    """Router 1's x-wire taps 0, 2, 3 — ascending, self skipped.

    SROTA would tap 0 and 2 only on a westbound wire and 2, 3 on an
    eastbound one, because its wires are directional. Pinning the difference
    here means a future shared tap rule cannot quietly unify them.
    """
    topology = materialize_gec_mecs(k=4, concentration=1, o=1, d=3)
    router_one = [link for link in topology.shared_links
                  if link.src_router == 1]
    assert len(router_one) == 2
    x_wire = next(link for link in router_one
                  if all(tap % 4 != 1 for tap in link.taps)
                  and all(tap // 4 == 0 for tap in link.taps))
    assert x_wire.taps == (0, 2, 3), x_wire.taps


def test_the_source_law_is_enforced():
    with pytest.raises(TopologyError, match="o\\*d"):
        materialize_gec_mecs(k=5, concentration=1, o=1, d=3)
    # A shape parameter below its floor raises ValueError from the shared
    # integer guard, before any topology law is evaluated.
    with pytest.raises(ValueError, match="d must be"):
        materialize_gec_mecs(k=4, concentration=1, o=3, d=1)
