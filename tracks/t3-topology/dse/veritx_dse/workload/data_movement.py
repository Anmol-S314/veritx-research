"""Explicit addressed READ/WRITE demand, not collective-to-memory inference.

READ sends control_bytes then receives the child payload. WRITE sends the child
payload then receives control_bytes of acknowledgement. Service cycles are
AUTHORED per child in the target clock; no memory contents/DRAM/protocol timing
is inferred. Dependencies and operation order are semantic.
"""
from dataclasses import dataclass

from veritx_dse.core.artifact import content_id, require_fields, require_type_tag, require_schema_version
from veritx_dse.core.errors import InvalidInput
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.transaction_intent import TransactionKind


@dataclass(frozen=True)
class DataMovementOperation:
    operation_id: str
    initiator: int
    target: int
    kind: TransactionKind
    address: int
    payload_bytes: int
    control_bytes: int
    service_cycles: int
    traffic_class: str
    deps: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("operation_id", "traffic_class"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise InvalidInput(f"{name} must be a nonempty string")
        if not isinstance(self.kind, TransactionKind):
            raise InvalidInput("kind must be READ or WRITE")
        for name in ("initiator", "target", "address", "service_cycles"):
            exact_int(name, getattr(self, name), 0)
        for name in ("payload_bytes", "control_bytes"):
            exact_int(name, getattr(self, name), 1)
        if self.initiator == self.target:
            raise InvalidInput("local transactions are outside the data-movement envelope")
        if not isinstance(self.deps, tuple) or any(not isinstance(d, str) or not d for d in self.deps):
            raise InvalidInput("deps must be a tuple of operation ids")
        if len(set(self.deps)) != len(self.deps):
            raise InvalidInput("duplicate operation dependency")

    def to_dict(self):
        return {"operation_id": self.operation_id, "initiator": self.initiator,
                "target": self.target, "kind": self.kind.value, "address": self.address,
                "payload_bytes": self.payload_bytes, "control_bytes": self.control_bytes,
                "service_cycles": self.service_cycles, "traffic_class": self.traffic_class,
                "deps": list(self.deps)}

    @classmethod
    def from_dict(cls, d):
        require_fields(d, cls.__dataclass_fields__, "data-movement operation")
        if set(cls.__dataclass_fields__) - {"deps"} - set(d):
            raise InvalidInput("data-movement operation is missing required fields")
        try:
            kind = TransactionKind(d.get("kind"))
        except (TypeError, ValueError) as exc:
            raise InvalidInput("kind must be READ or WRITE") from exc
        if not isinstance(d.get("deps", []), list):
            raise InvalidInput("deps must be a list")
        return cls(**{k: v for k, v in d.items() if k not in ("kind", "deps")},
                   kind=kind, deps=tuple(d.get("deps", [])))


@dataclass(frozen=True)
class DataMovementWorkload:
    design_hash: str
    network_clock: str
    operations: tuple[DataMovementOperation, ...]

    def __post_init__(self):
        if not isinstance(self.design_hash, str) or len(self.design_hash) != 64 or any(c not in "0123456789abcdef" for c in self.design_hash):
            raise InvalidInput("workload needs the exact V5 design hash")
        if not isinstance(self.network_clock, str) or not self.network_clock:
            raise InvalidInput("network_clock must be declared")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise InvalidInput("operations must be a nonempty tuple")
        seen = set()
        for op in self.operations:
            if not isinstance(op, DataMovementOperation):
                raise InvalidInput("operations must contain DataMovementOperation")
            if op.operation_id in seen:
                raise InvalidInput("duplicate operation id")
            # Ordered demand is the authority, so forward references/cycles refuse.
            if set(op.deps) - seen:
                raise InvalidInput("dependencies must name earlier operations")
            seen.add(op.operation_id)

    def to_dict(self):
        return {"type": "veritx/DataMovementWorkload", "schema_version": 1,
                "design_hash": self.design_hash, "network_clock": self.network_clock,
                "operations": [op.to_dict() for op in self.operations]}

    def workload_id(self):
        return content_id("veritx/DataMovementWorkload/v1", self.to_dict())

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"type", "schema_version", "design_hash", "network_clock", "operations"}, "data-movement workload")
        require_type_tag(d, "veritx/DataMovementWorkload", "data-movement workload")
        if type(d.get("schema_version")) is not int:
            raise InvalidInput("schema_version must be an exact int")
        require_schema_version(d, 1, "data-movement workload")
        if not isinstance(d.get("operations"), list):
            raise InvalidInput("operations must be a list")
        return cls(d.get("design_hash"), d.get("network_clock"),
                   tuple(DataMovementOperation.from_dict(op) for op in d["operations"]))
