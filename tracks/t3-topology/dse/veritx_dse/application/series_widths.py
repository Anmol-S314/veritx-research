"""Link/flit widths for the sampled series, read from the artifacts that declare them.

WHY THIS EXISTS
---------------
The series recorder needs a link capacity in whole flits per cycle, and
``booksim_execution.series_capacity_or_refuse`` refuses to guess one: it
requires a positive ``series_link_width_bits`` and ``series_flit_width_bits``
and derives ``link_width // flit_width``. Those two widths used to arrive
only through environment variables, which meant the packaged desktop app
recorded nothing — "Not recorded" for every counter, no observed watch
capture — unless the user knew an env var that the UI never mentions.

Both numbers are already DECLARED in the compiled fabric:

* every topology channel and shared link carries ``width_bits``;
* the packet format carries ``flit_width_bits``.

So they are READ here, not assumed. Nothing in this module invents a width.

MIXED WIDTHS ARE REFUSED
------------------------
A fabric whose links are not all the same width has no single capacity per
cycle. Averaging, or picking the first channel, would produce a utilization
number that is not true of any link. That case is refused and the caller
decides what to report.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SeriesWidthsUnavailable", "series_widths_from_bundle"]


class SeriesWidthsUnavailable(ValueError):
    """The fabric does not declare one usable (link, flit) width pair."""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def series_widths_from_bundle(bundle: Any) -> tuple[int, int]:
    """``(link_width_bits, flit_width_bits)`` as declared by the fabric."""
    packet_format = getattr(bundle, "packet_format", None)
    flit = _positive_int(getattr(packet_format, "flit_width_bits", None))
    if flit is None:
        raise SeriesWidthsUnavailable(
            "the packet format declares no positive flit_width_bits, so link "
            "capacity in flits per cycle is underivable")

    topology = getattr(bundle, "topology", None)
    if topology is None:
        raise SeriesWidthsUnavailable(
            "the compiled fabric carries no topology artifact")

    widths: set[int] = set()
    for attribute in ("channels", "shared_links"):
        for link in getattr(topology, attribute, ()) or ():
            width = _positive_int(getattr(link, "width_bits", None))
            if width is not None:
                widths.add(width)
    if not widths:
        raise SeriesWidthsUnavailable(
            "the topology declares no positive channel width_bits")
    if len(widths) > 1:
        raise SeriesWidthsUnavailable(
            f"the topology declares mixed link widths {sorted(widths)}; a "
            "single flits-per-cycle capacity is not true of any one link")
    link = widths.pop()
    if link % flit:
        raise SeriesWidthsUnavailable(
            f"link width {link} does not divide evenly into {flit}-bit "
            "flits, so capacity is fractional")
    return link, flit
