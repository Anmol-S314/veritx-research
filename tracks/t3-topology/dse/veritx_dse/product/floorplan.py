"""Authored floorplan for one materialized topology.

Die outline, non-overlapping router footprints, keepouts and a first-order wire
model. Integer micrometres keep the geometry exact; the wire model is a
declared ps/mm figure, not extracted parasitics.

Scope: AUTHORED_FLOORPLAN_NOT_PPA. This is not placement optimization, routing,
DRC/LVS, signoff timing or silicon area.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from veritx_dse.model.physical_placement import RouterFootprint

ARTIFACT_TYPE = "veritx/Floorplan"
SCHEMA_VERSION = 1
SCOPE = "AUTHORED_FLOORPLAN_NOT_PPA"

_KEYS = frozenset({
    "type", "schema_version", "topology_hash", "die_width_um",
    "die_height_um", "routers", "keepouts", "wire", "scope",
})
_WIRE_KEYS = frozenset({"ps_per_mm", "fixed_ps"})
_KEEPOUT_KEYS = frozenset({"keepout_id", "x_um", "y_um", "width_um", "height_um"})
_GRID_KEYS = frozenset({
    "origin_x_um", "origin_y_um", "pitch_x_um", "pitch_y_um",
    "router_width_um", "router_height_um", "margin_um", "wire",
})


def _positive_int(name: str, value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _non_negative_int(name: str, value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return value


def _identity(value: Any) -> str:
    if (not isinstance(value, str) or not value.startswith("sha256:")
            or len(value) != 71
            or any(c not in "0123456789abcdef" for c in value[7:])):
        raise ValueError(
            f"topology_hash must be a sha256:<64 hex> identity, got {value!r}")
    return value


def _exact_keys(document: Any, keys: frozenset[str], what: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError(f"{what} must be a JSON object")
    extra = sorted(set(document) - keys)
    missing = sorted(keys - set(document))
    if extra:
        raise ValueError(f"{what} has unknown fields {extra}")
    if missing:
        raise ValueError(f"{what} is missing fields {missing}")
    return document


@dataclass(frozen=True)
class Keepout:
    keepout_id: str
    x_um: int
    y_um: int
    width_um: int
    height_um: int

    def __post_init__(self):
        if not isinstance(self.keepout_id, str) or not self.keepout_id:
            raise ValueError("keepout_id must be a non-empty string")
        _non_negative_int("x_um", self.x_um)
        _non_negative_int("y_um", self.y_um)
        _positive_int("width_um", self.width_um)
        _positive_int("height_um", self.height_um)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def overlaps(self, other: "Keepout") -> bool:
        return (self.x_um < other.x_um + other.width_um
                and other.x_um < self.x_um + self.width_um
                and self.y_um < other.y_um + other.height_um
                and other.y_um < self.y_um + self.height_um)


@dataclass(frozen=True)
class WireModel:
    """Declared first-order link delay: length_mm * ps_per_mm + fixed_ps."""
    ps_per_mm: int
    fixed_ps: int = 0

    def __post_init__(self):
        _non_negative_int("ps_per_mm", self.ps_per_mm)
        _non_negative_int("fixed_ps", self.fixed_ps)
        if self.ps_per_mm == 0:
            raise ValueError("ps_per_mm must be greater than zero")

    def to_dict(self) -> dict[str, int]:
        return {"ps_per_mm": self.ps_per_mm, "fixed_ps": self.fixed_ps}

    def delay_ps(self, length_um: Fraction) -> Fraction:
        return length_um * self.ps_per_mm / 1000 + self.fixed_ps


@dataclass(frozen=True)
class Floorplan:
    topology_hash: str
    die_width_um: int
    die_height_um: int
    routers: tuple[RouterFootprint, ...]
    keepouts: tuple[Keepout, ...]
    wire: WireModel

    def __post_init__(self):
        _identity(self.topology_hash)
        _positive_int("die_width_um", self.die_width_um)
        _positive_int("die_height_um", self.die_height_um)
        if not isinstance(self.routers, tuple) or not self.routers:
            raise ValueError("routers must be a nonempty tuple of footprints")
        if any(not isinstance(r, RouterFootprint) for r in self.routers):
            raise ValueError("routers must be RouterFootprint instances")
        if len({r.router_id for r in self.routers}) != len(self.routers):
            raise ValueError("duplicate router footprint")
        object.__setattr__(
            self, "routers", tuple(sorted(self.routers, key=lambda r: r.router_id)))
        if not isinstance(self.keepouts, tuple):
            raise ValueError("keepouts must be a tuple")
        if any(not isinstance(k, Keepout) for k in self.keepouts):
            raise ValueError("keepouts must be Keepout instances")
        if len({k.keepout_id for k in self.keepouts}) != len(self.keepouts):
            raise ValueError("duplicate keepout id")
        if not isinstance(self.wire, WireModel):
            raise ValueError("wire must be a WireModel")
        for index, footprint in enumerate(self.routers):
            self._check_inside(footprint, "router footprint")
            for other in self.routers[:index]:
                if self._overlap(footprint, other):
                    raise ValueError(
                        f"router footprints {footprint.router_id} and "
                        f"{other.router_id} overlap")
        for index, keepout in enumerate(self.keepouts):
            self._check_inside(keepout, "keepout")
            for other in self.keepouts[:index]:
                if keepout.overlaps(other):
                    raise ValueError(
                        f"keepouts {keepout.keepout_id} and "
                        f"{other.keepout_id} overlap")
            for footprint in self.routers:
                if self._overlap(keepout, footprint):
                    raise ValueError(
                        f"keepout {keepout.keepout_id} overlaps router "
                        f"footprint {footprint.router_id}")

    def _check_inside(self, rect: Any, what: str) -> None:
        if (rect.x_um + rect.width_um > self.die_width_um
                or rect.y_um + rect.height_um > self.die_height_um):
            raise ValueError(f"{what} exceeds the die outline")

    @staticmethod
    def _overlap(a: Any, b: Any) -> bool:
        return (a.x_um < b.x_um + b.width_um
                and b.x_um < a.x_um + a.width_um
                and a.y_um < b.y_um + b.height_um
                and b.y_um < a.y_um + a.height_um)

    @property
    def die_area_um2(self) -> int:
        return self.die_width_um * self.die_height_um

    @property
    def router_area_um2(self) -> int:
        return sum(r.width_um * r.height_um for r in self.routers)

    @property
    def keepout_area_um2(self) -> int:
        return sum(k.width_um * k.height_um for k in self.keepouts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": ARTIFACT_TYPE,
            "schema_version": SCHEMA_VERSION,
            "topology_hash": self.topology_hash,
            "die_width_um": self.die_width_um,
            "die_height_um": self.die_height_um,
            "routers": [r.to_dict() for r in self.routers],
            "keepouts": [k.to_dict() for k in self.keepouts],
            "wire": self.wire.to_dict(),
            "scope": SCOPE,
        }

    def artifact_id(self) -> str:
        body = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, document: Any) -> "Floorplan":
        d = _exact_keys(document, _KEYS, "floorplan")
        if d["type"] != ARTIFACT_TYPE or d["schema_version"] != SCHEMA_VERSION:
            raise ValueError(
                f"floorplan must be {ARTIFACT_TYPE} v{SCHEMA_VERSION}")
        if d["scope"] != SCOPE:
            raise ValueError(f"floorplan scope must be {SCOPE!r}")
        if not isinstance(d["routers"], list):
            raise ValueError("routers must be a list")
        if not isinstance(d["keepouts"], list):
            raise ValueError("keepouts must be a list")
        wire = _exact_keys(d["wire"], _WIRE_KEYS, "wire")
        return cls(
            topology_hash=d["topology_hash"],
            die_width_um=d["die_width_um"],
            die_height_um=d["die_height_um"],
            routers=tuple(RouterFootprint(**r) for r in d["routers"]),
            keepouts=tuple(Keepout(**_exact_keys(k, _KEEPOUT_KEYS, "keepout"))
                           for k in d["keepouts"]),
            wire=WireModel(**wire),
        )


def from_grid(topology: dict[str, Any], spec: dict[str, Any]) -> Floorplan:
    """Generate a regular footprint grid from the topology's own coordinates.

    This is a declared layout rule — origin, pitch, footprint, margin — not a
    placer. Every router coordinate becomes one footprint, so the result is
    reproducible from the topology identity alone.
    """
    s = _exact_keys(spec, _GRID_KEYS, "grid")
    origin_x = _non_negative_int("origin_x_um", s["origin_x_um"])
    origin_y = _non_negative_int("origin_y_um", s["origin_y_um"])
    pitch_x = _positive_int("pitch_x_um", s["pitch_x_um"])
    pitch_y = _positive_int("pitch_y_um", s["pitch_y_um"])
    width = _positive_int("router_width_um", s["router_width_um"])
    height = _positive_int("router_height_um", s["router_height_um"])
    margin = _non_negative_int("margin_um", s["margin_um"])
    if pitch_x < width or pitch_y < height:
        raise ValueError("pitch must be at least the router footprint")
    wire = WireModel(**_exact_keys(s["wire"], _WIRE_KEYS, "wire"))

    routers = topology.get("routers") if isinstance(topology, dict) else None
    if not isinstance(routers, list) or not routers:
        raise ValueError("topology declares no routers")
    footprints: list[RouterFootprint] = []
    seen: set[tuple[int, int]] = set()
    for router in routers:
        coordinates = router.get("coordinates")
        if (not isinstance(coordinates, list) or len(coordinates) != 2
                or any(type(c) is not int or c < 0 for c in coordinates)):
            raise ValueError(
                f"router {router.get('router_id')!r} has no two-coordinate "
                "position, so a grid floorplan cannot place it")
        column, row = coordinates
        if (column, row) in seen:
            raise ValueError(f"two routers share coordinate ({column}, {row})")
        seen.add((column, row))
        footprints.append(RouterFootprint(
            router_id=router["router_id"],
            x_um=origin_x + column * pitch_x,
            y_um=origin_y + row * pitch_y,
            width_um=width,
            height_um=height))
    die_width = max(f.x_um + f.width_um for f in footprints) + margin
    die_height = max(f.y_um + f.height_um for f in footprints) + margin
    return Floorplan(
        topology_hash=_identity(topology.get("topology_hash")),
        die_width_um=die_width,
        die_height_um=die_height,
        routers=tuple(footprints),
        keepouts=(),
        wire=wire,
    )


def _statistics(values: list[Fraction]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    total = sum(values, Fraction(0))
    return {
        "count": len(values),
        "min": round(float(min(values)), 3),
        "mean": round(float(total / len(values)), 3),
        "max": round(float(max(values)), 3),
    }


def _validate_topology_binding(topology: dict[str, Any],
                               floorplan: Floorplan) -> None:
    if not isinstance(topology, dict):
        raise ValueError("topology must be an object")
    if floorplan.topology_hash != topology.get("topology_hash"):
        raise ValueError("floorplan belongs to a different topology")
    routers = {r["router_id"]: r for r in topology.get("routers") or []}
    if set(routers) != {r.router_id for r in floorplan.routers}:
        raise ValueError("floorplan must cover exactly the topology routers")


def _channel_lengths(topology: dict[str, Any],
                     floorplan: Floorplan) -> list[tuple[int, int, Fraction]]:
    """Manhattan centre-to-centre length per directed channel (um, exact).

    Formula: length = (|2*x1 + w1 - 2*x2 - w2| + |2*y1 + h1 - 2*y2 - h2|) / 2
    where (x1, y1, w1, h1) and (x2, y2, w2, h2) are the two footprints.
    """
    by_id = {r.router_id: r for r in floorplan.routers}
    rows: list[tuple[int, int, Fraction]] = []
    for channel in topology.get("channels") or []:
        source = by_id.get(channel.get("src_router"))
        destination = by_id.get(channel.get("dst_router"))
        if source is None or destination is None:
            raise ValueError("channel names a router without a footprint")
        rows.append((source.router_id, destination.router_id, Fraction(
            abs(2 * source.x_um + source.width_um
                - 2 * destination.x_um - destination.width_um)
            + abs(2 * source.y_um + source.height_um
                  - 2 * destination.y_um - destination.height_um), 2)))
    return rows


def derive(topology: dict[str, Any], floorplan: Floorplan) -> dict[str, Any]:
    """Area, utilization and declared link delay from the authored geometry."""
    _validate_topology_binding(topology, floorplan)
    lengths = [length for _src, _dst, length in _channel_lengths(
        topology, floorplan)]
    delays = [floorplan.wire.delay_ps(length) for length in lengths]
    length_stats = _statistics(lengths)
    delay_stats = _statistics(delays)
    return {
        "scope": SCOPE,
        "topology_hash": floorplan.topology_hash,
        "die": {
            "width_um": floorplan.die_width_um,
            "height_um": floorplan.die_height_um,
            "area_um2": floorplan.die_area_um2,
        },
        "routers": {
            "count": len(floorplan.routers),
            "area_um2": floorplan.router_area_um2,
            "utilization": round(
                floorplan.router_area_um2 / floorplan.die_area_um2, 6),
        },
        "keepouts": {
            "count": len(floorplan.keepouts),
            "area_um2": floorplan.keepout_area_um2,
        },
        "links": {
            "channels": length_stats["count"],
            "length_um": {k: length_stats[k] for k in ("min", "mean", "max")},
            "delay_ps": {k: delay_stats[k] for k in ("min", "mean", "max")},
        },
        "wire": floorplan.wire.to_dict(),
        "physical_estimates": estimate_planning(topology, floorplan),
    }


#: Planning-estimator scope. Every number in :func:`estimate_planning` is a
#: geometric planning estimate derived from the authored floorplan, never a
#: routed, parasitic-extracted, STA or CTS result.
PLANNING_SCOPE = "PLANNING_ESTIMATES_ONLY"

#: Typed NOT_RUN reason for STA/CTS quantities. STA requires Liberty cell
#: timing, a PDK and a timing engine (OpenSTA); CTS requires a vendor
#: clock-tree synthesizer. None is available in this environment, so these
#: are emitted as typed NOT_RUN rows rather than invented numbers.
STA_CTS_NOT_RUN_REASON = "no Liberty/PDK/OpenSTA in this environment"


def _router_centre(footprint) -> tuple[Fraction, Fraction]:
    return (Fraction(2 * footprint.x_um + footprint.width_um, 2),
            Fraction(2 * footprint.y_um + footprint.height_um, 2))


def _congestion_estimate(topology: dict[str, Any],
                         floorplan: Floorplan,
                         channels: list[tuple[int, int, Fraction]]) -> dict[str, Any]:
    """Per-macro HPWL load and per-region die-area density.

    Formulas (planning estimate only — no router has been routed):

    * Net HPWL for one directed channel (two terminals) is the half-perimeter
      of the bounding box of its terminal centres, which for two terminals
      equals their Manhattan distance:
      ``HPWL_net = |cx1 - cx2| + |cy1 - cy2|`` (um).
    * Per-macro load for router R:
      ``load(R) = sum(HPWL_net for nets incident to R) / (2*(w_R + h_R))``
      where ``(w_R, h_R)`` is R's footprint. The ratio is dimensionless:
      total incident wirelength per unit of macro perimeter. Higher means
      more wire is squeezed against the same perimeter (a congestion proxy,
      not a routed overflow count).
    * Die-area density per region: the die is split into ``side x side``
      equal regions with ``side = ceil(sqrt(n_routers))``; each router is
      assigned to the region holding its centre. ``density = router_area /
      region_area`` for that region (router area only; keepouts are not
      macros).
    """
    by_id = {r.router_id: r for r in floorplan.routers}
    incident: dict[int, list[Fraction]] = {rid: [] for rid in by_id}
    for src, dst, length in channels:
        incident[src].append(length)
        incident[dst].append(length)
    per_router: list[dict[str, Any]] = []
    loads: list[Fraction] = []
    for rid in sorted(by_id):
        footprint = by_id[rid]
        perimeter = 2 * (footprint.width_um + footprint.height_um)
        total = sum(incident[rid], Fraction(0))
        load = total / perimeter if perimeter else Fraction(0)
        loads.append(load)
        per_router.append({
            "router_id": rid,
            "incident_channels": len(incident[rid]),
            "incident_hpwl_um": round(float(total), 3),
            "load": round(float(load), 6),
        })
    side = max(1, math.ceil(math.sqrt(len(floorplan.routers))))
    region_w = Fraction(floorplan.die_width_um, side)
    region_h = Fraction(floorplan.die_height_um, side)
    region_area = region_w * region_h
    regions: list[dict[str, Any]] = []
    for row in range(side):
        for col in range(side):
            area = Fraction(0)
            for rid in sorted(by_id):
                cx, cy = _router_centre(by_id[rid])
                if (cx // region_w == col and cy // region_h == row):
                    area += by_id[rid].width_um * by_id[rid].height_um
            density = area / region_area if region_area else Fraction(0)
            regions.append({
                "region": [row, col],
                "area_um2": round(float(region_area), 3),
                "router_area_um2": round(float(area), 3),
                "density": round(float(density), 6),
            })
    return {
        "formula": ("HPWL_net = |cx1-cx2| + |cy1-cy2|; "
                    "load(R) = sum(incident HPWL) / (2*(w_R+h_R)); "
                    "density = router area / region area with "
                    "side = ceil(sqrt(n_routers)) regions "
                    "and centre-assigned routers"),
        "hpwl_stats_um": _statistics([length for _s, _d, length in channels]),
        "per_router": per_router,
        "load_stats": {
            "min": round(float(min(loads)), 6) if loads else None,
            "mean": round(float(sum(loads, Fraction(0)) / len(loads)), 6)
            if loads else None,
            "max": round(float(max(loads)), 6) if loads else None,
        },
        "density_by_region": regions,
        "max_density": max(region["density"] for region in regions)
        if regions else None,
    }


def _wire_delay_by_plane(topology: dict[str, Any],
                         floorplan: Floorplan,
                         channels: list[tuple[int, int, Fraction]]) -> dict[str, Any]:
    """Wire delay per plane: delay = length_um * ps_per_mm / 1000 + fixed_ps.

    The formula is the declared first-order model in :class:`WireModel`
    (``WireModel.delay_ps``); this estimator only surfaces min/mean/max of
    that model per topology plane. The topology artifact carries no
    per-channel plane attribution, so a single declared plane owns every
    channel; multiple declared planes cannot be split honestly.
    """
    delays = [floorplan.wire.delay_ps(length) for _s, _d, length in channels]
    overall = {
        "count": len(delays),
        "delay_ps": _statistics(delays),
        "length_um": _statistics([length for _s, _d, length in channels]),
    }
    formula = ("delay_ps = length_um * ps_per_mm / 1000 + fixed_ps "
               "(WireModel.delay_ps); per-plane min/mean/max are the "
               "declared-model statistics over that plane's channels")
    planes = topology.get("planes")
    if not planes:
        return {
            "status": "NOT_RUN",
            "formula": formula,
            "reason": "topology declares no planes, so no per-plane wire "
                      "delay split exists (channels carry no plane "
                      "attribution)",
            "overall": overall,
        }
    if len(planes) != 1:
        return {
            "status": "NOT_RUN",
            "formula": formula,
            "reason": f"topology declares {len(planes)} planes "
                      f"{list(planes)} but channels carry no plane "
                      "attribution, so a per-plane delay split would be "
                      "invented; overall stats below are the full channel set",
            "overall": overall,
        }
    stats = dict(overall)
    stats["status"] = "ESTIMATED"
    return {"status": "ESTIMATED", "formula": formula,
            "by_plane": {str(planes[0]): stats}, "overall": overall}


def _clock_tree_estimate(topology: dict[str, Any],
                         floorplan: Floorplan,
                         clock_domains: dict[int, str] | None) -> dict[str, Any]:
    """Manhattan die-far-point per clock domain (planning estimate, not CTS).

    Formulas (planning estimate only — nothing has been clock-tree
    synthesized):

    * Domain members: routers attached to endpoints of one clock domain. The
      topology artifact has no clock-domain attribute, so without an explicit
      ``clock_domains`` map the domain of a router is the ``group_index``
      of its attached endpoint(s) — a surrogate grouping, labelled as such.
      Routers with no endpoint form singleton domains of their own.
    * FAR-POINT per domain (the reported distance): the longest Manhattan
      run from any die corner to any member centre,
      ``max(|cx - X| + |cy - Y|)`` over members and corners (X, Y). This
      bounds the worst-case clock spine length reaching that domain.
    * CENTRE distance (reported for context): the same maximum but from the
      die centre (die_width/2, die_height/2), i.e. a centre-rooted spine.

    Skew is NOT estimated here: no tree exists, so there is nothing to
    measure skew on. See the sibling CTS skew NOT_RUN row.
    """
    by_id = {r.router_id: r for r in floorplan.routers}
    if clock_domains is not None:
        if set(clock_domains) != set(by_id):
            raise ValueError(
                "clock_domains must cover exactly the floorplan routers")
        domains: dict[str, list[int]] = {}
        for rid, name in sorted(clock_domains.items()):
            if not isinstance(name, str) or not name:
                raise ValueError(
                    "clock domain names must be non-empty strings")
            domains.setdefault(name, []).append(rid)
        surrogate = False
    else:
        domains = {}
        attached: set[int] = set()
        for endpoint in topology.get("endpoints") or []:
            rid = endpoint.get("router_id")
            if rid not in by_id:
                continue
            group = endpoint.get("group_index")
            name = (str(group) if group is not None
                    else f"unattached:R{rid}")
            domains.setdefault(name, []).append(rid)
            attached.add(rid)
        for rid in sorted(by_id):
            if rid not in attached:
                domains.setdefault(f"unattached:R{rid}", []).append(rid)
        surrogate = True
    corners = ((0, 0), (floorplan.die_width_um, 0),
               (0, floorplan.die_height_um),
               (floorplan.die_width_um, floorplan.die_height_um))
    die_cx = Fraction(floorplan.die_width_um, 2)
    die_cy = Fraction(floorplan.die_height_um, 2)
    rows: list[dict[str, Any]] = []
    for name in sorted(domains):
        members = sorted(set(domains[name]))
        far_point = Fraction(0)
        centre_dist = Fraction(0)
        for rid in members:
            cx, cy = _router_centre(by_id[rid])
            for corner_x, corner_y in corners:
                far_point = max(far_point, abs(cx - corner_x)
                                + abs(cy - corner_y))
            centre_dist = max(centre_dist,
                              abs(cx - die_cx) + abs(cy - die_cy))
        rows.append({
            "domain": name,
            "members": members,
            "far_point_um": round(float(far_point), 3),
            "centre_distance_um": round(float(centre_dist), 3),
        })
    return {
        "formula": ("far_point = max over members and die corners of "
                    "|cx - X| + |cy - Y|; centre_distance = the same "
                    "maximum from the die centre"),
        "domain_source": ("endpoint group_index (surrogate grouping; the "
                          "topology artifact carries no clock-domain "
                          "attribute)"
                          if surrogate else "explicit clock_domains map"),
        "domains": rows,
    }


def estimate_planning(topology: dict[str, Any],
                      floorplan: Floorplan,
                      *, clock_domains: dict[int, str] | None = None
                      ) -> dict[str, Any]:
    """Planning estimates from the authored floorplan + topology.

    Every number here is a planning estimate only: congestion is a geometric
    HPWL load (nothing is routed), wire delay is the declared first-order
    ps/mm model, clock-tree distance is a Manhattan far-point bound (no
    clock tree is synthesized). STA slack and CTS skew cannot be estimated
    without Liberty/PDK/OpenSTA and are emitted as typed NOT_RUN rows
    (``slack_estimate`` / ``cts_skew_estimate``), never as zeros.

    Deterministic and hash-stable: same inputs -> same output.
    """
    _validate_topology_binding(topology, floorplan)
    channels = _channel_lengths(topology, floorplan)
    return {
        "scope": PLANNING_SCOPE,
        "topology_hash": floorplan.topology_hash,
        "congestion": _congestion_estimate(topology, floorplan, channels),
        "wire_delay_by_plane": _wire_delay_by_plane(topology, floorplan,
                                                    channels),
        "clock_tree": _clock_tree_estimate(topology, floorplan,
                                           clock_domains),
        "slack_estimate": {
            "status": "NOT_RUN",
            "reason": STA_CTS_NOT_RUN_REASON,
            "estimate_ps": None,
        },
        "cts_skew_estimate": {
            "status": "NOT_RUN",
            "reason": STA_CTS_NOT_RUN_REASON,
            "estimate_ps": None,
        },
        "assumptions": [
            "planning estimate only — congestion: HPWL loads and region "
            "density are geometric proxies; no routing, DRC or overflow "
            "analysis has been run.",
            "planning estimate only — wire delay: length * ps/mm + fixed "
            "from the declared wire model; not extracted parasitics.",
            "planning estimate only — clock-tree distance: Manhattan "
            "far-point bounds per domain; explicitly NOT a CTS result "
            "(no clock tree has been synthesized, no skew is claimed).",
        ],
    }
