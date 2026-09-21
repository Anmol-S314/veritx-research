from dataclasses import dataclass


@dataclass(frozen=True)
class Comparison:
    metric:str
    values:tuple
    @classmethod
    def create(cls,metric,values): return cls(metric,tuple(sorted(values.items())))
