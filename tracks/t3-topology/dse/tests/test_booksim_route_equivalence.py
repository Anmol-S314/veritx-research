"""Instance-level BookSim route equivalence (RTEQ-*).

THE QUESTION: can a concrete custom topology obtain qualified BookSim
execution by proving its canonical RouteArtifact equals what BookSim
actually routes?

THE COMPARAND. `core.route_artifact._route_entries_from_adj` is documented
as "the one routing truth: AnyNet::route() first-hop table, all-pairs" —
it is a REPLICA of the vendored fork's `AnyNet::route()`. So comparing the
canonical custom producer against `ANYNET_MIN_HOPS` is comparing against
BookSim's routing without running the binary.

THE FINDING (measured, and it CORRECTS an earlier claim). BookSim
equivalence is NOT "false on equal-cost ties" in general. A diamond — a
canonical tie — AGREES. Divergence is STRUCTURE-dependent: it needs
several cost-optimal paths whose smallest-channel-id-sequence and
smallest-ascending-router-id choices differ.

SCOPE OF THE INDEPENDENT ORACLE: valid for the current contract, which is
unit-positive weights everywhere (TopologyIR has no weight field, so every
explicit graph materializes with route_weight 1). These tests do NOT
verify arbitrary weighted routing; if weighted authoring is ever added the
reference proof must be revisited.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model import topology_ir as tir
from veritx_dse.model.topology_artifact import materialize_ir
from veritx_dse.model.routing_materialize import materialize_route_artifact
from veritx_dse.model.routing import _weighted_shortest_path_policy
from veritx_dse.model.routing_policy import (
    CandidateMode, DecisionScope, DeadlockProofObligation, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, SelectionLocus,
)
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS


def booksim_replica_policy() -> RoutingPolicyDefinition:
    """The declared ANYNET_MIN_HOPS policy — the BookSim replica."""
    return RoutingPolicyDefinition(
        id=ANYNET_MIN_HOPS, algorithm="weighted_shortest_path",
        algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(RoutingResourceRole(
            id="default", kind=RoutingResourceRoleKind.DEFAULT),),
        parameters={"weight_metric": "hop_count",
                    "tie_break_policy": "anynet_ascending_min"})


def _art(n, links):
    return materialize_ir(tir.from_dict({
        "name": "g", "kind": "custom", "nodes": n, "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}),
        width_bits=64, latency_cycles=1)


def _norm(route):
    """Drop the routing-class component so two classes can be compared."""
    return {(s, d): c for (_cls, s, d), c in route.entries.items()}


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


#: name -> (nodes, links)
FIXTURES = {
    # unique shortest paths everywhere: tie-breaks cannot matter
    "tree_unique": (20, [[i, (i - 1) // 2] for i in range(1, 20)]),
    # a genuine canonical TIE
    "diamond": (20, [[0, 1], [0, 2], [1, 3], [2, 3]]
                + [[i, i + 1] for i in range(3, 19)]),
    "mesh5": (25, _mesh(5)),
    "ring25": (25, [[i, (i + 1) % 25] for i in range(25)]),
    # multiple cost-optimal paths whose two tie-breaks diverge
    "chorded": (20, [[i, i + 1] for i in range(19)]
                + [[0, 5], [3, 12], [8, 19]]),
    # Tranche-3 MILP-style: a 5x5 grid with express chords
    "synthesized_style": (25, _mesh(5) + [[0, 12], [4, 24], [20, 8]]),
}


def _compare(name):
    n, links = FIXTURES[name]
    art = _art(n, links)
    canon = _norm(materialize_route_artifact(
        _weighted_shortest_path_policy(), art, name="canonical"))
    bs = _norm(materialize_route_artifact(
        booksim_replica_policy(), art, name="booksim"))
    mism = sorted(k for k in canon if canon[k] != bs.get(k))
    return art, canon, bs, mism


# ══ RTEQ-1: unique-path graph is fully equivalent ══════════════════════

def test_rteq_1_unique_path_graph_is_fully_equivalent():
    _a, canon, bs, mism = _compare("tree_unique")
    assert len(canon) > 0
    assert mism == [], (
        "with unique shortest paths the tie-break cannot matter, so the "
        f"tables must agree; got {len(mism)} mismatches")


# ══ RTEQ-2: a tie graph AGREES (correcting the earlier blanket claim) ══

def test_rteq_2_diamond_tie_actually_agrees():
    """The earlier report claimed BookSim equivalence is 'false on
    equal-cost ties'. Measured: the diamond is a genuine tie and AGREES.
    The blanket claim was imprecise."""
    _a, canon, bs, mism = _compare("diamond")
    assert mism == [], (
        "a diamond tie must agree; divergence is structure-dependent, "
        "not tie-dependent")


def test_rteq_2b_divergence_is_structure_dependent():
    """A graph with several cost-optimal paths whose two tie-breaks differ
    DOES diverge. This is the real boundary."""
    _a, canon, bs, mism = _compare("chorded")
    assert mism, "expected divergence on the chorded fixture"
    first = mism[0]
    assert canon[first] != bs[first]


# ══ RTEQ-3: the comparison is over the complete pair universe ═════════

def test_rteq_3_comparison_covers_every_ordered_pair():
    n, links = FIXTURES["mesh5"]
    _a, canon, bs, _m = _compare("mesh5")
    assert len(canon) == n * (n - 1), (
        "the comparison universe must be every ordered src!=dst pair, "
        "not a source first-hop sample")
    assert set(canon) == set(bs)


# ══ RTEQ-4: a mismatch retains a counterexample ════════════════════════

def test_rteq_4_mismatch_retains_a_counterexample():
    art, canon, bs, mism = _compare("chorded")
    assert mism
    by_id = {c.channel_id: c for c in art.channels}
    src, dst = mism[0]
    c_ch, b_ch = by_id[canon[(src, dst)]], by_id[bs[(src, dst)]]
    # Both are cost-optimal; they differ only in which equal-cost path
    assert c_ch.dst_router != b_ch.dst_router
    assert c_ch.route_weight == b_ch.route_weight == 1


# ══ RTEQ-8: generic custom capability remains unqualified ═════════════

def test_rteq_8_generic_custom_is_not_universally_equivalent():
    """Some fixtures agree and some do not, so NO blanket CUSTOM claim is
    supportable. This is what keeps the capability row honest."""
    results = {name: bool(_compare(name)[3]) for name in FIXTURES}
    assert results["tree_unique"] is False
    assert results["chorded"] is True
    assert any(results.values()) and not all(results.values()), (
        "the suite must contain BOTH agreements and disagreements, or it "
        "is not evidence about the boundary")


def test_rteq_8b_agreement_is_not_provable_in_general():
    """Document the boundary honestly: agreement holds on many graphs but
    there is no simple structural property that guarantees it."""
    agreeing = [n for n in FIXTURES if not _compare(n)[3]]
    disagreeing = [n for n in FIXTURES if _compare(n)[3]]
    assert agreeing and disagreeing
    # A unique-path graph agrees; a diamond (non-unique) ALSO agrees; a
    # chorded graph (non-unique) disagrees. So "unique paths" is
    # sufficient but NOT necessary, and no tested property is both.
    assert "tree_unique" in agreeing
    assert "diamond" in agreeing
    assert "chorded" in disagreeing


# ══ RTEQ-6: a deadlock failure blocks execution regardless ════════════

def test_rteq_6_certificate_failure_blocks_execution_even_if_routes_match():
    """Order matters: canonical compile/certificate FIRST, backend
    qualification second. Route agreement cannot override a FAIL."""
    from veritx_dse.model.compile_model import CompileRequestV3
    from veritx_dse.application.fabric_compiler import FabricCompiler
    import json
    doc = json.loads((Path(__file__).resolve().parents[4]
                      / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json")
                     .read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    n = 25
    doc["explicit_topology"] = {
        "name": "ring25", "kind": "custom", "nodes": n,
        "links": [[i, (i + 1) % n] for i in range(n)],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = None
    c = FabricCompiler().compile(CompileRequestV3.from_dict(doc))
    assert c.status == "INVALID"
    assert c.certificate.overall == "FAIL"
    # and the ring's ROUTES are nonetheless equivalent to the replica
    _a, _canon, _bs, mism = _compare("ring25")
    assert mism == [], (
        "the ring routes identically to BookSim yet must NOT execute: "
        "certificate failure dominates")
