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

from collections import deque
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Any, Sequence

from veritx_dse.core.errors import SemanticError

SCHEMA_VERSION = 1


class DomainIntentError(ValueError, SemanticError):
    """The declared domain/reset/crossing intent is invalid or unsupported."""


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


# --------------------------------------------------------------------------
# vocabulary (contract §3)
# --------------------------------------------------------------------------

class ClockSourceKind(Enum):
    PLL = "PLL"
    XTAL = "XTAL"
    EXTERNAL = "EXTERNAL"
    DIVIDER = "DIVIDER"


class Polarity(Enum):
    ACTIVE_HIGH = "ACTIVE_HIGH"
    ACTIVE_LOW = "ACTIVE_LOW"


class AssertionMode(Enum):
    ASYNC = "ASYNC"
    SYNC = "SYNC"


class DeassertionMode(Enum):
    """Only SYNC exists. ASYNC deassertion is a typed refusal, not a member.

    Modeling it as an enum member would imply the system supports it. It does
    not, so the value is refused by name in ``ResetChannel.from_dict``.
    """
    SYNC = "SYNC"


class PowerPolicy(Enum):
    ALWAYS_ON = "ALWAYS_ON"
    COLLAPSIBLE = "COLLAPSIBLE"


class SignalKind(Enum):
    SINGLE_BIT = "SINGLE_BIT"
    MULTI_BIT = "MULTI_BIT"
    PULSE = "PULSE"
    BUS = "BUS"


class CrossingMechanism(Enum):
    SYNC_2FF = "SYNC_2FF"
    SYNC_3FF = "SYNC_3FF"
    HANDSHAKE = "HANDSHAKE"
    ASYNC_FIFO = "ASYNC_FIFO"
    UNRESOLVED = "UNRESOLVED"


class PointerEncoding(Enum):
    BINARY = "BINARY"
    GRAY = "GRAY"


class CrossingVerdict(Enum):
    INTENT_VALID = "INTENT_VALID"
    UNRESOLVED_CROSSING = "UNRESOLVED_CROSSING"


class FidelityLevel(Enum):
    HETERO_TIMING_ABSTRACT = "HETERO_TIMING_ABSTRACT"
    NOT_MODELED = "NOT_MODELED"


_SYNC_FLOP_MECHANISMS = frozenset({CrossingMechanism.SYNC_2FF, CrossingMechanism.SYNC_3FF})
_LEVEL_SENSITIVE = frozenset({SignalKind.SINGLE_BIT, SignalKind.PULSE})
_MULTI_BIT = frozenset({SignalKind.MULTI_BIT, SignalKind.BUS})
_REQUIRED_SYNC_STAGES = {
    CrossingMechanism.SYNC_2FF: 2,
    CrossingMechanism.SYNC_3FF: 3,
}
# Handshake flops use the same synchronizer stage vocabulary; anything else is
# an undeclared depth, so it refuses rather than being assumed.
_HANDSHAKE_ALLOWED_STAGES = (None, 2, 3)


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


