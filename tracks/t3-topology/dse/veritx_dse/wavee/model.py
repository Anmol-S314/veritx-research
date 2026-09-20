"""veritx_dse.wavee.model — WaveEPerformanceModel (§10/§13/§63).

One immutable, versioned, content-addressed artifact binding every
timing-affecting assumption of a Wave-E evaluation:

    performance_model_id = H(tag, schema_version, clocks,
                             compute_model, memory_model,
                             network_timing_model, resources,
                             arbitration policy)

Any change to a timing-affecting field changes the identity. Host data
(paths, wall time) never enters. The model carries no measured values
that lack provenance: rates are declared ANALYTICAL/UNCALIBRATED here
because the repository holds no calibration dataset.
"""
from __future__ import annotations


def _freeze(self, name: str, value: object) -> None:
    raise AttributeError(
        f"{type(self).__name__} is immutable (Wave-E §11); construct a new instance instead")

from fractions import Fraction
from typing import Any

from veritx_dse.wavee.time import TimeError

SCHEMA_VERSION = 1
_MODEL_TAG = "srota/wavee/performance-model/v1"

COMPUTE_SOURCE_EXPLICIT = "EXPLICIT_DURATION"
COMPUTE_SOURCE_ANALYTICAL = "ANALYTICAL_MODEL"
COMPUTE_SOURCES = (COMPUTE_SOURCE_EXPLICIT, COMPUTE_SOURCE_ANALYTICAL)

ARBITRATION_FIFO = "FIFO_SERIAL"
ARBITRATION_EQUAL_SHARE = "EQUAL_SHARE_BANDWIDTH"
EXCLUSIVE_ARBITRATIONS = (ARBITRATION_FIFO,)
BANDWIDTH_ARBITRATIONS = (ARBITRATION_EQUAL_SHARE,)

RESOURCE_KIND_EXCLUSIVE = "EXCLUSIVE"
RESOURCE_KIND_BANDWIDTH = "BANDWIDTH"
RESOURCE_KINDS = (RESOURCE_KIND_EXCLUSIVE, RESOURCE_KIND_BANDWIDTH)

NETWORK_TIMING_BOOKSIM = "QUALIFIED_BOOKSIM_WINDOW"


class ModelError(Exception):
    """Typed refusal for invalid performance-model construction (§127)."""

    code = "INVALID_PERFORMANCE_MODEL"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _hz(value: Any, what: str) -> int | Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise ModelError(f"{what} must be exact int/Fraction Hz")
    hz = Fraction(value)
    if hz <= 0:
        raise ModelError(f"{what} must be > 0, got {value}")
    return hz


def _bandwidth(value: Any, what: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise ModelError(f"{what} must be exact int/Fraction bytes/s")
    bw = Fraction(value)
    if bw <= 0:
        raise ModelError(f"{what} must be > 0, got {value}")
    return bw


class ClockDef:
    """One named, explicit clock binding (§13). No default 1 GHz."""

    __slots__ = ("name", "hz")

    __setattr__ = _freeze

    def __init__(self, name: str, hz: int | Fraction) -> None:
        if not isinstance(name, str) or not name:
            raise ModelError("clock name must be a non-empty string")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "hz", _hz(hz, f"clock {name!r}"))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "hz_num": self.hz.numerator,
                "hz_den": self.hz.denominator}

    @staticmethod
    def from_dict(d: Any) -> "ClockDef":
        if not isinstance(d, dict) or set(d) != {"name", "hz_num", "hz_den"}:
            raise ModelError(f"clock dict malformed: {d!r}")
        return ClockDef(d["name"],
                        Fraction(d["hz_num"], d["hz_den"]))


