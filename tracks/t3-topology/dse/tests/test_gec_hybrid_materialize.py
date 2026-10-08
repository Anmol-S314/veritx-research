"""GEC-HYBRID materializes as mesh channels PLUS MECS shared wires.

Materialization alone proves nothing about the live-credit route selector.
P2 adds an explicit mesh/MECS candidate union; it is not a deterministic
first-hop table or an escape-subnetwork theorem.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application import capability_truth as ct  # noqa: E402
from veritx_dse.compiler.orchestration import (  # noqa: E402
    probe_direct_materialize,
    probe_direct_route,
)
from veritx_dse.model.gec_hybrid_route import GecHybridRoute  # noqa: E402
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
    TopologyError,
    materialize_family,
    materialize_gec_hybrid,
)


@pytest.mark.parametrize("k,c,o,d", [(4, 1, 1, 3), (6, 1, 1, 5), (4, 2, 1, 3)])
def test_hybrid_is_the_union_of_mesh_channels_and_mecs_wires(k, c, o, d):
    topology = materialize_gec_hybrid(k=k, concentration=c, o=o, d=d)
    assert topology.family is MaterializedFamily.GEC_HYBRID
    mesh = materialize_family(
        MaterializedFamily.MESH, endpoint_count=k * k * c,
        concentration=c, radix=k)
    # The mesh step is EXACTLY the canonical mesh fabric -- not a lookalike.
    assert topology.channels == mesh.channels
    assert topology.routers == mesh.routers
    # The express layer is EXACTLY the MECS wires: one per (router, dim, group).
    assert len(topology.shared_links) == 2 * o * k * k
    assert topology.channel_count == len(mesh.channels)
    assert topology.router_count == k * k


def test_hybrid_refuses_the_source_law_violation():
    with pytest.raises(TopologyError, match="o\\*d"):
        materialize_gec_hybrid(k=5, concentration=1, o=1, d=3)
    # A hybrid express layer with a single destination per wire is not a
    # shared resource; d >= 2 is the MECS floor.
    with pytest.raises(ValueError, match="d must be"):
        materialize_gec_hybrid(k=4, concentration=1, o=3, d=1)


def test_route_derivation_preserves_both_runtime_candidates():
    """MATERIALIZABLE=YES, ROUTABLE=YES: no live choice is pruned."""
    request = ct._probe_request("gec_hybrid")
    topology = probe_direct_materialize(
        request, ct.PROBE_INTENTS["gec_hybrid"])
    assert topology.family is MaterializedFamily.GEC_HYBRID
    assert topology.shared_links, "the probe must exercise the shared wires"
    route = probe_direct_route(request, topology)
    assert isinstance(route, GecHybridRoute)
    assert len(route.choices[(0, 3)]) == 4  # three mesh VCs + one MECS tap VC
    assert {o.resource.kind.value for o in route.choices[(0, 3)]} == {"CHANNEL", "SHARED_LINK"}
    route.validate_against(topology)


def test_capability_truth_uses_the_qualified_six_vc_probe():
    truth = ct.derive_family_stages("gec_hybrid")
    assert all(value == "YES" for value in truth.stages.values()), truth.as_dict()
    assert truth.profile_id == "CERTIFIED_BOOKSIM_GEC_HYBRID_V1"
    assert truth.stopped_at_stage is None
