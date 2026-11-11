"""crossing — crossing intent, assessment, AsyncFIFOConfig.

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import UnsupportedSemantics

from ._core import DomainIntentError
from ._parse import _as_bool, _as_int, _as_str, _enum, _need, _strict_keys
from .enums import CrossingMechanism, CrossingVerdict, FidelityLevel, PointerEncoding, SignalKind, _HANDSHAKE_ALLOWED_STAGES, _LEVEL_SENSITIVE, _MULTI_BIT, _REQUIRED_SYNC_STAGES, _SYNC_FLOP_MECHANISMS
from .reset import _safe_id

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


def assess_crossing(crossing: Crossing, *,
                    require_rtl_qualification: bool = False
                    ) -> CrossingAssessment:
    """Judge a crossing WITHOUT ever recommending a mechanism.

    A ``UNRESOLVED`` crossing reports ``UNRESOLVED_CROSSING`` and repeats the
    author's stated reason. It is never silently promoted to SYNC_2FF.

    Performance fidelity is ``HETERO_TIMING_ABSTRACT`` only for ASYNC_FIFO,
    where :class:`AsyncFIFOModel` exists; every other mechanism reports
    ``NOT_MODELED`` rather than borrowing the FIFO model's label.

    ``require_rtl_qualification`` is the explicit request for RTL/signoff CDC
    qualification. No RTL differential exists in this repo, so such a request
    is a typed ``UNSUPPORTED_SEMANTICS`` refusal naming its owning stage. The
    default ``False`` leaves the abstract assessment unchanged: this module
    still reports structural intent only and never signs off.
    """
    if not isinstance(crossing, Crossing):
        raise DomainIntentError(
            f"assess_crossing needs a Crossing, got {type(crossing).__name__}")
    if _as_bool("assess_crossing.require_rtl_qualification",
                require_rtl_qualification):
        raise UnsupportedSemantics(
            f"crossing {crossing.id!r} was asked for RTL/signoff CDC "
            "qualification, which is not supported: owner stage = "
            "verification/RTL generation; no RTL differential exists. "
            "assess_crossing reports declared structure only "
            "(INTENT_VALID / HETERO_TIMING_ABSTRACT) and makes no "
            "metastability or signoff claim.")

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
