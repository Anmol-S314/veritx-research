"""Executed route realization observation (P0.10).

The comparison is derived from the canonical route artifacts and must
refuse missing, extra, divergent, malformed and duplicate dump rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim_projection import _parents  # noqa: E402

from veritx_dse.backend import booksim_projection as bp  # noqa: E402
from veritx_dse.backend.route_observation import (  # noqa: E402
    RouteObservationError, compare_route_realization, expected_route_rows,
    parse_route_dump,
)


def _prepared():
    _compiled, parents = _parents()
    return bp.prepare_booksim_input(parents)


def _dump_from(rows) -> str:
    return "\n".join(
        f"src_router {r} dst_node {n} next_router {x} port 0"
        for r, n, x in rows) + "\n"


def test_expected_rows_cover_every_router_node():
    prepared = _prepared()
    rows = prepared.expected_route_rows
    assert rows
    routers = {r for r, _n, _x in rows}
    nodes = {n for _r, n, _x in rows}
    assert routers == set(range(prepared.router_count))
    assert nodes == set(range(prepared.router_count))  # native mesh: node==router


def test_exact_dump_matches():
    prepared = _prepared()
    result = compare_route_realization(
        expected_rows=prepared.expected_route_rows,
        dump_text=_dump_from(prepared.expected_route_rows))
    assert result.pairs_compared == len(prepared.expected_route_rows)


def test_divergent_next_hop_refuses():
    prepared = _prepared()
    rows = list(prepared.expected_route_rows)
    src, node, nxt = rows[-1]
    rows[-1] = (src, node, (nxt + 1) % prepared.router_count)
    with pytest.raises(RouteObservationError, match="diverges"):
        compare_route_realization(
            expected_rows=prepared.expected_route_rows,
            dump_text=_dump_from(rows))


def test_missing_row_refuses():
    prepared = _prepared()
    rows = list(prepared.expected_route_rows)[:-1]
    with pytest.raises(RouteObservationError, match="coverage"):
        compare_route_realization(
            expected_rows=prepared.expected_route_rows,
            dump_text=_dump_from(rows))


def test_extra_row_refuses():
    prepared = _prepared()
    rows = list(prepared.expected_route_rows) + [(0, 999, 0)]
    with pytest.raises(RouteObservationError, match="coverage"):
        compare_route_realization(
            expected_rows=prepared.expected_route_rows,
            dump_text=_dump_from(rows))


def test_malformed_duplicate_and_empty_refuse():
    prepared = _prepared()
    with pytest.raises(RouteObservationError, match="malformed"):
        parse_route_dump("src_router 0 dst_node 1 next_router 2\n")
    with pytest.raises(RouteObservationError, match="repeats"):
        parse_route_dump("src_router 0 dst_node 0 next_router 0 port 0\n"
                         "src_router 0 dst_node 0 next_router 0 port 0\n")
    with pytest.raises(RouteObservationError, match="empty"):
        parse_route_dump("# only a comment\n")


def test_expected_rows_agree_with_route_artifact_directly():
    compiled, parents = _parents()
    rows = expected_route_rows(
        routing_class=bp.DOR_XY, topology=parents.topology,
        route=parents.route,
        node_to_router={n: n for n in range(parents.topology.router_count)})
    # identical to the projection's bound table
    assert rows == bp.prepare_booksim_input(parents).expected_route_rows


def test_nonadjacent_next_hop_refuses():
    """Invalid adjacency: a lexically valid dump line naming a router that
    is not a legal first hop is refused. Exact equality against the
    channel-derived expectation subsumes adjacency legality."""
    prepared = _prepared()
    rows = list(prepared.expected_route_rows)
    idx = next(i for i, (r, n, _x) in enumerate(rows) if r != n)
    r, n, x = rows[idx]
    rows[idx] = (r, n, (x + prepared.router_count // 2)
                 % prepared.router_count)          # far, non-adjacent
    with pytest.raises(RouteObservationError, match="diverges"):
        compare_route_realization(
            expected_rows=prepared.expected_route_rows,
            dump_text=_dump_from(rows))


def test_unknown_routing_class_refuses():
    """A routing class the RouteArtifact never proved is refused, not
    silently treated as an empty expectation."""
    _compiled, parents = _parents()
    with pytest.raises(RouteObservationError, match="no entry"):
        expected_route_rows(
            routing_class="NO_SUCH_CLASS", topology=parents.topology,
            route=parents.route,
            node_to_router={n: n for n in range(parents.topology.router_count)})


def test_transplanted_route_dump_refuses():
    """A dump produced for a different fabric cannot satisfy this
    expectation (no transplantation)."""
    _compiled, parents = _parents()
    prepared = _prepared()
    _other_compiled, other_parents = _parents(compute=4, tp=4)
    other = bp.prepare_booksim_input(other_parents)
    assert other.expected_route_rows != prepared.expected_route_rows
    with pytest.raises(RouteObservationError):
        compare_route_realization(
            expected_rows=prepared.expected_route_rows,
            dump_text=_dump_from(other.expected_route_rows))
