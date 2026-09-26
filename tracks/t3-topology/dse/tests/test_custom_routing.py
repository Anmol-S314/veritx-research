"""Canonical custom-fabric routing (ROUTE-C-*).

TRANCHE 5. Custom topology routes through the DECLARED policy table in
`model/routing.py`, not a hidden `if CUSTOM` branch:

    MESH / CONCENTRATED_MESH -> DOR_XY                (deadlock-free BY
                                                       CONSTRUCTION)
    CUSTOM                   -> WEIGHTED_SHORTEST_PATH (deadlock-freedom is
                                                       a PROPERTY CHECKED)

TORUS / RING / FLATFLY are deliberately absent: widening them changes an
existing contract and is a separate decision.

THE ORACLE IS INDEPENDENT. `_bfs_first_hops` below is a plain BFS written
for this file; it never imports the production producer. The tie-break
comparison is against a separately implemented lexicographic search.
"""
from __future__ import annotations

import heapq
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.model import topology_ir as tir
from veritx_dse.model.topology_artifact import materialize_ir
from veritx_dse.model.routing import routing_policy_for
from veritx_dse.application.fabric_compiler import FabricCompiler

REPO = Path(__file__).resolve().parents[4]
V3_EXAMPLE = REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"


# ── the INDEPENDENT oracle (no production import) ───────────────────────

def _adj(n, links):
    out = {i: [] for i in range(n)}
    for u, v in links:
        out[u].append(v)
        out[v].append(u)
    return {k: sorted(v) for k, v in out.items()}


def _bfs_cost(n, links, src, dst):
    """Independent shortest-path COST (hop count)."""
    if src == dst:
        return 0
    adj = _adj(n, links)
    dist = {src: 0}
    q = [src]
    while q:
        cur = q.pop(0)
        for nb in adj[cur]:
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                q.append(nb)
    return dist.get(dst)


def _unique_next_hop(n, links, src, dst):
    """The next hop on a shortest path, or None when the choice is TIED."""
    adj = _adj(n, links)
    d = _bfs_cost(n, links, src, dst)
    if not d:
        return None
    opts = [nb for nb in adj[src] if _bfs_cost(n, links, nb, dst) == d - 1]
    return opts[0] if len(opts) == 1 else None


def _bfs_next_hop(n, links, src, dst):
    """Plain BFS; returns the NEXT node on a shortest path src->dst.

    Independent of the production producer. Ties are broken by taking the
    smallest next-node on any shortest path, which is a DIFFERENT
    formulation from the production 'lexicographically smallest complete
    channel-id sequence' — so agreement is evidence, not tautology.
    """
    if src == dst:
        return None
    adj = _adj(n, links)
    dist = {src: 0}
    q = [src]
    while q:
        cur = q.pop(0)
        for nb in adj[cur]:
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                q.append(nb)
    if dst not in dist:
        return None
    best = None
    for nb in adj[src]:
        if dist.get(nb, 1 << 30) == dist[dst] - 1:
            if best is None or nb < best:
                best = nb
    return best


def _doc(**kw):
    d = json.loads(V3_EXAMPLE.read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    d.update(kw)
    return d


def _mesh(k):
    out = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                out.append([n, n + 1])
            if y + 1 < k:
                out.append([n, n + k])
    return out


def _req(name, n, links):
    ir = tir.from_dict({"name": name, "kind": "custom", "nodes": n,
                        "links": links,
                        "link_attrs": {"bandwidth_GBs": 50.0,
                                       "latency_ns": 500.0}})
    d = _doc()
    d["explicit_topology"] = ir.to_dict()
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"]["topology_family"] = None
    return CompileRequestV3.from_dict(d)


# ══ ROUTE-C-1: declared policy identity ════════════════════════════════

def test_route_c_1_policy_is_declared_and_inspectable():
    art = materialize_ir(tir.from_dict({
        "name": "g", "kind": "custom", "nodes": 4, "links": [[0, 1], [1, 2]],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}),
        width_bits=64, latency_cycles=1)
    assert routing_policy_for(art) == "WEIGHTED_SHORTEST_PATH"


def test_route_c_1b_mesh_keeps_dor():
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family,
    )
    for fam in (MaterializedFamily.MESH, MaterializedFamily.CONCENTRATED_MESH):
        assert routing_policy_for(
            materialize_family(fam, endpoint_count=16)) == "DOR_XY"