# --------------------------------------------------------------------------
# reset
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ResetChannel:
    """One reset source driving one target clock domain.

    The canonical supported case is **async assert / sync deassert**: the reset
    takes effect immediately on assertion and is released synchronously into the
    target domain through ``synchronizer_stages`` release flops.

    ``deassertion`` only ever accepts ``SYNC``. ASYNC deassertion is a typed
    REFUSAL because this system neither models nor claims it — it is a
    capability fact, not a default.

    ``source_id`` names a declared RESET source. It lives in a different
    namespace from ``ClockSource.id``; existence checking against a reset-source
    registry belongs to the container that owns both, not to this type.
    """

    id: str
    source_id: str
    target_clock_domain: str
    assertion: AssertionMode
    deassertion: DeassertionMode
    polarity: Polarity = Polarity.ACTIVE_HIGH
    synchronizer_stages: int | None = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _as_str("ResetChannel.id", self.id)
        _as_str("ResetChannel.source_id", self.source_id)
        _as_str("ResetChannel.target_clock_domain", self.target_clock_domain)
        _enum("ResetChannel.assertion", AssertionMode, self.assertion)
        _enum("ResetChannel.deassertion", DeassertionMode, self.deassertion)

        if self.deassertion is not DeassertionMode.SYNC:
            raise DomainIntentError(
                f"reset channel {self.id!r} requests ASYNC deassertion, which "
                "is not supported: this system does not model or claim it. "
                "Use deassertion=SYNC (async assert / sync deassert).")

        if self.synchronizer_stages is not None:
            _as_int("ResetChannel.synchronizer_stages",
                    self.synchronizer_stages, minimum=2)

        if self.assertion is AssertionMode.ASYNC:
            if self.synchronizer_stages is None or self.synchronizer_stages < 2:
                raise DomainIntentError(
                    f"reset channel {self.id!r} asserts ASYNC but declares no "
                    "release synchronizer: async assertion requires "
                    "synchronizer_stages >= 2 for a synchronous release into "
                    f"domain {self.target_clock_domain!r}. Declare "
                    "synchronizer_stages >= 2, or use assertion=SYNC.")

        deps = _str_tuple("ResetChannel.depends_on", tuple(self.depends_on))
        if self.id in deps:
            raise DomainIntentError(
                f"reset channel {self.id!r} depends on itself")
        object.__setattr__(self, "depends_on", deps)

    @property
    def async_assert_sync_deassert(self) -> bool:
        """The canonical supported release case (Scenario F)."""
        return (self.assertion is AssertionMode.ASYNC
                and self.deassertion is DeassertionMode.SYNC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_clock_domain": self.target_clock_domain,
            "assertion": self.assertion.value,
            "deassertion": self.deassertion.value,
            "polarity": self.polarity.value,
            "synchronizer_stages": self.synchronizer_stages,
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "ResetChannel":
        _strict_keys(d, frozenset({
            "id", "source_id", "target_clock_domain", "assertion",
            "deassertion", "polarity", "synchronizer_stages", "depends_on"}),
            "reset_channel")
        raw_deassert = _need(d, "deassertion", "reset_channel")
        if isinstance(raw_deassert, str) and raw_deassert.upper() == "ASYNC":
            raise DomainIntentError(
                f"reset channel {_safe_id(d)!r} requests deassertion='ASYNC', "
                "which is not supported: this system does not model or claim "
                "it. Use deassertion='SYNC' (async assert / sync deassert).")
        return cls(
            id=_need(d, "id", "reset_channel"),
            source_id=_need(d, "source_id", "reset_channel"),
            target_clock_domain=_need(d, "target_clock_domain",
                                      "reset_channel"),
            assertion=_enum("reset_channel.assertion", AssertionMode,
                            _need(d, "assertion", "reset_channel")),
            deassertion=_enum("reset_channel.deassertion", DeassertionMode,
                              raw_deassert),
            polarity=_enum("reset_channel.polarity", Polarity,
                           d.get("polarity", Polarity.ACTIVE_HIGH.value)),
            synchronizer_stages=d.get("synchronizer_stages"),
            depends_on=tuple(d.get("depends_on", ())),
        )


def _safe_id(d: dict[str, Any]) -> str:
    value = d.get("id")
    return value if isinstance(value, str) and value else "<unnamed>"


def validate_reset_channels(resets: Sequence[ResetChannel],
                            clock_domains: Sequence[ClockDomain] = (),
                            *, check_domain_existence: bool = False) -> None:
    """Cross-reference reset intent: release order and target domains.

    Refuses duplicate ids, an unknown target clock domain (when the caller
    supplies the domain universe), a ``depends_on`` reference that does not
    exist, and a cyclic release-order dependency — a cycle can never be
    released, so the design is not realizable.
    """
    resets = tuple(resets)
    for r in resets:
        if not isinstance(r, ResetChannel):
            raise DomainIntentError(
                "resets must contain ResetChannel, got "
                f"{type(r).__name__}")
    ids = [r.id for r in resets]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise DomainIntentError(f"duplicate reset channel ids: {dupes}")

    if check_domain_existence:
        known = {d.id for d in clock_domains}
        for r in resets:
            if r.target_clock_domain not in known:
                raise DomainIntentError(
                    f"reset channel {r.id!r} targets clock domain "
                    f"{r.target_clock_domain!r}, which is not declared "
                    f"(declared: {sorted(known)})")

    known_resets = set(ids)
    for r in resets:
        for dep in r.depends_on:
            if dep not in known_resets:
                raise DomainIntentError(
                    f"reset channel {r.id!r} depends on {dep!r}, which is not "
                    f"a declared reset channel (declared: {sorted(known_resets)})")

    # Release order must be acyclic: topological check over depends_on.
    edges: dict[str, tuple[str, ...]] = {r.id: r.depends_on for r in resets}
    state: dict[str, int] = {i: 0 for i in ids}   # 0=unvisited 1=in-stack 2=done

    def visit(node: str, trail: tuple[str, ...]) -> None:
        if state[node] == 2:
            return
        if state[node] == 1:
            cycle = trail[trail.index(node):] + (node,) \
                if node in trail else trail + (node,)
            raise DomainIntentError(
                "reset release-order dependency cycle: "
                f"{' -> '.join(cycle)}. A cyclic release order can never be "
                "released, so this reset intent is not realizable.")
        state[node] = 1
        for dep in edges.get(node, ()):
            visit(dep, trail + (node,))
        state[node] = 2

    for reset_id in ids:
        visit(reset_id, ())


# --------------------------------------------------------------------------
# power
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PowerDomain:
    """Architectural power policy for one domain.

    This is NOT UPF signoff. ``policy`` labels whether the domain is
    architecturally always-on or collapsible, and ``declared_states`` names
    power states the design declares. No isolation, retention or level-shifter
    requirement is implied, and none is generated from this record.
    """

    id: str
    policy: PowerPolicy
    name: str = ""
    declared_states: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _as_str("PowerDomain.id", self.id)
        _enum("PowerDomain.policy", PowerPolicy, self.policy)
        _as_str("PowerDomain.name", self.name, allow_empty=True)
        object.__setattr__(
            self, "declared_states",
            _str_tuple("PowerDomain.declared_states",
                       tuple(self.declared_states)))

    @property
    def always_on(self) -> bool:
        return self.policy is PowerPolicy.ALWAYS_ON

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "policy": self.policy.value,
                "name": self.name,
                "declared_states": list(self.declared_states)}

    @classmethod
    def from_dict(cls, d: Any) -> "PowerDomain":
        _strict_keys(d, frozenset(
            {"id", "policy", "name", "declared_states"}), "power_domain")
        return cls(
            id=_need(d, "id", "power_domain"),
            policy=_enum("power_domain.policy", PowerPolicy,
                         _need(d, "policy", "power_domain")),
            name=d.get("name", ""),
            declared_states=tuple(d.get("declared_states", ())),
        )


