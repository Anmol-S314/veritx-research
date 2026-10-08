"""Authored non-overlapping router footprints and Manhattan wire estimates.

Integer micrometres, topology-bound. This is a geometric model, not placement
optimization, routing, PPA, extracted delay or OpenROAD/signoff evidence.
"""
from dataclasses import dataclass
from fractions import Fraction

from veritx_dse.core.artifact import content_id, require_fields, require_type_tag, require_schema_version
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid
from veritx_dse.model.resource_graph import exact_int


@dataclass(frozen=True)
class RouterFootprint:
    router_id: int
    x_um: int
    y_um: int
    width_um: int
    height_um: int

    def __post_init__(self):
        for name in ("router_id", "x_um", "y_um"):
            exact_int(name, getattr(self, name))
        for name in ("width_um", "height_um"):
            exact_int(name, getattr(self, name), 1)

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class PhysicalPlacement:
    resource_graph_id: str
    die_width_um: int
    die_height_um: int
    routers: tuple[RouterFootprint, ...]

    def __post_init__(self):
        if not isinstance(self.resource_graph_id, str) or len(self.resource_graph_id) != 64 or any(c not in "0123456789abcdef" for c in self.resource_graph_id):
            raise InvalidInput("placement must bind a resource graph identity")
        exact_int("die_width_um", self.die_width_um, 1)
        exact_int("die_height_um", self.die_height_um, 1)
        if not isinstance(self.routers, tuple) or not self.routers or any(not isinstance(r, RouterFootprint) for r in self.routers):
            raise InvalidInput("routers must be nonempty router footprints")
        if len({r.router_id for r in self.routers}) != len(self.routers):
            raise InvalidInput("duplicate router placement")
        object.__setattr__(self, "routers", tuple(sorted(self.routers, key=lambda r: r.router_id)))
        for i, r in enumerate(self.routers):
            if r.x_um + r.width_um > self.die_width_um or r.y_um + r.height_um > self.die_height_um:
                raise InvalidInput("router footprint exceeds die bounds")
            for other in self.routers[:i]:
                if (r.x_um < other.x_um + other.width_um and other.x_um < r.x_um + r.width_um
                        and r.y_um < other.y_um + other.height_um and other.y_um < r.y_um + r.height_um):
                    raise InvalidInput("router footprints overlap")

    def validate_against(self, graph):
        if self.resource_graph_id != graph.artifact_id():
            raise EvidenceInvalid("placement belongs to a different resource graph")
        if {r.router_id for r in self.routers} != set(graph.routers):
            raise InvalidInput("placement must cover exactly the canonical routers")

    def length_um(self, source, destination):
        by_id = {r.router_id: r for r in self.routers}
        a, b = by_id[source], by_id[destination]
        return Fraction(abs(2*a.x_um + a.width_um - 2*b.x_um - b.width_um)
                        + abs(2*a.y_um + a.height_um - 2*b.y_um - b.height_um), 2)

    def to_dict(self):
        return {"type": "veritx/PhysicalPlacement", "schema_version": 1,
                "resource_graph_id": self.resource_graph_id,
                "die_width_um": self.die_width_um, "die_height_um": self.die_height_um,
                "routers": [r.to_dict() for r in self.routers],
                "scope": "AUTHORED_ROUTER_GEOMETRY_NOT_PPA"}

    def artifact_id(self):
        return content_id("veritx/PhysicalPlacement/v1", self.to_dict())

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"type", "schema_version", "resource_graph_id", "die_width_um", "die_height_um", "routers", "scope"}, "physical placement")
        require_type_tag(d, "veritx/PhysicalPlacement", "physical placement")
        if type(d.get("schema_version")) is not int:
            raise InvalidInput("schema_version must be an exact int")
        require_schema_version(d, 1, "physical placement")
        if d.get("scope") != "AUTHORED_ROUTER_GEOMETRY_NOT_PPA":
            raise InvalidInput("unsupported physical placement scope")
        if not isinstance(d.get("routers"), list):
            raise InvalidInput("routers must be a list")
        rows = []
        for row in d["routers"]:
            require_fields(row, RouterFootprint.__dataclass_fields__, "router footprint")
            if set(row) != set(RouterFootprint.__dataclass_fields__):
                raise InvalidInput("router footprint missing fields")
            rows.append(RouterFootprint(**row))
        return cls(d.get("resource_graph_id"), d.get("die_width_um"), d.get("die_height_um"), tuple(rows))
