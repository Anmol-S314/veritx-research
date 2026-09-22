"""ResolvedRouteArtifact tests — endpoint-resolved routing identity.

The resolved artifact is a join of three parents, not a fourth source of
truth: it copies endpoint→router placement, keeps the parent routing-class
order, and commits to an endpoint route-table digest that validate_against()
recomputes from the parents. LOCAL_EJECTION covers same-router pairs with no
fabricated channel.
"""
from __future__ import annotations

import dataclasses

import pytest

from veritx_dse.core.artifact import content_id
from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifact, RouteArtifactError,
)
from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, AgentInterfaceDescriptor, AttachmentError,
    Endpoint, derive_attachment,
)
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import AgentInstance, build_inventory
from veritx_dse.model.resolved_route import (
    LOCAL_EJECTION, ResolvedRouteArtifact, ResolvedRouteError,
    _endpoint_route_table, _endpoint_table_hash, derive_resolved_route,
)
from veritx_dse.model.topology_artifact import materialize_topology

_IFACE = AgentInterfaceDescriptor(
    data_width_bits=256, address_width_bits=64, protocol="AXI",
    clock_domain=None, power_domain=None)

GOLDEN_4MESH_ANYNET_TABLE = (
    "f926bd3880d5f8dcb309b9dfa1f84ccb1ea5951444d7e5cc9ce90f77d42390e4")
GOLDEN_4MESH_ANYNET_RESOLVED = (
    "afafbd3afb57fe06b53fb87f81dc984d5854453745287aee8060221b2c4c99d2")
GOLDEN_4MESH_DOR_TABLE = (
    "ffdb193a377441c1c37f9275bd55159538bfdf1fd29ec97c29193758fce90655")
GOLDEN_4MESH_DOR_RESOLVED = (
    "c4afd2db60326bcff2b9dc2b76a2849ec93fc33fe7543de3ac9c10c0e43b2815")
GOLDEN_16MESH_DOR_TABLE = (
    "fe6eeeb202dcbc23241cc5573a78e01ea3e651c37406682e08db2bfd2b8ba7a0")
GOLDEN_16MESH_DOR_RESOLVED = (
    "d86eca580fbd84bbe0ecb85b51c259e680b9adacd5eaf458b9d6eac7f1a6f07a")
GOLDEN_LOCAL_TABLE = (
    "aef92dbd6563f019fee1c18dbb8f8b7286ac1a676e5026404787545b5b3881f2")
GOLDEN_LOCAL_RESOLVED = (
    "2d14a711fa96f4d6cd69586e800ccafb623bed33faf3f6661483a4673bbe8df8")


def _cr(agents, family=TopologyFamily.MESH, concentration=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=agents, dependencies=[],
        noc_config=NocConfig(topology_family=family,
                             concentration=concentration))


def _fabric(n=4, family=TopologyFamily.MESH, concentration=None):
    cr = _cr([Agent(kind=AgentKind.COMPUTE_TILE, count=n)], family,
             concentration)
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    return topo, att


def _anynet_rr(topo) -> RouteArtifact:
    return RouteArtifact.from_topology(topo, name="t")


def _dor_rr(topo) -> RouteArtifact:
    return RouteArtifact.from_topology(topo, name="t",
                                       routing_classes=(DOR_XY,))


def _both_rr(topo) -> RouteArtifact:
    return RouteArtifact.from_topology(
        topo, name="t", routing_classes=(ANYNET_MIN_HOPS, DOR_XY))


def _channel(topo, src: int, dst: int) -> int:
    ids = [c.channel_id for c in topo.channels
           if c.src_router == src and c.dst_router == dst]
    assert len(ids) == 1, f"expected one channel {src}->{dst}, got {ids}"
    return ids[0]


@pytest.fixture(scope="module")
def mesh4():
    return _fabric(4)


@pytest.fixture(scope="module")
def mesh16():
    return _fabric(16)


@pytest.fixture(scope="module")
def local4():
    return _fabric(4, family=TopologyFamily.CONCENTRATED_MESH,
                   concentration=4)


@pytest.fixture(scope="module")
def torus4():
    return _fabric(4, family=TopologyFamily.TORUS)


# ── golden compatibility fixtures ──────────────────────────────────────────

def test_golden_4mesh_anynet(mesh4):
    topo, att = mesh4
    rra = derive_resolved_route(topo, att, _anynet_rr(topo))
    assert rra.endpoint_route_table_hash == GOLDEN_4MESH_ANYNET_TABLE
    assert rra.resolved_route_hash() == GOLDEN_4MESH_ANYNET_RESOLVED


