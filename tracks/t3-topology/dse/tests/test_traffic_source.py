"""Tests for the shared endpoint-level traffic-source contract.

No simulator binary is required: raw parsing, rendering and scanning are pure
Python.  The canonical adapter reuses the projection fixture from
``test_backend_booksim_projection`` and only renders an existing
``PhysicalTrafficArtifact``.
"""
from __future__ import annotations

import hashlib

import pytest

from veritx_dse.core.errors import SemanticError
from veritx_dse.workload import traffic_source as ts


RAW_TRACE = (
    b"# a raw single-class trace\n"
    b"0 0 0 1 4\n"
    b"\n"
    b"% percent comments are accepted too\n"
    b"2 3 0 2 1\n"
)

CANONICAL_RAW_TRACE = b"0 0 0 1 4\n2 3 0 2 1\n"

TWO_CLASS_TRACE = b"0 0 0 1 4\n1 2 1 3 2\n"
TWO_CLASS_NAMES = ("compute", "memory")
TWO_CLASS_IDENTITY = "sha256:" + hashlib.sha256(TWO_CLASS_TRACE).hexdigest()


class _StubSource(ts.TrafficSource):
    """A minimal source used to exercise the default contract methods."""

    def __init__(self, info: ts.TrafficSourceInfo,
                 packets: tuple[ts.Packet, ...]):
        self._info = info
        self._packets = packets

    def info(self) -> ts.TrafficSourceInfo:
        return self._info

    def packets(self, *, endpoint_count: int,
                max_packet_flits: int) -> tuple[ts.Packet, ...]:
        return self._packets


def test_error_is_value_and_semantic_error():
    err = ts.TrafficSourceError("nope")
    assert isinstance(err, ValueError)
    assert isinstance(err, SemanticError)
    assert err.code == "TRAFFIC_SOURCE_REFUSED"


@pytest.mark.parametrize("field, value", [
    ("timestamp", -1),
    ("src", -1),
    ("dst", -1),
    ("flits", 0),
])
def test_packet_refuses_invalid_numbers(field, value):
    kwargs = {"timestamp": 0, "src": 0, "dst": 1,
              "traffic_class": "compute", "flits": 1}
    kwargs[field] = value
    with pytest.raises(ts.TrafficSourceError, match=field):
        ts.Packet(**kwargs)


def test_packet_refuses_empty_class_and_non_int_fields():
    with pytest.raises(ts.TrafficSourceError, match="traffic_class"):
        ts.Packet(timestamp=0, src=0, dst=1, traffic_class="  ", flits=1)
    with pytest.raises(ts.TrafficSourceError, match="timestamp"):
        ts.Packet(timestamp=True, src=0, dst=1,
                  traffic_class="compute", flits=1)


def test_info_validates_identity_and_addressing():
    with pytest.raises(ts.TrafficSourceError, match="identity"):
        ts.TrafficSourceInfo(identity="", addressing="ENDPOINT",
                             limitations=(), class_names=("compute",))
    with pytest.raises(ts.TrafficSourceError, match="addressing"):
        ts.TrafficSourceInfo(identity="x", addressing="endpoint",
                             limitations=(), class_names=("compute",))
    info = ts.TrafficSourceInfo(identity="x", addressing="RANK",
                                limitations=(), class_names=("compute",))
    assert info.addressing == "RANK"


def test_raw_trace_parses_identity_addressing_and_class_map():
    source = ts.RawTraceSource(RAW_TRACE)
    info = source.info()
    assert info.identity == "sha256:" + hashlib.sha256(RAW_TRACE).hexdigest()
    assert info.addressing == "ENDPOINT"
    assert info.class_names == ("trace",)
    assert any("single-class" in limitation
               for limitation in info.limitations)
    assert any("raw bytes" in limitation for limitation in info.limitations)

    assert source.packets(endpoint_count=4, max_packet_flits=8) == (
        ts.Packet(timestamp=0, src=0, dst=1, traffic_class="trace",
                  flits=4),
        ts.Packet(timestamp=2, src=3, dst=2, traffic_class="trace",
                  flits=1),
    )


def test_raw_trace_custom_class_name_is_declared():
    source = ts.RawTraceSource(CANONICAL_RAW_TRACE, traffic_class="compute")
    assert source.info().class_names == ("compute",)
    assert {packet.traffic_class
            for packet in source.packets(endpoint_count=4,
                                         max_packet_flits=8)} == {"compute"}


