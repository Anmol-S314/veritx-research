from __future__ import annotations

import pytest

from veritx_dse.product.ring_vc_cdg import (
    analyze,
    dateline_switch_law,
    fork_direction,
    fork_law,
    fork_partition,
    per_hop_partition,
    ring_next_router,
    ring_path,
    vc_acyclicity,
)

SIZES = (8, 16, 64)


def test_the_fork_partition_is_the_models_dateline_half():
    """The analysis must use the product's own partition, not a lookalike."""
    from veritx_dse.model.ring_net import ring_dateline_partition
    for source in range(16):
        for destination in range(16):
            assert fork_partition(source, destination) == \
                ring_dateline_partition(source, destination)


def test_the_fork_keeps_one_direction_for_a_whole_flow():
    """A flow's direction is chosen once and never changes."""
    for n in SIZES:
        for source in range(n):
            for destination in range(n):
                if source == destination:
                    continue
                directions = fork_direction(source, destination, n)
                assert directions in ((0,), (1,), (0, 1))
                for direction in directions:
                    path = ring_path(source, destination, n, direction)
                    assert path[0] == source
                    assert path[-1] == destination
                    for step in range(len(path) - 1):
                        assert path[step + 1] == ring_next_router(
                            path[step], destination, n, direction)


@pytest.mark.parametrize("n", SIZES)
def test_the_fork_law_leaves_every_vc_class_acyclic(n):
    """The fork's own law — the dateline half fixed per flow — is acyclic.

    This is the law the BookSim fork executes (`dor_next_torus` sets the
    partition when the flow turns into the dimension and keeps it), and it
    is the law the ring's RTL now carries.
    """
    result = fork_law(n)
    assert result["edges"] > 0
    for vc, verdict in result["per_vc"].items():
        assert verdict["acyclic"], (n, vc, verdict["cycle"])
    assert result["union_acyclic"]


@pytest.mark.parametrize("n", SIZES)
def test_the_dateline_switch_law_is_also_acyclic(n):
    """The classic per-hop dateline switch is acyclic as well."""
    result = dateline_switch_law(n)
    for vc, verdict in result["per_vc"].items():
        assert verdict["acyclic"], (n, vc, verdict["cycle"])


@pytest.mark.parametrize("n", SIZES)
def test_one_class_for_every_flow_is_cyclic(n):
    """Why the VC has to carry the dateline half.

    When every flow shares one VC — which is what a class-valued VC does —
    the dependency graph of the ring is cyclic in that class, so a circular
    buffer wait is possible. This is the defect the ring's VC assignment
    used to have, and the reason the proof is per VC class.
    """
    result = vc_acyclicity(n, lambda source, destination, router: 0)
    assert not result["per_vc"][0]["acyclic"]
    assert result["per_vc"][0]["cycle"]


@pytest.mark.parametrize("n", SIZES)
def test_the_verdict_states_the_executed_law_is_acyclic(n):
    verdict = analyze(n)
    assert verdict["routers"] == n
    assert verdict["fork_law"]["per_vc_acyclic"] is True
    assert verdict["dateline_switch_law"]["per_vc_acyclic"] is True
    assert "acyclic" in verdict["verdict"]


def test_the_per_hop_partition_is_the_fork_rule_at_the_current_router():
    """The per-hop switch is the fork's rule applied at the hop's router."""
    for router in range(16):
        for destination in range(16):
            assert per_hop_partition(router, destination) == \
                (1 if router > destination else 0)
