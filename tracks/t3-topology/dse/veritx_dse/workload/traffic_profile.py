"""veritx_dse.workload.traffic_profile — strict single-class traffic profiles.

This module is a self-contained front end for the BookSim trace dialect
``cyc src cl dst sz`` (five whitespace-separated columns).  It does not
lower a topology and it does not run BookSim; it turns a small, declarative
set of initiator profiles into trace bytes and validates those bytes with the
same strict scanner the certified backend uses
(:func:`veritx_dse.backend.booksim._scan_trace`).

Scope and non-goals
-------------------
* **Single class only.**  The raw standalone BookSim path binds
  ``classes=1``, so every emitted row uses class index 0 and a spec may name
  exactly one ``traffic_class``.  Multi-class inputs are refused with
  :class:`TrafficProfileError` instead of being silently collapsed.
* **Deterministic.**  No randomness is used; ``seed`` is validated and
  reserved for a later stochastic extension.  The same spec always yields the
  same bytes.
* **Metadata stays metadata.**  ``protocol``, ``qos_class`` and
  ``latency_target_cycles`` are validated and preserved on the profile, but
  they do not alter the generated trace.
* **Outstanding is latency-bound.**  A request occupies an outstanding slot
  from its issue cycle until ``issue + response_latency_cycles``.  Real
  protocol credit return, retries and variable latency are out of scope.

Generation model
----------------
Each initiator has an independent token bucket holding flits.  It starts at
``burst_flits``, is refilled by ``rate_flits_per_cycle`` at the start of each
cycle, and is capped at ``burst_flits``.  A request costs ``packet_flits``
tokens; responses and write acknowledgements do not consume tokens.  Targets
are selected round-robin in issue order, and reads/writes follow an exact
credit accumulator over ``read_write_ratio``.  A request completes at
``issue_cycle + response_latency_cycles``; a zero-latency completion frees its
outstanding slot immediately.

Rationale: docs/decisions/modules/workload.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from veritx_dse.core.errors import SemanticError

# The certified backend owns the single strict parser for the BookSim trace
# dialect.  Importing the private scanner keeps this front end from growing a
# second, subtly different grammar; it is the same validator the runner uses
# before a certified simulation.
from veritx_dse.backend.booksim import (
    BookSimLoweringError,
    TraceSummary,
    _scan_trace,
)

SCHEMA = "veritx/traffic-profile/1"

# All six top-level keys are required.  Optionality is expressed only where
# the dataclass declares a default (flit_width_bits, protocol, qos_class,
# latency_target_cycles).
_TOP_LEVEL_KEYS = frozenset({
    "schema",
    "endpoint_count",
    "max_packet_flits",
    "cycles",
    "seed",
    "profiles",
})

_PROFILE_KEYS = frozenset({
    "name",
    "src",
    "targets",
    "traffic_class",
    "payload_bytes",
    "flit_width_bits",
    "rate_flits_per_cycle",
    "burst_flits",
    "outstanding",
    "read_write_ratio",
    "response_latency_cycles",
    "start_cycle",
    "requests",
    "protocol",
    "qos_class",
    "latency_target_cycles",
})

_PROFILE_REQUIRED = frozenset({
    "name",
    "src",
    "targets",
    "traffic_class",
    "payload_bytes",
    "rate_flits_per_cycle",
    "burst_flits",
    "outstanding",
    "read_write_ratio",
    "response_latency_cycles",
    "start_cycle",
    "requests",
})

_RATIO_PART_RE = re.compile(r"[0-9]+")


class TrafficProfileError(ValueError, SemanticError):
    """Typed refusal for an unsupported or malformed traffic profile."""

    code = "TRAFFIC_PROFILE_REFUSED"


def _require_mapping(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise TrafficProfileError(
            f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(mapping: dict, allowed: frozenset[str],
                    where: str) -> None:
    unknown = sorted(set(mapping) - allowed, key=repr)
    if unknown:
        raise TrafficProfileError(
            f"{where} has unknown keys {unknown}; "
            f"allowed keys: {sorted(allowed)}")


def _require_keys(mapping: dict, required: frozenset[str],
                  where: str) -> None:
    missing = sorted(required - set(mapping))
    if missing:
        raise TrafficProfileError(
            f"{where} is missing required keys {missing}")


def _require_int(field: str, value: object,
                 *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise TrafficProfileError(
            f"{field} must be an int, got {type(value).__name__}: {value!r}")
    if minimum is not None and value < minimum:
        raise TrafficProfileError(
            f"{field} must be >= {minimum}, got {value}")
    return value


def _require_optional_int(field: str, value: object,
                          *, minimum: int | None = None) -> int | None:
    if value is None:
        return None
    return _require_int(field, value, minimum=minimum)


def _require_text(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise TrafficProfileError(
            f"{field} must be a string, got {type(value).__name__}: "
            f"{value!r}")
    if not value.strip():
        raise TrafficProfileError(
            f"{field} must be a non-empty string, got {value!r}")
    return value


def _parse_rate(field: str, value: object) -> Fraction:
    """Parse an exact positive rate from a rational string, int or float."""
    if isinstance(value, bool):
        raise TrafficProfileError(
            f"{field} must not be a bool; pass a rate like '0.25' or '1/4'")
    if isinstance(value, Fraction):
        rate = value
    elif isinstance(value, int):
        rate = Fraction(str(value))
    elif isinstance(value, float):
        try:
            exact = Fraction(value)
        except (ValueError, OverflowError) as exc:
            raise TrafficProfileError(
                f"{field} is not a finite rational: {value!r}") from exc
        rate = exact.limit_denominator()
        if rate != exact:
            raise TrafficProfileError(
                f"{field} float {value!r} is not exactly representable as a "
                "rational; pass a string such as '0.25' or '1/4'")
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise TrafficProfileError(f"{field} must not be empty")
        try:
            rate = Fraction(text)
        except (ValueError, ZeroDivisionError) as exc:
            raise TrafficProfileError(
                f"{field} is not a valid rational: {value!r} "
                f"({exc})") from exc
    else:
        raise TrafficProfileError(
            f"{field} must be a string, int, Fraction or exactly "
            f"representable float, got {type(value).__name__}: {value!r}")
    if rate <= 0:
        raise TrafficProfileError(f"{field} must be > 0, got {rate}")
    return rate


def _parse_ratio(field: str, value: object) -> tuple[int, int]:
    """Parse ``"reads:writes"`` or a two-element sequence into a tuple."""
    if isinstance(value, str):
        text = value.strip()
        parts = text.split(":")
        if len(parts) != 2 or not all(
                _RATIO_PART_RE.fullmatch(part) for part in parts):
            raise TrafficProfileError(
                f"{field} must look like 'reads:writes' with non-negative "
                f"integers, got {value!r}")
        reads, writes = int(parts[0]), int(parts[1])
    elif isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise TrafficProfileError(
                f"{field} must have exactly two entries, got {value!r}")
        reads, writes = value
    else:
        raise TrafficProfileError(
            f"{field} must be a 'reads:writes' string or a two-element "
            f"sequence, got {type(value).__name__}: {value!r}")

    if type(reads) is not int or type(writes) is not int:
        raise TrafficProfileError(
            f"{field} entries must be ints, got {reads!r} and {writes!r}")
    if reads < 0 or writes < 0:
        raise TrafficProfileError(
            f"{field} entries must be >= 0, got {reads!r} and {writes!r}")
    if reads + writes <= 0:
        raise TrafficProfileError(
            f"{field} must have a positive total, got {reads!r}:{writes!r}")
    return (reads, writes)


@dataclass(frozen=True)
class InitiatorProfile:
    """One deterministic traffic initiator.

    The first twelve fields are required; ``flit_width_bits``, ``protocol``,
    ``qos_class`` and ``latency_target_cycles`` have defaults.  ``protocol``,
    ``qos_class`` and ``latency_target_cycles`` are metadata only.
    """

    name: str
    src: int
    targets: tuple[int, ...]
    traffic_class: str
    payload_bytes: int
    rate_flits_per_cycle: Fraction
    burst_flits: int
    outstanding: int
    read_write_ratio: tuple[int, int]
    response_latency_cycles: int
    start_cycle: int
    requests: int | None
    flit_width_bits: int = 64
    protocol: str = "AXI"
    qos_class: str = "best_effort"
    latency_target_cycles: int | None = None

    def __post_init__(self) -> None:
        _require_text("InitiatorProfile.name", self.name)
        _require_int("InitiatorProfile.src", self.src, minimum=0)
        if not isinstance(self.targets, tuple):
            raise TrafficProfileError(
                "InitiatorProfile.targets must be a tuple of ints, got "
                f"{type(self.targets).__name__}")
        if not self.targets:
            raise TrafficProfileError(
                "InitiatorProfile.targets must be a non-empty tuple")
        for index, target in enumerate(self.targets):
            _require_int(f"InitiatorProfile.targets[{index}]", target,
                         minimum=0)
        if len(set(self.targets)) != len(self.targets):
            raise TrafficProfileError(
                "InitiatorProfile.targets must be unique, got "
                f"{self.targets!r}")
        if self.src in self.targets:
            raise TrafficProfileError(
                f"InitiatorProfile.targets must not contain src {self.src}")
        _require_text("InitiatorProfile.traffic_class", self.traffic_class)
        _require_int("InitiatorProfile.payload_bytes", self.payload_bytes,
                     minimum=1)
        _require_int("InitiatorProfile.flit_width_bits", self.flit_width_bits,
                     minimum=1)
        if not isinstance(self.rate_flits_per_cycle, Fraction):
            raise TrafficProfileError(
                "InitiatorProfile.rate_flits_per_cycle must be a Fraction, "
                f"got {type(self.rate_flits_per_cycle).__name__}: "
                f"{self.rate_flits_per_cycle!r}")
        if self.rate_flits_per_cycle <= 0:
            raise TrafficProfileError(
                "InitiatorProfile.rate_flits_per_cycle must be > 0, got "
                f"{self.rate_flits_per_cycle}")
        _require_int("InitiatorProfile.burst_flits", self.burst_flits,
                     minimum=1)
        _require_int("InitiatorProfile.outstanding", self.outstanding,
                     minimum=1)
        if not isinstance(self.read_write_ratio, tuple) or \
                len(self.read_write_ratio) != 2:
            raise TrafficProfileError(
                "InitiatorProfile.read_write_ratio must be a two-element "
                f"tuple, got {self.read_write_ratio!r}")
        reads, writes = self.read_write_ratio
        _require_int("InitiatorProfile.read_write_ratio[0]", reads,
                     minimum=0)
        _require_int("InitiatorProfile.read_write_ratio[1]", writes,
                     minimum=0)
        if reads + writes <= 0:
            raise TrafficProfileError(
                "InitiatorProfile.read_write_ratio must have a positive "
                f"total, got {reads!r}:{writes!r}")
        _require_int("InitiatorProfile.response_latency_cycles",
                     self.response_latency_cycles, minimum=0)
        _require_int("InitiatorProfile.start_cycle", self.start_cycle,
                     minimum=0)
        _require_optional_int("InitiatorProfile.requests", self.requests,
                              minimum=1)
        _require_text("InitiatorProfile.protocol", self.protocol)
        _require_text("InitiatorProfile.qos_class", self.qos_class)
        _require_optional_int("InitiatorProfile.latency_target_cycles",
                              self.latency_target_cycles, minimum=0)
        if self.burst_flits < self.packet_flits:
            raise TrafficProfileError(
                f"InitiatorProfile.burst_flits ({self.burst_flits}) must be "
                f">= packet_flits ({self.packet_flits})")

    @property
    def packet_flits(self) -> int:
        """Flits needed for one payload packet (ceiling division)."""
        bits = self.payload_bytes * 8
        return (bits + self.flit_width_bits - 1) // self.flit_width_bits


@dataclass(frozen=True)
class TrafficProfileSpec:
    """A validated, single-class set of initiator profiles."""

    profiles: tuple[InitiatorProfile, ...]
    endpoint_count: int
    max_packet_flits: int
    cycles: int
    seed: int

    def __post_init__(self) -> None:
        if not isinstance(self.profiles, tuple):
            raise TrafficProfileError(
                "TrafficProfileSpec.profiles must be a tuple, got "
                f"{type(self.profiles).__name__}")
        if not self.profiles:
            raise TrafficProfileError(
                "TrafficProfileSpec.profiles must not be empty")
        for index, profile in enumerate(self.profiles):
            if not isinstance(profile, InitiatorProfile):
                raise TrafficProfileError(
                    f"TrafficProfileSpec.profiles[{index}] must be an "
                    f"InitiatorProfile, got {type(profile).__name__}")
        _require_int("TrafficProfileSpec.endpoint_count",
                     self.endpoint_count, minimum=1)
        _require_int("TrafficProfileSpec.max_packet_flits",
                     self.max_packet_flits, minimum=1)
        _require_int("TrafficProfileSpec.cycles", self.cycles, minimum=1)
        _require_int("TrafficProfileSpec.seed", self.seed, minimum=0)

        names: dict[str, int] = {}
        sources: dict[int, int] = {}
        classes: set[str] = set()
        for index, profile in enumerate(self.profiles):
            if profile.name in names:
                raise TrafficProfileError(
                    "TrafficProfileSpec.profiles has duplicate profile name "
                    f"{profile.name!r} at profiles[{names[profile.name]}] "
                    f"and profiles[{index}]")
            names[profile.name] = index
            if profile.src in sources:
                raise TrafficProfileError(
                    "TrafficProfileSpec.profiles has duplicate src "
                    f"{profile.src} at profiles[{sources[profile.src]}] "
                    f"and profiles[{index}]")
            sources[profile.src] = index
            if profile.src >= self.endpoint_count:
                raise TrafficProfileError(
                    f"TrafficProfileSpec.profiles[{index}].src "
                    f"{profile.src} is outside [0, {self.endpoint_count})")
            for target_index, target in enumerate(profile.targets):
                if target >= self.endpoint_count:
                    raise TrafficProfileError(
                        f"TrafficProfileSpec.profiles[{index}]."
                        f"targets[{target_index}] {target} is outside "
                        f"[0, {self.endpoint_count})")
            if profile.packet_flits > self.max_packet_flits:
                raise TrafficProfileError(
                    f"TrafficProfileSpec.profiles[{index}] needs "
                    f"{profile.packet_flits} packet flits, exceeding "
                    f"max_packet_flits {self.max_packet_flits}")
            classes.add(profile.traffic_class)
        if len(classes) != 1:
            raise TrafficProfileError(
                "TrafficProfileSpec.profiles must share exactly one "
                "traffic_class (the standalone BookSim path is single-class); "
                f"got {sorted(classes)}")

    @classmethod
    def from_dict(cls, d: object) -> "TrafficProfileSpec":
        """Strictly parse the ``veritx/traffic-profile/1`` document shape."""
        mapping = _require_mapping(d, "traffic profile spec")
        _reject_unknown(mapping, _TOP_LEVEL_KEYS, "traffic profile spec")
        _require_keys(mapping, _TOP_LEVEL_KEYS, "traffic profile spec")
        if mapping["schema"] != SCHEMA:
            raise TrafficProfileError(
                f"traffic profile spec schema must be {SCHEMA!r}, got "
                f"{mapping['schema']!r}")
        endpoint_count = _require_int(
            "endpoint_count", mapping["endpoint_count"], minimum=1)
        max_packet_flits = _require_int(
            "max_packet_flits", mapping["max_packet_flits"], minimum=1)
        cycles = _require_int("cycles", mapping["cycles"], minimum=1)
        seed = _require_int("seed", mapping["seed"], minimum=0)

        raw_profiles = mapping["profiles"]
        if not isinstance(raw_profiles, (list, tuple)):
            raise TrafficProfileError(
                "profiles must be a list, got "
                f"{type(raw_profiles).__name__}")
        if not raw_profiles:
            raise TrafficProfileError("profiles must not be empty")
        profiles = tuple(
            _profile_from_dict(item, index=index)
            for index, item in enumerate(raw_profiles)
        )
        return cls(
            profiles=profiles,
            endpoint_count=endpoint_count,
            max_packet_flits=max_packet_flits,
            cycles=cycles,
            seed=seed,
        )


def _profile_from_dict(value: object, *, index: int) -> InitiatorProfile:
    where = f"profiles[{index}]"
    mapping = _require_mapping(value, where)
    _reject_unknown(mapping, _PROFILE_KEYS, where)
    _require_keys(mapping, _PROFILE_REQUIRED, where)

    raw_targets = mapping["targets"]
    if not isinstance(raw_targets, (list, tuple)):
        raise TrafficProfileError(
            f"{where}.targets must be a list of ints, got "
            f"{type(raw_targets).__name__}")
    targets = tuple(
        _require_int(f"{where}.targets[{target_index}]", target, minimum=0)
        for target_index, target in enumerate(raw_targets)
    )

    return InitiatorProfile(
        name=_require_text(f"{where}.name", mapping["name"]),
        src=_require_int(f"{where}.src", mapping["src"], minimum=0),
        targets=targets,
        traffic_class=_require_text(
            f"{where}.traffic_class", mapping["traffic_class"]),
        payload_bytes=_require_int(
            f"{where}.payload_bytes", mapping["payload_bytes"], minimum=1),
        flit_width_bits=_require_int(
            f"{where}.flit_width_bits",
            mapping.get("flit_width_bits", 64), minimum=1),
        rate_flits_per_cycle=_parse_rate(
            f"{where}.rate_flits_per_cycle",
            mapping["rate_flits_per_cycle"]),
        burst_flits=_require_int(
            f"{where}.burst_flits", mapping["burst_flits"], minimum=1),
        outstanding=_require_int(
            f"{where}.outstanding", mapping["outstanding"], minimum=1),
        read_write_ratio=_parse_ratio(
            f"{where}.read_write_ratio", mapping["read_write_ratio"]),
        response_latency_cycles=_require_int(
            f"{where}.response_latency_cycles",
            mapping["response_latency_cycles"], minimum=0),
        start_cycle=_require_int(
            f"{where}.start_cycle", mapping["start_cycle"], minimum=0),
        requests=_require_optional_int(
            f"{where}.requests", mapping["requests"], minimum=1),
        protocol=_require_text(
            f"{where}.protocol", mapping.get("protocol", "AXI")),
        qos_class=_require_text(
            f"{where}.qos_class", mapping.get("qos_class", "best_effort")),
        latency_target_cycles=_require_optional_int(
            f"{where}.latency_target_cycles",
            mapping.get("latency_target_cycles"), minimum=0),
    )


def scan_trace(data: bytes, *, endpoint_count: int,
               max_packet_flits: int) -> TraceSummary:
    """Validate BookSim trace bytes with the certified strict scanner.

    The whitespace dialect additionally carries a class index in column 3.
    This front end emits class 0 only, because the raw standalone BookSim
    path binds ``classes=1``; any other class index is refused here rather
    than silently accepted.  CSV traces carry a type label instead of a
    class index and are left to the shared scanner.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TrafficProfileError(
            f"trace data must be bytes, got {type(data).__name__}")
    _require_int("endpoint_count", endpoint_count, minimum=1)
    _require_int("max_packet_flits", max_packet_flits, minimum=1)
    payload = bytes(data)
    try:
        summary = _scan_trace(
            payload,
            endpoint_count=endpoint_count,
            max_packet_flits=max_packet_flits,
        )
    except BookSimLoweringError as exc:
        raise TrafficProfileError(
            f"invalid BookSim trace: {exc}") from exc

    if summary.dialect == "whitespace":
        for line_no, raw in enumerate(payload.decode().splitlines(), 1):
            line = raw.strip()
            if not line or line[0] in ("#", "%"):
                continue
            class_index = int(line.split()[2])
            if class_index != 0:
                raise TrafficProfileError(
                    f"trace line {line_no}: class index {class_index} is "
                    "unsupported; the standalone BookSim path binds "
                    "classes=1, so only class 0 is representable")
    return summary


