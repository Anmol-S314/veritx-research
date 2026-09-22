"""RouteArtifact tests — exact class-aware channel routes and sealed identity.

The route table is execution authority: every (class, src, dst) resolves to
one exact directed channel, and parent validation proves the table both
leaves src and terminates for every destination. Identity is the sealed
domain-free digest convention; name and provenance are transport only.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import deque
from collections.abc import Mapping

import pytest

from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS,
    ANYNET_MIN_HOPS_DEFINITION,
    DOR_XY,
    DOR_XY_DEFINITION,
    RouteArtifact,
    RouteArtifactError,
    RoutingClassDefinition,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel,
    MaterializedFamily,
    Router,
    TopologyArtifact,
    materialize_family,
)

GOLDEN_4MESH_ANYNET_TABLE = (
    "sha256:f83f2b83d3a6e564a6a8d686d521142c877395c2a692f9842f7a7e63c0e00f21")
GOLDEN_4MESH_ANYNET_ARTIFACT = (
    "sha256:18cc6856ca5d17e615e53e66a01a19f74106529ec67771591b9182107ef03e34")
GOLDEN_4MESH_DOR_TABLE = (
    "sha256:4453bfaa95859168166c7097decf11757e5d9e81e7f150f964f77fa500c39b37")
GOLDEN_4MESH_DOR_ARTIFACT = (
    "sha256:c3f2e5fd87e0efeb53f38d0532854c4727422725077ee44cfd59e6f5a637177b")
GOLDEN_16MESH_DOR_TABLE = (
    "sha256:5a5fa9fe190d51c8107bae557bd07e470db08770e2e5f02786a32fb3fb80cec7")
GOLDEN_16MESH_DOR_ARTIFACT = (
    "sha256:4f60ec53df7a226e84f58afa7d415a809722b55c71127993c55b44a9f0af6ef2")


def _mesh(n: int, **kw) -> TopologyArtifact:
    return materialize_family(MaterializedFamily.MESH, endpoint_count=n, **kw)


def _anynet(topo, name="route", **kw) -> RouteArtifact:
    return RouteArtifact.from_topology(
        topo, name=name, routing_classes=(ANYNET_MIN_HOPS,), **kw)


def _dor(topo, name="route", **kw) -> RouteArtifact:
    return RouteArtifact.from_topology(
        topo, name=name, routing_classes=(DOR_XY,), **kw)


def _by_id(topo) -> dict[int, DirectedChannel]:
    return {c.channel_id: c for c in topo.channels}


def _channel(topo, src: int, dst: int) -> int:
    ids = [c.channel_id for c in topo.channels
           if c.src_router == src and c.dst_router == dst]
    assert len(ids) == 1, f"expected one channel {src}->{dst}, got {ids}"
    return ids[0]


def _route(artifact, topo, cid, src, dst) -> list[DirectedChannel]:
    """Follow the exact table from src to dst; fails on any local illegality."""
    channels = _by_id(topo)
    hops: list[DirectedChannel] = []
    cur = src
    seen = {cur}
    while cur != dst:
        ch = channels[artifact.entries[(cid, cur, dst)]]
        assert ch.src_router == cur, f"channel {ch.channel_id} leaves {ch.src_router}"
        hops.append(ch)
        cur = ch.dst_router
        assert cur not in seen, "route revisits a router"
        seen.add(cur)
    return hops


def _bfs(topo, src: int) -> dict[int, int]:
    adj: dict[int, list[int]] = {r.router_id: [] for r in topo.routers}
    for c in topo.channels:
        adj[c.src_router].append(c.dst_router)
    dist = {src: 0}
    queue = deque([src])
    while queue:
        cur = queue.popleft()
        for nxt in adj[cur]:
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


def _coords(topo) -> dict[int, tuple[int, int]]:
    return {r.router_id: r.coordinates for r in topo.routers}


def _sealed(payload) -> str:
    """Independent reimplementation of the sealed legacy digest convention."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _table_payload(artifact) -> dict:
    return {
        "routing_classes": [d.to_dict() for d in artifact.routing_classes],
        "entries": [[cls, s, t, ch] for (cls, s, t), ch
                    in sorted(artifact.entries.items())],
    }


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mesh4() -> TopologyArtifact:
    return _mesh(4)


@pytest.fixture(scope="module")
def mesh16() -> TopologyArtifact:
    return _mesh(16)


@pytest.fixture(scope="module")
def anynet4(mesh4) -> RouteArtifact:
    return _anynet(mesh4, name="anynet-4mesh")