def test_raw_trace_to_trace_roundtrip():
    source = ts.RawTraceSource(CANONICAL_RAW_TRACE)
    assert source.to_trace(
        endpoint_count=4, max_packet_flits=8) == CANONICAL_RAW_TRACE


def test_raw_trace_refuses_out_of_bounds_endpoints():
    source = ts.RawTraceSource(b"0 1 0 1 4\n")
    with pytest.raises(ts.TrafficSourceError, match="endpoint outside"):
        source.packets(endpoint_count=1, max_packet_flits=8)

    destination = ts.RawTraceSource(b"0 0 0 1 4\n")
    with pytest.raises(ts.TrafficSourceError, match="endpoint outside"):
        destination.packets(endpoint_count=1, max_packet_flits=8)


def test_raw_trace_refuses_flit_cap_and_invalid_limits():
    source = ts.RawTraceSource(b"0 0 0 1 4\n")
    with pytest.raises(ts.TrafficSourceError, match="max_packet_flits"):
        source.packets(endpoint_count=2, max_packet_flits=3)
    with pytest.raises(ts.TrafficSourceError, match="endpoint_count"):
        source.packets(endpoint_count=0, max_packet_flits=8)
    with pytest.raises(ts.TrafficSourceError, match="max_packet_flits"):
        source.packets(endpoint_count=2, max_packet_flits=0)


@pytest.mark.parametrize("class_index", [1, 2, 7, -1])
def test_raw_trace_refuses_multiclass(class_index):
    trace = f"0 0 {class_index} 1 4\n".encode("ascii")
    with pytest.raises(ts.TrafficSourceError,
                       match="multi-class|classes=1"):
        ts.RawTraceSource(trace)


@pytest.mark.parametrize("trace, match", [
    (b"0 0 0 1\n", "whitespace columns"),
    (b"0 0 0 1 4 9\n", "whitespace columns"),
    (b"0 x 0 1 4\n", "not an integer"),
    (b"-1 0 0 1 4\n", "negative timestamp"),
    (b"0 -1 0 1 4\n", "negative src"),
    (b"0 0 0 -1 4\n", "negative dst"),
    (b"0 0 0 1 0\n", "flits"),
    (b"\xff\n", "UTF-8"),
])
def test_raw_trace_refuses_malformed_lines(trace, match):
    with pytest.raises(ts.TrafficSourceError, match=match):
        ts.RawTraceSource(trace)


def test_raw_trace_refuses_empty_input():
    for trace in (b"", b"\n\n", b"# only a comment\n% and another\n"):
        with pytest.raises(ts.TrafficSourceError,
                           match="no parseable packets"):
            ts.RawTraceSource(trace)


def test_rendered_trace_maps_class_indices():
    source = ts.RenderedTraceSource(
        TWO_CLASS_TRACE,
        class_names=TWO_CLASS_NAMES,
        identity=TWO_CLASS_IDENTITY,
        limitations=("synthetic",),
    )
    info = source.info()
    assert info.identity == TWO_CLASS_IDENTITY
    assert info.addressing == "ENDPOINT"
    assert info.class_names == TWO_CLASS_NAMES
    assert info.limitations == ("synthetic",)

    packets = source.packets(endpoint_count=4, max_packet_flits=8)
    assert packets == (
        ts.Packet(timestamp=0, src=0, dst=1, traffic_class="compute",
                  flits=4),
        ts.Packet(timestamp=1, src=2, dst=3, traffic_class="memory",
                  flits=2),
    )


def test_rendered_trace_to_trace_preserves_class_indices():
    source = ts.RenderedTraceSource(
        TWO_CLASS_TRACE,
        class_names=TWO_CLASS_NAMES,
        identity=TWO_CLASS_IDENTITY,
    )
    assert source.to_trace(
        endpoint_count=4, max_packet_flits=8) == TWO_CLASS_TRACE


def test_rendered_trace_preserves_declared_wire_class_order():
    names = ("memory", "compute")
    source = ts.RenderedTraceSource(
        TWO_CLASS_TRACE,
        class_names=names,
        identity=TWO_CLASS_IDENTITY,
    )
    assert [packet.traffic_class for packet in source.packets(
        endpoint_count=4, max_packet_flits=8)] == ["memory", "compute"]
    assert source.to_trace(
        endpoint_count=4, max_packet_flits=8) == TWO_CLASS_TRACE