def _profile_rows(spec: TrafficProfileSpec,
                  profile: InitiatorProfile
                  ) -> list[tuple[int, int, int, int, int]]:
    """Simulate one initiator and return ``(cycle, src, cl, dst, flits)``."""
    packet_flits = profile.packet_flits
    burst = Fraction(profile.burst_flits)
    tokens = burst
    rate = profile.rate_flits_per_cycle
    reads, writes = profile.read_write_ratio
    ratio_total = reads + writes
    write_credit = 0
    in_flight: list[int] = []
    target_index = 0
    issued = 0
    rows: list[tuple[int, int, int, int, int]] = []

    for cycle in range(profile.start_cycle,
                       profile.start_cycle + spec.cycles):
        # Refill first, then release completions.  The bucket starts full, so
        # the cycle-0 refill is capped and the burst is available immediately.
        tokens = min(burst, tokens + rate)
        if in_flight:
            in_flight = [done for done in in_flight if done > cycle]

        while (len(in_flight) < profile.outstanding
               and tokens >= packet_flits
               and (profile.requests is None or issued < profile.requests)):
            target = profile.targets[target_index % len(profile.targets)]
            target_index += 1

            # Exact read/write interleaving: over one period the sequence has
            # exactly ``reads`` reads and ``writes`` writes.  Adding the write
            # weight first makes a 2:1 ratio start R,R,W rather than W,R,R.
            write_credit += writes
            if write_credit >= ratio_total:
                write_credit -= ratio_total
                is_write = True
            else:
                is_write = False

            completion = cycle + profile.response_latency_cycles
            rows.append((cycle, profile.src, 0, target, packet_flits))
            rows.append((completion, target, 0, profile.src,
                         1 if is_write else packet_flits))
            tokens -= packet_flits
            issued += 1
            # A zero-latency completion is already done; it must not occupy an
            # outstanding slot for the rest of this cycle.
            if completion > cycle:
                in_flight.append(completion)

    return rows


