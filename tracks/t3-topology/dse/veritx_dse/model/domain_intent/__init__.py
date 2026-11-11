"""veritx_dse.model.domain_intent — clock, reset, power and crossing intent.

This module owns ARCHITECTURAL intent only. It states what a design *declares*
about its clocking, its reset release, its power policy and its clock-domain
crossings. It is deliberately NOT:

- a static-timing or signoff engine. No metastability claim is made or implied
  anywhere in this module. ``INTENT_VALID`` means "the declared structure is
  internally consistent and does not violate a stated law" — nothing more.
- a UPF exporter. ``PowerDomain`` is an architectural policy label
  (ALWAYS_ON / COLLAPSIBLE). Isolation, retention and level-shifter
  requirements are NOT implied and NOT generated. This is not UPF signoff.
- a performance oracle for every mechanism. Intent correctness (did you declare
  something coherent?) and performance consequence (what latency/throughput does
  it cost?) are SEPARATE objects here:

    ``Crossing`` / ``assess_crossing``  -> intent correctness
    ``AsyncFIFOModel``                  -> performance consequence

  A mechanism with no performance model reports ``FidelityLevel.NOT_MODELED``
  rather than inheriting the FIFO model's ``HETERO_TIMING_ABSTRACT`` label.

Exactness
---------
``frequency_hz`` is an exact ``int``. Binary floats are refused outright: a
clock identity must never round. The divider law is exact integer division —
``(source_hz * divider_den) % divider_num == 0`` — and a non-integer result is
REFUSED, never rounded, per docs/INTENT-V5-CONTRACT.md §6.

Nothing here auto-selects a mechanism. When the information needed to decide is
absent the correct value is ``CrossingMechanism.UNRESOLVED`` with an explicit
reason — never an assumed ``SYNC_2FF``.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from ._core import SCHEMA_VERSION, DomainIntentError
from .enums import (
    AssertionMode, ClockSourceKind, CrossingMechanism, CrossingVerdict,
    DeassertionMode, FidelityLevel, PointerEncoding, Polarity, PowerPolicy,
    SignalKind,
)
from .clock import (
    ClockDomain, ClockSource, MaterializedClockDomains, check_clock_domains,
    materialize_clock_domains, validate_clock_domains,
)
from .reset import ResetChannel, validate_reset_channels
from .power import PowerDomain
from .crossing import (
    AsyncFIFOConfig, Crossing, CrossingAssessment, assess_crossing,
)
from .fifo import AsyncFIFOModel

__all__ = [
    "SCHEMA_VERSION",
    "DomainIntentError",
    "ClockSourceKind",
    "Polarity",
    "AssertionMode",
    "DeassertionMode",
    "PowerPolicy",
    "SignalKind",
    "CrossingMechanism",
    "PointerEncoding",
    "CrossingVerdict",
    "FidelityLevel",
    "ClockSource",
    "ClockDomain",
    "validate_clock_domains",
    "check_clock_domains",
    "MaterializedClockDomains",
    "materialize_clock_domains",
    "ResetChannel",
    "validate_reset_channels",
    "PowerDomain",
    "AsyncFIFOConfig",
    "Crossing",
    "CrossingAssessment",
    "assess_crossing",
    "AsyncFIFOModel",
]
