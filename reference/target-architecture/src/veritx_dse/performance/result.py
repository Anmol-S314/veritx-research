from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from .metrics import request_latencies,utilization

DOMAIN="veritx/performance-result/v2"


def _frac(q): return {"numerator":q.numerator,"denominator":q.denominator}


@dataclass(frozen=True)
class PerformanceResult:
    workload_id:str
    performance_model_id:str
    makespan:dict
    request_latencies:tuple
    utilization:tuple

    @classmethod
    def build(cls,*,workload_id,temporal_workload,model,schedule):
        lats=request_latencies(temporal_workload,schedule); util=utilization(schedule)
        return cls(workload_id,model.performance_model_id(),schedule.makespan().to_dict(),
                   tuple(sorted((k,_frac(v)) for k,v in lats.items())),
                   tuple(sorted((k,_frac(v)) for k,v in util.items())))
    def identity_dict(self):
        return {"workload_id":self.workload_id,"performance_model_id":self.performance_model_id,
                "makespan":self.makespan,"request_latencies":dict(self.request_latencies),
                "utilization":dict(self.utilization)}
    def performance_result_id(self): return content_id(DOMAIN,self.identity_dict())