@pytest.fixture(scope="module")
def dor4(mesh4) -> RouteArtifact:
    return _dor(mesh4, name="dor-4mesh")


def _parallel_2router_topology() -> TopologyArtifact:
    """Two routers joined by two parallel forward channels plus one reverse."""
    return TopologyArtifact(
        family=MaterializedFamily.MESH,
        routers=(Router(router_id=0, coordinates=(0, 0), seat_capacity=1),
                 Router(router_id=1, coordinates=(1, 0), seat_capacity=1)),
        channels=(
            DirectedChannel(channel_id=0, src_router=0, src_port=1,
                            dst_router=1, dst_port=1, width_bits=128,
                            latency_cycles=1),
            DirectedChannel(channel_id=1, src_router=0, src_port=2,
                            dst_router=1, dst_port=1, width_bits=128,
                            latency_cycles=1),
            DirectedChannel(channel_id=2, src_router=1, src_port=1,
                            dst_router=0, dst_port=1, width_bits=128,
                            latency_cycles=1),
        ),
    )


# ── golden identity: sealed hashes must not move ────────────────────────────

def test_golden_4mesh_anynet_identity(anynet4):
    assert anynet4.route_table_hash == GOLDEN_4MESH_ANYNET_TABLE
    assert anynet4.artifact_hash == GOLDEN_4MESH_ANYNET_ARTIFACT


def test_golden_4mesh_dor_identity(dor4):
    assert dor4.route_table_hash == GOLDEN_4MESH_DOR_TABLE
    assert dor4.artifact_hash == GOLDEN_4MESH_DOR_ARTIFACT


def test_golden_16mesh_dor_identity(mesh16):
    artifact = _dor(mesh16, name="dor-16mesh")
    assert artifact.route_table_hash == GOLDEN_16MESH_DOR_TABLE
    assert artifact.artifact_hash == GOLDEN_16MESH_DOR_ARTIFACT


def test_hashes_use_sealed_domain_free_digest(anynet4):
    # A content_id() form would prepend a domain + NUL separator; the sealed
    # route convention is plain canonical-JSON SHA-256 with a sha256: tag.
    assert anynet4.route_table_hash == _sealed(_table_payload(anynet4))
    assert anynet4.artifact_hash == _sealed({
        "schema_version": anynet4.schema_version,
        "topology_hash": anynet4.topology_hash,
        "route_table_hash": anynet4.route_table_hash,
    })
    assert anynet4.route_table_hash.startswith("sha256:")
    assert "srota/RouteArtifact" not in _table_payload(anynet4)["routing_classes"][0].keys()


# ── routing-class axis and complete coverage ────────────────────────────────

def test_every_class_covers_every_ordered_pair(mesh4):
    artifact = RouteArtifact.from_topology(
        mesh4, name="both", routing_classes=(ANYNET_MIN_HOPS, DOR_XY))
    expected = {(cid, s, t) for cid in (ANYNET_MIN_HOPS, DOR_XY)
                for s in range(4) for t in range(4) if s != t}
    assert set(artifact.entries) == expected
    assert len(artifact.entries) == 24


def test_no_self_route_entries(anynet4):
    assert all(s != t for (_cls, s, t) in anynet4.entries)


def test_entries_never_mix_class_axes(anynet4):
    classes = [d.id for d in anynet4.routing_classes]
    assert classes == [ANYNET_MIN_HOPS]
    assert {key[0] for key in anynet4.entries} == {ANYNET_MIN_HOPS}


def test_missing_entry_is_rejected(mesh4, anynet4):
    table = dict(anynet4.entries)
    del table[(ANYNET_MIN_HOPS, 0, 1)]
    with pytest.raises(RouteArtifactError, match="do not cover every"):
        _anynet(mesh4, entries=table)


def test_extra_entry_is_rejected(mesh4, anynet4):
    table = dict(anynet4.entries)
    table[(ANYNET_MIN_HOPS, 0, 99)] = next(iter(anynet4.entries.values()))
    with pytest.raises(RouteArtifactError, match="outside the topology"):
        _anynet(mesh4, entries=table)


def test_undeclared_class_entry_is_rejected(mesh4, anynet4):
    table = dict(anynet4.entries)
    table[("NO_SUCH_CLASS", 0, 1)] = table[(ANYNET_MIN_HOPS, 0, 1)]
    with pytest.raises(RouteArtifactError, match="undeclared routing class"):
        _anynet(mesh4, entries=table)