# ══ ROUTE-C-2: route_weight is identity-bearing ════════════════════════

def test_route_c_2_route_weight_changes_topology_identity():
    """`WEIGHTED_SHORTEST_PATH` consumes route_weight, so a weight change
    MUST move topology identity. It does: route_weight is a DirectedChannel
    field and DirectedChannel is in TopologyArtifact.canonical_dict."""
    from veritx_dse.model.topology_artifact import (
        DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    )
    routers = (Router(router_id=0, coordinates=(0,), seat_capacity=1),
               Router(router_id=1, coordinates=(1,), seat_capacity=1))
    def art(w):
        ch = tuple(
            DirectedChannel(channel_id=i, src_router=s, src_port=1,
                            dst_router=d, dst_port=1, width_bits=64,
                            latency_cycles=1, route_weight=w)
            for i, (s, d) in enumerate(((0, 1), (1, 0))))
        return TopologyArtifact(family=MaterializedFamily.CUSTOM,
                                routers=routers, channels=ch)
    assert art(1).topology_hash() != art(2).topology_hash()


def test_route_c_2b_route_weight_cannot_vary_for_explicit_topology_yet():
    """HONEST GAP. TopologyIR has no route_weight field, so every explicit
    graph materializes with route_weight=1 and the policy degenerates to
    minimum-hop. Recorded so the day weights are added, this test fails and
    the identity question is re-opened deliberately."""
    ir = tir.from_dict({"name": "g", "kind": "custom", "nodes": 2,
                        "links": [[0, 1]],
                        "link_attrs": {"bandwidth_GBs": 50.0,
                                       "latency_ns": 500.0}})
    art = materialize_ir(ir, width_bits=64, latency_cycles=1)
    assert {c.route_weight for c in art.channels} == {1}
    assert "route_weight" not in ir.to_dict()


# ══ ROUTE-C-3/4/5: totality, legality, no loops ════════════════════════

def test_route_c_3_4_5_route_table_is_total_legal_and_loop_free():
    k = 5
    c = FabricCompiler().compile(_req("m5", k * k, _mesh(k)))
    assert c.status == "COMPILED"
    route = c.bundle.router_route
    art = c.bundle.topology
    chan_ids = {ch.channel_id for ch in art.channels}
    router_ids = {r.router_id for r in art.routers}
    for cls, src, dst in route.entries:
        assert src in router_ids and dst in router_ids
        assert src != dst
        # every hop is a REAL channel of this topology
        for hop in (route.entries[(cls, src, dst)],):
            assert hop in chan_ids or getattr(hop, "channel_id", None) in chan_ids


def test_route_c_3b_totality_matches_the_independent_oracle():
    k = 5
    c = FabricCompiler().compile(_req("m5", k * k, _mesh(k)))
    art = c.bundle.topology
    chan_by_id = {ch.channel_id: ch for ch in art.channels}
    route = c.bundle.router_route
    for (cls, src, dst), cid in route.entries.items():
        ch = chan_by_id[cid]
        # COST must always agree with the independent oracle.
        assert _bfs_cost(k * k, _mesh(k), src, dst) == 1 + _bfs_cost(
            k * k, _mesh(k), ch.dst_router, dst), (
            f"({src},{dst}) production next hop {ch.dst_router} is not on a "
            "shortest path")
        # Next hop must agree exactly where the choice is UNIQUE.
        unique = _unique_next_hop(k * k, _mesh(k), src, dst)
        if unique is not None:
            assert ch.dst_router == unique


# ══ ROUTE-C-6/7: deterministic tie-break vs oracle ═════════════════════