def generate_trace(spec: TrafficProfileSpec) -> bytes:
    """Generate a deterministic, strictly validated single-class trace."""
    if not isinstance(spec, TrafficProfileSpec):
        raise TrafficProfileError(
            f"spec must be a TrafficProfileSpec, got {type(spec).__name__}")

    rows: list[tuple[int, int, int, int, int]] = []
    for profile in spec.profiles:
        rows.extend(_profile_rows(spec, profile))
    if not rows:
        raise TrafficProfileError(
            "traffic profile generated zero packets; refusing an empty trace")

    # Canonical order: responses/acks may share a cycle with requests and may
    # lie beyond the generation window, so sort the complete row set.
    rows.sort(key=lambda row: (row[0], row[1], row[3], row[4]))
    data = "".join(
        f"{cycle} {src} 0 {dst} {flits}\n"
        for cycle, src, _class_index, dst, flits in rows
    ).encode("ascii")

    try:
        scan_trace(
            data,
            endpoint_count=spec.endpoint_count,
            max_packet_flits=spec.max_packet_flits,
        )
    except TrafficProfileError as exc:
        raise TrafficProfileError(
            f"generated trace failed strict validation: {exc}") from exc
    return data


__all__ = [
    "InitiatorProfile",
    "TrafficProfileError",
    "TrafficProfileSpec",
    "generate_trace",
    "scan_trace",
]
