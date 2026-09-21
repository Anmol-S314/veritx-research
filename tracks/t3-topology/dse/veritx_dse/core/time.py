"""veritx_dse.core.time — canonical exact rational time (§12/§13/§86/§87).

Wave E never mixes GPU cycles, BookSim cycles, and seconds as if they
were interchangeable. The canonical scheduler time is an exact rational
number of **seconds** (``QTime``), serialized as numerator/denominator so
persisted artifacts stay exact. ``1 / 1.4 GHz`` is not an integer number
of picoseconds — no silent rounding enters causal scheduling.

Floats are a *reporting* concern only: ``QTime.to_float()`` exists for
human-facing summaries and is never used in identity or comparisons.
"""
from __future__ import annotations


def _freeze(self, name: str, value: object) -> None:
    raise AttributeError(
        f"{type(self).__name__} is immutable (Wave-E §11); construct a new instance instead")

from fractions import Fraction
from typing import Any


class TimeError(Exception):
    """Typed refusal for invalid time/clock/unit usage (§126).

    Self-contained like ``waved.errors``: no dependency on legacy error
    plumbing, machine-readable ``code``, never silent.
    """

    code = "INVALID_TIME"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _q(value: Fraction | int) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    raise TimeError(f"time values must be exact (int/Fraction), got "
                    f"{type(value).__name__}")


class QTime:
    """Exact rational seconds. Immutable; total order; exact arithmetic."""

    __slots__ = ("q",)

    __setattr__ = _freeze

    def __init__(self, numerator: int | Fraction,
                 denominator: int = 1) -> None:
        if isinstance(numerator, Fraction):
            if denominator != 1:
                raise TimeError(
                    "QTime(Fraction) takes no separate denominator")
            q = numerator
        else:
            # bool is an int subclass: `QTime(True)` must not silently
            # mean one second.
            if isinstance(numerator, bool) or isinstance(denominator, bool):
                raise TimeError(
                    "QTime numerator/denominator must be int, not bool")
            if not isinstance(numerator, int) or not isinstance(denominator,
                                                               int):
                raise TimeError("QTime numerator/denominator must be int")
            if denominator <= 0:
                raise TimeError(
                    f"QTime denominator must be > 0, got {denominator}")
            q = Fraction(numerator, denominator)
        if q != q or q in (float("inf"), float("-inf")):  # NaN/inf guard
            raise TimeError("QTime cannot be NaN or infinite")
        if q < 0:
            # Time is an instant or a duration: neither is negative.
            # A subtraction that would go backwards refuses here instead
            # of producing a meaningless negative instant.
            raise TimeError(
                f"QTime cannot be negative, got {q} "
                f"(use duration_between for a guarded difference)")
        object.__setattr__(self, "q", q)

    # ── constructors ─────────────────────────────────────────────
    @staticmethod
    def zero() -> "QTime":
        return _ZERO

    @staticmethod
    def from_seconds(seconds: int | Fraction) -> "QTime":
        return QTime(_q(seconds))

    @staticmethod
    def from_cycles(cycles: int, clock_hz: int | Fraction) -> "QTime":
        """cycles × (1/clock_hz) = seconds, with an explicit clock (§13)."""
        if isinstance(cycles, bool) or not isinstance(cycles, int):
            raise TimeError("cycles must be an integer")
        if cycles < 0:
            raise TimeError(f"cycles must be >= 0, got {cycles}")
        hz = _validate_clock(clock_hz)
        return QTime(Fraction(cycles, 1) / hz)

    # ── arithmetic (exact) ───────────────────────────────────────
    def __add__(self, other: "QTime") -> "QTime":
        return QTime(self.q + _coerce(other))

    def __sub__(self, other: "QTime") -> "QTime":
        return QTime(self.q - _coerce(other))

    def __mul__(self, factor: int | Fraction) -> "QTime":
        return QTime(self.q * _q(factor))

    def __truediv__(self, divisor: int | Fraction) -> "QTime":
        d = _q(divisor)
        if d == 0:
            raise TimeError("division by zero time")
        return QTime(self.q / d)

    # ── comparison ───────────────────────────────────────────────
    def __eq__(self, other: object) -> bool:
        if isinstance(other, QTime):
            return self.q == other.q
        return NotImplemented

    def __lt__(self, other: "QTime") -> bool:
        return self.q < _coerce(other)

    def __le__(self, other: "QTime") -> bool:
        return self.q <= _coerce(other)

    def __gt__(self, other: "QTime") -> bool:
        return self.q > _coerce(other)

    def __ge__(self, other: "QTime") -> bool:
        return self.q >= _coerce(other)

    def __hash__(self) -> int:
        return hash(self.q)

    # ── serialization / reporting ────────────────────────────────
    def to_dict(self) -> dict[str, int]:
        """Exact persisted form: {numerator, denominator} (den > 0)."""
        return {"numerator": self.q.numerator,
                "denominator": self.q.denominator}

    @staticmethod
    def from_dict(d: Any) -> "QTime":
        if not isinstance(d, dict) or set(d) != {"numerator", "denominator"}:
            raise TimeError(
                f"QTime dict must have exactly {{numerator, denominator}}, "
                f"got {sorted(d) if isinstance(d, dict) else type(d).__name__}")
        n, den = d["numerator"], d["denominator"]
        if not isinstance(n, int) or not isinstance(den, int):
            raise TimeError("QTime numerator/denominator must be ints")
        return QTime(n, den)

    def to_float(self) -> float:
        """Reporting boundary only — never identity or comparisons."""
        return float(self.q)

    def is_zero(self) -> bool:
        return self.q == 0

    def __repr__(self) -> str:
        return f"QTime({self.q.numerator}/{self.q.denominator}s)"

    def __str__(self) -> str:
        return f"{self.q.numerator}/{self.q.denominator}s"


def _coerce(other: "QTime") -> Fraction:
    if not isinstance(other, QTime):
        raise TimeError(f"QTime arithmetic requires QTime, "
                        f"got {type(other).__name__}")
    return other.q


def _validate_clock(clock_hz: int | Fraction) -> Fraction:
    if isinstance(clock_hz, bool) or not isinstance(clock_hz,
                                                    (int, Fraction)):
        raise TimeError("clock_hz must be an exact int or Fraction")
    hz = Fraction(clock_hz)
    if hz <= 0:
        raise TimeError(f"clock_hz must be > 0, got {clock_hz}")
    return hz


def seconds_to_clock_periods(seconds: int | Fraction,
                             clock_hz: int | Fraction) -> int:
    """Whole clock periods contained in a duration (ceil, exact).

    Used by evidence cross-checks; returns the smallest period count
    whose total time is >= ``seconds``. Refuses non-exact inputs.
    """
    hz = _validate_clock(clock_hz)
    s = _q(seconds)
    if s < 0:
        raise TimeError("seconds must be >= 0")
    return int(-(-s * hz // 1)) if s > 0 else 0


_ZERO = QTime(0)


def duration_between(start: QTime, end: QTime) -> QTime:
    if end < start:
        raise TimeError(
            f"duration end {end} before start {start}")
    return QTime(end.q - start.q)
