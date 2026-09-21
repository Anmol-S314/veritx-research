from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from veritx_dse.core.artifact import content_id, require_exact_fields, require_embedded_id
from veritx_dse.core.errors import InvalidInput

DOMAIN = "veritx/parallelism/v2"


@dataclass(frozen=True)
class ParallelismArtifact:
    tp: int
    pp: int
    ep: int
    dp: int

    def __post_init__(self):
        for name in ("tp", "pp", "ep", "dp"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise InvalidInput(f"{name} must be positive int")

    @property
    def world_size(self):
        return self.tp * self.pp * self.ep * self.dp

    def rank_of(self, t, p, e, d):
        vals, bounds = (t,p,e,d), (self.tp,self.pp,self.ep,self.dp)
        if any(type(v) is not int or v < 0 or v >= b for v,b in zip(vals,bounds)):
            raise InvalidInput("parallelism coordinates out of range")
        return ((p * self.dp + d) * self.ep + e) * self.tp + t

    def coords_of(self, rank):
        if type(rank) is not int or not 0 <= rank < self.world_size:
            raise InvalidInput("rank out of range")
        t = rank % self.tp
        x = rank // self.tp
        e = x % self.ep
        x //= self.ep
        d = x % self.dp
        p = x // self.dp
        return t,p,e,d

    def identity_dict(self):
        return {"tp": self.tp, "pp": self.pp, "ep": self.ep, "dp": self.dp}

    def parallelism_id(self):
        return content_id(DOMAIN, self.identity_dict())

    def to_dict(self):
        return {
            "schema_version": 2, **self.identity_dict(),
            "world_size": self.world_size,
            "parallelism_id": self.parallelism_id()
        }

    @classmethod
    def from_dict(cls, doc: Any):
        require_exact_fields(
            doc,
            {"schema_version","tp","pp","ep","dp","world_size","parallelism_id"},
            "parallelism"
        )
        if doc["schema_version"] != 2:
            raise InvalidInput("unsupported parallelism schema")
        obj = cls(doc["tp"],doc["pp"],doc["ep"],doc["dp"])
        if doc["world_size"] != obj.world_size:
            raise InvalidInput("stored world_size is inconsistent")
        require_embedded_id(doc, "parallelism_id", obj.parallelism_id(), "parallelism")
        return obj
