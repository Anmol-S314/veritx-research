"""The Compile Result freshness guard must not be unsatisfiable.

Regression: `compile_result_is_current` invalidated any payload whose fabric
declared shared links but whose routing group carried no `shared_route`. A
GEC-hybrid route is a ranked candidate union per (source, destination), so
`_shared_route_table` refuses to publish one BY DESIGN — the guard could
therefore never be satisfied for a hybrid revision, and every Compile Result
and diff read recompiled the whole 49-router fabric through the hash-checked
fallback (~10 s per request, twice for a diff).

The guard now accepts a payload that DECLARES the withheld relation, and still
refuses one that merely dropped it. Both claims are pinned here.
"""
from __future__ import annotations

from types import SimpleNamespace

from veritx_dse.application.compile_result_view import (
    CONTRACT_VERSION,
    SHARED_ROUTE_POLICY_CANDIDATE_UNION,
    SHARED_ROUTE_POLICY_TABLE,
    _routing,
    compile_result_is_current,
)
from veritx_dse.model.gec_hybrid_route import (
    GecHybridParams, gec_hybrid_route_for_topology,
)
from veritx_dse.model.topology_artifact import materialize_gec_hybrid

_SHARED_LINK = {"shared_link_id": 0, "src_router": 0, "taps": [1, 2]}


def _payload(routing, *, shared_links=(_SHARED_LINK,)):
    return {
        "contract_version": CONTRACT_VERSION,
        "certificate": None,
        "groups": {
            "fabric": {"topology": {"shared_links": list(shared_links)}},
            "routing": routing,
        },
    }


def _hybrid_routing():
    topology = materialize_gec_hybrid(k=3, concentration=1, o=1, d=2)
    params = GecHybridParams(k=3, c=1, o=1, d=2, num_vcs=4)
    route = gec_hybrid_route_for_topology(params, topology)
    return _routing(SimpleNamespace(router_route=route, topology=topology),
                    None)


def test_a_hybrid_revision_declares_its_withheld_candidate_union():
    routing = _hybrid_routing()

    assert routing["shared_route"] is None, (
        "a candidate union is not one deterministic table")
    assert routing["shared_route_policy"] == SHARED_ROUTE_POLICY_CANDIDATE_UNION
    assert compile_result_is_current(_payload(routing)) is True


def test_a_payload_that_silently_dropped_the_relation_is_still_refused():
    """An older inspector published no `shared_route` and no policy at all."""
    assert compile_result_is_current(
        _payload({"routing_classes": ["row"]})) is False


def test_a_payload_that_declares_no_shared_route_artifact_is_still_refused():
    """Only the deliberate candidate-union refusal is accepted."""
    assert compile_result_is_current(
        _payload({"shared_route": None,
                  "shared_route_policy": "NO_SHARED_ROUTE_ARTIFACT"})) is False


def test_a_published_table_and_a_fabric_without_shared_links_are_current():
    assert compile_result_is_current(
        _payload({"shared_route": {"choices": []},
                  "shared_route_policy": SHARED_ROUTE_POLICY_TABLE})) is True
    assert compile_result_is_current(
        _payload({}, shared_links=())) is True
