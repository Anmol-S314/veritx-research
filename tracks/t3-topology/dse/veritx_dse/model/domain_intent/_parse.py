"""_parse — typed coercion helpers (raise DomainIntentError).

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from enum import Enum
from fractions import Fraction
from typing import Any

from ._core import DomainIntentError

# --------------------------------------------------------------------------
# local typed helpers — a semantic refusal must raise DomainIntentError, not a
# bare ValueError (contract §1). compile_model's _as_int raises ValueError, so
# the same laws are re-expressed here in this module's type.
# --------------------------------------------------------------------------

def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise DomainIntentError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise DomainIntentError(
            f"unknown field {where}.{unknown[0]} (allowed: "
            f"{sorted(allowed)})")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise DomainIntentError(f"missing required field {where}.{key}")
    return d[key]


def _as_int(name: str, value: Any, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise DomainIntentError(
            f"{name} must be an exact int, got {type(value).__name__} "
            f"{value!r}")
    if minimum is not None and value < minimum:
        raise DomainIntentError(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DomainIntentError(
            f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise DomainIntentError(f"{name} must be a non-empty string")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise DomainIntentError(
            f"{name} must be a bool, got {type(value).__name__} {value!r}")
    return value


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Any:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, TypeError) as exc:
        raise DomainIntentError(
            f"{name} must be one of "
            f"{[m.value for m in enum_cls]}, got {value!r}") from exc


def _as_hz(name: str, value: Any) -> int:
    """An exact integer Hz. Binary floats are REFUSED, not approximated.

    Strings are accepted only when they denote an exact integer ("1e9",
    "2500000000"); "1.5" and "0.1" refuse because a clock identity may not
    round. Integers above 2**53 survive untouched.
    """
    if isinstance(value, bool):
        raise DomainIntentError(f"{name} must be an exact Hz count, got bool")
    if isinstance(value, float):
        raise DomainIntentError(
            f"{name} must be an exact integer Hz, got binary float {value!r}. "
            "A clock identity may not round: pass an int or an exact string "
            "such as '1e9'.")
    if isinstance(value, int):
        hz = value
    elif isinstance(value, str):
        try:
            number = Fraction(value)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise DomainIntentError(
                f"{name} {value!r} is not an exact number") from exc
        if number.denominator != 1:
            raise DomainIntentError(
                f"{name} {value!r} Hz is not an exact integer count — "
                "refusing inexact clock claims")
        hz = number.numerator
    else:
        raise DomainIntentError(
            f"{name} must be an exact int or exact string, got "
            f"{type(value).__name__}")
    if hz < 1:
        raise DomainIntentError(f"{name} must be >= 1 Hz, got {hz}")
    return hz


def _str_tuple(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise DomainIntentError(
            f"{name} must be a list of ids, got {type(value).__name__}")
    out = tuple(_as_str(f"{name}[]", item) for item in value)
    if len(set(out)) != len(out):
        raise DomainIntentError(f"{name} contains duplicate ids: {sorted(out)}")
    return out
