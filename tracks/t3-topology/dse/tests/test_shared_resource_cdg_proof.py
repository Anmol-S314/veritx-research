"""Acyclicity certificates for the shared-resource dependency graph.

The fixtures are the same two hand-derived fabrics as
``test_shared_resource_cdg.py``: a chain (acyclic) and a triangle (cyclic).
Nothing here restates the implementation. Each test asks a different reader the
same question, because the whole point of a witness is that a PASS stops
depending on one traversal:

  * the witness itself must satisfy every edge inequality when checked by hand;
  * Kahn and DFS must agree on both fixtures;
  * SMT-LIB emitted from the graph must be decided the same way by z3;
  * a tampered witness must be refused, not tolerated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.shared_resource import ResourceKind, ResourceRef, RouteDecision  # noqa: E402
from veritx_dse.verification.shared_resource_cdg import (  # noqa: E402
    build_shared_resource_cdg,
)
from veritx_dse.verification.shared_resource_cdg_proof import (  # noqa: E402
    AcyclicityProof,
    SharedResourceCDGProofError,
    certificate,
    check_with_solver,
    emit_smtlib,
    prove_acyclic,
    solver_available,
    topological_rank,
    verify_rank_witness,
)

A = ResourceRef(ResourceKind.SHARED_LINK, 0)
B = ResourceRef(ResourceKind.SHARED_LINK, 1)
C = ResourceRef(ResourceKind.SHARED_LINK, 2)


def _bus(resource, next_router, tap=0, partition=0):
    return RouteDecision(resource=resource, next_router=next_router,
                         vc_partition=partition, tap=tap)


def _chain():
    """Acyclic: only 0->3 spans two buses, so the single edge is A -> B."""
    return build_shared_resource_cdg(
        decisions={
            (0, 1): _bus(A, 1, tap=0),
            (0, 2): _bus(A, 2, tap=1),
            (0, 3): _bus(A, 1, tap=0),
            (1, 3): _bus(B, 3, tap=0),
            (2, 3): _bus(C, 3, tap=0),
        },
        partition_to_vcs={0: (0,)}, allowed_transitions=((0, 0),),
        routers=(0, 1, 2, 3))


def _triangle():
    """Cyclic: A -> B -> C -> A, the smallest fabricated cycle."""
    return build_shared_resource_cdg(
        decisions={
            (0, 1): _bus(A, 1),
            (0, 2): _bus(A, 1),
            (1, 2): _bus(B, 2),
            (1, 0): _bus(B, 2),
            (2, 0): _bus(C, 0),
            (2, 1): _bus(C, 0),
        },
        partition_to_vcs={0: (0,)}, allowed_transitions=((0, 0),),
        routers=(0, 1, 2))


def test_chain_yields_a_witness_that_satisfies_every_edge():
    cdg = _chain()
    proof = prove_acyclic(cdg)
    assert proof is not None
    ranks = proof.rank_map()
    assert set(ranks) == set(cdg.nodes)
    # Derived on paper: the only edge is A -> B, so A must rank below B.
    assert ranks[(A, 0)] < ranks[(B, 0)]
    # C carries no dependency either way, but it must still be ranked.
    assert (C, 0) in ranks


def test_witness_verifies_without_the_producer():
    """An auditor checks the artifact, not this module's traversal."""
    cdg = _chain()
    proof = prove_acyclic(cdg)
    assert isinstance(proof, AcyclicityProof)
    verify_rank_witness(cdg, proof)             # from the frozen artifact
    verify_rank_witness(cdg, proof.rank_map())  # from a plain dict
    as_dict = proof.as_dict()
    assert as_dict["proof_method"] == "SHARED_RESOURCE_RANK_WITNESS"
    assert as_dict["arbitration_fairness_modeled"] is False
    assert as_dict["sufficient_for_egress_under_any_arbitration"] is False


def test_triangle_has_no_rank_and_no_proof():
    cdg = _triangle()
    assert topological_rank(cdg) is None
    assert prove_acyclic(cdg) is None
    # The DFS reader must agree that it is cyclic, and name the cycle.
    assert cdg.find_cycle() is not None


def test_the_two_readers_always_agree():
    """Kahn and DFS are separate code paths on the same question."""
    for build in (_chain, _triangle):
        cdg = build()
        assert (topological_rank(cdg) is None) == (cdg.find_cycle() is not None)


