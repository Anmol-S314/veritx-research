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
    ROUTING_ALGORITHM,
    RouteArtifact,
    RouteArtifactError,
    artifact_from_anynet,
    equivalence_report,
    route_entries_from_adj,
    topology_hash_from_adj,
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
        assert art.schema_version == 1
        assert art.routing_algorithm == "anynet_dijkstra_hops"
        assert art.topology_hash.startswith("sha256:")
        assert art.route_table_hash.startswith("sha256:")
        assert art.artifact_hash.startswith("sha256:")
        assert art.tie_break_policy, "tie-break policy must be documented"

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
        d["entries"]["0|2"] = "3"  # lie about a next hop
        with pytest.raises(RouteArtifactError, match="hash mismatch"):
            RouteArtifact.from_dict(d)


# ── extraction: the artifact IS the AnyNet::route() replica ───────────────

class TestExtraction:
    def test_entries_match_anynet_replica_exactly(self):
        adj = _square_grid()
        art = RouteArtifact.from_adjacency(adj, name="grid")
        replica = booksim_first_hop_table(len(adj), adj)
        assert dict(art.entries) == replica

    def test_from_anynet_real_topology(self):
        if not ANYNET16.exists():
            pytest.skip("anynet16.links not present")
        g = parse_anynet_file(ANYNET16)
        art = artifact_from_anynet(g, name="anynet16")
        assert len(art.entries) == g.n_routers * (g.n_routers - 1)
        replica = booksim_first_hop_table(
            g.n_routers, g.sequential_adj())
        assert dict(art.entries) == replica

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
        rep = equivalence_report(art, booksim_first_hop_table(len(adj), adj))
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
        rep = equivalence_report(art, executed)
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
        rep = equivalence_report(art, executed)
        assert rep["status"] == "DIVERGENT"
        assert any(m["src"] == 0 and m["dst"] == 2
                   for m in rep["missing_in_executed"])


# ── F6: routing correctness consumes artifact evidence ────────────────────

class TestF6Evidence:
    def _cr(self):
        from veritx_dse.model.compile_model import (
            Agent, AgentKind, CompileRequest, DependencyGraph, ModelFamily,
            NocConfig, Workload,
        )
        return CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                              collectives=()),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )

    def test_f6_upgrades_to_pass_on_comparable_evidence(self):
        from veritx_dse.model.compile_model import verify_design
        adj = _ring_adj(4)
        art = RouteArtifact.from_adjacency(adj, name="r")
        rep = equivalence_report(art, booksim_first_hop_table(4, adj))
        vr = verify_design(self._cr(), evidence={"route_equivalence": rep,
                                                 "route_artifact": art.serialize()})
        f6 = next(c for c in vr.checks if c["name"] == "F6_routing_correctness")
        assert f6["status"] == "PASS"
        assert art.route_table_hash in f6["detail"]

    def test_f6_fails_on_divergent_evidence(self):
        from veritx_dse.model.compile_model import verify_design
        adj = _square_grid()
        art = RouteArtifact.from_adjacency(adj, name="grid")
        executed = booksim_first_hop_table(len(adj), adj)
        flow = next(iter(executed))
        executed[flow] = next(
            n for n in adj[flow[0]] if n != executed[flow])
        rep = equivalence_report(art, executed)
        vr = verify_design(self._cr(), evidence={"route_equivalence": rep})
        f6 = next(c for c in vr.checks if c["name"] == "F6_routing_correctness")
        assert f6["status"] == "FAIL"
        assert "DIVERGENT" in f6["detail"]

    def test_f6_stays_not_run_without_evidence(self):
        from veritx_dse.model.compile_model import verify_design
        vr = verify_design(self._cr())
        f6 = next(c for c in vr.checks if c["name"] == "F6_routing_correctness")
        assert f6["status"] == "NOT_RUN"

    def test_f6_refuses_unsigned_or_tampered_artifact(self):
        from veritx_dse.model.compile_model import verify_design
        adj = _ring_adj(4)
        art = RouteArtifact.from_adjacency(adj, name="r")
        rep = equivalence_report(art, booksim_first_hop_table(4, adj))
        bad = art.serialize()
        bad["entries"]["0|1"] = "2"  # tamper: table no longer matches hash
        vr = verify_design(self._cr(), evidence={"route_equivalence": rep,
                                                 "route_artifact": bad})
        f6 = next(c for c in vr.checks if c["name"] == "F6_routing_correctness")
        assert f6["status"] == "FAIL"
        assert "hash mismatch" in f6["detail"]
