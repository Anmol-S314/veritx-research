"""clock — clock sources, domains, materialisation.

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ._core import DomainIntentError, SCHEMA_VERSION
from ._parse import _as_hz, _as_int, _as_str, _enum, _need, _strict_keys
from .enums import ClockSourceKind

# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ClockSource:
    """A declared clock source: an oscillator, PLL output or external feed.

    ``frequency_hz`` is exact. There is no jitter, uncertainty or phase noise
    field here because none of them is modelled — inventing one would be a
    claim without an artifact.
    """

    id: str
    kind: ClockSourceKind
    frequency_hz: int

    def __post_init__(self) -> None:
        _as_str("ClockSource.id", self.id)
        _enum("ClockSource.kind", ClockSourceKind, self.kind)
        # Normalize "1e9" -> 10**9 here: a frozen dataclass does not store
        # what __post_init__ returns, so the exact-int law must be written
        # back or the artifact would carry a string identity.
        object.__setattr__(self, "frequency_hz",
                           _as_hz("ClockSource.frequency_hz",
                                  self.frequency_hz))

    @property
    def period_ps(self) -> int:
        """Exact integer period in picoseconds: 10**12 / f. REFUSES a clock
        that does not divide 10**12 evenly rather than rounding it, because a
        rounded period would be a fabricated timing identity."""
        if 10 ** 12 % self.frequency_hz != 0:
            raise DomainIntentError(
                f"clock source {self.id!r} at {self.frequency_hz} Hz does not "
                "produce an exact integer picosecond period, so no period is "
                "reported instead of a rounded one")
        return 10 ** 12 // self.frequency_hz

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind.value,
                "frequency_hz": self.frequency_hz}

    @classmethod
    def from_dict(cls, d: Any) -> "ClockSource":
        _strict_keys(d, frozenset({"id", "kind", "frequency_hz"}),
                     "clock_source")
        return cls(
            id=_need(d, "id", "clock_source"),
            kind=_enum("clock_source.kind", ClockSourceKind,
                       _need(d, "kind", "clock_source")),
            frequency_hz=_need(d, "frequency_hz", "clock_source"),
        )


@dataclass(frozen=True)
class ClockDomain:
    """A clock domain derived from a declared source through an exact divider.

    ``frequency_hz`` is the domain's OWN frequency and is cross-checked against
    ``source.frequency_hz * divider_den / divider_num`` by
    :func:`validate_clock_domains`. The two must agree exactly; a non-integer
    derivation refuses instead of rounding.
    """

    id: str
    source_id: str
    frequency_hz: int
    divider_num: int = 1
    divider_den: int = 1

    def __post_init__(self) -> None:
        _as_str("ClockDomain.id", self.id)
        _as_str("ClockDomain.source_id", self.source_id)
        object.__setattr__(self, "frequency_hz",
                           _as_hz("ClockDomain.frequency_hz",
                                  self.frequency_hz))
        _as_int("ClockDomain.divider_num", self.divider_num, minimum=1)
        _as_int("ClockDomain.divider_den", self.divider_den, minimum=1)

    def derived_from(self, source_hz: int) -> int:
        """Exact domain frequency implied by ``source_hz`` and this divider.

        Raises rather than rounding when the quotient is not an integer.
        """
        numerator = _as_int("source.frequency_hz", source_hz, minimum=1) \
            * self.divider_den
        if numerator % self.divider_num != 0:
            raise DomainIntentError(
                f"clock domain {self.id!r} divider {self.divider_num}/"
                f"{self.divider_den} does not divide source {source_hz} Hz "
                "evenly ("
                f"{numerator} / {self.divider_num}): an exact integer domain "
                "frequency does not exist, and this module does not round one")
        derived = numerator // self.divider_num
        if derived < 1:
            raise DomainIntentError(
                f"clock domain {self.id!r} would derive {derived} Hz, which "
                "is not a legal clock frequency")
        return derived

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "source_id": self.source_id,
                "frequency_hz": self.frequency_hz,
                "divider_num": self.divider_num,
                "divider_den": self.divider_den}

    @classmethod
    def from_dict(cls, d: Any) -> "ClockDomain":
        _strict_keys(d, frozenset({
            "id", "source_id", "frequency_hz", "divider_num", "divider_den"}),
            "clock_domain")
        return cls(
            id=_need(d, "id", "clock_domain"),
            source_id=_need(d, "source_id", "clock_domain"),
            frequency_hz=_need(d, "frequency_hz", "clock_domain"),
            divider_num=d.get("divider_num", 1),
            divider_den=d.get("divider_den", 1),
        )


def validate_clock_domains(sources: Sequence[ClockSource],
                           domains: Sequence[ClockDomain]) -> None:
    """Cross-reference clock intent: declared sources, exact derivation.

    Refuses duplicate ids, an unknown ``source_id``, and any domain whose
    authored frequency does not equal its exact derived frequency.
    """
    sources = tuple(sources)
    domains = tuple(domains)
    for s in sources:
        if not isinstance(s, ClockSource):
            raise DomainIntentError(
                "sources must contain ClockSource, got "
                f"{type(s).__name__}")
    for d in domains:
        if not isinstance(d, ClockDomain):
            raise DomainIntentError(
                "domains must contain ClockDomain, got "
                f"{type(d).__name__}")

    src_ids = [s.id for s in sources]
    if len(set(src_ids)) != len(src_ids):
        dupes = sorted({i for i in src_ids if src_ids.count(i) > 1})
        raise DomainIntentError(f"duplicate clock source ids: {dupes}")
    dom_ids = [d.id for d in domains]
    if len(set(dom_ids)) != len(dom_ids):
        dupes = sorted({i for i in dom_ids if dom_ids.count(i) > 1})
        raise DomainIntentError(f"duplicate clock domain ids: {dupes}")

    by_id = {s.id: s for s in sources}
    for d in domains:
        source = by_id.get(d.source_id)
        if source is None:
            raise DomainIntentError(
                f"clock domain {d.id!r} references source "
                f"{d.source_id!r}, which is not a declared clock source "
                f"(declared: {sorted(by_id)})")
        derived = d.derived_from(source.frequency_hz)
        if derived != d.frequency_hz:
            raise DomainIntentError(
                f"clock domain {d.id!r} declares {d.frequency_hz} Hz but "
                f"source {d.id!r} ({source.frequency_hz} Hz) through divider "
                f"{d.divider_num}/{d.divider_den} derives {derived} Hz. The "
                "two must agree exactly; this module will not pick one.")


def check_clock_domains(sources: Sequence[ClockSource],
                        domains: Sequence[ClockDomain]) -> bool:
    """True when the clock intent is structurally valid. Never repairs."""
    try:
        validate_clock_domains(sources, domains)
    except DomainIntentError:
        return False
    return True


@dataclass(frozen=True)
class MaterializedClockDomains:
    """A validated clock tree: declared sources and their exact domains.

    Content-addressed so it can be a compiler output. It carries NO ratio
    simulation and NO backend semantics: it is the declared clock intent,
    proved structurally (exact integer derivation) and nothing more.
    """

    sources: tuple[ClockSource, ...]
    domains: tuple[ClockDomain, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or \
                self.schema_version != SCHEMA_VERSION:
            raise DomainIntentError(
                f"unsupported clock-domain schema_version "
                f"{self.schema_version!r}")
        validate_clock_domains(self.sources, self.domains)
        if tuple(s.id for s in self.sources) != tuple(
                sorted(s.id for s in self.sources)):
            raise DomainIntentError("clock sources must be sorted by id")
        if tuple(d.id for d in self.domains) != tuple(
                sorted(d.id for d in self.domains)):
            raise DomainIntentError("clock domains must be sorted by id")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/MaterializedClockDomains",
            "schema_version": self.schema_version,
            "sources": [s.to_dict() for s in self.sources],
            "domains": [d.to_dict() for d in self.domains],
        }

    @property
    def content_hash(self) -> str:
        from veritx_dse.core.artifact import content_id
        return content_id("srota/MaterializedClockDomains/v1",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "content_hash": self.content_hash}


def materialize_clock_domains(
        sources: Sequence[ClockSource],
        domains: Sequence[ClockDomain]) -> MaterializedClockDomains:
    """Prove the clock intent structurally and content-address it."""
    return MaterializedClockDomains(
        sources=tuple(sorted(sources, key=lambda s: s.id)),
        domains=tuple(sorted(domains, key=lambda d: d.id)))
