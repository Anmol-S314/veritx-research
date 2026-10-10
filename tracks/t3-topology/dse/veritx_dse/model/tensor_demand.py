"""Explicit immutable tensor layout and cache-policy demand; no inferred traffic.

OWNER_CACHE is executable only in the coupled reference consumer. Runtime
lowering stays in workload/application, outside the canonical compiler.
Contract: docs/TENSOR-DEMAND-CONTRACT.md.
"""
from dataclasses import dataclass, asdict

from veritx_dse.core.artifact import content_id, require_fields, require_type_tag
from veritx_dse.core.errors import InvalidInput, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.access_policy import AddressSpace
from veritx_dse.model.transaction_intent import TransactionKind

MAX_TENSORS = 64
MAX_SHARDS = 256
MAX_ACCESSES = 256
MAX_BLOCKS = 4096
MAX_REQUESTS = 65536
MAX_DEMAND_BYTES = 16 * 1024 * 1024


def _name(name, value):
    if not isinstance(value, str) or not value:
        raise InvalidInput(f"{name} must be a nonempty string")


def _hash(name, value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise InvalidInput(f"{name} must be an exact bare sha256 digest")


def _fields(d, cls):
    require_fields(d, cls.__dataclass_fields__, cls.__name__)
    if set(d) != set(cls.__dataclass_fields__):
        raise InvalidInput(f"{cls.__name__} is missing required fields")


def _enum(cls, value):
    try:
        return cls(value)
    except (ValueError, TypeError) as exc:
        raise InvalidInput(f"invalid {cls.__name__}") from exc


@dataclass(frozen=True)
class TensorShard:
    shard_id: str
    offset_bytes: int
    size_bytes: int
    target: int
    address_space: AddressSpace
    base_address: int
    transaction_bytes: int

    def __post_init__(self):
        _name("shard_id", self.shard_id)
        for name in ("offset_bytes", "target", "base_address"):
            exact_int(name, getattr(self, name), 0)
        for name in ("size_bytes", "transaction_bytes"):
            exact_int(name, getattr(self, name), 1)
        if not isinstance(self.address_space, AddressSpace):
            raise InvalidInput("address_space must be explicit GLOBAL or LOCAL")
        if self.base_address + self.size_bytes > 1 << 64:
            raise InvalidInput("shard address overflow")
        if self.transaction_bytes > 65536:
            raise InvalidInput("transaction_bytes must be <=65536")

    def to_dict(self):
        return {**asdict(self), "address_space": self.address_space.value}

    @classmethod
    def from_dict(cls, d):
        _fields(d, cls)
        return cls(**{**d, "address_space": _enum(AddressSpace, d["address_space"])})


@dataclass(frozen=True)
class Tensor:
    tensor_id: str
    element_bytes: int
    element_count: int
    size_bytes: int
    shards: tuple[TensorShard, ...]

    def __post_init__(self):
        _name("tensor_id", self.tensor_id)
        for name in ("element_bytes", "element_count", "size_bytes"):
            exact_int(name, getattr(self, name), 1)
        if self.size_bytes != self.element_bytes * self.element_count or self.size_bytes > 1 << 64:
            raise InvalidInput("tensor size must equal element_bytes * element_count within 64 bits")
        if not isinstance(self.shards, tuple) or not self.shards or len(self.shards) > MAX_SHARDS:
            raise InvalidInput("tensor needs a bounded nonempty tuple of shards")
        if any(not isinstance(s, TensorShard) for s in self.shards):
            raise InvalidInput("shards must contain TensorShard")
        if len({s.shard_id for s in self.shards}) != len(self.shards):
            raise InvalidInput("duplicate shard id within tensor")
        end = 0
        for shard in sorted(self.shards, key=lambda s: s.offset_bytes):
            if shard.offset_bytes != end:
                raise InvalidInput("logical shards must exactly cover tensor without gaps/overlap")
            if shard.offset_bytes % self.element_bytes or shard.size_bytes % self.element_bytes:
                raise InvalidInput("logical shards must be element aligned")
            end += shard.size_bytes
        if end != self.size_bytes:
            raise InvalidInput("logical shards must exactly cover tensor size")

    def to_dict(self):
        return {"tensor_id": self.tensor_id, "element_bytes": self.element_bytes,
                "element_count": self.element_count, "size_bytes": self.size_bytes,
                "shards": [s.to_dict() for s in self.shards]}

    @classmethod
    def from_dict(cls, d):
        _fields(d, cls)
        if not isinstance(d["shards"], list) or not 1 <= len(d["shards"]) <= MAX_SHARDS:
            raise InvalidInput("shards must be a bounded nonempty list")
        return cls(**{**d, "shards": tuple(TensorShard.from_dict(s) for s in d["shards"])})


@dataclass(frozen=True)
class TensorAccess:
    access_id: str
    tensor_id: str
    issuer: int
    kind: TransactionKind
    offset_bytes: int
    block_bytes: int
    count: int
    stride_bytes: int
    deps: tuple[str, ...]
    cache_policy: str

    def __post_init__(self):
        for name in ("access_id", "tensor_id"):
            _name(name, getattr(self, name))
        for name in ("issuer", "offset_bytes"):
            exact_int(name, getattr(self, name), 0)
        for name in ("block_bytes", "count", "stride_bytes"):
            exact_int(name, getattr(self, name), 1)
        if self.count > MAX_BLOCKS or self.stride_bytes < self.block_bytes:
            raise InvalidInput("access blocks must be bounded, positive-stride and nonoverlapping")
        if not isinstance(self.kind, TransactionKind):
            raise InvalidInput("kind must be READ or WRITE")
        if self.cache_policy not in ("BYPASS", "OWNER_CACHE"):
            raise UnsupportedSemantics("cache_policy must be explicit BYPASS or OWNER_CACHE")
        if (not isinstance(self.deps, tuple) or len(self.deps) > MAX_ACCESSES
                or any(not isinstance(d, str) or not d for d in self.deps)):
            raise InvalidInput("deps must be a bounded tuple of access ids")
        if len(set(self.deps)) != len(self.deps):
            raise InvalidInput("duplicate dependency")

    def to_dict(self):
        return {**asdict(self), "kind": self.kind.value, "deps": list(self.deps)}

    @classmethod
    def from_dict(cls, d):
        _fields(d, cls)
        if not isinstance(d["deps"], list) or len(d["deps"]) > MAX_ACCESSES:
            raise InvalidInput("deps must be a bounded list")
        return cls(**{**d, "kind": _enum(TransactionKind, d["kind"]), "deps": tuple(d["deps"])})


@dataclass(frozen=True)
class TensorDemandWorkload:
    design_hash: str
    system_hash: str
    tensors: tuple[Tensor, ...]
    accesses: tuple[TensorAccess, ...]

    def __post_init__(self):
        _hash("design_hash", self.design_hash)
        _hash("system_hash", self.system_hash)
        for name, cls, limit in (("tensors", Tensor, MAX_TENSORS), ("accesses", TensorAccess, MAX_ACCESSES)):
            rows = getattr(self, name)
            if not isinstance(rows, tuple) or len(rows) > limit or any(not isinstance(r, cls) for r in rows):
                raise InvalidInput(f"{name} must be a bounded tuple of {cls.__name__}")
        tensors = {t.tensor_id: t for t in self.tensors}
        if len(tensors) != len(self.tensors):
            raise InvalidInput("duplicate tensor id")
        if sum(len(t.shards) for t in self.tensors) > MAX_SHARDS:
            raise InvalidInput("too many shards")
        physical = {}
        for tensor in self.tensors:
            for shard in tensor.shards:
                physical.setdefault((shard.target, shard.address_space), []).append(
                    (shard.base_address, shard.base_address + shard.size_bytes))
        for spans in physical.values():
            ordered = sorted(spans)
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
                raise InvalidInput("physical tensor shards must not alias/overlap")
        ids = {a.access_id for a in self.accesses}
        if len(ids) != len(self.accesses):
            raise InvalidInput("duplicate access id")
        for access in self.accesses:
            tensor = tensors.get(access.tensor_id)
            if tensor is None:
                raise InvalidInput("access references unknown tensor")
            if set(access.deps) - ids:
                raise InvalidInput("dependency references unknown access")
            if any(x % tensor.element_bytes for x in (access.offset_bytes, access.block_bytes, access.stride_bytes)):
                raise InvalidInput("access must be element aligned")
            if access.offset_bytes + (access.count - 1) * access.stride_bytes + access.block_bytes > tensor.size_bytes:
                raise InvalidInput("access exceeds tensor bounds")
        if sum(a.count for a in self.accesses) > MAX_BLOCKS:
            raise InvalidInput("too many expanded blocks")
        if sum(a.count * a.block_bytes for a in self.accesses) > MAX_DEMAND_BYTES:
            raise InvalidInput("explicit demand exceeds byte bound")
        self.topological_accesses()

    def topological_accesses(self):
        """Stable id tie-break; consumers must still honor completion dependencies."""
        remaining = {a.access_id: a for a in self.accesses}
        done, ordered = set(), []
        while remaining:
            ready = sorted(k for k, a in remaining.items() if set(a.deps) <= done)
            if not ready:
                raise InvalidInput("access dependency cycle")
            for key in ready:
                ordered.append(remaining.pop(key))
                done.add(key)
        return tuple(ordered)

    def to_dict(self):
        return {"type": "veritx/TensorDemandWorkload", "schema_version": 1,
                "design_hash": self.design_hash, "system_hash": self.system_hash,
                "tensors": [t.to_dict() for t in self.tensors],
                "accesses": [a.to_dict() for a in self.accesses]}

    def workload_id(self):
        return content_id("veritx/TensorDemandWorkload/v1", self.to_dict())

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"type", "schema_version", *cls.__dataclass_fields__}, "tensor demand")
        require_type_tag(d, "veritx/TensorDemandWorkload", "tensor demand")
        if type(d.get("schema_version")) is not int or d["schema_version"] != 1:
            raise InvalidInput("tensor demand schema_version must be exact int 1")
        if (not isinstance(d.get("tensors"), list) or len(d["tensors"]) > MAX_TENSORS
                or not isinstance(d.get("accesses"), list) or len(d["accesses"]) > MAX_ACCESSES):
            raise InvalidInput("tensors and accesses must be explicit bounded lists")
        return cls(d.get("design_hash"), d.get("system_hash"),
                   tuple(Tensor.from_dict(t) for t in d["tensors"]),
                   tuple(TensorAccess.from_dict(a) for a in d["accesses"]))