def test_unknown_routing_class_id_is_rejected(mesh4):
    with pytest.raises(RouteArtifactError, match="unknown routing class"):
        RouteArtifact.from_topology(mesh4, name="x",
                                    routing_classes=("NO_SUCH_CLASS",))


def test_class_without_materializer_is_rejected(mesh4):
    custom = RoutingClassDefinition(id="CUSTOM", algorithm="custom",
                                    algorithm_version=1)
    with pytest.raises(RouteArtifactError, match="no materializer"):
        RouteArtifact.from_topology(mesh4, name="x", routing_classes=(custom,))


# ── DOR_XY is exact, non-wrap, x-then-y ─────────────────────────────────────

def test_dor_xy_consumes_x_before_y(dor4, mesh4):
    channels = _by_id(mesh4)
    first = channels[dor4.entries[(DOR_XY, 0, 3)]]
    assert (first.src_router, first.dst_router) == (0, 1)
    first = channels[dor4.entries[(DOR_XY, 0, 2)]]
    assert (first.src_router, first.dst_router) == (0, 2)
    first = channels[dor4.entries[(DOR_XY, 1, 2)]]
    assert (first.src_router, first.dst_router) == (1, 0)


def test_dor_xy_steps_to_adjacent_router_toward_destination(dor4, mesh4):
    coords = _coords(mesh4)
    channels = _by_id(mesh4)
    for (cid, src, dst), ch_id in dor4.entries.items():
        assert cid == DOR_XY
        ch = channels[ch_id]
        (sx, sy), (dx, dy) = coords[src], coords[dst]
        (hx, hy) = coords[ch.dst_router]
        assert abs(sx - hx) + abs(sy - hy) == 1
        assert abs(hx - dx) + abs(hy - dy) == abs(sx - dx) + abs(sy - dy) - 1


def test_dor_xy_definition_declares_non_wrap():
    assert DOR_XY_DEFINITION.parameters_dict() == {
        "dimension_order": ("x", "y"), "wraparound": False}


def test_dor_xy_refuses_torus(mesh16):
    torus = materialize_family(MaterializedFamily.TORUS, endpoint_count=16)
    with pytest.raises(RouteArtifactError, match="UNSUPPORTED"):
        _dor(torus)


def test_dor_xy_refuses_ring():
    ring = materialize_family(MaterializedFamily.RING, endpoint_count=4)
    with pytest.raises(RouteArtifactError, match="UNSUPPORTED"):
        _dor(ring)


def test_dor_xy_accepts_concentrated_mesh():
    cmesh = materialize_family(MaterializedFamily.CONCENTRATED_MESH,
                               endpoint_count=4)
    artifact = _dor(cmesh)
    assert len(artifact.entries) == 12


def test_dor_xy_refuses_parallel_hops():
    topo = _parallel_2router_topology()
    with pytest.raises(RouteArtifactError, match="ambiguous"):
        _dor(topo)


# ── ANYNET_MIN_HOPS semantics and parallel policy ───────────────────────────

def test_anynet_tie_break_is_deterministic(mesh16):
    first = _anynet(mesh16, name="a")
    second = _anynet(mesh16, name="b")
    assert first.entries == second.entries
    assert first.route_table_hash == second.route_table_hash


def test_anynet_hop_count_is_bfs_shortest(anynet4, mesh4):
    for dst in range(4):
        for src in range(4):
            if src == dst:
                continue
            hops = _route(anynet4, mesh4, ANYNET_MIN_HOPS, src, dst)
            assert len(hops) == _bfs(mesh4, src)[dst]


def test_anynet_definition_declares_parallel_realization():
    assert ANYNET_MIN_HOPS_DEFINITION.parameters_dict()[
        "parallel_hop_realization"] == "min_channel_id"


def test_anynet_parallel_hop_uses_min_channel_id():
    topo = _parallel_2router_topology()
    artifact = _anynet(topo)
    assert artifact.entries[(ANYNET_MIN_HOPS, 0, 1)] == 0
    assert artifact.entries[(ANYNET_MIN_HOPS, 1, 0)] == 2


# ── parent validation: local legality plus whole-route termination ─────────

def test_first_channel_must_leave_source(mesh4, anynet4):
    table = dict(anynet4.entries)
    table[(ANYNET_MIN_HOPS, 0, 3)] = _channel(mesh4, 1, 0)
    with pytest.raises(RouteArtifactError, match="leaves router"):
        _anynet(mesh4, entries=table)


def test_missing_channel_is_rejected(mesh4, anynet4):
    table = dict(anynet4.entries)
    table[(ANYNET_MIN_HOPS, 0, 3)] = 999999
    with pytest.raises(RouteArtifactError, match="does not exist"):
        _anynet(mesh4, entries=table)


