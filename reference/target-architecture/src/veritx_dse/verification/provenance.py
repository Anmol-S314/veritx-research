from dataclasses import dataclass
from veritx_dse.core.errors import EvidenceInvalid


@dataclass(frozen=True)
class ScientificChain:
    workload_id:str
    message_artifact_id:str
    traffic_id:str
    fabric_id:str
    mapping_id:str
    evidence_id:str
    stats_sha256:str

    def verify(self,**actual):
        if self.__dict__ != actual:
            raise EvidenceInvalid("scientific parent chain mismatch")
