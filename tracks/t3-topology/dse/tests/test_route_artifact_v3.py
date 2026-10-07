"""RouteArtifactV3: the differential-proven rule as a real artifact.

The point of this file is the last assertion in the first test: the GEC-MECS
route realization, built from the rule that was checked against the
simulator, yields a concrete (resource, VC) dependency graph with NO cycle.
That is deadlock-safety evidence for a shared-wire fabric — the thing that
did not exist before, because the representation could not describe the
resource.

Non-vacuity is checked too: the graph must have real edges, and the same
builder must report a cycle when handed a table that has one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.gec_mecs_route import GecMecsParams  # noqa: E402
from veritx_dse.model.route_artifact_v3 import (  # noqa: E402
    ROUTE_ARTIFACT_V3_SCHEMA_VERSION,
    RouteArtifactV3,
    RouteArtifactV3Error,
    route_artifact_v3_for_gec_mecs,
)
from veritx_dse.model.topology_artifact import materialize_gec_mecs  # noqa: E402
from veritx_dse.model.shared_resource import (  # noqa: E402
    ResourceKind,
    ResourceRef,
    RouteDecision,
)

_PARAMS = GecMecsParams(k=4, c=1, o=1, d=3, num_vcs=3)

def _artifact() -> RouteArtifactV3:
    return route_artifact_v3_for_gec_mecs(_PARAMS, topology_hash="sha256:test")

def test_gec_mecs_route_is_proven_deadlock_free():
    """The result this whole line of work existed to produce."""
    art = _artifact()
    cdg = art.shared_resource_cdg()
    cycle = cdg.find_cycle()
    assert cycle is None, (
        "the GEC-MECS route realization produced a shared-resource cycle: "
        f"{cycle}")
    # ...and the answer is not vacuous: real resources, real edges.
    assert cdg.node_count > 0 and cdg.edge_count > 0
    assert art.shared_resource_count > 0
    assert art.private_resource_count > 0

def test_edges_only_ever_go_row_then_column():
    """The actual reason it is acyclic: strict X-then-Y dimension order.

    Every edge must leave the row-dimension resource set for the column one
    (or stay inside the column set). No edge may go back to a row resource —
    that is the turn that would close a cycle.
    """
    art = _artifact()
    cdg = art.shared_resource_cdg()
    # Row wires are the first o groups of ports; column wires the next o.
    row_ids = {r * 3 + 1 for r in range(_PARAMS.router_count)}
    for (res_in, _vc_in), (res_out, _vc_out) in cdg.edges:
        if res_in.kind is ResourceKind.SHARED_LINK and res_in.resource_id in row_ids:
            assert res_out.kind is ResourceKind.SHARED_LINK, (
                f"row hop {res_in} must be followed by a shared column hop, "
                f"got {res_out}")
            assert res_out.resource_id not in row_ids, (
                f"row hop {res_in} went back to a row resource {res_out} — "
                "that is the cycle-closing turn")

def test_a_table_with_a_cycle_is_reported():
    """Guard: the builder must not be trivially acyclic."""
    # Two wires, each hop of a route taking the next, and the last one
    # turning back to the first: a genuine resource cycle.
    a = ResourceRef(ResourceKind.SHARED_LINK, 100)
    b = ResourceRef(ResourceKind.SHARED_LINK, 101)
    decisions = {
        (0, 2): RouteDecision(resource=a, next_router=1, vc_partition=0,
                              tap=0),
        (1, 2): RouteDecision(resource=b, next_router=2, vc_partition=0,
                              tap=0),
        (0, 1): RouteDecision(resource=a, next_router=1, vc_partition=0,
                              tap=0),
        (1, 0): RouteDecision(resource=b, next_router=2, vc_partition=0,
                              tap=0),
        (2, 0): RouteDecision(resource=a, next_router=0, vc_partition=0,
                              tap=0),
        (2, 1): RouteDecision(resource=b, next_router=1, vc_partition=0,
                              tap=0),
    }
    art = RouteArtifactV3(
        routing_class="CYCLIC_FIXTURE", topology_hash="sha256:fixture",
        routers=(0, 1, 2), decisions=decisions,
        partition_to_vcs={0: (0,)}, allowed_transitions=((0, 0),))
    cdg = art.shared_resource_cdg()
    assert cdg.edge_count > 0
    assert cdg.find_cycle() is not None, (
        "a table whose hops form a resource cycle must be reported as one")

def test_terminal_ejection_accepts_any_arriving_vc():
    """The eject port is a sink, not a partition member."""
    art = _artifact()
    cdg = art.shared_resource_cdg()
    # Every terminal resource appears with the full VC range, so a packet
    # arriving on any VC can leave it.
    for (s, d), decision in art.decisions.items():
        if decision.next_router != d:
            continue
        for vc in range(_PARAMS.num_vcs):
            assert (decision.resource, vc) in cdg.nodes, (
                f"terminal hop for ({s},{d}) cannot eject on VC {vc}")

def test_route_resources_bind_to_exact_topology_taps():
    topology = materialize_gec_mecs(k=4, concentration=1, o=1, d=3)
    route = route_artifact_v3_for_gec_mecs(
        _PARAMS, topology_hash=topology.topology_hash())
    route.validate_against(topology)

    key, decision = next(
        (key, decision) for key, decision in route.decisions.items()
        if decision.resource.kind is ResourceKind.SHARED_LINK)
    bad = RouteArtifactV3(
        routing_class=route.routing_class,
        topology_hash=route.topology_hash, routers=route.routers,
        decisions={**route.decisions,
                   key: RouteDecision(
                       resource=decision.resource,
                       next_router=(decision.next_router + 1) % 16,
                       vc_partition=decision.vc_partition,
                       tap=decision.tap)},
        partition_to_vcs=route.partition_to_vcs,
        allowed_transitions=route.allowed_transitions,
        terminal_to_router=route.terminal_to_router)
    with pytest.raises(RouteArtifactV3Error, match="binds to 0 topology wires"):
        bad.validate_against(topology)

def test_identity_round_trips_and_moves_with_content():
    art = _artifact()
    again = RouteArtifactV3.from_dict(art.to_dict())
    assert again.route_artifact_id() == art.route_artifact_id()
    assert again.decisions == art.decisions
    other = route_artifact_v3_for_gec_mecs(
        GecMecsParams(k=4, c=1, o=1, d=3, num_vcs=6),
        topology_hash="sha256:test")
    assert other.route_artifact_id() != art.route_artifact_id()

def test_the_privacy_of_the_eject_port_is_not_aliasable():
    """A private channel and a shared wire with the same id are distinct."""
    art = _artifact()
    kinds = {d.resource.kind for d in art.decisions.values()}
    assert kinds == {ResourceKind.SHARED_LINK, ResourceKind.CHANNEL}
    for decision in art.decisions.values():
        if decision.resource.kind is ResourceKind.CHANNEL:
            assert decision.tap is None, (
                "a private eject port must not carry a tap")

def test_from_dict_rejects_a_stale_content_identity():
    doc = _artifact().to_dict()
    doc["route_artifact_id"] = "tampered"
    with pytest.raises(RouteArtifactV3Error, match="does not match"):
        RouteArtifactV3.from_dict(doc)

def test_schema_version_and_unknown_fields_are_refused():
    assert ROUTE_ARTIFACT_V3_SCHEMA_VERSION == 3
    doc = _artifact().to_dict()
    doc["unexpected"] = 1
    with pytest.raises(RouteArtifactV3Error, match="unknown fields"):
        RouteArtifactV3.from_dict(doc)

def test_from_dict_refuses_a_dangling_hop():
    doc = _artifact().to_dict()
    # Router 3 is the TRANSIT landing point for row hops out of row 0, so
    # removing its rows leaves (0, 7) with nowhere to continue.
    doc["decisions"] = [row for row in doc["decisions"] if row[0] != 3]
    doc.pop("route_artifact_id")
    art = RouteArtifactV3.from_dict(doc)
    with pytest.raises(Exception, match="not realizable"):
        art.shared_resource_cdg()
