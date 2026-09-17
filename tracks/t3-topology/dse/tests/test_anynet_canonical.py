"""core.anynet: one parser, BookSim's anynet.cpp grammar, both dialects.

The regression this file pins: three parsers had diverged and the
two-line dialect (configs/anynet16.links) parsed as EMPTY (presets) or
DIRECTED (deadlock_routing). These tests build tiny files per grammar
rule and assert against the C source's documented behavior — symmetrized
router-router edges, one-router-per-node, sequential ids from 0.
"""
import pytest

from veritx_dse.core.anynet import (
    AnynetError,
    check_anynet_connected,
    count_anynet_edges,
    parse_anynet_file,
)

ONE_LINE_RING = (
    "router 0 node 0 router 1 router 3\n"
    "router 1 node 1 router 0 router 2\n"
    "router 2 node 2 router 1 router 3\n"
    "router 3 node 3 router 2 router 0\n"
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_two_line_dialect_parses(tmp_path):
    """The configs/anynet16.links shape: node lines + one-way router-router
    lines. BookSym symmetrizes; the parser must too."""
    p = _write(tmp_path, "links", (
        "router 0 node 0\nrouter 1 node 1\nrouter 2 node 2\nrouter 3 node 3\n"
        "router 0 router 1 1\nrouter 1 router 2 1\n"
        "router 2 router 3 1\nrouter 3 router 0 1\n"))
    n, e = count_anynet_edges(p)
    assert (n, e) == (4, 4)
    g = parse_anynet_file(p)
    assert g.n_nodes == 4
    # symmetrized: 0's peers include 3 even though only '3 router 0' declared it
    assert g.router_adj[0] == {1, 3}


def test_one_line_dialect_parses(tmp_path):
    p = _write(tmp_path, "one", ONE_LINE_RING)
    assert count_anynet_edges(p) == (4, 4)
    connected, n, unreached = check_anynet_connected(p)
    assert connected and n == 4 and unreached == 0


def test_weights_are_accepted_and_ignored_for_adjacency(tmp_path):
    """anynet.cpp LINK_WEIGHT: trailing integer sets channel latency —
    adjacency topology is unchanged."""
    p = _write(tmp_path, "w", (
        "router 0 node 0 router 1 15\n"
        "router 1 node 1 router 0\n"))
    n, e = count_anynet_edges(p)
    assert (n, e) == (2, 1)


def test_one_way_declaration_symmetrizes(tmp_path):
    """The old deadlock_routing blind spot: declared-one-way ring became a
    DIRECTED cycle. Now always undirected."""
    p = _write(tmp_path, "dir", (
        "router 0 node 0 router 1\n"
        "router 1 node 1 router 2\n"
        "router 2 node 2 router 0\n"))
    assert count_anynet_edges(p)[1] == 3
    connected, _, _ = check_anynet_connected(p)
    assert connected


def test_node_must_attach_to_one_router(tmp_path):
    p = _write(tmp_path, "multi", (
        "router 0 node 0\n"
        "router 1 node 0\n"))          # node 0 claims two routers
    with pytest.raises(AnynetError, match="exactly one router"):
        parse_anynet_file(p)


def test_node_to_node_is_rejected(tmp_path):
    p = _write(tmp_path, "nn", "node 0 node 1\n")
    with pytest.raises(AnynetError, match="node-to-node"):
        parse_anynet_file(p)


def test_non_sequential_ids_rejected(tmp_path):
    """BookSim: 'Router and node numbers must be sequential starting with 0.'"""
    p = _write(tmp_path, "gap", (
        "router 0 node 0 router 2\n"
        "router 2 node 2 router 0\n"))
    g = parse_anynet_file(p)
    with pytest.raises(AnynetError, match="sequential"):
        g.sequential_adj()


def test_garbage_line_fails_loud_with_location(tmp_path):
    p = _write(tmp_path, "bad", "router 0 node zero\n")
    with pytest.raises(AnynetError, match="not an integer"):
        parse_anynet_file(p)


def test_empty_and_unreadable_yield_disconnected(tmp_path):
    empty = _write(tmp_path, "empty", "# comments only\n")
    assert check_anynet_connected(empty) == (False, 0, 0)
    assert check_anynet_connected(tmp_path / "nope") == (False, 0, 0)


def test_regression_real_anynet16_links():
    """The exact file that exposed the three-parser split."""
    from veritx_dse.core.paths import DSE_DIR
    links = DSE_DIR.parent / "configs" / "anynet16.links"
    if not links.exists():
        pytest.skip("configs/anynet16.links not present")
    n, e = count_anynet_edges(links)
    assert (n, e) == (16, 16)
    connected, _, unreached = check_anynet_connected(links)
    assert connected and unreached == 0


def test_legacy_delegates_agree_with_canonical(tmp_path):
    """deadlock_routing.parse_anynet and presets._parse_anynet_adj are
    delegating shims — their answers must equal the canonical parser's
    on both dialects (this is the contract that was silently broken)."""
    from veritx_dse.model.presets import _parse_anynet_adj
    import sys
    sys.path.insert(0, str(
        __import__("pathlib").Path(
            __import__("veritx_dse.tools.deadlock_routing",
                       fromlist=["parse_anynet"]).__file__).parent))
    from deadlock_routing import parse_anynet as legacy_parse

    for text in (ONE_LINE_RING,
                 "router 0 node 0\nrouter 1 node 1\nrouter 2 node 2\n"
                 "router 0 router 1\nrouter 1 router 2\nrouter 2 router 0\n"):
        p = _write(tmp_path, "t", text)
        n, adj = legacy_parse(p)
        g = parse_anynet_file(p)
        assert n == g.n_routers
        assert adj == g.router_adj
        assert _parse_anynet_adj(p) == g.router_adj