def test_golden_4mesh_dor(mesh4):
    topo, att = mesh4
    rra = derive_resolved_route(topo, att, _dor_rr(topo))
    assert rra.endpoint_route_table_hash == GOLDEN_4MESH_DOR_TABLE
    assert rra.resolved_route_hash() == GOLDEN_4MESH_DOR_RESOLVED


def test_golden_16mesh_dor(mesh16):
    topo, att = mesh16
    rra = derive_resolved_route(topo, att, _dor_rr(topo))
    assert rra.endpoint_route_table_hash == GOLDEN_16MESH_DOR_TABLE
    assert rra.resolved_route_hash() == GOLDEN_16MESH_DOR_RESOLVED


def test_golden_local_ejection(local4):
    topo, att = local4
    assert topo.router_count == 1
    rra = derive_resolved_route(topo, att, _anynet_rr(topo))
    assert rra.endpoint_route_table_hash == GOLDEN_LOCAL_TABLE
    assert rra.resolved_route_hash() == GOLDEN_LOCAL_RESOLVED


# ── parent binding ─────────────────────────────────────────────────────────

def test_binds_all_three_parents(mesh4):
    topo, att = mesh4
    rr = _anynet_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    assert rra.topology_hash == topo.topology_hash()
    assert rra.attachment_hash == att.attachment_hash()
    assert rra.router_route_hash == rr.artifact_hash
    assert rra.endpoint_to_router == tuple(
        (e.endpoint_id, e.router_id) for e in att.endpoints)
    assert rra.routing_classes == tuple(d.id for d in rr.routing_classes)
    assert rra.validate_against(topo, att, rr) is None
    assert len(rra.resolved_route_hash()) == 64
    assert not rra.resolved_route_hash().startswith("sha256:")


def test_identity_domains_are_explicit(mesh4):
    topo, att = mesh4
    rra = derive_resolved_route(topo, att, _anynet_rr(topo))
    assert rra.resolved_route_hash() == content_id(
        "srota/ResolvedRouteArtifact/v2", rra.canonical_dict())
    rows = _endpoint_route_table(rra.endpoint_to_router, rra.routing_classes,
                                 _anynet_rr(topo).entries)
    assert rra.endpoint_route_table_hash == content_id(
        "srota/ResolvedRouteArtifact/endpoint-table/v2", rows)


def test_artifact_stores_no_expanded_table():
    assert {f.name for f in dataclasses.fields(ResolvedRouteArtifact)} == {
        "topology_hash", "attachment_hash", "router_route_hash",
        "endpoint_to_router", "routing_classes", "endpoint_route_table_hash",
        "schema_version", "artifact_hash"}


# ── LOCAL_EJECTION semantics ───────────────────────────────────────────────

def test_local_ejection_rows_for_same_router_endpoints(local4):
    topo, att = local4
    rra = derive_resolved_route(topo, att, _anynet_rr(topo))
    rows = _endpoint_route_table(rra.endpoint_to_router, rra.routing_classes,
                                 {})
    assert len(rows) == 12  # 4 endpoints x 3 destinations
    assert all(row[3] == LOCAL_EJECTION and row[4] is None for row in rows)


def test_endpoint_table_mixes_local_and_routed_rows():
    pairs = ((0, 0), (1, 0), (2, 1))
    entries = {(ANYNET_MIN_HOPS, 0, 1): 7, (ANYNET_MIN_HOPS, 1, 0): 8}
    rows = _endpoint_route_table(pairs, (ANYNET_MIN_HOPS,), entries)
    local = [r for r in rows if r[3] == LOCAL_EJECTION]
    routed = [r for r in rows if r[3] == "ROUTED"]
    assert len(local) == 2 and len(routed) == 4
    assert all(r[4] is None for r in local)
    assert sorted(r[4] for r in routed) == [7, 7, 8, 8]


def test_local_rows_do_not_require_router_entries():
    rows = _endpoint_route_table(((0, 0), (1, 0)), (ANYNET_MIN_HOPS,), {})
    assert rows == [[0, 1, ANYNET_MIN_HOPS, LOCAL_EJECTION, None],
                    [1, 0, ANYNET_MIN_HOPS, LOCAL_EJECTION, None]]


def test_endpoint_table_missing_router_entry_is_rejected():
    with pytest.raises(ResolvedRouteError, match="no .* entry"):
        _endpoint_route_table(((0, 0), (1, 1)), (ANYNET_MIN_HOPS,), {})


