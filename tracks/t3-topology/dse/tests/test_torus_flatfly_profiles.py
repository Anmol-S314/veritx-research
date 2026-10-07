"""Torus/FlatFly backend profiles: audit, qualifier gates, select dispatch.

Qualifier parents are synthetic-but-real: real TopologyArtifact +
real RouteArtifact, stub attachment/endpoints, real VCResourceArtifact,
stub vc_assignment binding. The qualifier is the unit under test not
certification — certification additionally requires the DEADLOCK_FREE
CDG verdict (torus: open dateline-partition bridge, pinned by
test_torus_route.py).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.booksim_projection import (  # noqa: E402
    FLATFLY_MIN_PROFILE,
    TORUS_DOR_PROFILE,
    SemanticLoss,
    qualify_native_flatfly_min,
    qualify_native_torus_dor,
    select_booksim_profile,
    source_audit_report,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.core.route_artifact import (  # noqa: E402
    DOR_TORUS_XY,
    FLATFLY_MIN,
    RouteArtifact,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    materialize_family,
    materialize_flatfly,
)
from veritx_dse.model.vc_resource import VCResourceArtifact  # noqa: E402


def _ep(n):
    return SimpleNamespace(
        endpoints=[SimpleNamespace(endpoint_id=i, router_id=i, port_id=0)
                   for i in range(n)],
        attachment_hash=lambda: 'test-attachment')


def _vc2(cls):
    return VCResourceArtifact(
        vc_count=2, vc_ids=(0, 1),
        traffic_class_to_vcs=(("default", (0, 1)),),
        allowed_transitions=((0, 0), (1, 1)), derivation="unit-test")


def _vc1(cls):
    return VCResourceArtifact(
        vc_count=1, vc_ids=(0,),
        traffic_class_to_vcs=(("default", (0,)),),
        allowed_transitions=((0, 0),), derivation="unit-test")


def _traffic():
    return SimpleNamespace(
        logical=SimpleNamespace(traffic_class="default"),
        traffic=[object()])


def _torus_parents(k=5, vc=None):
    t = materialize_family(
        MaterializedFamily.TORUS, endpoint_count=k * k, concentration=1,
        radix=k)
    r = RouteArtifact.from_topology(
        t, name="t", routing_classes=(DOR_TORUS_XY,))
    return SimpleNamespace(
        resolved_fabric=SimpleNamespace(), topology=t,
        attachment=_ep(k * k), mapping=SimpleNamespace(),
        vc_resource=vc or _vc2(DOR_TORUS_XY),
        vc_assignment=SimpleNamespace(
            vc_to_routing_class=((0, DOR_TORUS_XY), (1, DOR_TORUS_XY))),
        packet_format=SimpleNamespace(), route=r,
        physical_traffic=_traffic())


def _flatfly_parents():
    f = materialize_flatfly(k=4, n=2, concentration=1)
    r = RouteArtifact.from_topology(
        f, name="f", routing_classes=(FLATFLY_MIN,))
    return SimpleNamespace(
        resolved_fabric=SimpleNamespace(), topology=f,
        attachment=_ep(16), mapping=SimpleNamespace(),
        vc_resource=_vc1(FLATFLY_MIN),
        vc_assignment=SimpleNamespace(
            vc_to_routing_class=((0, FLATFLY_MIN),)),
        packet_format=SimpleNamespace(), route=r,
        physical_traffic=_traffic())


def test_torus_source_audit_clean_and_key_registered():
    for profile in (TORUS_DOR_PROFILE, FLATFLY_MIN_PROFILE):
        report = source_audit_report(
            profile, source_root=REPO / "third_party/booksim2/src")
        assert report["clean"], report["missing_from_source"]


def test_torus_qualifier_accepts_odd_k_with_2vcs():
    q = qualify_native_torus_dor(_torus_parents(k=5))
    assert q.k == 5 and q.router_count == 25
    assert q.tie_flows == ()


def test_torus_qualifier_refuses_even_k_randomized_midpoint_ties():
    with pytest.raises(SemanticLoss, match="requires odd side length"):
        qualify_native_torus_dor(_torus_parents(k=4))


def test_torus_qualifier_refuses_vc1():
    with pytest.raises(SemanticLoss, match="exactly 2 VCs"):
        qualify_native_torus_dor(_torus_parents(k=5, vc=_vc1(DOR_TORUS_XY)))


def test_torus_qualifier_refuses_mesh():
    p = _torus_parents(k=5)
    mesh = materialize_family(
        MaterializedFamily.MESH, endpoint_count=25, concentration=1,
        radix=5)
    p.topology = mesh
    with pytest.raises(SemanticLoss, match="TORUS only"):
        qualify_native_torus_dor(p)


def test_flatfly_qualifier_accepts():
    q = qualify_native_flatfly_min(_flatfly_parents())
    assert (q.k, q.n, q.concentration) == (4, 2, 1)


def test_flatfly_qualifier_refuses_mesh():
    p = _flatfly_parents()
    p.topology = materialize_family(
        MaterializedFamily.MESH, endpoint_count=16, concentration=1,
        radix=4)
    with pytest.raises(SemanticLoss, match="FLATFLY only"):
        qualify_native_flatfly_min(p)


def test_select_dispatches_torus_and_flatfly():
    assert select_booksim_profile(
        _torus_parents(k=5)).profile_id == TORUS_DOR_PROFILE.profile_id
    assert select_booksim_profile(
        _flatfly_parents()).profile_id == FLATFLY_MIN_PROFILE.profile_id
