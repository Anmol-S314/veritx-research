"""veritx_dse.backend.channel_measurements — MEASURED per-channel load.

A measured channel-load artifact answers what the backend's counters saw:
per directed channel, how many flits crossed, broken down by traffic class.
It is read from the fork's versioned ``veritx/channel-activity/v1`` dump,
never scraped from stdout, and never mixed with DERIVED EXPECTED load
(measured endpoint-pair flits walked over the frozen route table).

The two loads answer different questions and share no type: a measured
artifact says what happened; an expected artifact says what the certified
routes predict. Loom renders them side by side, never merged.

Join rule: a (router, output port) counter attributes to the certified
channel with that (src_router, src_port) if exactly one exists. Ports with
no certified channel (injection, ejection, unmapped) are reported under
``unmatched_ports`` — counted, never attributed, never dropped silently.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CHANNEL_ACTIVITY_SCHEMA = "veritx/channel-activity/v1"


class ChannelMeasurementError(ValueError):
    """The measurement artifact cannot be read as MEASURED load."""


def _need_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ChannelMeasurementError(
            f"{where} must be a non-negative int, got {value!r}")
    return value


@dataclass(frozen=True)
class MeasuredChannel:
    """One directed channel's measured counters."""

    channel_id: int
    src_router: int
    dst_router: int
    flits: int
    flits_by_class: tuple[int, ...]


@dataclass(frozen=True)
class MeasuredChannelLoad:
    """MEASURED per-channel load for one simulated subnet.

    ``kind`` is the load identity: MEASURED_CHANNEL_LOAD is backend
    counters, DERIVED_EXPECTED_LOAD (elsewhere) is trace × route table.
    ``unmatched_ports`` are (router, port) counters with no certified
    channel — injection/ejection or unmapped — reported, not attributed.
    """

    kind: str
    schema: str
    subnet: int
    cycles_observed: int
    cycles_observed_min: int
    channels: tuple[MeasuredChannel, ...]
    unmatched_ports: tuple[tuple[int, int, int], ...]
    skipped_non_iq_routers: int

    def flits_total(self) -> int:
        """Measured flits attributed to certified channels."""
        return sum(c.flits for c in self.channels)


def parse_channel_activity(doc: Any) -> dict[str, Any]:
    """Validate the raw dump document. Returns the normalized document.

    Refuses unknown schemas, missing keys, negative counts, and ragged
    per-class vectors. A partial dump is not a measurement.
    """
    if not isinstance(doc, dict):
        raise ChannelMeasurementError(
            f"channel activity document must be an object, got "
            f"{type(doc).__name__}")
    schema = doc.get("schema")
    if schema != CHANNEL_ACTIVITY_SCHEMA:
        raise ChannelMeasurementError(
            f"channel activity schema {schema!r} is not "
            f"{CHANNEL_ACTIVITY_SCHEMA!r} — refusing to parse an "
            "unknown version")
    for key in ("subnet", "router_count", "routers",
                "skipped_non_iq_routers"):
        if key not in doc:
            raise ChannelMeasurementError(
                f"channel activity document is missing {key!r}")
    routers = doc["routers"]
    if not isinstance(routers, list):
        raise ChannelMeasurementError("routers must be a list")
    return {
        "schema": schema,
        "subnet": _need_int(doc["subnet"], "subnet"),
        "routers": routers,
        "skipped": _need_int(
            doc["skipped_non_iq_routers"], "skipped_non_iq_routers"),
    }


def join_measured_load(parsed: Mapping[str, Any],
                       channels: list[dict[str, Any]],
                       ) -> MeasuredChannelLoad:
    """Attribute measured counters to certified channels.

    ``channels`` carries the certified channel table
    ({channel_id, src_router, src_port, dst_router, ...}). Exactly one
    channel per (src_router, src_port) is required — an ambiguous port
    refuses rather than splitting flits by guess.
    """
    by_port: dict[tuple[int, int], dict[str, Any]] = {}
    for channel in channels:
        key = (channel["src_router"], channel["src_port"])
        if key in by_port:
            raise ChannelMeasurementError(
                f"channel table maps port {key} twice "
                f"({by_port[key]['channel_id']} and "
                f"{channel['channel_id']}) — refusing an ambiguous join")
        by_port[key] = channel

    measured: list[MeasuredChannel] = []
    unmatched: list[tuple[int, int, int]] = []
    cycles: list[int] = []
    for router in parsed["routers"]:
        if not isinstance(router, dict):
            raise ChannelMeasurementError(
                f"router entry must be an object, got {router!r}")
        router_id = _need_int(router.get("id"), "router.id")
        classes = _need_int(router.get("num_classes"), "num_classes")
        cycles.append(_need_int(
            router.get("cycles_observed"), "cycles_observed"))
        outputs = router.get("output_activity")
        if not isinstance(outputs, list):
            raise ChannelMeasurementError(
                f"router {router_id} is missing output_activity")
        for entry in outputs:
            if not isinstance(entry, dict):
                raise ChannelMeasurementError(
                    f"router {router_id} output entry must be an object")
            port = _need_int(entry.get("port"), "output port")
            flits_by_class = entry.get("flits_by_class")
            if (not isinstance(flits_by_class, list)
                    or len(flits_by_class) != classes
                    or any(not isinstance(v, int) or v < 0
                           for v in flits_by_class)):
                raise ChannelMeasurementError(
                    f"router {router_id} port {port}: flits_by_class "
                    "must be a full non-negative per-class vector")
            channel = by_port.get((router_id, port))
            if channel is None:
                unmatched.append(
                    (router_id, port, sum(flits_by_class)))
                continue
            measured.append(MeasuredChannel(
                channel_id=_need_int(
                    channel["channel_id"], "channel_id"),
                src_router=router_id,
                dst_router=_need_int(
                    channel["dst_router"], "dst_router"),
                flits=sum(flits_by_class),
                flits_by_class=tuple(flits_by_class),
            ))
    # Router monitors tick per router; counts can differ by a few cycles
    # across routers (creation order, drain). The window is reported as a
    # max/min pair, never silently equalized and never a refusal: a few
    # cycles of skew do not invalidate flit counts.
    cycles_observed = max(cycles) if cycles else 0
    cycles_min = min(cycles) if cycles else 0
    measured.sort(key=lambda c: c.channel_id)
    return MeasuredChannelLoad(
        kind="MEASURED_CHANNEL_LOAD",
        schema=parsed["schema"],
        subnet=parsed["subnet"],
        cycles_observed=cycles_observed,
        cycles_observed_min=cycles_min,
        channels=tuple(measured),
        unmatched_ports=tuple(unmatched),
        skipped_non_iq_routers=parsed["skipped"],
    )


def read_measured_load(doc: Any,
                       channels: list[dict[str, Any]],
                       ) -> MeasuredChannelLoad:
    """Parse a raw dump and join it to the certified channel table."""
    return join_measured_load(parse_channel_activity(doc), channels)