def test_endpoint_table_non_integer_channel_is_rejected():
    with pytest.raises(ResolvedRouteError, match="non-integer"):
        _endpoint_route_table(((0, 0), (1, 1)), (ANYNET_MIN_HOPS,),
                              {(ANYNET_MIN_HOPS, 0, 1): True})


# ── identity is bound to all three parents ─────────────────────────────────

def test_same_router_route_different_attachment_differs(mesh4):
    topo, _att = mesh4
    rr = _anynet_rr(topo)
    a0 = AgentInstance(0, 0, AgentKind.COMPUTE_TILE)
    a1 = AgentInstance(0, 1, AgentKind.COMPUTE_TILE)
    att_a = AgentAttachmentArtifact(
        topology_hash=topo.topology_hash(),
        endpoints=(Endpoint(0, a0, 0, 0, _IFACE),
                   Endpoint(1, a1, 3, 0, _IFACE)))
    att_b = AgentAttachmentArtifact(
        topology_hash=topo.topology_hash(),
        endpoints=(Endpoint(0, a0, 3, 0, _IFACE),
                   Endpoint(1, a1, 0, 0, _IFACE)))
    ra = derive_resolved_route(topo, att_a, rr)
    rb = derive_resolved_route(topo, att_b, rr)
    assert ra.topology_hash == rb.topology_hash
    assert ra.router_route_hash == rb.router_route_hash
    assert ra.attachment_hash != rb.attachment_hash
    assert ra.endpoint_to_router != rb.endpoint_to_router
    assert ra.endpoint_route_table_hash != rb.endpoint_route_table_hash
    assert ra.resolved_route_hash() != rb.resolved_route_hash()


def test_router_route_mutation_changes_both_hashes(mesh4):
    topo, att = mesh4
    rr = _both_rr(topo)
    base = derive_resolved_route(topo, att, rr)
    entries = dict(rr.entries)
    old = entries[(DOR_XY, 0, 3)]
    old_dst = {c.channel_id: c.dst_router for c in topo.channels}[old]
    alt = _channel(topo, 0, 2 if old_dst == 1 else 1)
    entries[(DOR_XY, 0, 3)] = alt
    mutated = RouteArtifact(
        schema_version=rr.schema_version, name=rr.name,
        topology_hash=rr.topology_hash, routing_classes=rr.routing_classes,
        entries=entries)
    mutated.validate_against(topo)
    after = derive_resolved_route(topo, att, mutated)
    assert after.topology_hash == base.topology_hash
    assert after.attachment_hash == base.attachment_hash
    assert mutated.route_table_hash != rr.route_table_hash
    assert mutated.artifact_hash != rr.artifact_hash
    assert after.endpoint_route_table_hash != base.endpoint_route_table_hash
    assert after.resolved_route_hash() != base.resolved_route_hash()


def test_wrong_parents_are_rejected(mesh4, torus4):
    topo, att = mesh4
    other_topo, other_att = torus4
    rr = _anynet_rr(topo)
    other_rr = _anynet_rr(other_topo)
    rra = derive_resolved_route(topo, att, rr)
    with pytest.raises(ResolvedRouteError, match="topology_hash"):
        rra.validate_against(other_topo, att, rr)
    with pytest.raises(ResolvedRouteError, match="attachment_hash"):
        rra.validate_against(topo, other_att, rr)
    with pytest.raises(ResolvedRouteError, match="router_route_hash"):
        rra.validate_against(topo, att, other_rr)


def test_attachment_declaring_another_topology_is_rejected(mesh4, torus4):
    topo, _att = mesh4
    _other_topo, att_torus = torus4
    rr = _anynet_rr(topo)
    with pytest.raises(AttachmentError, match="topology_hash"):
        derive_resolved_route(topo, att_torus, rr)


def test_router_route_declaring_another_topology_is_rejected(mesh4, torus4):
    topo, att = mesh4
    other_topo, _other_att = torus4
    rr_other = _anynet_rr(other_topo)
    with pytest.raises(RouteArtifactError, match="topology_hash"):
        derive_resolved_route(topo, att, rr_other)


def test_non_artifact_parents_are_rejected(mesh4):
    topo, att = mesh4
    rr = _anynet_rr(topo)
    with pytest.raises(ResolvedRouteError, match="TopologyArtifact"):
        derive_resolved_route(object(), att, rr)
    with pytest.raises(ResolvedRouteError, match="AgentAttachmentArtifact"):
        derive_resolved_route(topo, object(), rr)
    with pytest.raises(ResolvedRouteError, match="RouteArtifact"):
        derive_resolved_route(topo, att, object())