def test_whole_route_termination_rejects_loops(mesh4, anynet4):
    table = dict(anynet4.entries)
    table[(ANYNET_MIN_HOPS, 0, 3)] = _channel(mesh4, 0, 1)
    table[(ANYNET_MIN_HOPS, 1, 3)] = _channel(mesh4, 1, 0)
    with pytest.raises(RouteArtifactError, match="routing loop"):
        _anynet(mesh4, entries=table)


def test_validate_against_wrong_parent_is_refused(anynet4, mesh16):
    with pytest.raises(RouteArtifactError,
                       match="does not match the materialized topology"):
        anynet4.validate_against(mesh16)


# ── identity vs transport ───────────────────────────────────────────────────

def test_name_and_provenance_are_not_identity(anynet4):
    renamed = dataclasses.replace(anynet4, name="other",
                                  provenance="explanation only")
    assert renamed.route_table_hash == anynet4.route_table_hash
    assert renamed.artifact_hash == anynet4.artifact_hash
    assert renamed.identity_dict() == anynet4.identity_dict()
    assert renamed.to_dict() != anynet4.to_dict()
    assert "name" not in anynet4.identity_dict()
    assert "provenance" not in anynet4.identity_dict()


def test_topology_binding_is_exact(anynet4, mesh4):
    assert anynet4.topology_hash == mesh4.topology_hash()
    ring = materialize_family(MaterializedFamily.RING, endpoint_count=4)
    other = _anynet(ring, name="anynet-4ring")
    assert other.topology_hash != anynet4.topology_hash
    assert other.artifact_hash != anynet4.artifact_hash


def test_exact_resource_choice_is_identity(mesh4, anynet4):
    table = dict(anynet4.entries)
    pick = table[(ANYNET_MIN_HOPS, 0, 3)]
    alternate = _channel(mesh4, 0, 2) if pick == _channel(mesh4, 0, 1) \
        else _channel(mesh4, 0, 1)
    table[(ANYNET_MIN_HOPS, 0, 3)] = alternate
    changed = _anynet(mesh4, entries=table)
    assert changed.route_table_hash != anynet4.route_table_hash
    assert changed.artifact_hash != anynet4.artifact_hash


def test_class_definition_is_identity(mesh4, anynet4):
    custom = RoutingClassDefinition(
        id=ANYNET_MIN_HOPS, algorithm=ANYNET_MIN_HOPS_DEFINITION.algorithm,
        algorithm_version=1,
        parameters=(("tie_break_policy", "different policy"),))
    artifact = RouteArtifact.from_topology(
        mesh4, name=anynet4.name, routing_classes=(custom,),
        entries=dict(anynet4.entries))
    assert artifact.entries == anynet4.entries
    assert artifact.route_table_hash != anynet4.route_table_hash


# ── serialization: self-integrity, strict shape, v1 refusal ────────────────

def test_serialize_roundtrip_preserves_identity(anynet4):
    restored = RouteArtifact.from_dict(anynet4.to_dict())
    assert restored.to_dict() == anynet4.to_dict()
    assert restored.identity_dict() == anynet4.identity_dict()
    assert restored.route_table_hash == anynet4.route_table_hash
    assert restored.artifact_hash == anynet4.artifact_hash
    assert dict(restored.entries) == dict(anynet4.entries)
    assert restored.provenance == anynet4.provenance


def test_from_dict_rejects_unknown_fields(anynet4):
    d = anynet4.to_dict()
    d["extra"] = 1
    with pytest.raises(RouteArtifactError, match="unknown fields"):
        RouteArtifact.from_dict(d)


@pytest.mark.parametrize("field", [
    "schema_version", "name", "topology_hash", "routing_classes", "entries",
    "route_table_hash", "artifact_hash",
])
def test_from_dict_rejects_missing_required_fields(anynet4, field):
    d = anynet4.to_dict()
    d.pop(field)
    with pytest.raises(RouteArtifactError, match="missing required field"):
        RouteArtifact.from_dict(d)


def test_from_dict_refuses_schema_v1():
    with pytest.raises(RouteArtifactError, match="no silent migration"):
        RouteArtifact.from_dict({"schema_version": 1})


def test_from_dict_rejects_unsupported_schema_version(anynet4):
    d = anynet4.to_dict()
    d["schema_version"] = 3
    with pytest.raises(RouteArtifactError, match="unsupported route-artifact"):
        RouteArtifact.from_dict(d)