# --------------------------------------------------------------------------
# crossing intent
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AsyncFIFOConfig:
    """Declared structure of an asynchronous FIFO bridge.

    ``pointer_encoding == GRAY`` requires a power-of-two ``depth``: a Gray-code
    pointer only wraps correctly when the counter modulus is a power of two.
    Refusing otherwise is a structural law, not a preference.
    """

    depth: int
    write_width: int
    read_width: int
    pointer_encoding: PointerEncoding
    synchronizer_stages: int

    def __post_init__(self) -> None:
        _as_int("AsyncFIFOConfig.depth", self.depth, minimum=2)
        _as_int("AsyncFIFOConfig.write_width", self.write_width, minimum=1)
        _as_int("AsyncFIFOConfig.read_width", self.read_width, minimum=1)
        _enum("AsyncFIFOConfig.pointer_encoding", PointerEncoding,
              self.pointer_encoding)
        _as_int("AsyncFIFOConfig.synchronizer_stages",
                self.synchronizer_stages, minimum=2)
        if self.pointer_encoding is PointerEncoding.GRAY and \
                (self.depth & (self.depth - 1)) != 0:
            raise DomainIntentError(
                f"AsyncFIFOConfig depth {self.depth} is not a power of two, "
                "but pointer_encoding=GRAY requires a power-of-two depth: a "
                "Gray-code pointer only wraps correctly when the modulus is a "
                "power of two. Use a power-of-two depth or "
                "pointer_encoding=BINARY.")

    def to_dict(self) -> dict[str, Any]:
        return {"depth": self.depth, "write_width": self.write_width,
                "read_width": self.read_width,
                "pointer_encoding": self.pointer_encoding.value,
                "synchronizer_stages": self.synchronizer_stages}

    @classmethod
    def from_dict(cls, d: Any) -> "AsyncFIFOConfig":
        _strict_keys(d, frozenset({
            "depth", "write_width", "read_width", "pointer_encoding",
            "synchronizer_stages"}), "async_fifo")
        return cls(
            depth=_need(d, "depth", "async_fifo"),
            write_width=_need(d, "write_width", "async_fifo"),
            read_width=_need(d, "read_width", "async_fifo"),
            pointer_encoding=_enum(
                "async_fifo.pointer_encoding", PointerEncoding,
                _need(d, "pointer_encoding", "async_fifo")),
            synchronizer_stages=_need(d, "synchronizer_stages", "async_fifo"),
        )


