from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import InvalidInput

DOMAIN = "veritx/memory-artifact/v2"


@dataclass(frozen=True)
class MemoryAccess:
    operation_id: str
    node: int
    kind: str
    bytes: int
    location: str

    def __post_init__(self):
        if self.kind not in {"READ","WRITE"}:
            raise InvalidInput("memory access kind must be READ or WRITE")
        if self.node < 0 or self.bytes < 0:
            raise InvalidInput("memory access values cannot be negative")


@dataclass(frozen=True)
class MemoryArtifact:
    workload_id: str
    num_nodes: int
    accesses: tuple[MemoryAccess, ...]

    def __post_init__(self):
        if self.num_nodes <= 0:
            raise InvalidInput("num_nodes must be positive")
        if any(a.node >= self.num_nodes for a in self.accesses):
            raise InvalidInput("memory access outside participant namespace")

    def identity_dict(self):
        return {
            "workload_id": self.workload_id,
            "num_nodes": self.num_nodes,
            "accesses": [a.__dict__ for a in self.accesses]
        }

    def memory_id(self):
        return content_id(DOMAIN, self.identity_dict())
