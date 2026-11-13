"""Bounded reuse of one pure structural derivation inside one adjudication.

A single Studio read can ask for the same pure derivation many times: the
GEC-hybrid per-instance proof is requested once per planned question per
backend adapter (13 times for the 49-router hybrid, ~2.5 s of a 3.9 s plan),
always with identical arguments. Re-running it is not extra checking — it is
the same derivation over the same immutable inputs.

This scope makes that reuse EXPLICIT and SHORT-LIVED:

* nothing is cached between calls — a scope is entered and dropped by one
  adjudication, so a caller (or a test) that monkeypatches a derivation still
  sees the patched result on its next call;
* the derivation still runs in full the first time the scope asks for it, so
  every check and refusal path executes exactly as before;
* keys are content-addressed arguments, never object identity.

Outside an active scope `scoped_derivation` simply calls `derive()`, so code
that does not opt in behaves exactly as it did.
"""
from __future__ import annotations

import functools
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Hashable, Iterator

_PRIMED: ContextVar[dict[tuple[str, Hashable], Any] | None] = ContextVar(
    "veritx_derivation_scope", default=None)

_MISSING = object()


@contextmanager
def derivation_scope() -> Iterator[None]:
    """Adjudication boundary: derivations reuse within, never across.

    Re-entrant: an inner adjudication joins the scope already open around the
    caller rather than starting a second, shorter-lived one.
    """
    if _PRIMED.get() is not None:
        yield
        return
    token = _PRIMED.set({})
    try:
        yield
    finally:
        _PRIMED.reset(token)


def scoped_adjudication(adjudicate: Callable[..., Any]) -> Callable[..., Any]:
    """Mark one product read as an adjudication boundary."""
    @functools.wraps(adjudicate)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with derivation_scope():
            return adjudicate(*args, **kwargs)
    return wrapper


def scoped_derivation(kind: str, key: Hashable,
                      derive: Callable[[], Any]) -> Any:
    """`derive()` once per ``(kind, key)`` inside the active scope.

    Outside a scope the call is unconditional.
    """
    primed = _PRIMED.get()
    if primed is None:
        return derive()
    slot = (kind, key)
    cached = primed.get(slot, _MISSING)
    if cached is not _MISSING:
        return cached
    value = derive()
    primed[slot] = value
    return value


__all__ = ["derivation_scope", "scoped_adjudication", "scoped_derivation"]
