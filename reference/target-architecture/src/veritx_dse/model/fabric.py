from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import InvalidInput

DOMAIN = "veritx/fabric/v2"


@dataclass(frozen=True)
class FabricSpec:
    endpoints: int
    topology: str
    link_width_bits: int
    flit_bits: int

    def __post_init__(self):
        if type(self.endpoints) is not int or self.endpoints <= 0:
            raise InvalidInput("endpoints must be positive")
        if self.topology not in {"MESH","TORUS","CUSTOM"}:
            raise InvalidInput("unsupported topology")
        if self.link_width_bits <= 0 or self.flit_bits <= 0:
            raise InvalidInput("link/flit widths must be positive")

    def identity_dict(self):
        return {
            "endpoints": self.endpoints,
            "topology": self.topology,
            "link_width_bits": self.link_width_bits,
            "flit_bits": self.flit_bits
        }

    def fabric_id(self):
        return content_id(DOMAIN, self.identity_dict())
