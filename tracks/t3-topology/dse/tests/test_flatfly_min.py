"""FlatFly minimal routing: lowest-dimension-first, canonical numbering."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.route_artifact import (  # noqa: E402
    FLATFLY_MIN,
    RouteArtifact,
    RouteArtifactError,
)
from veritx_dse.model.routing import (  # noqa: E402
    _POLICY_BY_FAMILY,
    routing_policy_for,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    materialize_flatfly,
)

def _ff():
    return materialize_flatfly(k=4, n=2, concentration=1)

def test_flatfly_shape_and_policy():
    f = _ff()
    assert len(f.routers) == 16 and f.family is MaterializedFamily.FLATFLY
    assert _POLICY_BY_FAMILY[MaterializedFamily.FLATFLY] == FLATFLY_MIN
    assert routing_policy_for(f) == FLATFLY_MIN
    r = RouteArtifact.from_topology(
        f, name="f", routing_classes=(FLATFLY_MIN,))
    assert len(r.entries) == 16 * 15

def test_lowest_dimension_first():
    f = _ff()
    r = RouteArtifact.from_topology(
        f, name="f", routing_classes=(FLATFLY_MIN,))
    by_hop = {(c.src_router, c.dst_router): c.channel_id
              for c in f.channels}
    coords = {x.router_id: tuple(x.coordinates) for x in f.routers}
    for (cls, s, t), ch in r.entries.items():
        assert cls == FLATFLY_MIN
        nxt = next(c.dst_router for c in f.channels if c.channel_id == ch)
        sc, tc, nc = coords[s], coords[t], coords[nxt]
        diffs = [i for i in range(2) if sc[i] != nc[i]]
        assert len(diffs) == 1
        dim = diffs[0]
        assert all(sc[i] == tc[i] for i in range(dim))
        assert sc[dim] != tc[dim] and nc[dim] == tc[dim]
        assert all(nc[i] == sc[i] for i in range(2) if i != dim)
        assert (s, nxt) in by_hop

def test_flatfly_min_refuses_non_flatfly():
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        materialize_family,
    )

    m = materialize_family(
        MaterializedFamily.MESH, endpoint_count=16, concentration=1,
        radix=4)
    with pytest.raises(RouteArtifactError, match="FLATFLY"):
        RouteArtifact.from_topology(
            m, name="m", routing_classes=(FLATFLY_MIN,))

def test_flatfly_diameter_bound():
    f = _ff()
    r = RouteArtifact.from_topology(
        f, name="f", routing_classes=(FLATFLY_MIN,))
    coords = {x.router_id: tuple(x.coordinates) for x in f.routers}
    nxt_of = {}
    for (cls, s, t), ch in r.entries.items():
        nxt_of[(s, t)] = next(
            c.dst_router for c in f.channels if c.channel_id == ch)
    for s in range(16):
        for t in range(16):
            if s == t:
                continue
            hops, cur, seen = 0, s, set()
            while cur != t:
                assert cur not in seen
                seen.add(cur)
                cur = nxt_of[(cur, t)]
                hops += 1
            sc, tc = coords[s], coords[t]
            assert hops == sum(1 for i in range(2) if sc[i] != tc[i]) <= 2
