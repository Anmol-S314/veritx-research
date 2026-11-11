"""reset — reset channels and validation.

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ._core import DomainIntentError
from ._parse import _as_int, _as_str, _enum, _need, _str_tuple, _strict_keys
from .enums import AssertionMode, DeassertionMode, Polarity
from .clock import ClockDomain

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
