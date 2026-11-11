"""The series widths come from the fabric, never from a default.

Rationale: docs/decisions/modules/application.md
"""
from types import SimpleNamespace

import pytest

from veritx_dse.application.series_widths import (
    SeriesWidthsUnavailable,
    series_widths_from_bundle,
)


def _bundle(*, flit=64, channel_widths=(64,), shared_widths=()):
    channels = [SimpleNamespace(width_bits=w) for w in channel_widths]
    shared = [SimpleNamespace(width_bits=w) for w in shared_widths]
    return SimpleNamespace(
        packet_format=SimpleNamespace(flit_width_bits=flit),
        topology=SimpleNamespace(channels=channels, shared_links=shared))


def test_reads_channel_width_and_flit_width():
    assert series_widths_from_bundle(_bundle(flit=32, channel_widths=(256,))) \
        == (256, 32)


def test_reads_shared_link_width_when_channels_declare_none():
    assert series_widths_from_bundle(
        _bundle(flit=64, channel_widths=(), shared_widths=(128,))) == (128, 64)


def test_refuses_a_missing_flit_width():
    with pytest.raises(SeriesWidthsUnavailable, match="flit_width_bits"):
        series_widths_from_bundle(_bundle(flit=None))


def test_refuses_a_topology_with_no_widths():
    with pytest.raises(SeriesWidthsUnavailable, match="no positive channel"):
        series_widths_from_bundle(_bundle(channel_widths=()))


def test_refuses_mixed_link_widths():
    # A fabric with 64- and 128-bit links has no single flits-per-cycle
    # capacity, so picking one would be true of only some links.
    with pytest.raises(SeriesWidthsUnavailable, match="mixed link widths"):
        series_widths_from_bundle(_bundle(channel_widths=(64, 128)))


def test_refuses_a_fractional_capacity():
    with pytest.raises(SeriesWidthsUnavailable, match="fractional"):
        series_widths_from_bundle(_bundle(flit=48, channel_widths=(64,)))