@dataclass(frozen=True)
class Crossing:
    """One clock-domain crossing, declared structurally.

    Every law in contract §6 is enforced in ``__post_init__``, so a crossing
    that constructs is a crossing whose structure is coherent. Coherence is not
    signoff: see :func:`assess_crossing`.
    """

    id: str
    src_clock: str
    dst_clock: str
    signal_kind: SignalKind
    mechanism: CrossingMechanism
    synchronizer_stages: int | None = None
    async_fifo: AsyncFIFOConfig | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _as_str("Crossing.id", self.id)
        _as_str("Crossing.src_clock", self.src_clock)
        _as_str("Crossing.dst_clock", self.dst_clock)
        _enum("Crossing.signal_kind", SignalKind, self.signal_kind)
        _enum("Crossing.mechanism", CrossingMechanism, self.mechanism)
        _as_str("Crossing.reason", self.reason, allow_empty=True)

        if self.src_clock == self.dst_clock:
            raise DomainIntentError(
                f"crossing {self.id!r} has src_clock == dst_clock "
                f"({self.src_clock!r}): it is not a clock-domain crossing. "
                "Remove it, or declare two distinct domains.")

        if self.async_fifo is not None and \
                not isinstance(self.async_fifo, AsyncFIFOConfig):
            raise DomainIntentError(
                f"crossing {self.id!r} async_fifo must be an AsyncFIFOConfig, "
                f"got {type(self.async_fifo).__name__}")

        # ASYNC_FIFO <-> async_fifo must agree in BOTH directions: a declared
        # FIFO with no ASYNC_FIFO mechanism, or the mechanism with no config,
        # is two authorities for one fact.
        if self.mechanism is CrossingMechanism.ASYNC_FIFO:
            if self.async_fifo is None:
                raise DomainIntentError(
                    f"crossing {self.id!r} declares mechanism=ASYNC_FIFO but "
                    "no async_fifo configuration: depth, width and pointer "
                    "encoding are the design, so they must be stated.")
            if self.synchronizer_stages is not None:
                raise DomainIntentError(
                    f"crossing {self.id!r} declares both "
                    "synchronizer_stages and an async_fifo: the FIFO's own "
                    "synchronizer_stages is the authority, so the crossing "
                    "level must leave it None.")
        elif self.async_fifo is not None:
            raise DomainIntentError(
                f"crossing {self.id!r} carries an async_fifo configuration "
                f"with mechanism={self.mechanism.value}: a FIFO config with a "
                "non-ASYNC_FIFO mechanism is two authorities for one fact. "
                "Set mechanism=ASYNC_FIFO or drop async_fifo.")

        if self.mechanism is CrossingMechanism.UNRESOLVED:
            if not self.reason:
                raise DomainIntentError(
                    f"crossing {self.id!r} declares mechanism=UNRESOLVED with "
                    "no reason: UNRESOLVED is the honest answer only when the "
                    "missing information is named. State what is unknown.")
            if self.synchronizer_stages is not None:
                raise DomainIntentError(
                    f"crossing {self.id!r} is UNRESOLVED but declares "
                    "synchronizer_stages: an unresolved crossing must not "
                    "carry a mechanism's parameters.")

        # signal-kind / mechanism compatibility
        if self.signal_kind in _LEVEL_SENSITIVE and \
                self.mechanism is CrossingMechanism.ASYNC_FIFO:
            raise DomainIntentError(
                f"crossing {self.id!r} applies ASYNC_FIFO to a "
                f"{self.signal_kind.value} signal: a FIFO bridges a stream, "
                "not a single level/pulse. Use SYNC_2FF/SYNC_3FF (with "
                "synchronizer_stages) or HANDSHAKE, or set "
                "mechanism=UNRESOLVED with a reason.")
        if self.signal_kind in _MULTI_BIT and self.mechanism in _SYNC_FLOP_MECHANISMS:
            raise DomainIntentError(
                f"crossing {self.id!r} applies {self.mechanism.value} to a "
                f"{self.signal_kind.value} signal: a multi-bit value cannot "
                "cross on a single-flop synchronizer because the bits may "
                "arrive on different cycles. Use ASYNC_FIFO or HANDSHAKE, or "
                "set mechanism=UNRESOLVED with a reason.")

        # stage-count laws
        required = _REQUIRED_SYNC_STAGES.get(self.mechanism)
        if required is not None:
            if self.synchronizer_stages is None:
                raise DomainIntentError(
                    f"crossing {self.id!r} declares {self.mechanism.value} "
                    f"but no synchronizer_stages: {self.mechanism.value} "
                    f"requires synchronizer_stages == {required}.")
            if self.synchronizer_stages != required:
                raise DomainIntentError(
                    f"crossing {self.id!r} declares {self.mechanism.value} "
                    f"with synchronizer_stages="
                    f"{self.synchronizer_stages}: "
                    f"{self.mechanism.value} requires exactly {required}.")
        if self.mechanism is CrossingMechanism.HANDSHAKE:
            if self.synchronizer_stages not in _HANDSHAKE_ALLOWED_STAGES:
                raise DomainIntentError(
                    f"crossing {self.id!r} is HANDSHAKE with "
                    f"synchronizer_stages={self.synchronizer_stages}: "
                    "HANDSHAKE accepts None, 2 or 3 stages.")

    @property
    def requires_clock_crossing(self) -> bool:
        """Always True for a constructed Crossing — the two ends differ.

        Exposed so a sibling module (sideband) can flag a crossing without
        duplicating this type's existence law.
        """
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "src_clock": self.src_clock,
            "dst_clock": self.dst_clock,
            "signal_kind": self.signal_kind.value,
            "mechanism": self.mechanism.value,
            "synchronizer_stages": self.synchronizer_stages,
            "async_fifo": (self.async_fifo.to_dict()
                           if self.async_fifo is not None else None),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "Crossing":
        _strict_keys(d, frozenset({
            "id", "src_clock", "dst_clock", "signal_kind", "mechanism",
            "synchronizer_stages", "async_fifo", "reason"}), "crossing")
        raw_fifo = d.get("async_fifo")
        fifo = None
        if raw_fifo is not None:
            if not isinstance(raw_fifo, dict):
                raise DomainIntentError(
                    f"crossing {_safe_id(d)!r} async_fifo must be an object "
                    f"or null, got {type(raw_fifo).__name__}")
            fifo = AsyncFIFOConfig.from_dict(raw_fifo)
        return cls(
            id=_need(d, "id", "crossing"),
            src_clock=_need(d, "src_clock", "crossing"),
            dst_clock=_need(d, "dst_clock", "crossing"),
            signal_kind=_enum("crossing.signal_kind", SignalKind,
                              _need(d, "signal_kind", "crossing")),
            mechanism=_enum("crossing.mechanism", CrossingMechanism,
                            _need(d, "mechanism", "crossing")),
            synchronizer_stages=d.get("synchronizer_stages"),
            async_fifo=fifo,
            reason=d.get("reason", ""),
        )