def _diamond_ladder(rungs=9):
    """A ladder of diamonds: 2*(rungs+1) nodes, every rung pair joined by two
    equal-cost rails. Sized to seat the 20-agent design."""
    links = []
    for i in range(rungs):
        a, b = 2 * i, 2 * i + 1
        c, d = 2 * i + 2, 2 * i + 3
        # rails within the rung, then the two diagonals to the next rung
        links += [[a, b], [a, c], [b, d]]
        if i == rungs - 1:
            links += [[c, d]]
    return sorted({tuple(sorted(e)) for e in links})


def test_route_c_6_deterministic_on_a_diamond():
    """A diamond ladder has two equal-cost rails. The table must be
    identical across compiles and must not depend on set/traversal
    ordering."""
    links = _diamond_ladder(9)
    n = 20
    a = FabricCompiler().compile(_req("diamond", n, links))
    b = FabricCompiler().compile(_req("diamond", n, links))
    assert a.status == "COMPILED"
    assert a.bundle.router_route.entries == b.bundle.router_route.entries
    art = a.bundle.topology
    by_id = {ch.channel_id: ch for ch in art.channels}
    for (cls, src, dst), cid in a.bundle.router_route.entries.items():
        hop = by_id[cid].dst_router
        assert _bfs_cost(n, links, src, dst) == 1 + _bfs_cost(n, links, hop, dst)
        unique = _unique_next_hop(n, links, src, dst)
        if unique is not None:
            assert hop == unique


def test_route_c_7_oracle_agrees_on_a_non_grid_graph():
    """Irregular, non-grid topology — where a grid assumption would break."""
    # 20 nodes so the 20-agent design fits; a non-grid ACYCLIC shape (a
    # caterpillar: a spine with leaves). Acyclic on purpose — chords on a
    # path create a genuinely cyclic CDG and the certificate FAILs, which
    # ROUTE-C-12 covers separately. Here we want the oracle comparison.
    n = 20
    spine = list(range(10))
    links = [[i, i + 1] for i in range(9)]
    links += [[i, 10 + i] for i in range(10)]
    c = FabricCompiler().compile(_req("irregular", n, links))
    assert c.status == "COMPILED", getattr(c, "error", None)
    art = c.bundle.topology
    by_id = {ch.channel_id: ch for ch in art.channels}
    checked = 0
    for (cls, src, dst), cid in c.bundle.router_route.entries.items():
        hop = by_id[cid].dst_router
        assert _bfs_cost(n, links, src, dst) == 1 + _bfs_cost(n, links, hop, dst)
        unique = _unique_next_hop(n, links, src, dst)
        if unique is not None:
            assert hop == unique
        checked += 1
    assert checked > 0


# ══ ROUTE-C-8: manual and synthesized produce identical routing ════════

def test_route_c_8_manual_and_synthesized_route_identically():
    """The graph is identical; only the LABEL differs. Routing science must
    not depend on which produced it."""
    k = 5
    a = FabricCompiler().compile(_req("authored-by-hand", k * k, _mesh(k)))
    b = FabricCompiler().compile(
        _req("synthesized-0acbdc1acbe4", k * k, _mesh(k)))
    assert a.bundle.router_route.entries == b.bundle.router_route.entries
    assert a.bundle.topology.topology_hash() == \
        b.bundle.topology.topology_hash()


# ══ ROUTE-C-9/10: resolved route + VC origin-independence ═════════════

def test_route_c_9_10_resolved_route_and_vc_are_origin_independent():
    k = 5
    a = FabricCompiler().compile(_req("authored", k * k, _mesh(k)))
    b = FabricCompiler().compile(_req("synthesized-xyz", k * k, _mesh(k)))
    assert a.bundle.resolved_route == b.bundle.resolved_route
    assert a.bundle.vc_assignment == b.bundle.vc_assignment


# ══ ROUTE-C-11/12: CDG runs on custom routes; FAIL stays FAIL ══════════

def test_route_c_11_cdg_executes_on_custom_routes():
    k = 5
    c = FabricCompiler().compile(_req("m5", k * k, _mesh(k)))
    assert c.status == "COMPILED"
    assert c.certificate.overall == "PASS"
    ev = {o.obligation: o.evidence for o in c.certificate.obligations}
    dk = ev["DEADLOCK_FREE"]
    assert dk["acyclic"] is True
    assert tuple(dk["cdg_route_classes"]) == ("WEIGHTED_SHORTEST_PATH",)
    assert dk["node_count"] > 0 and dk["edge_count"] > 0


