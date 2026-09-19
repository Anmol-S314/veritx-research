"""Wave B3.4a tests — PacketFormatArtifact: the wire-format authority.

Tests are seam-level: they build real TopologyArtifact /
AgentAttachmentArtifact / VCAssignmentArtifact parents, derive the
canonical format, and assert the pinned bit layout, the semantics of
each field role, and fail-closed persistence.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, AgentInterfaceDescriptor, Endpoint,
)
from veritx_dse.model.compile_model import AgentKind
from veritx_dse.model.packet_format import (
    DEFAULT_MAX_PACKET_FLITS, FLIT_TYPE_ENCODING,
    PACKETIZATION_BOUNDED_WORMHOLE, FieldMutability, FieldRole,
    PacketField, PacketFormatArtifact, PacketFormatError,
    canonical_field_layout, derive_packet_format, encoding_width,
    network_packet_count,
)
from veritx_dse.model.placement import AgentInstance
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_family,
)
from veritx_dse.model.vc_assignment import VCAssignmentArtifact


# ── fixtures ──────────────────────────────────────────────────────────────

_IFACE = AgentInterfaceDescriptor(
    data_width_bits=256, address_width_bits=64, protocol="AXI",
    clock_domain=None, power_domain=None)


def _attachment(topology, endpoint_count):
    endpoints = tuple(
        Endpoint(endpoint_id=i,
                 agent=AgentInstance(i, i, AgentKind.COMPUTE_TILE),
                 router_id=i % topology.router_count,
                 port_id=i // topology.router_count,
                 interface=_IFACE)
        for i in range(endpoint_count))
    return AgentAttachmentArtifact(
        topology_hash=topology.topology_hash(), endpoints=endpoints)


def _vc(vc_count, resolved_route_hash="r" * 64):
    return VCAssignmentArtifact(
        resolved_route_hash=resolved_route_hash,
        vc_count=vc_count,
        vc_ids=tuple(range(vc_count)),
        traffic_class_to_vcs=(("A", (0,)),),
        vc_to_routing_class=tuple(
            (i, "ANYNET_MIN_HOPS") for i in range(vc_count)),
        allowed_transitions=tuple((i, i) for i in range(vc_count)),
        escape_vcs=(),
        derivation="packet_format_test",
    )


def _derive(endpoint_count=4, vc_count=1, requested_width=None,
            max_packet_flits=DEFAULT_MAX_PACKET_FLITS,
            family=MaterializedFamily.MESH, concentration=1,
            width_bits=64):
    topo = materialize_family(
        family, endpoint_count=endpoint_count, concentration=concentration,
        width_bits=width_bits)
    att = _attachment(topo, endpoint_count)
    vc = _vc(vc_count)
    art = derive_packet_format(
        topology=topo, attachment=att, vc_assignment=vc,
        requested_flit_width_bits=requested_width,
        max_packet_flits=max_packet_flits)
    return topo, att, vc, art


def _by_role(artifact):
    return {f.role: f for f in artifact.field_layout}


# ── golden layouts (§70) ──────────────────────────────────────────────────

class TestGoldenLayouts:
    def test_golden_a_4endpoints_1vc_64bit(self):
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=1)
        by = _by_role(art)
        assert art.flit_width_bits == 64
        assert art.packetization == PACKETIZATION_BOUNDED_WORMHOLE
        assert art.max_packet_flits == 8
        assert art.payload_width_bits == 57
        assert art.endpoint_width_bits == 2
        assert art.vc_width_bits == 1
        assert art.endpoint_capacity == 4
        assert art.vc_capacity == 2
        assert (by[FieldRole.PAYLOAD].lsb, by[FieldRole.PAYLOAD].width) == (0, 57)
        assert (by[FieldRole.SOURCE_ENDPOINT].lsb,
                by[FieldRole.SOURCE_ENDPOINT].width) == (57, 2)
        assert (by[FieldRole.DESTINATION_ENDPOINT].lsb,
                by[FieldRole.DESTINATION_ENDPOINT].width) == (59, 2)
        assert (by[FieldRole.FLIT_TYPE].lsb,
                by[FieldRole.FLIT_TYPE].width) == (61, 2)
        assert (by[FieldRole.VC_ID].lsb,
                by[FieldRole.VC_ID].width) == (63, 1)
        covered = sum(f.width for f in art.field_layout)
        assert covered == art.flit_width_bits

    def test_golden_b_72endpoints_4vcs_64bit(self):
        _t, _a, _v, art = _derive(endpoint_count=72, vc_count=4)
        assert art.endpoint_width_bits == 7
        assert art.vc_width_bits == 2
        assert art.payload_width_bits == 46
        assert art.endpoint_capacity == 128
        assert art.vc_capacity == 4


class TestEncodingWidthBoundaries:
    @pytest.mark.parametrize("count,width", [
        (1, 1), (2, 1), (3, 2), (4, 2), (5, 3),
        (64, 6), (65, 7), (72, 7),
    ])
    def test_endpoint_boundaries(self, count, width):
        assert encoding_width(count) == width

    @pytest.mark.parametrize("count,width", [
        (1, 1), (2, 1), (3, 2), (4, 2), (16, 4),
    ])
    def test_vc_boundaries(self, count, width):
        assert encoding_width(count) == width

    def test_zero_and_negative_refused(self):
        with pytest.raises(PacketFormatError):
            encoding_width(0)
        with pytest.raises(PacketFormatError):
            encoding_width(-1)
        with pytest.raises(PacketFormatError):
            encoding_width(True)


# ── semantics (§21, §24, §29, §78) ────────────────────────────────────────

class TestFieldSemantics:
    def test_roles_and_mutability_are_pinned(self):
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=1)
        by = _by_role(art)
        assert by[FieldRole.PAYLOAD].mutability is FieldMutability.PAYLOAD
        assert by[FieldRole.SOURCE_ENDPOINT].mutability \
            is FieldMutability.PACKET_IMMUTABLE
        assert by[FieldRole.DESTINATION_ENDPOINT].mutability \
            is FieldMutability.PACKET_IMMUTABLE
        assert by[FieldRole.FLIT_TYPE].mutability \
            is FieldMutability.FLIT_STRUCTURAL
        assert by[FieldRole.VC_ID].mutability is FieldMutability.HOP_LOCAL

    def test_source_and_destination_share_endpoint_namespace(self):
        _t, _a, _v, art = _derive(endpoint_count=5, vc_count=1)
        by = _by_role(art)
        assert by[FieldRole.SOURCE_ENDPOINT].width \
            == by[FieldRole.DESTINATION_ENDPOINT].width
        assert art.endpoint_width_bits == 3  # 5 endpoints require 3 bits

    def test_traffic_class_and_routing_class_are_absent(self):
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=2)
        names = {f.name for f in art.field_layout}
        assert names == {"payload", "source_endpoint",
                         "destination_endpoint", "flit_type", "vc_id"}
        blob = repr(art.identity_dict()).lower()
        assert "traffic" not in blob
        assert "routing" not in blob

    def test_two_vc_transition_rewrites_only_vc_id(self):
        """VC0 -> VC1 rewrites the hop-local vc_id; RoutingClass is not
        written into the flit (it is derived from vc_out)."""
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=2)
        by = _by_role(art)
        assert art.vc_width_bits == 1
        assert by[FieldRole.VC_ID].mutability is FieldMutability.HOP_LOCAL
        assert FieldRole.VC_ID.value == "vc_id"

    def test_layout_has_no_gaps_or_overlaps(self):
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=1)
        cursor = 0
        for field in sorted(art.field_layout, key=lambda f: f.lsb):
            assert field.lsb == cursor
            cursor += field.width
        assert cursor == art.flit_width_bits


# ── rejections (§24, §29) ─────────────────────────────────────────────────

def _zero_channel_fixture(endpoint_count=4):
    topo = materialize_family(
        MaterializedFamily.CONCENTRATED_MESH,
        endpoint_count=endpoint_count, concentration=endpoint_count)
    return topo, _attachment(topo, endpoint_count), _vc(1)


class TestRejections:
    def test_header_cannot_consume_the_whole_flit(self):
        topo, att, vc = _zero_channel_fixture(4)
        # 4 endpoints (2 bits x2) + 2-bit type + 1-bit VC = 7-bit header
        with pytest.raises(PacketFormatError, match="header"):
            derive_packet_format(
                topology=topo, attachment=att, vc_assignment=vc,
                requested_flit_width_bits=7)

    def test_heterogeneous_channel_widths_refused(self):
        routers = (Router(0, (0,), 1), Router(1, (1,), 1))
        topo = TopologyArtifact(
            family=MaterializedFamily.MESH, routers=routers,
            channels=(
                DirectedChannel(0, 0, 0, 1, 0, 64, 1),
                DirectedChannel(1, 1, 0, 0, 0, 32, 1),
            ))
        att = _attachment(topo, 2)
        with pytest.raises(PacketFormatError, match="heterogeneous"):
            derive_packet_format(
                topology=topo, attachment=att, vc_assignment=_vc(1))

    def test_requested_width_must_match_channels(self):
        topo = materialize_family(
            MaterializedFamily.MESH, endpoint_count=4)
        att = _attachment(topo, 4)
        with pytest.raises(PacketFormatError, match="does not match"):
            derive_packet_format(
                topology=topo, attachment=att, vc_assignment=_vc(1),
                requested_flit_width_bits=128)

    def test_wrong_parent_hashes_refused(self):
        topo, att, vc, art = _derive()
        other_topo = materialize_family(
            MaterializedFamily.TORUS, endpoint_count=4)
        with pytest.raises(PacketFormatError, match="topology_hash"):
            art.validate_against(other_topo, att, vc)
        with pytest.raises(PacketFormatError, match="attachment_hash"):
            art.validate_against(topo, _attachment(other_topo, 4), vc)
        with pytest.raises(PacketFormatError, match="vc_assignment_hash"):
            art.validate_against(topo, att, _vc(1, "s" * 64))

    def test_endpoint_capacity_exceeded_refused(self):
        topo = materialize_family(
            MaterializedFamily.MESH, endpoint_count=5)
        att = _attachment(topo, 5)
        vc = _vc(1)
        layout = canonical_field_layout(
            endpoint_width=2, vc_width=1, payload_width=64 - 7)
        art = PacketFormatArtifact(
            topology_hash=topo.topology_hash(),
            attachment_hash=att.attachment_hash(),
            vc_assignment_hash=vc.vc_assignment_hash(),
            flit_width_bits=64,
            packetization=PACKETIZATION_BOUNDED_WORMHOLE,
            max_packet_flits=8,
            header_replication="EVERY_FLIT",
            field_layout=layout)
        with pytest.raises(PacketFormatError, match="endpoints exceed"):
            art.validate_against(topo, att, vc)

    def test_vc_capacity_exceeded_refused(self):
        topo = materialize_family(
            MaterializedFamily.MESH, endpoint_count=4)
        att = _attachment(topo, 4)
        vc = _vc(5)  # 5 VCs required, 2-bit field encodes 4
        layout = canonical_field_layout(
            endpoint_width=2, vc_width=2, payload_width=64 - 8)
        art = PacketFormatArtifact(
            topology_hash=topo.topology_hash(),
            attachment_hash=att.attachment_hash(),
            vc_assignment_hash=vc.vc_assignment_hash(),
            flit_width_bits=64,
            packetization=PACKETIZATION_BOUNDED_WORMHOLE,
            max_packet_flits=8,
            header_replication="EVERY_FLIT",
            field_layout=layout)
        with pytest.raises(PacketFormatError, match="vc_count"):
            art.validate_against(topo, att, vc)

    def test_overlapping_layout_refused(self):
        _t, _a, _v, art = _derive()
        bad = tuple(
            replace(f, lsb=f.lsb - 1) if f.role is FieldRole.FLIT_TYPE else f
            for f in art.field_layout)
        with pytest.raises(PacketFormatError):
            PacketFormatArtifact(
                topology_hash=art.topology_hash,
                attachment_hash=art.attachment_hash,
                vc_assignment_hash=art.vc_assignment_hash,
                flit_width_bits=art.flit_width_bits,
                packetization=art.packetization,
                max_packet_flits=art.max_packet_flits,
                header_replication=art.header_replication,
                field_layout=bad)

    def test_gap_layout_refused(self):
        _t, _a, _v, art = _derive()
        bad = tuple(
            replace(f, lsb=f.lsb + 1) if f.role is FieldRole.VC_ID else f
            for f in art.field_layout)
        with pytest.raises(PacketFormatError, match="contiguous|missing"):
            PacketFormatArtifact(
                topology_hash=art.topology_hash,
                attachment_hash=art.attachment_hash,
                vc_assignment_hash=art.vc_assignment_hash,
                flit_width_bits=art.flit_width_bits,
                packetization=art.packetization,
                max_packet_flits=art.max_packet_flits,
                header_replication=art.header_replication,
                field_layout=bad)

    def test_missing_role_refused(self):
        _t, _a, _v, art = _derive()
        with pytest.raises(PacketFormatError, match="missing roles"):
            PacketFormatArtifact(
                topology_hash=art.topology_hash,
                attachment_hash=art.attachment_hash,
                vc_assignment_hash=art.vc_assignment_hash,
                flit_width_bits=art.flit_width_bits,
                packetization=art.packetization,
                max_packet_flits=art.max_packet_flits,
                header_replication=art.header_replication,
                field_layout=tuple(
                    f for f in art.field_layout
                    if f.role is not FieldRole.VC_ID))

    def test_duplicate_role_refused(self):
        _t, _a, _v, art = _derive()
        extra = PacketField("payload", 63, 1, FieldRole.PAYLOAD,
                            FieldMutability.PAYLOAD)
        with pytest.raises(PacketFormatError, match="duplicate|contiguous"):
            PacketFormatArtifact(
                topology_hash=art.topology_hash,
                attachment_hash=art.attachment_hash,
                vc_assignment_hash=art.vc_assignment_hash,
                flit_width_bits=art.flit_width_bits,
                packetization=art.packetization,
                max_packet_flits=art.max_packet_flits,
                header_replication=art.header_replication,
                field_layout=tuple(f for f in art.field_layout
                                   if f.role is not FieldRole.VC_ID) + (extra,))

    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(flit_width_bits=True), "flit_width_bits"),
        (lambda d: d.update(flit_width_bits=64.0), "flit_width_bits"),
        (lambda d: d.update(flit_width_bits="64"), "flit_width_bits"),
        (lambda d: d.update(max_packet_flits=0), "max_packet_flits"),
        (lambda d: d.update(artifact_hash="0" * 64), "artifact_hash"),
        (lambda d: d.update(flit_type_encoding=[["HEAD", 0], ["BODY", 1]]),
         "flit_type_encoding"),
    ])
    def test_persisted_mutations_refused(self, mutate, match):
        _t, _a, _v, art = _derive()
        d = art.to_dict()
        mutate(d)
        with pytest.raises(PacketFormatError, match=match):
            PacketFormatArtifact.from_dict(d)

    def test_missing_artifact_hash_refused(self):
        _t, _a, _v, art = _derive()
        d = art.to_dict()
        del d["artifact_hash"]
        with pytest.raises(PacketFormatError, match="artifact_hash"):
            PacketFormatArtifact.from_dict(d)

    def test_unknown_role_refused(self):
        _t, _a, _v, art = _derive()
        d = art.to_dict()
        d["field_layout"][0]["role"] = "traffic_class"
        with pytest.raises(PacketFormatError, match="unknown packet field role"):
            PacketFormatArtifact.from_dict(d)

    def test_wrong_mutability_refused(self):
        _t, _a, _v, art = _derive()
        d = art.to_dict()
        d["field_layout"][0]["mutability"] = "hop_local"
        with pytest.raises(PacketFormatError, match="mutability"):
            PacketFormatArtifact.from_dict(d)

    def test_roundtrip_preserves_hash(self):
        _t, _a, _v, art = _derive()
        loaded = PacketFormatArtifact.from_dict(art.to_dict())
        assert loaded.packet_format_hash() == art.packet_format_hash()


# ── identity mutations (§29) ──────────────────────────────────────────────

class TestIdentityMutations:
    def test_field_position_change_changes_hash(self):
        _t, _a, _v, art = _derive()
        alternate = (
            PacketField("vc_id", 0, 1, FieldRole.VC_ID,
                        FieldMutability.HOP_LOCAL),
            PacketField("flit_type", 1, 2, FieldRole.FLIT_TYPE,
                        FieldMutability.FLIT_STRUCTURAL),
            PacketField("destination_endpoint", 3, 2,
                        FieldRole.DESTINATION_ENDPOINT,
                        FieldMutability.PACKET_IMMUTABLE),
            PacketField("source_endpoint", 5, 2, FieldRole.SOURCE_ENDPOINT,
                        FieldMutability.PACKET_IMMUTABLE),
            PacketField("payload", 7, 57, FieldRole.PAYLOAD,
                        FieldMutability.PAYLOAD),
        )
        twin = PacketFormatArtifact(
            topology_hash=art.topology_hash,
            attachment_hash=art.attachment_hash,
            vc_assignment_hash=art.vc_assignment_hash,
            flit_width_bits=64, packetization=art.packetization,
            max_packet_flits=8, header_replication=art.header_replication,
            field_layout=alternate)
        assert twin.packet_format_hash() != art.packet_format_hash()

    def test_max_packet_flits_change_changes_hash(self):
        _t, _a, _v, art = _derive()
        _t2, _a2, _v2, bigger = _derive(max_packet_flits=16)
        assert bigger.packet_format_hash() != art.packet_format_hash()

    def test_flit_width_change_changes_hash(self):
        _t, _a, _v, wide = _derive(width_bits=128)
        _t2, _a2, _v2, narrow = _derive(width_bits=64)
        assert wide.flit_width_bits == 128
        assert narrow.flit_width_bits == 64
        assert wide.packet_format_hash() != narrow.packet_format_hash()

    def test_vc_parent_change_changes_hash(self):
        _t, _a, _v, art = _derive(vc_count=1)
        _t2, _a2, _v2, other = _derive(vc_count=2)
        assert other.vc_assignment_hash != art.vc_assignment_hash
        assert other.packet_format_hash() != art.packet_format_hash()

    def test_attachment_parent_change_changes_hash(self):
        topo = materialize_family(
            MaterializedFamily.MESH, endpoint_count=4)
        art_a = derive_packet_format(
            topology=topo, attachment=_attachment(topo, 4),
            vc_assignment=_vc(1))
        changed = AgentInterfaceDescriptor(512, 64, "CHI", None, None)
        att_b = AgentAttachmentArtifact(
            topology_hash=topo.topology_hash(),
            endpoints=tuple(
                Endpoint(endpoint_id=i,
                         agent=AgentInstance(i, i, AgentKind.COMPUTE_TILE),
                         router_id=i % topo.router_count, port_id=0,
                         interface=changed)
                for i in range(4)))
        art_b = derive_packet_format(
            topology=topo, attachment=att_b, vc_assignment=_vc(1))
        assert art_a.attachment_hash != art_b.attachment_hash
        assert art_a.packet_format_hash() != art_b.packet_format_hash()


# ── packetization / fragmentation (§30, §72) ──────────────────────────────

class TestPacketization:
    def test_default_is_bounded_wormhole(self):
        _t, _a, _v, art = _derive()
        assert art.packetization == "BOUNDED_WORMHOLE"
        assert art.header_replication == "EVERY_FLIT"
        assert art.max_packet_flits == DEFAULT_MAX_PACKET_FLITS == 8
        assert art.flit_type_encoding == FLIT_TYPE_ENCODING

    def test_golden_a_payload_capacity_and_fragmentation(self):
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=1)
        assert art.max_network_packet_payload_bits == 57 * 8 == 456
        mib16_bits = 16 * 1024 * 1024 * 8
        assert network_packet_count(mib16_bits, art) == 294338
        assert network_packet_count(mib16_bits, art) > 1
        assert network_packet_count(0, art) == 0
        assert network_packet_count(1, art) == 1
        assert network_packet_count(456, art) == 1
        assert network_packet_count(457, art) == 2

    def test_16mib_is_never_one_unbounded_packet(self):
        """B3.7 regression guard: a 16 MiB message is fragmented by the
        NI into bounded network packets, not one giant wormhole packet."""
        _t, _a, _v, art = _derive(endpoint_count=4, vc_count=1)
        assert art.max_packet_flits == 8
        assert network_packet_count(16 * 1024 * 1024 * 8, art) > 1