def test_a_tampered_witness_is_refused():
    cdg = _chain()
    ranks = topological_rank(cdg)
    assert ranks is not None
    # Swap the ranks: A -> B now fails to increase.
    swapped = dict(ranks)
    swapped[(A, 0)], swapped[(B, 0)] = swapped[(B, 0)], swapped[(A, 0)]
    with pytest.raises(SharedResourceCDGProofError, match="does not increase"):
        verify_rank_witness(cdg, swapped)


def test_a_partial_witness_is_refused():
    cdg = _chain()
    ranks = topological_rank(cdg)
    assert ranks is not None
    del ranks[(C, 0)]
    with pytest.raises(SharedResourceCDGProofError, match="omits"):
        verify_rank_witness(cdg, ranks)


def test_a_witness_naming_uncharted_nodes_is_refused():
    cdg = _chain()
    ranks = topological_rank(cdg)
    assert ranks is not None
    ranks[(A, 99)] = 99
    with pytest.raises(SharedResourceCDGProofError, match="does not declare"):
        verify_rank_witness(cdg, ranks)


def test_a_non_integer_rank_is_refused():
    cdg = _chain()
    ranks = topological_rank(cdg)
    assert ranks is not None
    ranks[(A, 0)] = "0"  # type: ignore[assignment]
    with pytest.raises(SharedResourceCDGProofError, match="must be an int"):
        verify_rank_witness(cdg, ranks)


def test_the_smt_encoding_states_every_edge_and_bounds_every_rank():
    cdg = _chain()
    script = emit_smtlib(cdg)
    assert "(set-logic QF_LIA)" in script
    assert script.count("(declare-fun r") == cdg.node_count
    # One strict inequality per dependency edge: exactly the question asked.
    assert script.count("(assert (< r") == cdg.edge_count
    assert script.count("(assert (>= r") == cdg.node_count
    assert script.count("(assert (<= r") == cdg.node_count
    assert script.rstrip().endswith(")")
    # The graph identity travels with the artifact so it cannot be rebased.
    assert cdg.cdg_id() in script


def test_the_witness_is_deterministic_across_rebuilds():
    """The proof id is hashed, so an unstable order would make it undiffable."""
    first = prove_acyclic(_chain())
    second = prove_acyclic(build_shared_resource_cdg(
        decisions={
            (0, 1): _bus(A, 1, tap=0),
            (0, 2): _bus(A, 2, tap=1),
            (0, 3): _bus(A, 1, tap=0),
            (1, 3): _bus(B, 3, tap=0),
            (2, 3): _bus(C, 3, tap=0),
        },
        partition_to_vcs={0: (0,)}, allowed_transitions=((0, 0),),
        routers=(0, 1, 2, 3)))
    assert first is not None and second is not None
    assert first.ranks == second.ranks
    assert first.proof_id() == second.proof_id()


@pytest.mark.skipif(not solver_available(), reason="z3 not installed")
def test_the_solver_re_decides_the_acyclic_case_as_sat():
    state, model = check_with_solver(_chain())
    assert state == "sat", state
    assert model is not None
    cdg = _chain()
    # The solver's model is a topological order in its own right; check it with
    # the same O(V+E) verifier, so the two readers are compared on evidence.
    ranks = {node: model[index]
             for (node, index) in {n: i for i, n in enumerate(cdg.nodes)}.items()}
    verify_rank_witness(cdg, ranks)


@pytest.mark.skipif(not solver_available(), reason="z3 not installed")
def test_the_solver_re_decides_the_cyclic_case_as_unsat():
    state, _ = check_with_solver(_triangle())
    assert state == "unsat", state


@pytest.mark.skipif(not solver_available(), reason="z3 not installed")
def test_certificate_carries_both_readers():
    cert = certificate(_chain())
    assert cert["acyclic"] is True
    assert cert["solver"] == "sat"
    assert cert["proof"]["proof_method"] == "SHARED_RESOURCE_RANK_WITNESS"
    assert "(check-sat)" in cert["smtlib"]

    cyclic = certificate(_triangle(), cross_check_solver=False)
    assert cyclic["acyclic"] is False
    assert cyclic["proof"] is None
    assert cyclic["solver"] == "not-asked"


def test_certificate_verdict_matches_the_dfs_verdict():
    """The certificate layer and the verdict layer must not drift apart."""
    from veritx_dse.verification.shared_resource_cdg_proof import certificate

    for build, expected in ((_chain, True), (_triangle, False)):
        cdg = build()
        assert certificate(cdg, cross_check_solver=False)["acyclic"] is expected
        assert (cdg.find_cycle() is None) is expected
