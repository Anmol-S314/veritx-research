"""A rank-policy SROTA route must reach the Studio as a shared route table.

Regression: `compile_result_view._routing` recognized a shared-resource route
by `schema_version == 3`. `srota_rank_route.RankPolicyRoute` stamps
`schema_version = 1` from its own module constant while being a v3
shared-resource artifact, so every SROTA revision compiled with
`vc_policy=rank` served `routing_classes: []` and `shared_route: None`.

The Studio reads that field to place a flit on a single wire, so the whole
"Flit playback" and "Route sweep" pair died with the message "This revision
exposes no deterministic shared-resource route table" — for a fabric that
declared 80 shared links with a fully derived, differentially-qualified route
artifact in its bundle.

The fix is a shape test, not a schema-integer test, because the artifact
shape is what the reader depends on. Two claims are pinned here: the rank
route is exposed, and the adaptive GEC-hybrid union is still refused.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.compile_result_view import _routing  # noqa: E402
from veritx_dse.model.gec_hybrid_route import (  # noqa: E402
    GEC_HYBRID_ROUTING_CLASS,
)
from veritx_dse.model.srota_rank_route import (  # noqa: E402
    rank_policy_route_for_srota,
)


def _rank_route():
    return rank_policy_route_for_srota(
        k=3, c=1, shapes=frozenset({"row", "column"}),
        mecs_row=True, mecs_col=True, topology_hash="sha256:test")


def test_compile_result_view_exposes_the_rank_shared_route():
    route = _rank_route()
    view = _routing(SimpleNamespace(router_route=route, topology=None), None)

    assert view["available"] is True
    assert view["routing_classes"] == [route.routing_class]
    assert view["default_class"] == route.routing_class
    shared = view["shared_route"]
    assert shared is not None, (
        "the rank route is a shared-resource artifact; withholding it leaves "
        "the Studio unable to place a flit on a wire")
    assert shared["artifact_id"] == route.route_artifact_id()
    assert shared["routing_class"] == route.routing_class
    assert len(shared["choices"]) == len(route.choices)
    assert set(shared["partition_to_vcs"]) == {"0", "1"}


def test_the_route_artifact_identity_is_unchanged():
    """Exposing the table must not rewrite recorded identities.

    A revision pins `router_route_hash`. Re-stamping the schema changes the
    artifact id, and every stored revision then fails its own evidence check
    with EVIDENCE_INVALID — so the historical `1` is pinned here on purpose.
    The view recognizes the artifact by shape instead of asking the artifact
    to lie about its version.
    """
    route = _rank_route()
    assert route.schema_version == 1
    assert route.route_artifact_id() == _rank_route().route_artifact_id()


def test_an_adaptive_union_route_is_still_not_a_deterministic_shared_route():
    """GEC-hybrid is a ranked candidate union per (src, dst).

    The Studio refuses to draw one wire for it on purpose, so it must not be
    handed a shared route table by the shape test.
    """
    adaptive = SimpleNamespace(
        schema_version=1, routing_class=GEC_HYBRID_ROUTING_CLASS,
        routing_classes=(), entries={},
        canonical_dict=lambda: {"routing_class": GEC_HYBRID_ROUTING_CLASS},
        route_artifact_id=lambda: "sha256:adaptive")
    view = _routing(SimpleNamespace(router_route=adaptive, topology=None),
                    None)
    assert view["shared_route"] is None
    assert view["default_class"] is None
