from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import MappingInvalid

DOMAIN = "veritx/mapping/v2"


@dataclass(frozen=True)
class MappingArtifact:
    participant_count: int
    rank_to_endpoint: tuple[int, ...]
    fabric_id: str

    def __post_init__(self):
        if type(self.participant_count) is not int or self.participant_count <= 0:
            raise MappingInvalid("participant_count must be positive")
        if len(self.rank_to_endpoint) != self.participant_count:
            raise MappingInvalid("mapping cardinality must equal participant_count")
        if len(set(self.rank_to_endpoint)) != len(self.rank_to_endpoint):
            raise MappingInvalid("one endpoint per participant required")
        if any(type(x) is not int or x < 0 for x in self.rank_to_endpoint):
            raise MappingInvalid("invalid endpoint")
        if not self.fabric_id:
            raise MappingInvalid("fabric_id required")

    def endpoint_for(self, rank):
        if type(rank) is not int or not 0 <= rank < self.participant_count:
            raise MappingInvalid("participant rank out of range")
        return self.rank_to_endpoint[rank]

    def identity_dict(self):
        return {
            "participant_count": self.participant_count,
            "rank_to_endpoint": list(self.rank_to_endpoint),
            "fabric_id": self.fabric_id
        }

    def mapping_id(self):
        return content_id(DOMAIN, self.identity_dict())