def test_from_dict_detects_tampered_entries(anynet4):
    d = anynet4.to_dict()
    key = "ANYNET_MIN_HOPS|0|1"
    d["entries"][key] = d["entries"][key] + 100
    with pytest.raises(RouteArtifactError,
                       match="route_table_hash does not match"):
        RouteArtifact.from_dict(d)


def test_from_dict_detects_tampered_artifact_hash(anynet4):
    d = anynet4.to_dict()
    d["artifact_hash"] = "sha256:" + "0" * 64
    with pytest.raises(RouteArtifactError,
                       match="artifact_hash does not match"):
        RouteArtifact.from_dict(d)


def test_from_dict_entry_shape_is_strict(anynet4):
    d = anynet4.to_dict()
    d["entries"]["ANYNET_MIN_HOPS|0"] = 0
    with pytest.raises(RouteArtifactError, match="class\\|src\\|dst"):
        RouteArtifact.from_dict(d)
    d = anynet4.to_dict()
    d["entries"]["ANYNET_MIN_HOPS|x|1"] = 0
    with pytest.raises(RouteArtifactError, match="non-integer router ids"):
        RouteArtifact.from_dict(d)
    d = anynet4.to_dict()
    d["entries"]["ANYNET_MIN_HOPS|0|1"] = "0"
    with pytest.raises(RouteArtifactError, match="must be an int"):
        RouteArtifact.from_dict(d)


def test_from_dict_refuses_undeclared_class_key(anynet4):
    d = anynet4.to_dict()
    d["entries"]["NO_SUCH_CLASS|0|1"] = 0
    with pytest.raises(RouteArtifactError, match="undeclared routing class"):
        RouteArtifact.from_dict(d)


# ── in-memory immutability of sealed values ────────────────────────────────

def test_route_table_is_read_only_over_a_private_copy(mesh4, anynet4):
    table = dict(anynet4.entries)
    artifact = _anynet(mesh4, entries=table)
    snapshot = dict(artifact.entries)
    table[(ANYNET_MIN_HOPS, 0, 1)] = 999999
    assert dict(artifact.entries) == snapshot
    assert isinstance(artifact.entries, Mapping)
    assert not isinstance(artifact.entries, dict)
    with pytest.raises(TypeError):
        artifact.entries[(ANYNET_MIN_HOPS, 0, 1)] = 0


def test_routing_class_parameters_defensively_frozen():
    source = [1, 2]
    definition = RoutingClassDefinition(
        id="X", algorithm="custom", algorithm_version=1,
        parameters=(("items", source),))
    source.append(3)
    assert definition.parameters == (("items", (1, 2)),)
    assert definition.parameters_dict() == {"items": (1, 2)}
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.algorithm = "other"


def test_routing_class_definition_is_strict():
    with pytest.raises(RouteArtifactError, match="declared twice"):
        RoutingClassDefinition(id="X", algorithm="a", algorithm_version=1,
                               parameters=(("p", 1), ("p", 2)))
    with pytest.raises(RouteArtifactError, match="JSON-serializable"):
        RoutingClassDefinition(id="X", algorithm="a", algorithm_version=1,
                               parameters=(("p", object()),))
    with pytest.raises(RouteArtifactError, match="unknown fields"):
        RoutingClassDefinition.from_dict({
            "id": "X", "algorithm": "a", "algorithm_version": 1,
            "parameters": {}, "extra": 1})


def test_artifact_field_shape_is_strict():
    base = dict(schema_version=2, name="r", topology_hash="sha256:x",
                routing_classes=(ANYNET_MIN_HOPS_DEFINITION,))
    with pytest.raises(RouteArtifactError, match="entries must be an object"):
        RouteArtifact(**base, entries=[])
    with pytest.raises(RouteArtifactError, match="must be \\(str, int, int\\)"):
        RouteArtifact(**base, entries={("ANYNET_MIN_HOPS", True, 1): 0})
    with pytest.raises(RouteArtifactError, match="channel id .* must be an int"):
        RouteArtifact(**base, entries={("ANYNET_MIN_HOPS", 0, 1): True})
    with pytest.raises(RouteArtifactError, match="non-empty tuple"):
        RouteArtifact(schema_version=2, name="r", topology_hash="sha256:x",
                      routing_classes=())
    with pytest.raises(RouteArtifactError, match="must be unique"):
        RouteArtifact(schema_version=2, name="r", topology_hash="sha256:x",
                      routing_classes=(ANYNET_MIN_HOPS_DEFINITION,
                                       ANYNET_MIN_HOPS_DEFINITION))