@dataclass(frozen=True)
class CrossingAssessment:
    """Three separate verdicts, never collapsed into one word.

    - ``intent_verdict``: is the declared structure coherent? (structural only)
    - ``performance_fidelity``: does a performance consequence model exist?
    - ``signoff_verified``: always False. This module performs no timing or
      metastability analysis, so it can never be True. The Domains view shows
      INTENT VALID / PERFORMANCE MODEL AVAILABLE / SIGNOFF VERIFIED as three
      facts, and the third is NO.
    """

    crossing_id: str
    intent_verdict: CrossingVerdict
    reason: str
    performance_fidelity: FidelityLevel
    signoff_verified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "crossing_id": self.crossing_id,
            "intent_verdict": self.intent_verdict.value,
            "reason": self.reason,
            "performance_fidelity": self.performance_fidelity.value,
            "signoff_verified": self.signoff_verified,
        }


def assess_crossing(crossing: Crossing) -> CrossingAssessment:
    """Judge a crossing WITHOUT ever recommending a mechanism.

    A ``UNRESOLVED`` crossing reports ``UNRESOLVED_CROSSING`` and repeats the
    author's stated reason. It is never silently promoted to SYNC_2FF.

    Performance fidelity is ``HETERO_TIMING_ABSTRACT`` only for ASYNC_FIFO,
    where :class:`AsyncFIFOModel` exists; every other mechanism reports
    ``NOT_MODELED`` rather than borrowing the FIFO model's label.
    """
    if not isinstance(crossing, Crossing):
        raise DomainIntentError(
            f"assess_crossing needs a Crossing, got {type(crossing).__name__}")

    if crossing.mechanism is CrossingMechanism.UNRESOLVED:
        return CrossingAssessment(
            crossing_id=crossing.id,
            intent_verdict=CrossingVerdict.UNRESOLVED_CROSSING,
            reason=crossing.reason,
            performance_fidelity=FidelityLevel.NOT_MODELED,
        )

    if crossing.mechanism is CrossingMechanism.ASYNC_FIFO:
        fidelity = FidelityLevel.HETERO_TIMING_ABSTRACT
        reason = (
            f"{crossing.signal_kind.value} signal from {crossing.src_clock} "
            f"to {crossing.dst_clock} through an ASYNC_FIFO of depth "
            f"{crossing.async_fifo.depth} with "
            f"{crossing.async_fifo.synchronizer_stages} synchronizer stages. "
            "Structure is consistent with every declared law. Occupancy, "
            "full/empty and backpressure are modelled at abstract "
            "heterogeneous fidelity; this is NOT signoff and makes no "
            "metastability claim.")
    else:
        fidelity = FidelityLevel.NOT_MODELED
        stages = (f" with synchronizer_stages={crossing.synchronizer_stages}"
                  if crossing.synchronizer_stages is not None else "")
        reason = (
            f"{crossing.signal_kind.value} signal from {crossing.src_clock} "
            f"to {crossing.dst_clock} through {crossing.mechanism.value}"
            f"{stages}. Structure is consistent with every declared law. No "
            "performance model exists for this mechanism, so no latency or "
            "throughput consequence is claimed. This is NOT signoff and makes "
            "no metastability claim.")

    return CrossingAssessment(
        crossing_id=crossing.id,
        intent_verdict=CrossingVerdict.INTENT_VALID,
        reason=reason,
        performance_fidelity=fidelity,
    )


