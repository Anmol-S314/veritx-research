from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from .errors import InvalidInput


@dataclass(frozen=True, order=True)
class QTime:
    q: Fraction

    def __post_init__(self):
        if self.q < 0:
            raise InvalidInput("time cannot be negative")

    @classmethod
    def seconds(cls, n: int, d: int = 1):
        if d == 0:
            raise InvalidInput("zero time denominator")
        return cls(Fraction(n, d))

    @classmethod
    def nanoseconds(cls, ns: int):
        if type(ns) is not int or ns < 0:
            raise InvalidInput("nanoseconds must be non-negative int")
        return cls(Fraction(ns, 1_000_000_000))

    def __add__(self, other):
        return QTime(self.q + other.q)

    def __sub__(self, other):
        if self.q < other.q:
            raise InvalidInput("time subtraction would be negative")
        return QTime(self.q - other.q)

    def to_dict(self):
        return {"numerator": self.q.numerator, "denominator": self.q.denominator}