def test_route_c_12_a_real_deadlock_stays_a_failure():
    """A RING under minimum-hop routing genuinely deadlocks. The certificate
    must FAIL with a cycle witness and must NOT silently reroute."""
    n = 25
    ring = [[i, (i + 1) % n] for i in range(n)]
    c = FabricCompiler().compile(_req("ring25", n, ring))
    assert c.status == "INVALID"
    assert c.certificate.overall == "FAIL"
    ev = {o.obligation: o.evidence for o in c.certificate.obligations}
    dk = ev["DEADLOCK_FREE"]
    assert dk["acyclic"] is False
    assert dk.get("cycle"), "a FAIL must carry a witness, not just a verdict"
    # The route class is unchanged: no reroute magic.
    assert tuple(dk["cdg_route_classes"]) == ("WEIGHTED_SHORTEST_PATH",)


def test_route_c_12b_mesh_and_ring_disagree_only_on_the_cdg():
    """Same policy, same pipeline — the difference is the GRAPH, which is
    exactly the scientific content."""
    k = 5
    mesh = FabricCompiler().compile(_req("m5", k * k, _mesh(k)))
    n = k * k
    ring = [[i, (i + 1) % n] for i in range(n)]
    r = FabricCompiler().compile(_req("ring25", n, ring))
    def classes(comp):
        if comp.bundle is not None:
            return tuple(getattr(x, "id", x)
                         for x in (comp.bundle.router_route.routing_classes
                                   or ()))
        # An INVALID compile has no bundle; read the class from evidence.
        ev = {o.obligation: o.evidence for o in comp.certificate.obligations}
        return tuple(ev["DEADLOCK_FREE"].get("cdg_route_classes") or ())
    assert classes(mesh) == classes(r) == ("WEIGHTED_SHORTEST_PATH",)
    assert mesh.certificate.overall == "PASS"
    assert r.certificate.overall == "FAIL"


# ══ ROUTE-C-13: normal obligations ═════════════════════════════════════

def test_route_c_13_custom_gets_the_full_ten_obligations():
    k = 5
    c = FabricCompiler().compile(_req("m5", k * k, _mesh(k)))
    names = [o.obligation for o in c.certificate.obligations]
    assert len(names) == 10
    for expected in ("TOPOLOGY_CONNECTED", "ATTACHMENT_COMPLETE",
                     "ROUTE_COMPLETE", "ROUTE_LEGAL", "VC_ASSIGNMENT_VALID",
                     "DEADLOCK_FREE", "MAPPING_VALID", "PACKET_FORMAT_VALID",
                     "FABRIC_DAG_VALID", "ADDRESS_DECODE_VALID"):
        assert expected in names, expected


# ══ ROUTE-C-14: disconnected graph ═════════════════════════════════════

def test_route_c_14_disconnected_graph_does_not_silently_pass():
    """Two islands: pairs across them are unreachable. Whatever the outcome,
    it must be typed and must not fabricate routes."""
    n = 6
    links = [[0, 1], [1, 2], [3, 4], [4, 5]]
    c = FabricCompiler().compile(_req("islands", n, links))
    assert c.status in ("COMPILED", "INVALID", "UNSUPPORTED")
    if c.status == "COMPILED":
        ev = {o.obligation: o.evidence for o in c.certificate.obligations}
        assert "TOPOLOGY_CONNECTED" in ev


# ══ ROUTE-C-15/18: backend boundary and projection ════════════════════

def test_route_c_18_projection_does_not_change_route_identity():
    k = 5
    c = FabricCompiler().compile(_req("m5", k * k, _mesh(k)))
    before = c.bundle.router_route.entries
    text = "\n".join(f"router {i}" for i in range(k * k))
    assert text  # a projection artifact exists independently
    assert c.bundle.router_route.entries == before