# --------------------------------------------------------------------------
# async FIFO performance model (intent correctness vs consequence, §33)
# --------------------------------------------------------------------------

class AsyncFIFOModel:
    """Deterministic occupancy / backpressure model for one async FIFO.

    This answers "what does the FIFO COST?" — accepted writes, accepted reads,
    occupancy, full/empty and backpressure — as distinct from
    :func:`assess_crossing`, which answers "is the intent coherent?".

    It is a Q1 micro-oracle over an exact integer cycle counter. It models:
    capacity, backpressure, and the ``synchronizer_stages`` read-domain latency
    before a written item becomes readable. It does NOT model analog
    metastability, bit-error rates, clock ratio, or multi-rate event execution.
    Clock-ratio exploration belongs to the Level-1 heterogeneous timing model;
    this class deliberately reports ``HETERO_TIMING_ABSTRACT`` and no more.

    Invariants held by construction: occupancy never exceeds ``depth``, never
    goes negative, and items become readable in write order.
    """

    def __init__(self, config: AsyncFIFOConfig,
                 synchronizer_latency_cycles: int | None = None) -> None:
        if not isinstance(config, AsyncFIFOConfig):
            raise DomainIntentError(
                "AsyncFIFOModel needs an AsyncFIFOConfig, got "
                f"{type(config).__name__}")
        if synchronizer_latency_cycles is not None and \
                synchronizer_latency_cycles != config.synchronizer_stages:
            # Two authorities for one fact: the declared config wins and the
            # conflict is refused rather than silently resolved.
            raise DomainIntentError(
                f"synchronizer_latency_cycles="
                f"{synchronizer_latency_cycles} contradicts the declared "
                f"async_fifo.synchronizer_stages="
                f"{config.synchronizer_stages}. One value, one authority.")
        self._config = config
        self._latency = config.synchronizer_stages
        # (sequence, read-eligible cycle) in write order.
        self._entries: deque[tuple[int, int]] = deque()
        self._next_seq = 0
        self._cycle = 0
        self._accepted_writes = 0
        self._accepted_reads = 0
        self._rejected_writes = 0
        self._rejected_reads = 0
        self._read_order: list[int] = []

    # -- introspection ---------------------------------------------------
    @property
    def config(self) -> AsyncFIFOConfig:
        return self._config

    @property
    def fidelity(self) -> FidelityLevel:
        return FidelityLevel.HETERO_TIMING_ABSTRACT

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def depth(self) -> int:
        return self._config.depth

    @property
    def occupancy(self) -> int:
        """Items occupying a slot: readable plus still in synchronizer."""
        return len(self._entries)

    @property
    def full(self) -> bool:
        return self.occupancy >= self._config.depth

    @property
    def empty(self) -> bool:
        return self.occupancy == 0

    @property
    def readable(self) -> int:
        """Items whose synchronizer latency has elapsed."""
        return sum(1 for _, eligible in self._entries
                   if eligible <= self._cycle)

    @property
    def in_synchronizer(self) -> int:
        return self.occupancy - self.readable

    @property
    def accepted_writes(self) -> int:
        return self._accepted_writes

    @property
    def accepted_reads(self) -> int:
        return self._accepted_reads

    @property
    def backpressured_writes(self) -> int:
        """Writes refused because the FIFO was full."""
        return self._rejected_writes

    @property
    def read_order(self) -> tuple[int, ...]:
        """Sequence numbers in the order they were read (ordering invariant)."""
        return tuple(self._read_order)

    # -- operations ------------------------------------------------------
    def advance(self, cycles: int = 1) -> None:
        """Advance the shared reference cycle counter by ``cycles``."""
        _as_int("AsyncFIFOModel.advance(cycles)", cycles, minimum=0)
        self._cycle += cycles

    def write_accepted(self) -> bool:
        """Attempt one write. False when full => backpressure, not a drop."""
        if self.full:
            self._rejected_writes += 1
            return False
        seq = self._next_seq
        self._next_seq += 1
        self._entries.append((seq, self._cycle + self._latency))
        self._accepted_writes += 1
        return True

    def read_accepted(self) -> bool:
        """Attempt one read. False when empty or not yet synchronised."""
        if not self._entries:
            self._rejected_reads += 1
            return False
        seq, eligible = self._entries[0]
        if eligible > self._cycle:
            # Occupied but still in the synchronizer: not yet readable.
            self._rejected_reads += 1
            return False
        self._entries.popleft()
        self._accepted_reads += 1
        self._read_order.append(seq)
        return True

    def fill(self) -> int:
        """Write until full; returns accepted count. Test/oracle helper."""
        accepted = 0
        while self.write_accepted():
            accepted += 1
        return accepted

    def drain(self) -> int:
        """Read every currently-readable item; returns accepted count."""
        accepted = 0
        while self.read_accepted():
            accepted += 1
        return accepted

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"AsyncFIFOModel(depth={self.depth}, occupancy="
                f"{self.occupancy}, cycle={self._cycle}, "
                f"fidelity={self.fidelity.value})")


__all__ = [
    "SCHEMA_VERSION",
    "DomainIntentError",
    "ClockSourceKind", "Polarity", "AssertionMode", "DeassertionMode",
    "PowerPolicy", "SignalKind", "CrossingMechanism", "PointerEncoding",
    "CrossingVerdict", "FidelityLevel",
    "ClockSource", "ClockDomain", "validate_clock_domains",
    "check_clock_domains", "MaterializedClockDomains",
    "materialize_clock_domains",
    "ResetChannel", "validate_reset_channels",
    "PowerDomain",
    "AsyncFIFOConfig", "Crossing", "CrossingAssessment", "assess_crossing",
    "AsyncFIFOModel",
]
