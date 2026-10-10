"""Explicit finite reference compute/access DAG, byte image and value contracts."""
from dataclasses import dataclass, asdict

from veritx_dse.core.artifact import content_id, require_fields
from veritx_dse.core.errors import InvalidInput, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.tensor_demand import TensorDemandWorkload, _name


def fields(doc, names, label):
    require_fields(doc, names, label)
    if set(doc) != set(names):
        raise InvalidInput(f"{label} requires exactly {sorted(names)}")


def hex_bytes(value, label):
    if not isinstance(value, str) or len(value) % 2 or any(c not in "0123456789abcdef" for c in value):
        raise InvalidInput(f"{label} must be canonical lowercase byte hex")
    return bytes.fromhex(value)


@dataclass(frozen=True)
class ComputeEngine:
    engine_id: str
    clock: str
    capacity: int

    def __post_init__(self):
        _name("engine_id", self.engine_id)
        _name("clock", self.clock)
        exact_int("capacity", self.capacity, 1)
        if self.capacity > 256:
            raise InvalidInput("engine capacity exceeds 256")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, doc):
        fields(doc, cls.__dataclass_fields__, "compute engine")
        return cls(**doc)


@dataclass(frozen=True)
class CoupledNode:
    node_id: str
    kind: str
    deps: tuple[str, ...]
    access_id: str | None = None
    engine_id: str | None = None
    cycles: int | None = None
    occupancy: int | None = None
    retry_of: str | None = None
    reset_clock: str | None = None

    def __post_init__(self):
        _name("node_id", self.node_id)
        if self.kind not in ("ACCESS", "COMPUTE", "BARRIER", "DRAIN_RESET"):
            raise UnsupportedSemantics("node kind requires ACCESS, COMPUTE, BARRIER or DRAIN_RESET")
        if not isinstance(self.deps, tuple) or any(not isinstance(d, str) or not d for d in self.deps) or len(set(self.deps)) != len(self.deps):
            raise InvalidInput("node deps must be unique explicit node ids")
        if self.kind == "ACCESS":
            _name("access_id", self.access_id)
        elif self.access_id is not None:
            raise InvalidInput("only ACCESS may declare access_id")
        if self.retry_of is not None:
            if self.kind != "ACCESS":
                raise InvalidInput("only ACCESS may declare retry_of")
            _name("retry_of", self.retry_of)
        if self.kind == "COMPUTE":
            _name("engine_id", self.engine_id)
            exact_int("cycles", self.cycles, 0)
            exact_int("occupancy", self.occupancy, 1)
        elif self.kind == "DRAIN_RESET":
            _name("reset_clock", self.reset_clock)
            exact_int("reset cycles", self.cycles, 0)
            if self.engine_id is not None or self.occupancy is not None:
                raise InvalidInput("reset cannot reserve compute occupancy")
        elif any(v is not None for v in (self.engine_id, self.cycles, self.occupancy)):
            raise InvalidInput("only COMPUTE/RESET may declare execution cycles")
        if self.kind != "DRAIN_RESET" and self.reset_clock is not None:
            raise InvalidInput("only DRAIN_RESET may declare reset_clock")

    def to_dict(self):
        return {k: list(v) if k == "deps" else v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, doc):
        require_fields(doc, cls.__dataclass_fields__, "coupled node")
        kind = doc.get("kind")
        names = {"node_id", "kind", "deps"}
        names |= {"access_id"} if kind == "ACCESS" else {"engine_id", "cycles", "occupancy"} if kind == "COMPUTE" else {"reset_clock", "cycles"} if kind == "DRAIN_RESET" else set()
        if kind == "ACCESS" and "retry_of" in doc:
            names.add("retry_of")
        fields(doc, names, "coupled node")
        if not isinstance(doc["deps"], list):
            raise InvalidInput("node deps must be a list")
        return cls(**{**doc, "deps": tuple(doc["deps"])})


def ancestors(deps):
    result = {}
    remaining = set(deps)
    while remaining:
        ready = sorted(n for n in remaining if deps[n] <= result.keys())
        if not ready:
            raise InvalidInput("coupled dependency cycle")
        for n in ready:
            result[n] = set(deps[n]).union(*(result[d] for d in deps[n]))
            remaining.remove(n)
    return result


@dataclass(frozen=True)
class OwnerCacheProfile:
    line_bytes: int
    capacity_bytes: int
    lookup_cycles: int
    line_fill_service_cycles: int

    def __post_init__(self):
        exact_int("line_bytes", self.line_bytes, 1)
        exact_int("capacity_bytes", self.capacity_bytes, 1)
        exact_int("lookup_cycles", self.lookup_cycles, 0)
        exact_int("line_fill_service_cycles", self.line_fill_service_cycles, 1)
        if self.line_bytes & (self.line_bytes - 1):
            raise InvalidInput("cache line_bytes must be a power of two")
        if self.capacity_bytes % self.line_bytes:
            raise InvalidInput("cache capacity_bytes must be a multiple of line_bytes")
        if self.capacity_bytes > 16 * 1024 * 1024 or self.capacity_bytes // self.line_bytes > 65536:
            raise InvalidInput("owner cache exceeds bounded capacity")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, doc):
        fields(doc, cls.__dataclass_fields__, "owner cache profile")
        return cls(**doc)