class ResourceDef:
    """One resource: EXCLUSIVE capacity>=1 or BANDWIDTH bytes/s>0 (§19)."""

    __slots__ = ("name", "kind", "capacity", "bandwidth_bps")

    __setattr__ = _freeze

    def __init__(self, name: str, kind: str, *,
                 capacity: int | None = None,
                 bandwidth_bytes_per_s: int | Fraction | None = None
                 ) -> None:
        if not isinstance(name, str) or not name:
            raise ModelError("resource name must be a non-empty string")
        if kind == RESOURCE_KIND_EXCLUSIVE:
            if capacity is None:
                raise ModelError(f"exclusive resource {name!r} needs capacity")
            if isinstance(capacity, bool) or not isinstance(capacity, int) \
                    or capacity < 1:
                raise ModelError(
                    f"capacity must be int >= 1, got {capacity!r} (§127)")
            cap: int | None = capacity
            bw: Fraction | None = None
        elif kind == RESOURCE_KIND_BANDWIDTH:
            if bandwidth_bytes_per_s is None:
                raise ModelError(
                    f"bandwidth resource {name!r} needs bandwidth_bytes_per_s")
            bw = _bandwidth(bandwidth_bytes_per_s,
                            f"bandwidth {name!r}")
            cap = None
        else:
            raise ModelError(
                f"resource kind must be one of {RESOURCE_KINDS}, got {kind!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "capacity", cap)
        object.__setattr__(self, "bandwidth_bps", bw)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "kind": self.kind}
        if self.kind == RESOURCE_KIND_EXCLUSIVE:
            d["capacity"] = self.capacity
        else:
            d["bandwidth_bps_num"] = self.bandwidth_bps.numerator
            d["bandwidth_bps_den"] = self.bandwidth_bps.denominator
        return d

    @staticmethod
    def from_dict(d: Any) -> "ResourceDef":
        if not isinstance(d, dict) or "name" not in d or "kind" not in d:
            raise ModelError(f"resource dict malformed: {d!r}")
        if d["kind"] == RESOURCE_KIND_EXCLUSIVE:
            return ResourceDef(d["name"], d["kind"], capacity=d.get("capacity"))
        if d["kind"] == RESOURCE_KIND_BANDWIDTH:
            return ResourceDef(
                d["name"], d["kind"],
                bandwidth_bytes_per_s=Fraction(d["bandwidth_bps_num"],
                                               d["bandwidth_bps_den"]))
        raise ModelError(f"unknown resource kind {d['kind']!r}")


