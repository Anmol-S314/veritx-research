"""Torus + GEC-Express canonical routing/materialization.

DOR_TORUS_XY: wraparound-minimal X-then-Y with deterministic +x/+y
midpoint ties. GEC-EXPRESS: pure point-to-point express graph routed by
the sealed ANYNET_MIN_HOPS contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.route_artifact import (  # noqa: E402
    ANYNET_MIN_HOPS,
    DOR_TORUS_XY,
    RouteArtifact,
    RouteArtifactError,
    dor_torus_xy_tie_flows,
)
from veritx_dse.model.routing import (  # noqa: E402
    _POLICY_BY_FAMILY,
    routing_policy_for,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    TopologyError,
    materialize_family,
    materialize_gec_express,
)

def _torus(k: int = 4):
    return materialize_family(
        MaterializedFamily.TORUS, endpoint_count=k * k, concentration=1,
        radix=k)

def test_torus_materializes_wrap_links():
    t = _torus(4)
    assert len(t.routers) == 16 and len(t.channels) == 64
    deg = [0] * 16
    for c in t.channels:
        deg[c.src_router] += 1
    assert set(deg) == {4}
    assert any(c.src_router == 3 and c.dst_router == 0 for c in t.channels)

def test_dor_torus_xy_covers_all_pairs():
    t = _torus(4)
    r = RouteArtifact.from_topology(
        t, name="t", routing_classes=(DOR_TORUS_XY,))
    assert len(r.entries) == 16 * 15

def test_dor_torus_xy_x_then_y_with_wrap():
    t = _torus(5)
    r = RouteArtifact.from_topology(
        t, name="t", routing_classes=(DOR_TORUS_XY,))
    by_hop = {(c.src_router, c.dst_router): c.channel_id
              for c in t.channels}
    assert r.entries[(DOR_TORUS_XY, 0, 4)] == by_hop[(0, 4)]
    assert r.entries[(DOR_TORUS_XY, 0, 1)] == by_hop[(0, 1)]
    assert r.entries[(DOR_TORUS_XY, 0, 8)] == by_hop[(0, 4)]
    assert r.entries[(DOR_TORUS_XY, 0, 20)] == by_hop[(0, 20)]

def test_midpoint_tie_resolves_positive_and_is_carved_out():
    t = _torus(4)
    r = RouteArtifact.from_topology(
        t, name="t", routing_classes=(DOR_TORUS_XY,))
    by_hop = {(c.src_router, c.dst_router): c.channel_id
              for c in t.channels}
    assert r.entries[(DOR_TORUS_XY, 0, 2)] == by_hop[(0, 1)]
    ties = dor_torus_xy_tie_flows(t)
    assert (0, 2) in ties and len(ties) > 0
    assert dor_torus_xy_tie_flows(_torus(5)) == frozenset()
    assert dor_torus_xy_tie_flows(_torus(3)) == frozenset()

def test_dor_torus_xy_refuses_non_torus():
    m = materialize_family(
        MaterializedFamily.MESH, endpoint_count=16, concentration=1, radix=4)
    with pytest.raises(RouteArtifactError, match="TORUS"):
        RouteArtifact.from_topology(
            m, name="m", routing_classes=(DOR_TORUS_XY,))

def test_policy_table_routes_torus():
    t = _torus(4)
    assert _POLICY_BY_FAMILY[MaterializedFamily.TORUS] == DOR_TORUS_XY
    assert routing_policy_for(t) == DOR_TORUS_XY

def test_torus_deadlock_free_fails_with_named_dateline_cycle():
    """CHARACTERIZATION of the remaining open bridge (not a pass-to-fix).

    The 1-VC torus is genuinely cyclic: VC0 alone carries the X-ring
    cycle, so DEADLOCK_FREE FAILs with a named cycle witness. The 2-VC
    dateline domain (exact halves + identity transitions) discharges via
    the dateline-restricted CDG expansion — proven by the companion
    2-VC test below, NOT by this one. This test pins the 1-VC verdict
    so no one can claim the bridge is done for all torus designs.
    """
    import copy
    import json

    from veritx_dse.application.fabric_compiler import (  # noqa: E402
        FabricCompiler,
    )
    from veritx_dse.core.paths import REPO  # noqa: E402
    from veritx_dse.model.compile_model import (  # noqa: E402
        CompileRequestV3,
    )

    doc = json.loads(
        (REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json")
        .read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["noc_config"]["topology_family"] = "torus"
    doc["dependencies"] = []
    compilation = FabricCompiler().compile(CompileRequestV3.from_dict(doc))
    assert compilation.status == "INVALID"
    assert compilation.certificate is not None
    dead = [o for o in compilation.certificate.obligations
            if o.obligation == "DEADLOCK_FREE"]
    assert len(dead) == 1 and dead[0].status == "FAIL"
    assert dead[0].evidence.get("acyclic") is False
    assert dead[0].evidence.get("cycle"), "a witness is required, not a bare FAIL"

def test_gec_express_materializes_full_row_col_graph():
    g = materialize_gec_express(k=4, concentration=1)
    assert len(g.routers) == 16 and g.family is MaterializedFamily.GEC_EXPRESS
    deg = [0] * 16
    for c in g.channels:
        deg[c.src_router] += 1
    assert set(deg) == {6}
    outs = {c.dst_router for c in g.channels if c.src_router == 0}
    assert {1, 2, 3, 4, 8, 12} <= outs

def test_gec_express_law_enforced():
    from types import SimpleNamespace  # noqa: E402

    from veritx_dse.model.topology_intent import (  # noqa: E402
        GecMode,
        GecTopologyIntent,
    )
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        materialize_topology_intent,
    )

    inv = SimpleNamespace(agent_count=16)
    good = GecTopologyIntent(
        mode=GecMode.EXPRESS, grid_side_length=4, concentration=1,
        express_channel_groups_per_dimension=3,
        destinations_per_express_channel=1)
    art = materialize_topology_intent(inv, good)
    assert art.family is MaterializedFamily.GEC_EXPRESS
    assert len(art.routers) == 16
    from veritx_dse.model.topology_intent import (  # noqa: E402
        TopologyIntentError,
    )
    with pytest.raises(TopologyIntentError, match="o\\*d == k-1"):
        GecTopologyIntent(
            mode=GecMode.EXPRESS, grid_side_length=4, concentration=1,
            express_channel_groups_per_dimension=2,
            destinations_per_express_channel=1)
    mecs = GecTopologyIntent(
        mode=GecMode.MULTIDROP, grid_side_length=4, concentration=1,
        express_channel_groups_per_dimension=1,
        destinations_per_express_channel=3)
    with pytest.raises(TopologyError, match="never|flatten|shared tapped"):
        materialize_topology_intent(inv, mecs)
    hybrid = GecTopologyIntent(
        mode=GecMode.HYBRID, grid_side_length=4, concentration=1,
        express_channel_groups_per_dimension=1,
        destinations_per_express_channel=3)
    with pytest.raises(TopologyError, match="HYBRID"):
        materialize_topology_intent(inv, hybrid)

def test_gec_express_routes_anynet_min_hops():
    from veritx_dse.core.route_artifact import (  # noqa: E402
        compare_first_hop_tables,
    )

    g = materialize_gec_express(k=4, concentration=1)
    assert routing_policy_for(g) == ANYNET_MIN_HOPS
    r = RouteArtifact.from_topology(
        g, name="g", routing_classes=(ANYNET_MIN_HOPS,))
    assert len(r.entries) == 16 * 15
    by_hop = {(c.src_router, c.dst_router) for c in g.channels}
    for (cls, s, t), ch in r.entries.items():
        assert cls == ANYNET_MIN_HOPS
        ch_obj = next(c for c in g.channels if c.channel_id == ch)
        assert (ch_obj.src_router, ch_obj.dst_router) in by_hop
