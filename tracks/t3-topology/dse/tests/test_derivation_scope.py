"""Reuse of one pure derivation is bounded to one adjudication.

The hybrid per-instance proof is requested once per planned question per
backend adapter with identical arguments. Reusing it inside that adjudication
is sound (same immutable inputs, same derivation); reusing it ACROSS them is
not, because a caller that swaps a derivation implementation must see its own
result. These tests pin both halves, plus the equal-input cache on the hybrid
route union.
"""
from __future__ import annotations

from dataclasses import replace

from veritx_dse.core.derivation_scope import (
    derivation_scope, scoped_adjudication, scoped_derivation,
)
from veritx_dse.model.gec_hybrid_route import gec_hybrid_route_for_topology
from veritx_dse.model.topology_artifact import materialize_gec_hybrid
from veritx_dse.verification.gec_hybrid_candidate_cdg import GecHybridParams


def _hybrid(k=3, o=1, d=2, num_vcs=4):
    topology = materialize_gec_hybrid(k=k, concentration=1, o=o, d=d)
    return GecHybridParams(k=k, c=1, o=o, d=d, num_vcs=num_vcs), topology


def test_outside_a_scope_every_call_derives():
    calls = []

    def derive():
        calls.append(1)
        return object()

    first = scoped_derivation("kind", "key", derive)
    second = scoped_derivation("kind", "key", derive)
    assert len(calls) == 2
    assert first is not second


def test_inside_a_scope_one_derivation_serves_every_ask():
    calls = []

    def derive():
        calls.append(1)
        return object()

    with derivation_scope():
        values = [scoped_derivation("kind", "key", derive) for _ in range(5)]
        other = scoped_derivation("kind", "another-key", derive)
    assert len(calls) == 2
    assert all(value is values[0] for value in values)
    assert other is not values[0]

    scoped_derivation("kind", "key", derive)
    assert len(calls) == 3, "the scope must not outlive its block"


def test_a_nested_scope_joins_the_open_one_instead_of_shadowing_it():
    calls = []

    def derive():
        calls.append(1)
        return object()

    with derivation_scope():
        first = scoped_derivation("kind", "key", derive)
        with derivation_scope():
            inner = scoped_derivation("kind", "key", derive)
    assert len(calls) == 1
    assert first is inner


def test_the_decorator_scopes_one_adjudication():
    calls = []

    @scoped_adjudication
    def adjudicate(times):
        return [scoped_derivation("k", "i", lambda: calls.append(1) or object())
                for _ in range(times)]

    adjudicate(3)
    adjudicate(3)
    assert len(calls) == 2


def test_the_hybrid_route_union_is_reused_for_equal_inputs_only():
    params, topology = _hybrid()
    union = gec_hybrid_route_for_topology(params, topology)

    assert gec_hybrid_route_for_topology(params, topology) is union

    # A different topology with a different hash is a different union, never
    # a cached one.
    other_params, other_topology = _hybrid(k=4, o=1, d=3, num_vcs=6)
    assert other_topology.topology_hash() != topology.topology_hash()
    other_union = gec_hybrid_route_for_topology(other_params, other_topology)
    assert other_union is not union

    # A different VC count is a different union too.
    assert gec_hybrid_route_for_topology(
        replace(params, num_vcs=params.num_vcs + 2), topology) is not union


def test_the_reused_union_keeps_its_artifact_identity():
    params, topology = _hybrid()
    union = gec_hybrid_route_for_topology(params, topology)
    fresh = gec_hybrid_route_for_topology(params, topology)
    assert union is fresh
    assert union.route_artifact_id() == union.route_artifact_id()
    assert union.shared_resource_cdg() is union.shared_resource_cdg()
