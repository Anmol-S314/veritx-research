from dataclasses import dataclass
from fractions import Fraction
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import InvalidInput

DOMAIN="veritx/performance-model/v2"


@dataclass(frozen=True)
class ResourceDef:
    name:str
    kind:str
    capacity:int=1
    bandwidth_bytes_per_s:Fraction|None=None
    def __post_init__(self):
        if not self.name: raise InvalidInput("resource name required")
        if self.kind not in {"EXCLUSIVE","BANDWIDTH"}: raise InvalidInput("unknown resource kind")
        if self.capacity<=0: raise InvalidInput("capacity must be positive")
        if self.kind=="BANDWIDTH" and (self.bandwidth_bytes_per_s is None or self.bandwidth_bytes_per_s<=0):
            raise InvalidInput("bandwidth resource requires rate")


@dataclass(frozen=True)
class PerformanceModel:
    resources:tuple[ResourceDef,...]
    compute_source:str="EXPLICIT_DURATION"
    memory_source:str="EXPLICIT_DURATION"
    def __post_init__(self):
        if self.compute_source!="EXPLICIT_DURATION": raise InvalidInput("unsupported compute source")
        if self.memory_source not in {"EXPLICIT_DURATION","ANALYTICAL_BANDWIDTH"}: raise InvalidInput("unsupported memory source")
        names=[r.name for r in self.resources]
        if len(names)!=len(set(names)): raise InvalidInput("duplicate resource names")
    def identity_dict(self):
        rows=[]
        for r in self.resources:
            bw=None if r.bandwidth_bytes_per_s is None else {
                "numerator":r.bandwidth_bytes_per_s.numerator,
                "denominator":r.bandwidth_bytes_per_s.denominator}
            rows.append({"name":r.name,"kind":r.kind,"capacity":r.capacity,"bandwidth":bw})
        return {"resources":rows,"compute_source":self.compute_source,"memory_source":self.memory_source}
    def performance_model_id(self): return content_id(DOMAIN,self.identity_dict())