# ── routing-class axis follows the parent exactly ──────────────────────────

def test_routing_class_order_is_bound_to_parent(mesh4):
    topo, att = mesh4
    rr = _both_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    assert rra.routing_classes == (ANYNET_MIN_HOPS, DOR_XY)


def test_routing_class_order_mismatch_is_rejected(mesh4):
    topo, att = mesh4
    rr = _both_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    reversed_classes = (DOR_XY, ANYNET_MIN_HOPS)
    rows = _endpoint_route_table(rra.endpoint_to_router, reversed_classes,
                                 rr.entries)
    fake = ResolvedRouteArtifact(
        topology_hash=rra.topology_hash,
        attachment_hash=rra.attachment_hash,
        router_route_hash=rra.router_route_hash,
        endpoint_to_router=rra.endpoint_to_router,
        routing_classes=reversed_classes,
        endpoint_route_table_hash=_endpoint_table_hash(rows))
    assert set(fake.routing_classes) == {d.id for d in rr.routing_classes}
    with pytest.raises(ResolvedRouteError, match="routing_classes"):
        fake.validate_against(topo, att, rr)


# ── the fabricated endpoint-table regression ───────────────────────────────

def test_fabricated_endpoint_table_hash_is_rejected(mesh4):
    """The historical attack: a self-consistent artifact around a fake
    endpoint-table digest must not survive parent validation."""
    topo, att = mesh4
    rr = _anynet_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    fake = dataclasses.replace(rra, endpoint_route_table_hash="deadbeef")
    with pytest.raises(ResolvedRouteError,
                       match="endpoint_route_table_hash does not match"):
        fake.validate_against(topo, att, rr)


def test_fabricated_table_survives_self_integrity_but_not_parents(mesh4):
    topo, att = mesh4
    rr = _anynet_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    fake = dataclasses.replace(rra, endpoint_route_table_hash="deadbeef")
    loaded = ResolvedRouteArtifact.from_dict(fake.to_dict())
    assert loaded.endpoint_route_table_hash == "deadbeef"
    assert loaded.resolved_route_hash() == fake.resolved_route_hash()
    with pytest.raises(ResolvedRouteError,
                       match="endpoint_route_table_hash does not match"):
        loaded.validate_against(topo, att, rr)


# ── strict persisted parsing ───────────────────────────────────────────────

def _valid_dict(mesh4) -> dict:
    topo, att = mesh4
    return derive_resolved_route(topo, att, _anynet_rr(topo)).to_dict()


def test_roundtrip_self_integrity(mesh4):
    topo, att = mesh4
    rr = _anynet_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    loaded = ResolvedRouteArtifact.from_dict(rra.to_dict())
    assert loaded.resolved_route_hash() == rra.resolved_route_hash()
    assert loaded.canonical_dict() == rra.canonical_dict()
    assert loaded.validate_against(topo, att, rr) is None


def test_unknown_fields_refused(mesh4):
    d = _valid_dict(mesh4)
    d["router"] = 1
    with pytest.raises(ResolvedRouteError, match="unknown fields"):
        ResolvedRouteArtifact.from_dict(d)


@pytest.mark.parametrize("field", [
    "type", "schema_version", "topology_hash", "attachment_hash",
    "router_route_hash", "endpoint_to_router", "routing_classes",
    "endpoint_route_table_hash",
])
def test_missing_required_fields_refused(mesh4, field):
    d = _valid_dict(mesh4)
    d.pop(field)
    with pytest.raises(ResolvedRouteError, match="missing required field"):
        ResolvedRouteArtifact.from_dict(d)


@pytest.mark.parametrize("bad_type", [None, "srota/RouteArtifact", 7])
def test_type_tag_is_strict(mesh4, bad_type):
    d = _valid_dict(mesh4)
    if bad_type is None:
        d.pop("type")
    else:
        d["type"] = bad_type
    with pytest.raises(ResolvedRouteError, match="type"):
        ResolvedRouteArtifact.from_dict(d)


@pytest.mark.parametrize("bad_pairs", [
    [["0", "3"]],
    [[0, "3"]],
    [[True, 3]],
    [[0, False]],
    [[0, 3, 4]],
    [[0]],
    [{"0": 3}],
    [(0, 3)],
    ["0,3"],
    {},
    [],
])
def test_endpoint_pair_parsing_is_strict(mesh4, bad_pairs):
    d = _valid_dict(mesh4)
    d["endpoint_to_router"] = bad_pairs
    with pytest.raises(ResolvedRouteError, match="endpoint_to_router"):
        ResolvedRouteArtifact.from_dict(d)