@dataclass(frozen=True)
class CoupledTensorWorkload:
    demand: TensorDemandWorkload
    engines: tuple[ComputeEngine, ...]
    nodes: tuple[CoupledNode, ...]
    initial_images: tuple[tuple[str, str], ...]
    access_values: tuple[tuple[str, str], ...]
    horizon_cycles: int
    horizon_clock: str
    cache_profile: OwnerCacheProfile | None = None

    def __post_init__(self):
        if not isinstance(self.demand, TensorDemandWorkload):
            raise InvalidInput("explicit tensor demand is required")
        if self.cache_profile is not None and not isinstance(self.cache_profile, OwnerCacheProfile):
            raise InvalidInput("cache_profile must be an explicit OwnerCacheProfile")
        cached = [a for a in self.demand.accesses if a.cache_policy == "OWNER_CACHE"]
        if cached and self.cache_profile is None:
            raise InvalidInput("OWNER_CACHE accesses require cache_profile")
        if self.cache_profile is not None and not cached:
            raise InvalidInput("cache_profile requires at least one OWNER_CACHE access")
        exact_int("horizon_cycles", self.horizon_cycles, 1)
        _name("horizon_clock", self.horizon_clock)
        for name, cls, maximum in (("engines", ComputeEngine, 64), ("nodes", CoupledNode, 512)):
            value = getattr(self, name)
            if not isinstance(value, tuple) or len(value) > maximum or any(not isinstance(v, cls) for v in value):
                raise InvalidInput(f"{name} must be a bounded typed tuple")
        engines = {e.engine_id: e for e in self.engines}
        nodes = {n.node_id: n for n in self.nodes}
        if len(engines) != len(self.engines) or len(nodes) != len(self.nodes):
            raise InvalidInput("duplicate engine/node id")
        accesses = {a.access_id: a for a in self.demand.accesses}
        access_nodes = [n.access_id for n in self.nodes if n.kind == "ACCESS"]
        if set(access_nodes) != set(accesses) or len(set(access_nodes)) != len(access_nodes):
            raise InvalidInput("each access must have exactly one ACCESS node")
        for n in self.nodes:
            if set(n.deps) - nodes.keys():
                raise InvalidInput("unknown node dependency")
            if n.kind == "COMPUTE" and (n.engine_id not in engines or n.occupancy > engines[n.engine_id].capacity):
                raise InvalidInput("compute requires known engine and feasible occupancy")
        self.dependency_ancestors()
        for name, expected in (("initial_images", {t.tensor_id: t.size_bytes for t in self.demand.tensors}),
                               ("access_values", {a.access_id: a.count*a.block_bytes for a in self.demand.accesses})):
            rows = getattr(self, name)
            if not isinstance(rows, tuple) or any(not isinstance(r, tuple) or len(r) != 2
                    or not isinstance(r[0], str) or not isinstance(r[1], str) for r in rows):
                raise InvalidInput(f"{name} requires tuple pairs")
            if len({r[0] for r in rows}) != len(rows) or {r[0] for r in rows} != set(expected):
                raise InvalidInput(f"{name} must cover every declared identity exactly once")
            if sum(expected.values()) > 16*1024*1024:
                raise InvalidInput(f"{name} exceeds 16 MiB")
            for key, value in rows:
                if len(value) != 2*expected[key] or len(hex_bytes(value, name)) != expected[key]:
                    raise InvalidInput(f"{name} byte extent mismatch")

    def dependency_ancestors(self, extra=None):
        deps = {n.node_id: set(n.deps) for n in self.nodes}
        access_nodes = {n.access_id: n.node_id for n in self.nodes if n.kind == "ACCESS"}
        for a in self.demand.accesses:
            deps[access_nodes[a.access_id]].update(access_nodes[d] for d in a.deps)
        for node, more in (extra or {}).items():
            deps[node].update(more)
        return deps, ancestors(deps)

    def to_dict(self):
        return {"type": "veritx/CoupledTensorWorkload", "schema_version": 1,
                "demand": self.demand.to_dict(), "engines": [e.to_dict() for e in self.engines],
                "nodes": [n.to_dict() for n in self.nodes],
                "initial_images": dict(self.initial_images), "access_values": dict(self.access_values),
                "horizon_cycles": self.horizon_cycles, "horizon_clock": self.horizon_clock,
                **({"cache_profile": self.cache_profile.to_dict()} if self.cache_profile else {})}

    def workload_id(self):
        return content_id("veritx/CoupledTensorWorkload/v1", self.to_dict())

    @classmethod
    def from_dict(cls, doc):
        required = {"type", "schema_version", *(set(cls.__dataclass_fields__) - {"cache_profile"})}
        require_fields(doc, required | {"cache_profile"}, "coupled workload")
        if set(doc) not in (required, required | {"cache_profile"}):
            raise InvalidInput("coupled workload has unknown fields")
        if doc["type"] != "veritx/CoupledTensorWorkload" or type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
            raise InvalidInput("unknown coupled workload schema")
        for name, bound in (("engines", 64), ("nodes", 512)):
            if not isinstance(doc[name], list) or len(doc[name]) > bound:
                raise InvalidInput(f"{name} must be bounded list")
        for name in ("initial_images", "access_values"):
            if not isinstance(doc[name], dict):
                raise InvalidInput(f"{name} must be an object")
        return cls(TensorDemandWorkload.from_dict(doc["demand"]),
                   tuple(ComputeEngine.from_dict(e) for e in doc["engines"]),
                   tuple(CoupledNode.from_dict(n) for n in doc["nodes"]),
                   tuple(sorted(doc["initial_images"].items())), tuple(sorted(doc["access_values"].items())),
                   doc["horizon_cycles"], doc["horizon_clock"],
                   OwnerCacheProfile.from_dict(doc["cache_profile"]) if "cache_profile" in doc else None)
