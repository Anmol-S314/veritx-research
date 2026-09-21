from dataclasses import dataclass
from veritx_dse.backend.evidence import EvidenceArtifact
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import EvidenceInvalid

DOMAIN="veritx/evaluation-result/v2"


@dataclass(frozen=True)
class EvaluationResult:
    workload_id:str
    message_artifact_id:str
    traffic_id:str
    evidence:EvidenceArtifact

    def __post_init__(self):
        if self.evidence.backend_input_id != self.traffic_id:
            raise EvidenceInvalid(
                "evidence was produced for backend input "
                f"{self.evidence.backend_input_id!r}, not traffic "
                f"{self.traffic_id!r}; a valid artifact cannot be transplanted")

    def result_id(self):
        return content_id(DOMAIN,{
            "workload_id":self.workload_id,
            "message_artifact_id":self.message_artifact_id,
            "traffic_id":self.traffic_id,
            "backend":self.evidence.backend,
            "evidence_id":self.evidence.evidence_id(),
            "backend_input_sha256":self.evidence.backend_input_sha256,
            "raw_evidence_sha256":self.evidence.raw_evidence_sha256,
            "stats_sha256":self.evidence.stats_sha256,
        })
