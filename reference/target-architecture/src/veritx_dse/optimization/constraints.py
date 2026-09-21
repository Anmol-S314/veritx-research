from dataclasses import dataclass
from fractions import Fraction
from veritx_dse.core.errors import InvalidInput


@dataclass(frozen=True)
class Constraint:
    metric:str
    op:str
    threshold:Fraction
    def evaluate(self,value):
        if self.op=="<=": return value<=self.threshold
        if self.op==">=": return value>=self.threshold
        raise InvalidInput("unsupported constraint operator")