@pytest.mark.parametrize("bad_classes", [
    "ANYNET_MIN_HOPS",
    ["ANYNET_MIN_HOPS", ""],
    [""],
    [1],
    ["ok", 2],
    [],
    {},
])
def test_routing_class_parsing_is_strict(mesh4, bad_classes):
    d = _valid_dict(mesh4)
    d["routing_classes"] = bad_classes
    with pytest.raises(ResolvedRouteError, match="routing_classes"):
        ResolvedRouteArtifact.from_dict(d)


def test_schema_v1_is_refused(mesh4):
    d = _valid_dict(mesh4)
    d["schema_version"] = 1
    with pytest.raises(ResolvedRouteError, match="v1|migration"):
        ResolvedRouteArtifact.from_dict(d)


def test_unsupported_schema_version_is_refused(mesh4):
    d = _valid_dict(mesh4)
    d["schema_version"] = 3
    with pytest.raises(ResolvedRouteError, match="unsupported resolved-route"):
        ResolvedRouteArtifact.from_dict(d)


def test_derive_refuses_a_non_v2_router_route(mesh4):
    topo, att = mesh4
    rr = _anynet_rr(topo)
    object.__setattr__(rr, "schema_version", 1)
    with pytest.raises(ResolvedRouteError, match="v2"):
        derive_resolved_route(topo, att, rr)


def test_persisted_artifact_hash_tamper_is_detected(mesh4):
    d = _valid_dict(mesh4)
    d["artifact_hash"] = "0" * 64
    with pytest.raises(ResolvedRouteError, match="artifact_hash"):
        ResolvedRouteArtifact.from_dict(d)


def test_persisted_endpoint_tamper_needs_parents(mesh4):
    topo, att = mesh4
    rr = _anynet_rr(topo)
    rra = derive_resolved_route(topo, att, rr)
    d = rra.to_dict()
    d["endpoint_to_router"][0][1] = d["endpoint_to_router"][1][1]
    d.pop("artifact_hash")  # attacker drops the self-check
    loaded = ResolvedRouteArtifact.from_dict(d)
    with pytest.raises(ResolvedRouteError, match="does not match"):
        loaded.validate_against(topo, att, rr)


# ── constructor strictness and immutability ────────────────────────────────

def test_constructor_rejects_malformed_endpoint_pairs(mesh4):
    base = dict(topology_hash="a", attachment_hash="b",
                router_route_hash="c", routing_classes=(ANYNET_MIN_HOPS,),
                endpoint_route_table_hash="d")
    with pytest.raises(ResolvedRouteError, match="pair"):
        ResolvedRouteArtifact(**base, endpoint_to_router=([0, 1],))
    with pytest.raises(ResolvedRouteError, match="exact integers"):
        ResolvedRouteArtifact(**base, endpoint_to_router=((0, "1"),))
    with pytest.raises(ResolvedRouteError, match="exact integers"):
        ResolvedRouteArtifact(**base, endpoint_to_router=((True, 1),))
    with pytest.raises(ResolvedRouteError, match="< 0"):
        ResolvedRouteArtifact(**base, endpoint_to_router=((0, -1),))
    with pytest.raises(ResolvedRouteError, match="contiguous"):
        ResolvedRouteArtifact(**base, endpoint_to_router=((1, 0),))
    with pytest.raises(ResolvedRouteError, match="non-empty tuple"):
        ResolvedRouteArtifact(**base, endpoint_to_router=())


def test_constructor_rejects_bad_class_and_hash_shapes():
    base = dict(topology_hash="a", attachment_hash="b",
                router_route_hash="c", endpoint_to_router=((0, 0),),
                endpoint_route_table_hash="d")
    with pytest.raises(ResolvedRouteError, match="non-empty"):
        ResolvedRouteArtifact(**base, routing_classes=())
    with pytest.raises(ResolvedRouteError, match="non-empty strings"):
        ResolvedRouteArtifact(**base, routing_classes=("",))
    with pytest.raises(ResolvedRouteError, match="unique"):
        ResolvedRouteArtifact(**base,
                              routing_classes=("A", "A"))
    with pytest.raises(ResolvedRouteError, match="non-empty string"):
        ResolvedRouteArtifact(**{**base, "topology_hash": ""},
                              routing_classes=("A",))
    with pytest.raises(ResolvedRouteError, match="unsupported resolved-route"):
        ResolvedRouteArtifact(**base, routing_classes=("A",),
                              schema_version=3)
