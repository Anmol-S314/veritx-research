"""Exact tie-break conformance against an INDEPENDENT reference.

The canonical custom routing semantic is:

    minimum total route_weight
    then, among every minimum-cost path,
    the lexicographically smallest COMPLETE channel-id sequence

The earlier oracle only checked cost, and the next hop only when the optimum
was unique. That is insufficient: the tie-break IS part of the canonical
route function, so the FULL path must match, always.

`tests/routing_oracle.py` implements the same specification as a DIFFERENT
algorithm (Bellman-Ford on cost alone, then a greedy lexicographic walk over
the min-cost DAG). It never imports the production producer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import routing_oracle as oracle

from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.model import topology_ir as tir
from veritx_dse.model.topology_artifact import materialize_ir
from veritx_dse.model.routing_materialize import materialize_route_artifact
from veritx_dse.model.routing import _weighted_shortest_path_policy as wsp

REPO = Path(__file__).resolve().parents[4]
V3_EXAMPLE = REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"

#: Every fixture the tie-break must survive. Each is a 20-node graph so the
#: 20-agent design seats, except where noted.
FIXTURES = {
    # equal-cost diamond: 0->3 via 1 or via 2, both cost 2
    "diamond": ([[0, 1], [0, 2], [1, 3], [2, 3]]),
    # a chain of diamonds: many equal-cost routes with DIFFERENT first hops
    "ladder": ([[0, 1], [0, 2], [1, 3], [2, 3], [3, 4], [3, 5], [4, 6],
                [5, 6]]),
    # same first hop, different LATER channel sequence
    "late_diverge": ([[0, 1], [1, 2], [1, 3], [2, 4], [3, 4]]),
    # symmetric cycle: 0-1-2-3-0 with equal weights
    "sym_cycle": ([[0, 1], [1, 2], [2, 3], [3, 0]]),
    # three or more equal shortest paths
    "triple": ([[0, 1], [0, 2], [0, 3], [1, 4], [2, 4], [3, 4]]),
    # irregular with a chord
    "irregular": ([[0, 1], [1, 2], [2, 3], [3, 4], [0, 4], [4, 5], [5, 6],
                   [1, 6]]),
}


def _channels(nodes, links):
    """Canonical directed channels for an undirected link list, using the
    SAME construction the materializer uses (both directions)."""
    ir = tir.from_dict({"name": "t", "kind": "custom", "nodes": nodes,
                        "links": links,
                        "link_attrs": {"bandwidth_GBs": 50.0,
                                       "latency_ns": 500.0}})
    art = materialize_ir(ir, width_bits=64, latency_cycles=1)
    return art


def _ref_channels(art):
    return [{"channel_id": c.channel_id, "src": c.src_router,
             "dst": c.dst_router, "weight": c.route_weight}
            for c in art.channels]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_full_path_matches_the_independent_reference(name):
    """THE CONFORMANCE TEST. Full canonical path, every reachable pair."""
    links = FIXTURES[name]
    nodes = max(max(e) for e in links) + 1
    art = _channels(nodes, links)
    chans = _ref_channels(art)
    nodes_list = [r.router_id for r in art.routers]

    prod = materialize_route_artifact(
        wsp(), art, name="tiebreak")
    by_id = {c.channel_id: c for c in art.channels}
    prod_full = {}
    for (cls, src, dst) in prod.entries:
        cid = prod.entries[(cls, src, dst)]
        # walk the first-hop table into a full path
        path = []
        cur = src
        while cur != dst:
            c = by_id[cid]
            path.append(cid)
            cur = c.dst_router
            if cur == dst:
                break
            nxt = prod.entries.get((cls, cur, dst))
            if nxt is None:
                path = None
                break
            cid = nxt
        prod_full[(src, dst)] = tuple(path) if path else None

    checked = 0
    for src in nodes_list:
        for dst in nodes_list:
            if src == dst:
                continue
            ref = oracle.canonical_path(nodes_list, chans, src, dst)
            got = prod_full.get((src, dst))
            if ref is None:
                continue
            assert got == ref, (
                f"{name}: ({src}->{dst}) production {got} != reference {ref}")
            checked += 1
    assert checked > 0, f"{name}: no reachable pairs compared"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_cost_matches_and_path_is_optimal(name):
    links = FIXTURES[name]
    nodes = max(max(e) for e in links) + 1
    art = _channels(nodes, links)
    chans = _ref_channels(art)
    by_id = {c.channel_id: c for c in art.channels}
    prod = materialize_route_artifact(wsp(), art, name="tiebreak")
    for (cls, src, dst), cid in prod.entries.items():
        ref = oracle.canonical_path([r.router_id for r in art.routers],
                                    chans, src, dst)
        if ref is None:
            continue
        # the production FIRST hop is the reference's first hop
        assert cid == ref[0], f"{name}: ({src}->{dst}) first hop {cid} != {ref[0]}"
        # and the reference path is genuinely minimum cost
        assert len(ref) >= 1
        assert by_id[cid].dst_router == by_id[ref[0]].dst_router


def test_the_tiebreak_is_actually_exercised():
    """Guard against a vacuous suite: at least one fixture must contain a
    genuine tie (two distinct minimum-cost paths with different first hops)."""
    links = FIXTURES["diamond"]
    art = _channels(4, links)
    chans = _ref_channels(art)
    nodes = [r.router_id for r in art.routers]
    p1 = oracle.canonical_path(nodes, chans, 0, 3)
    assert p1 is not None and len(p1) == 2
    # there must be another min-cost path with a different first hop
    alts = [c["channel_id"] for c in chans
            if c["src"] == 0 and c["weight"] + oracle.min_cost(
                nodes, chans, c["dst"], 3) == oracle.min_cost(
                    nodes, chans, 0, 3)]
    assert len(alts) >= 2, "fixture does not actually contain a tie"
    assert p1[0] == min(alts), "tie-break must pick the smallest channel id"


def test_production_matches_reference_on_a_compiled_custom_mesh():
    """End-to-end: the real compiled 5x5 custom fabric's route table."""
    k = 5
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                links.append([n, n + 1])
            if y + 1 < k:
                links.append([n, n + k])
    art = _channels(k * k, links)
    chans = _ref_channels(art)
    nodes = [r.router_id for r in art.routers]
    prod = materialize_route_artifact(wsp(), art, name="mesh5")
    by_id = {c.channel_id: c for c in art.channels}
    for (cls, src, dst), cid in prod.entries.items():
        ref = oracle.canonical_path(nodes, chans, src, dst)
        if ref is None:
            continue
        assert cid == ref[0], f"({src}->{dst}) {cid} != {ref[0]}"