class WaveEPerformanceModel:
    """Immutable binding of every timing-affecting assumption (§10)."""

    __slots__ = ("clocks", "resources", "compute_source",
                 "network_timing_model", "network_clock",
                 "arbitration_exclusive", "arbitration_bandwidth", "_id")

    __setattr__ = _freeze

    def __init__(self, *, clocks: tuple[ClockDef, ...],
                 resources: tuple[ResourceDef, ...],
                 compute_source: str = COMPUTE_SOURCE_EXPLICIT,
                 network_timing_model: str = NETWORK_TIMING_BOOKSIM,
                 network_clock: str | None = None,
                 arbitration_exclusive: str = ARBITRATION_FIFO,
                 arbitration_bandwidth: str = ARBITRATION_EQUAL_SHARE
                 ) -> None:
        # §20: the contention policy is DECLARED and identity-bearing.
        # Two evaluations under different arbitration are different
        # performance models; an undeclared policy would be a hidden
        # timing assumption.
        if arbitration_exclusive not in EXCLUSIVE_ARBITRATIONS:
            raise ModelError(
                f"arbitration_exclusive must be one of "
                f"{EXCLUSIVE_ARBITRATIONS}, got "
                f"{arbitration_exclusive!r}")
        if arbitration_bandwidth not in BANDWIDTH_ARBITRATIONS:
            raise ModelError(
                f"arbitration_bandwidth must be one of "
                f"{BANDWIDTH_ARBITRATIONS}, got "
                f"{arbitration_bandwidth!r}")
        if compute_source not in COMPUTE_SOURCES:
            raise ModelError(
                f"compute_source must be one of {COMPUTE_SOURCES}, "
                f"got {compute_source!r}")
        if network_timing_model != NETWORK_TIMING_BOOKSIM:
            raise ModelError(
                "network_timing_model must be QUALIFIED_BOOKSIM_WINDOW; "
                "other network timing authorities are not established")
        if not clocks:
            raise ModelError(
                "at least one explicit clock is required (no default 1GHz, "
                "§13/§127)")
        names = [c.name for c in clocks]
        if len(names) != len(set(names)):
            raise ModelError("clock names must be unique")
        rnames = [r.name for r in resources]
        if len(rnames) != len(set(rnames)):
            raise ModelError("resource names must be unique")
        if not resources:
            raise ModelError("at least one resource is required")
        if network_clock is not None and \
                network_clock not in set(names):
            raise ModelError(
                f"network_clock {network_clock!r} must name a bound clock")
        if network_clock is None:
            raise ModelError(
                "network_clock must name the clock converting BookSim "
                "cycles to seconds (§13/§37)")
        object.__setattr__(self, "clocks", tuple(clocks))
        object.__setattr__(self, "resources", tuple(resources))
        object.__setattr__(self, "compute_source", compute_source)
        object.__setattr__(self, "network_timing_model",
                           network_timing_model)
        object.__setattr__(self, "network_clock", network_clock)
        object.__setattr__(self, "arbitration_exclusive",
                           arbitration_exclusive)
        object.__setattr__(self, "arbitration_bandwidth",
                           arbitration_bandwidth)
        object.__setattr__(self, "_id", None)

    # ── identity ────────────────────────────────────────────────
    def canonical(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "clocks": [c.to_dict() for c in self.clocks],
            "compute_source": self.compute_source,
            "network_timing_model": self.network_timing_model,
            "network_clock": self.network_clock,
            "arbitration_exclusive": self.arbitration_exclusive,
            "arbitration_bandwidth": self.arbitration_bandwidth,
            "resources": [r.to_dict() for r in self.resources],
        }

    def performance_model_id(self) -> str:
        if self._id is None:
            import hashlib
            from veritx_dse.core.spec import canonical_json
            body = _MODEL_TAG + "\0" + canonical_json(self.canonical())
            object.__setattr__(self, "_id",
                               hashlib.sha256(body.encode()).hexdigest())
        return self._id

    def clock_hz(self, name: str) -> Fraction:
        for c in self.clocks:
            if c.name == name:
                return c.hz
        raise ModelError(f"unknown clock {name!r}")

    def resource(self, name: str) -> ResourceDef:
        for r in self.resources:
            if r.name == name:
                return r
        raise ModelError(f"unknown resource {name!r}")

    # ── serialization ───────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return self.canonical()

    @staticmethod
    def from_dict(d: Any) -> "WaveEPerformanceModel":
        if not isinstance(d, dict):
            raise ModelError("performance model must be a dict")
        allowed = {"schema_version", "clocks", "compute_source",
                   "network_timing_model", "network_clock", "resources",
                   "arbitration_exclusive", "arbitration_bandwidth"}
        if set(d) != allowed:
            raise ModelError(
                f"performance model fields must be exactly {sorted(allowed)}, "
                f"got {sorted(d)}")
        if d["schema_version"] != SCHEMA_VERSION:
            raise ModelError(
                f"schema_version must be {SCHEMA_VERSION}")
        clocks = tuple(ClockDef.from_dict(c) for c in d["clocks"])
        resources = tuple(ResourceDef.from_dict(r) for r in d["resources"])
        return WaveEPerformanceModel(
            clocks=clocks, resources=resources,
            compute_source=d["compute_source"],
            network_timing_model=d["network_timing_model"],
            network_clock=d["network_clock"],
            arbitration_exclusive=d["arbitration_exclusive"],
            arbitration_bandwidth=d["arbitration_bandwidth"])


def rate_duration(bytes_count: int, bandwidth_bps: int | Fraction,
                  latency: int | Fraction = 0) -> Fraction:
    """Analytical transfer: T = latency + bytes / bandwidth (§30).

    Exact rational. This is a *declared analytical model*, not an HBM
    prediction; the caller binds it into model identity via the
    resource/bandwidth definitions.
    """
    if isinstance(bytes_count, bool) or not isinstance(bytes_count, int) \
            or bytes_count < 0:
        raise ModelError(f"bytes_count must be int >= 0, got {bytes_count!r}")
    bw = _bandwidth(bandwidth_bps, "bandwidth")
    if isinstance(latency, bool) or not isinstance(latency, (int, Fraction)) \
            or latency < 0:
        raise ModelError("latency must be exact and >= 0")
    lat = Fraction(latency)
    return lat + Fraction(bytes_count, 1) / bw
