from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from .pareto import pareto_front

DOMAIN="veritx/optimization-result/v2"


@dataclass(frozen=True)
class CandidateResult:
    candidate_id:str
    metrics:tuple


@dataclass(frozen=True)
class OptimizationResult:
    definition_id:str
    candidates:tuple[CandidateResult,...]
    directions:tuple[str,...]
    def frontier(self):
        return pareto_front({c.candidate_id:c.metrics for c in self.candidates},self.directions)
    def result_id(self):
        rows=[]
        for c in self.candidates:
            rows.append({"candidate_id":c.candidate_id,
                         "metrics":[{"numerator":x.numerator,"denominator":x.denominator} for x in c.metrics]})
        return content_id(DOMAIN,{"definition_id":self.definition_id,
                                  "candidates":rows,"directions":list(self.directions),
                                  "frontier":list(self.frontier())})
