from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import InvalidInput

DOMAIN="veritx/optimization-definition/v2"


@dataclass(frozen=True)
class Parameter:
    name:str
    values:tuple[int|str,...]
    def __post_init__(self):
        if not self.name or not self.values: raise InvalidInput("parameter name/values required")


@dataclass(frozen=True)
class Objective:
    metric:str
    direction:str
    def __post_init__(self):
        if self.direction not in {"MIN","MAX"}: raise InvalidInput("direction must be MIN or MAX")


@dataclass(frozen=True)
class OptimizationDefinition:
    parameters:tuple[Parameter,...]
    objectives:tuple[Objective,...]
    def __post_init__(self):
        names=[p.name for p in self.parameters]
        if len(names)!=len(set(names)): raise InvalidInput("duplicate parameter names")
        if not self.objectives: raise InvalidInput("objective required")
    def definition_id(self):
        return content_id(DOMAIN,{
            "parameters":[{"name":p.name,"values":list(p.values)} for p in self.parameters],
            "objectives":[o.__dict__ for o in self.objectives]
        })