def test_rendered_trace_refuses_unknown_class_index():
    trace = b"0 0 2 1 4\n"
    with pytest.raises(ts.TrafficSourceError, match="class index"):
        ts.RenderedTraceSource(
            trace,
            class_names=TWO_CLASS_NAMES,
            identity="sha256:" + hashlib.sha256(trace).hexdigest(),
        )


def test_to_trace_refuses_class_name_outside_declared_map():
    info = ts.TrafficSourceInfo(
        identity="stub",
        addressing="ENDPOINT",
        limitations=(),
        class_names=("compute",),
    )
    source = _StubSource(
        info,
        (ts.Packet(timestamp=0, src=0, dst=1, traffic_class="ghost",
                   flits=1),),
    )
    with pytest.raises(ts.TrafficSourceError, match="not declared"):
        source.to_trace(endpoint_count=2, max_packet_flits=8)


def test_to_trace_is_deterministic():
    source = ts.RenderedTraceSource(
        TWO_CLASS_TRACE,
        class_names=TWO_CLASS_NAMES,
        identity=TWO_CLASS_IDENTITY,
    )
    first = source.to_trace(endpoint_count=4, max_packet_flits=8)
    assert first == source.to_trace(endpoint_count=4, max_packet_flits=8)
    assert first == TWO_CLASS_TRACE


def test_scan_summary_matches_packets():
    source = ts.RawTraceSource(CANONICAL_RAW_TRACE)
    packets = source.packets(endpoint_count=4, max_packet_flits=8)
    summary = source.scan(endpoint_count=4, max_packet_flits=8)
    assert summary == {
        "packets": len(packets),
        "max_timestamp": max(packet.timestamp for packet in packets),
        "endpoints": len({packet.src for packet in packets}
                         | {packet.dst for packet in packets}),
        "classes": tuple(sorted({packet.traffic_class
                                 for packet in packets})),
    }
    assert summary["endpoints"] == 4
    assert summary["classes"] == ("trace",)


def test_scan_summary_preserves_multiple_class_names():
    source = ts.RenderedTraceSource(
        TWO_CLASS_TRACE,
        class_names=TWO_CLASS_NAMES,
        identity=TWO_CLASS_IDENTITY,
    )
    summary = source.scan(endpoint_count=4, max_packet_flits=8)
    assert summary["packets"] == 2
    assert summary["max_timestamp"] == 1
    assert summary["endpoints"] == 4
    assert summary["classes"] == ("compute", "memory")


def test_canonical_source_matches_render_trace():
    from test_backend_booksim_projection import _parents

    from veritx_dse.backend import booksim_projection as bp

    compiled, parents = _parents()
    physical_traffic = parents.physical_traffic
    rendered = bp.render_trace(physical_traffic)
    class_names = bp.trace_class_map(physical_traffic)

    source = ts.CanonicalTraceSource.from_physical_traffic(physical_traffic)
    info = source.info()
    assert info.identity == "sha256:" + hashlib.sha256(rendered).hexdigest()
    assert info.addressing == "ENDPOINT"
    assert info.class_names == class_names
    assert info.limitations == (
        "canonical renderer assigns dense 0..N-1 timestamps; "
        "class indices are dense over sorted class names",
    )

    endpoint_count = compiled.attachment.endpoint_count
    max_packet_flits = compiled.packet_format.max_packet_flits
    packets = source.packets(
        endpoint_count=endpoint_count,
        max_packet_flits=max_packet_flits)
    rows = [line for line in rendered.decode("ascii").splitlines() if line]
    assert len(packets) == len(rows)
    assert [packet.timestamp for packet in packets] == list(
        range(len(packets)))
    assert source.to_trace(
        endpoint_count=endpoint_count,
        max_packet_flits=max_packet_flits) == rendered

    # Identity and packets are stable across independent adaptations.
    again = ts.CanonicalTraceSource.from_physical_traffic(physical_traffic)
    assert again.info().identity == info.identity
    assert again.packets(
        endpoint_count=endpoint_count,
        max_packet_flits=max_packet_flits) == packets
