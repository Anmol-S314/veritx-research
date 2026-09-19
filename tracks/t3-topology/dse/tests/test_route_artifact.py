"""Phase 10 — RouteArtifact: one content-addressed routing truth.

The program (§14) requires that no subsystem independently reinterprets
the routing algorithm and merely hopes it agrees. The certifier already
replicates AnyNet::route() exactly (documented tie-breaks); Phase 10
promotes that replica into a versioned, content-addressed artifact:

  topology_hash      canonical graph serialization (identity, not the
                     raw file bytes — comment/whitespace noise must not
                     alter routing identity)
  routing_algorithm  the EXECUTED semantics ("anynet_dijkstra_hops"),
                     not the design label
  tie_break_policy   the documented AnyNet tie-break string
  entries            {(src,dst): next_hop}, first hop after src
  route_table_hash   hash over entries ONLY — the hash BookSim/RTL
                     eventually verify against
  artifact_hash      hash over the full identity dict

Fail-closed at construction: unknown algorithm, weighted topology
(PR D: the replica is hop-count based; certifying a weighted graph
would certify route set A while BookSim runs B), disconnected graph,
non-integer or out-of-range next hops. The class axis is deferred to
schema v2 with the VC artifact (§14: no VC-aware deadlock claims while
only physical channels are checked).

Tests live at the seams (construction, hashing, extraction from a real
anynet file, equivalence, F6 evidence), never against internals.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.anynet import parse_anynet_file
from veritx_dse.core.paths import REPO
from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS,
    ANYNET_MIN_HOPS_DEFINITION,
    DOR_XY,
    ROUTING_ALGORITHM,
    TIE_BREAK_POLICY,
    RouteArtifact,
    RouteArtifactError,
    artifact_from_anynet,
    equivalence_report,
    first_hop_table,
    route_entries_from_adj,
    standalone_channel_dst,
    topology_hash_from_adj,
    upgrade_v1_to_v2,
)
from veritx_dse.tools.deadlock_routing import booksim_first_hop_table

ANYNET16 = REPO / "tracks" / "t3-topology" / "configs" / "anynet16.links"


def _ring_adj(n: int) -> dict[int, set[int]]:
    return {i: {(i - 1) % n, (i + 1) % n} for i in range(n)}


def _square_grid() -> dict[int, set[int]]:
    return {
        0: {1, 3}, 1: {0, 2, 4}, 2: {1, 5},
        3: {0, 4, 6}, 4: {1, 3, 5, 7}, 5: {2, 4, 8},
        6: {3, 7}, 7: {4, 6, 8}, 8: {5, 7},
    }


# ── construction: the only sanctioned path validates eagerly ─────────────

class TestConstruction:
    def test_valid_construction_records_executed_semantics(self):
        adj = _ring_adj(4)
        art = RouteArtifact.from_adjacency(adj, name="ring4")
        assert art.schema_version == 2
        definition = art.routing_classes[0]
        assert definition.id == ANYNET_MIN_HOPS
        assert definition.algorithm == "anynet_dijkstra_hops"
        assert art.topology_hash.startswith("sha256:")
        assert art.route_table_hash.startswith("sha256:")
        assert art.artifact_hash.startswith("sha256:")
        assert dict(definition.parameters)["tie_break_policy"]

    def test_unknown_algorithm_fails_closed(self):
        with pytest.raises(RouteArtifactError, match="routing_algorithm"):
            RouteArtifact.from_adjacency(
                _ring_adj(4), name="x", routing_algorithm="dor_north_last")

    def test_weighted_topology_refused(self):
        # PR D policy, now enforced at artifact construction too.
        with pytest.raises(RouteArtifactError, match="weight"):
            RouteArtifact.from_adjacency(
                {0: {1, 2}, 1: {0}, 2: {0}}, name="w",
                weights={(0, 1): 2.5})

    def test_disconnected_graph_refused(self):
        with pytest.raises(RouteArtifactError, match="connected"):
            RouteArtifact.from_adjacency(
                {0: {1}, 1: {0}, 2: {3}, 3: {2}}, name="split")

    def test_bad_next_hop_fails_closed(self):
        adj = _ring_adj(4)
        bad = {(0, 1): 7}  # 7 out of range and not a neighbor
        with pytest.raises(RouteArtifactError, match="0.*1.*7|7.*0.*1"):
            RouteArtifact.from_adjacency(adj, name="bad", entries=bad)

    def test_incomplete_entries_refused(self):
        # all-pairs minus diagonal is the AnyNet contract; a missing entry
        # means the artifact lies about coverage.
        adj = _ring_adj(4)
        full = route_entries_from_adj(adj)
        del full[(0, 2)]
        with pytest.raises(RouteArtifactError, match="coverage|missing"):
            RouteArtifact.from_adjacency(adj, name="gap", entries=full)


# ── hashing: identity vs transport (the Phase-9 lesson, applied) ──────────

class TestHashing:
    def test_same_semantics_same_hashes(self):
        a = RouteArtifact.from_adjacency(_ring_adj(6), name="a")
        b = RouteArtifact.from_adjacency(_ring_adj(6), name="b")
        assert a.route_table_hash == b.route_table_hash
        assert a.topology_hash == b.topology_hash
        assert a.artifact_hash == b.artifact_hash

    def test_route_table_hash_excludes_presentation(self):
        # name is presentation: it must not alter routing identity
        a = RouteArtifact.from_adjacency(_ring_adj(6), name="prod")
        b = RouteArtifact.from_adjacency(_ring_adj(6), name="debug")
        assert a.artifact_hash == b.artifact_hash

    def test_route_change_changes_table_hash(self):
        adj = _ring_adj(6)
        base = RouteArtifact.from_adjacency(adj, name="x")
        entries = route_entries_from_adj(adj)
        # reroute flow (0,3) through the other neighbor: one hop differs
        entries[(0, 3)] = 5 if entries[(0, 3)] != 5 else 1
        other = RouteArtifact.from_adjacency(adj, name="x", entries=entries)
        assert other.route_table_hash != base.route_table_hash
        assert other.topology_hash == base.topology_hash

    def test_topology_change_changes_topology_hash(self):
        a = RouteArtifact.from_adjacency(_ring_adj(6), name="x")
        b = RouteArtifact.from_adjacency(_ring_adj(8), name="x")
        assert a.topology_hash != b.topology_hash

    def test_serialize_roundtrip_preserves_hashes(self):
        art = RouteArtifact.from_adjacency(_ring_adj(4), name="rt")
        d = art.serialize()
        rt = RouteArtifact.from_dict(json.loads(json.dumps(d)))
        assert rt.artifact_hash == art.artifact_hash
        assert rt.route_table_hash == art.route_table_hash
        assert rt.topology_hash == art.topology_hash
        assert rt.entries == art.entries

    def test_tampered_entries_detected_on_load(self):
        art = RouteArtifact.from_adjacency(_ring_adj(4), name="rt")
        d = art.serialize()
        key = next(iter(d["entries"]))
        d["entries"][key] = int(d["entries"][key]) + 1  # lie about a channel
        with pytest.raises(RouteArtifactError, match="route_table_hash"):
            RouteArtifact.from_dict(d)


# ── extraction: the artifact IS the AnyNet::route() replica ───────────────

class TestExtraction:
    def test_entries_match_anynet_replica_exactly(self):
        adj = _square_grid()
        art = RouteArtifact.from_adjacency(adj, name="grid")
        replica = booksim_first_hop_table(len(adj), adj)
        assert first_hop_table(art, standalone_channel_dst(adj)) == replica

    def test_from_anynet_real_topology(self):
        if not ANYNET16.exists():
            pytest.skip("anynet16.links not present")
        g = parse_anynet_file(ANYNET16)
        art = artifact_from_anynet(g, name="anynet16")
        assert len(art.entries) == g.n_routers * (g.n_routers - 1)
        replica = booksim_first_hop_table(
            g.n_routers, g.sequential_adj())
        assert first_hop_table(
            art, standalone_channel_dst(g.sequential_adj())) == replica

    def test_topology_hash_canonicalizes_noise(self):
        # adjacency construction order/set representation is transport,
        # not identity — the canonical serialization absorbs it
        adj = {0: {2, 1}, 1: {0, 2}, 2: {0, 1}}
        h1 = topology_hash_from_adj(adj)
        h2 = topology_hash_from_adj(
            {k: set(v) for k, v in sorted(adj.items())})
        assert h1 == h2


# ── equivalence: report, not a boolean smeared into a string ──────────────

class TestEquivalence:
    def test_identical_tables_report_comparable(self):
        adj = _square_grid()
        art = RouteArtifact.from_adjacency(adj, name="grid")
        rep = equivalence_report(
            art, booksim_first_hop_table(len(adj), adj),
            channel_dst=standalone_channel_dst(adj))
        assert rep["status"] == "COMPARABLE"
        assert rep["mismatched"] == []
        assert rep["coverage"]["matched"] == rep["coverage"]["artifact_flows"]

    def test_divergence_pinned_per_flow(self):
        adj = _square_grid()
        art = RouteArtifact.from_adjacency(adj, name="grid")
        executed = booksim_first_hop_table(len(adj), adj)
        flow = next(iter(executed))
        executed[flow] = next(
            n for n in adj[flow[0]] if n != executed[flow])
        rep = equivalence_report(
            art, executed, channel_dst=standalone_channel_dst(adj))
        assert rep["status"] == "DIVERGENT"
        assert len(rep["mismatched"]) == 1
        m = rep["mismatched"][0]
        assert (m["src"], m["dst"]) == flow
        assert m["artifact_next_hop"] is not None
        assert m["executed_next_hop"] is not None

    def test_missing_executed_flow_is_visible(self):
        adj = _ring_adj(4)
        art = RouteArtifact.from_adjacency(adj, name="r")
        executed = booksim_first_hop_table(4, adj)
        del executed[(0, 2)]
        rep = equivalence_report(
            art, executed, channel_dst=standalone_channel_dst(adj))
        assert rep["status"] == "DIVERGENT"
        assert any(m["src"] == 0 and m["dst"] == 2
                   for m in rep["missing_in_executed"])


# ── F6: routing correctness consumes artifact evidence ────────────────────

class TestF6Evidence:
    def _fabric(self):
        """ResolvedRouteArtifact for a 4-agent mesh (real derivation)."""
        from veritx_dse.model.attachment import derive_attachment
        from veritx_dse.model.compile_model import (
            Agent, AgentKind, CompileRequest, DependencyGraph, ModelFamily,
            NocConfig, Workload,
        )
        from veritx_dse.model.mapping import derive_mapping
        from veritx_dse.model.placement import build_inventory
        from veritx_dse.model.resolved_route import derive_resolved_route
        from veritx_dse.model.topology_artifact import materialize_topology
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                              collectives=()),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        inv = build_inventory(cr)
        topo = materialize_topology(inv, cr)
        att = derive_attachment(inv, derive_mapping(cr), topo, cr)
        rr = RouteArtifact.from_topology(topo, name="mesh")
        return cr, rr, derive_resolved_route(topo, att, rr)

    def _f6(self, vr):
        return next(c for c in vr.checks
                    if c["name"] == "F6_routing_correctness")

    def test_f6_stays_not_run_without_evidence(self):
        from veritx_dse.model.compile_model import verify_design
        cr, _rr, _rra = self._fabric()
        assert self._f6(verify_design(cr))["status"] == "NOT_RUN"

    def test_f6_replica_evidence_is_inconclusive(self):
        """The B3.2 invariant: Python agreement with Python is not proof."""
        from veritx_dse.model.compile_model import verify_design
        cr, rr, rra = self._fabric()
        adj = _ring_adj(4)
        rep = equivalence_report(
            rr, booksim_first_hop_table(4, adj),
            channel_dst={ch: 0 for ch in set(rr.entries.values())})
        vr = verify_design(cr, evidence={
            "resolved_route_artifact": rra.to_dict(),
            "executed_route_evidence": {
                "provenance": "python_replica",
                "resolved_route_hash": rra.resolved_route_hash(),
                "matches": True,
            },
            "route_equivalence": rep,
        })
        f6 = self._f6(vr)
        assert f6["status"] == "INCONCLUSIVE"
        assert "replica" in f6["detail"].lower()
        assert f6["status"] != "PASS"

    def test_f6_pass_requires_independent_provenance(self):
        from veritx_dse.model.compile_model import verify_design
        cr, _rr, rra = self._fabric()
        vr = verify_design(cr, evidence={
            "resolved_route_artifact": rra.to_dict(),
            "executed_route_evidence": {
                "provenance": "booksim_dumped_table",
                "resolved_route_hash": rra.resolved_route_hash(),
                "matches": True,
            },
        })
        f6 = self._f6(vr)
        assert f6["status"] == "PASS"
        assert rra.resolved_route_hash() in f6["detail"]

    def test_f6_fails_when_executed_evidence_is_another_fabric(self):
        from veritx_dse.model.compile_model import verify_design
        cr, _rr, rra = self._fabric()
        vr = verify_design(cr, evidence={
            "resolved_route_artifact": rra.to_dict(),
            "executed_route_evidence": {
                "provenance": "rtl_emitted_table",
                "resolved_route_hash": "0" * 64,
                "matches": True,
            },
        })
        assert self._f6(vr)["status"] == "FAIL"

    def test_f6_fails_on_independent_divergence(self):
        from veritx_dse.model.compile_model import verify_design
        cr, _rr, rra = self._fabric()
        vr = verify_design(cr, evidence={
            "resolved_route_artifact": rra.to_dict(),
            "executed_route_evidence": {
                "provenance": "booksim_dumped_table",
                "resolved_route_hash": rra.resolved_route_hash(),
                "matches": False,
            },
        })
        assert self._f6(vr)["status"] == "FAIL"

    def test_f6_refuses_tampered_resolved_artifact(self):
        from veritx_dse.model.compile_model import verify_design
        cr, _rr, rra = self._fabric()
        bad = rra.to_dict()
        bad["endpoint_to_router"][0][1] = 99
        vr = verify_design(cr, evidence={"resolved_route_artifact": bad})
        f6 = self._f6(vr)
        assert f6["status"] == "FAIL"
        assert "untrusted" in f6["detail"].lower()


# ── B3.2d: routing classes, exact resources, whole-route termination ───────

def _mesh_topo(k: int):
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family,
    )
    return materialize_family(MaterializedFamily.MESH, endpoint_count=k * k)


def _adjacency_of(topo):
    adj = {r.router_id: set() for r in topo.routers}
    for c in topo.channels:
        adj[c.src_router].add(c.dst_router)
    return adj


def _walk(art, topo, cls, s, t):
    by_id = {c.channel_id: c for c in topo.channels}
    cur = s
    while cur != t:
        ch = by_id[art.entries[(cls, cur, t)]]
        yield ch
        cur = ch.dst_router


class TestDORXY:
    @pytest.mark.parametrize("k", (2, 3, 4))
    def test_dor_xy_is_minimal_and_x_before_y(self, k):
        topo = _mesh_topo(k)
        art = RouteArtifact.from_topology(
            topo, name=f"mesh{k}", routing_classes=(DOR_XY,))
        assert art.routing_classes[0].algorithm == "dimension_order"
        assert dict(art.routing_classes[0].parameters) == {
            "dimension_order": ("x", "y"), "wraparound": False}
        coord = {r.router_id: r.coordinates for r in topo.routers}
        for s in coord:
            for t in coord:
                if s == t:
                    continue
                path = list(_walk(art, topo, DOR_XY, s, t))
                sx, sy = coord[s]
                tx, ty = coord[t]
                assert len(path) == abs(sx - tx) + abs(sy - ty)
                if sx != tx:
                    assert coord[path[0].dst_router][0] != sx
                moved_y = False
                cur = s
                for ch in path:
                    a, b = coord[cur], coord[ch.dst_router]
                    if b[1] != a[1]:
                        moved_y = True
                    if moved_y:
                        assert b[0] == a[0], "X movement after a Y turn"
                    cur = ch.dst_router

    def test_dor_xy_refuses_torus_and_ring(self):
        from veritx_dse.model.topology_artifact import (
            MaterializedFamily, materialize_family,
        )
        for family in (MaterializedFamily.TORUS, MaterializedFamily.RING):
            topo = materialize_family(family, endpoint_count=4)
            with pytest.raises(RouteArtifactError, match="DOR_XY"):
                RouteArtifact.from_topology(
                    topo, name=family.value, routing_classes=(DOR_XY,))

    def test_unknown_class_refused(self):
        with pytest.raises(RouteArtifactError, match="unknown routing class"):
            RouteArtifact.from_topology(
                _mesh_topo(2), name="x", routing_classes=("MAGIC",))


class TestV1Migration:
    def _v1(self, adj, name="legacy"):
        return {
            "schema_version": 1,
            "name": name,
            "topology_hash": topology_hash_from_adj(adj),
            "routing_algorithm": ROUTING_ALGORITHM,
            "tie_break_policy": TIE_BREAK_POLICY,
            "entries": {f"{s}|{t}": nh for (s, t), nh
                        in sorted(route_entries_from_adj(adj).items())},
            "route_table_hash": "sha256:x",
            "artifact_hash": "sha256:y",
        }

    def test_v1_direct_load_is_refused(self):
        with pytest.raises(RouteArtifactError,
                           match="v1|upgrade_v1_to_v2"):
            RouteArtifact.from_dict(self._v1(_ring_adj(4)))

    def test_upgrade_unique_hops_succeeds_and_is_deterministic(self):
        topo = _mesh_topo(2)
        v1 = self._v1(_adjacency_of(topo))
        a = upgrade_v1_to_v2(v1, topo)
        b = upgrade_v1_to_v2(v1, topo)
        assert a.artifact_hash == b.artifact_hash
        assert a.routing_classes[0].id == ANYNET_MIN_HOPS
        assert "upgraded" in a.provenance
        fresh = RouteArtifact.from_topology(
            topo, name="x", routing_classes=(ANYNET_MIN_HOPS,))
        assert a.route_table_hash == fresh.route_table_hash
        assert a.artifact_hash == fresh.artifact_hash

    def test_upgrade_parallel_links_refused_as_ambiguous(self):
        from veritx_dse.model.topology_artifact import (
            DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
        )
        topo = TopologyArtifact(
            family=MaterializedFamily.MESH,
            routers=(Router(0, (0, 0), 1), Router(1, (1, 0), 1)),
            channels=(
                DirectedChannel(0, 0, 0, 1, 0, 64, 1),
                DirectedChannel(1, 0, 1, 1, 1, 64, 1),
                DirectedChannel(2, 1, 0, 0, 0, 64, 1),
            ),
        )
        v1 = self._v1({0: {1}, 1: {0}})
        with pytest.raises(RouteArtifactError, match="ambiguous"):
            upgrade_v1_to_v2(v1, topo)

    def test_provenance_does_not_change_identity(self):
        topo = _mesh_topo(2)
        base = RouteArtifact.from_topology(
            topo, name="m", routing_classes=(ANYNET_MIN_HOPS,))
        twin = RouteArtifact(
            schema_version=base.schema_version,
            name="other",
            topology_hash=base.topology_hash,
            routing_classes=base.routing_classes,
            entries=dict(base.entries),
            provenance="explanatory migration text is not identity",
        )
        assert twin.route_table_hash == base.route_table_hash
        assert twin.artifact_hash == base.artifact_hash


class TestWholeRouteTermination:
    def test_locally_legal_but_looping_table_refused(self):
        topo = _mesh_topo(2)
        by_hop = {}
        for c in topo.channels:
            by_hop.setdefault((c.src_router, c.dst_router), []).append(
                c.channel_id)
        base = RouteArtifact.from_topology(
            topo, name="m", routing_classes=(ANYNET_MIN_HOPS,))
        entries = dict(base.entries)
        # destination 3: 0 -> 1 and 1 -> 0 are each a legal first channel,
        # but together they never reach 3.
        entries[(ANYNET_MIN_HOPS, 0, 3)] = min(by_hop[(0, 1)])
        entries[(ANYNET_MIN_HOPS, 1, 3)] = min(by_hop[(1, 0)])
        art = RouteArtifact(
            schema_version=2, name="loop",
            topology_hash=topo.topology_hash(),
            routing_classes=(ANYNET_MIN_HOPS_DEFINITION,),
            entries=entries)
        with pytest.raises(RouteArtifactError, match="routing loop"):
            art.validate_against(topo)

    def test_wrong_class_entry_is_refused_at_construction(self):
        topo = _mesh_topo(2)
        base = RouteArtifact.from_topology(
            topo, name="m", routing_classes=(ANYNET_MIN_HOPS,))
        entries = {(DOR_XY, s, t): ch
                   for (cls, s, t), ch in base.entries.items()}
        with pytest.raises(RouteArtifactError, match="undeclared"):
            RouteArtifact(
                schema_version=2, name="x",
                topology_hash=topo.topology_hash(),
                routing_classes=(ANYNET_MIN_HOPS_DEFINITION,),
                entries=entries)
