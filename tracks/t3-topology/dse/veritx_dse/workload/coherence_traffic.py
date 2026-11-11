"""Synthetic coherency traffic: deterministic MSI miss-sequence intents.

WHAT THIS IS
------------
A small, self-contained front end that turns a declarative
:class:`CoherenceTrafficSpec` into request-level
:class:`~veritx_dse.model.compile_model.CoherenceIntent` objects and applies
them to a v4 compile request.  It reuses the EXISTING coherence seam: the
same ``CoherencePattern`` values, the same ``CoherenceIntent`` payload, the
same ``KIND_COHERENCE`` lowering, and the same REQ/RSP/SNP/ACK message
fanout.  It adds no protocol model and no new message kind.

TRAFFIC SHAPE ONLY
------------------
An intent declares the traffic a miss sequence emits.  It does NOT model
directory state, exclusivity, ownership transfer, writeback races, cache
hits, retries, or protocol correctness.  The existing lowering also places
every COHERENCE operation at ``step=0``; this module does not add a temporal
or rate model.

DETERMINISTIC ENUMERATION
-------------------------
For every home (declared order), every pattern (declared order), and every
repetition in ``range(intents_per_pattern)`` exactly one intent is emitted.
``seed`` is validated and reserved for a future stochastic extension; no
randomness is used, so the same spec always yields the same intents.

SHARER DERIVATION
-----------------
When ``sharers`` is omitted, ``sharing_degree`` selects the sharer set per
home as follows:

* Candidate ranks are visited starting at ``home_rank + 1`` and wrapping
  through ``world_size - 1`` back to ``0``, skipping ``home_rank`` and, when
  a writer is declared, skipping the writer.
* For a spec that declares ``WRITE_INVALIDATE``, the writer is added first
  so the declared writer is always a sharer; the remaining slots are filled
  from that wrapping order.
* The result is sorted ascending before it is returned, so the derived set
  is a deterministic, order-stable tuple for a given spec and home.

The explicit ``sharers`` path is validated as declared: non-empty, unique,
in range, and disjoint from every home.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compile_model import CoherenceIntent, CoherencePattern
from veritx_dse.model.compile_request_v4 import CompileRequestV4

READ_SHARED = CoherencePattern.READ_SHARED.value
WRITE_INVALIDATE = CoherencePattern.WRITE_INVALIDATE.value
PATTERNS = frozenset({READ_SHARED, WRITE_INVALIDATE})
DEFAULT_TRAFFIC_CLASS = "coherence"


class CoherenceTrafficError(ValueError, SemanticError):
    """Typed refusal for a malformed or unbounded coherence traffic spec."""

    code = "COHERENCE_TRAFFIC_REFUSED"


def _require_int(name: str, value: object, *, minimum: int) -> int:
    if type(value) is not int:
        raise CoherenceTrafficError(
            f"{name} must be an int, got {type(value).__name__}: {value!r}")
    if value < minimum:
        raise CoherenceTrafficError(
            f"{name} must be >= {minimum}, got {value}")
    return value


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise CoherenceTrafficError(
            f"{name} must be a string, got {type(value).__name__}: "
            f"{value!r}")
    if not value.strip():
        raise CoherenceTrafficError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


def _require_tuple(name: str, value: object) -> tuple:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, tuple):
        return value
    raise CoherenceTrafficError(
        f"{name} must be a list or tuple, got {type(value).__name__}")


def _require_rank_tuple(name: str, value: object,
                        world_size: int) -> tuple[int, ...]:
    ranks = _require_tuple(name, value)
    if not ranks:
        raise CoherenceTrafficError(f"{name} must not be empty")
    for index, rank in enumerate(ranks):
        if type(rank) is not int:
            raise CoherenceTrafficError(
                f"{name}[{index}] must be an int, got "
                f"{type(rank).__name__}: {rank!r}")
        if rank < 0 or rank >= world_size:
            raise CoherenceTrafficError(
                f"{name}[{index}] {rank} is outside [0, {world_size})")
    if len(set(ranks)) != len(ranks):
        raise CoherenceTrafficError(
            f"{name} has duplicates: {sorted(ranks)}")
    return ranks


def _pattern_value(name: str, value: object) -> str:
    if isinstance(value, CoherencePattern):
        return value.value
    if not isinstance(value, str):
        raise CoherenceTrafficError(
            f"{name} must be a string, got {type(value).__name__}: "
            f"{value!r}")
    if value not in PATTERNS:
        raise CoherenceTrafficError(
            f"{name} {value!r} is outside {sorted(PATTERNS)} "
            "(MSI miss-sequence traffic shapes only)")
    return value


@dataclass(frozen=True)
class CoherenceTrafficSpec:
    """A validated, deterministic description of synthetic coherence traffic.

    ``intents_per_pattern`` is applied per home AND per pattern; the total
    intent count is ``len(homes) * len(patterns) * intents_per_pattern``.
    Exactly one of ``sharers`` or ``sharing_degree`` must be supplied.
    """

    world_size: int
    homes: tuple[int, ...]
    patterns: tuple[str, ...]
    lines: int
    line_bytes: int
    intents_per_pattern: int = 1
    max_intents: int = 64
    traffic_class: str = DEFAULT_TRAFFIC_CLASS
    sharers: tuple[int, ...] | None = None
    sharing_degree: int | None = None
    writer: int | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        world_size = _require_int("world_size", self.world_size, minimum=2)
        object.__setattr__(self, "world_size", world_size)
        object.__setattr__(
            self, "traffic_class",
            _require_text("traffic_class", self.traffic_class))

        homes = _require_rank_tuple("homes", self.homes, world_size)
        object.__setattr__(self, "homes", homes)

        patterns = _require_tuple("patterns", self.patterns)
        if not patterns:
            raise CoherenceTrafficError("patterns must not be empty")
        normalized = tuple(
            _pattern_value(f"patterns[{index}]", value)
            for index, value in enumerate(patterns))
        object.__setattr__(self, "patterns", normalized)

        object.__setattr__(
            self, "lines", _require_int("lines", self.lines, minimum=1))
        object.__setattr__(
            self, "line_bytes",
            _require_int("line_bytes", self.line_bytes, minimum=1))
        object.__setattr__(
            self, "intents_per_pattern",
            _require_int("intents_per_pattern", self.intents_per_pattern,
                         minimum=1))
        object.__setattr__(
            self, "seed", _require_int("seed", self.seed, minimum=0))
        object.__setattr__(
            self, "max_intents",
            _require_int("max_intents", self.max_intents, minimum=1))

        if self.sharers is not None:
            object.__setattr__(
                self, "sharers",
                _require_rank_tuple("sharers", self.sharers, world_size))
        if self.sharing_degree is not None:
            object.__setattr__(
                self, "sharing_degree",
                _require_int("sharing_degree", self.sharing_degree,
                             minimum=1))
        if (self.sharers is None) == (self.sharing_degree is None):
            raise CoherenceTrafficError(
                "exactly one of sharers or sharing_degree must be declared; "
                f"got sharers={self.sharers!r}, "
                f"sharing_degree={self.sharing_degree!r}")

        if self.writer is not None:
            writer = _require_int("writer", self.writer, minimum=0)
            if writer >= world_size:
                raise CoherenceTrafficError(
                    f"writer {writer} is outside [0, {world_size})")
            object.__setattr__(self, "writer", writer)

        declares_write = WRITE_INVALIDATE in normalized
        if declares_write:
            if self.writer is None:
                raise CoherenceTrafficError(
                    "WRITE_INVALIDATE requires an explicit writer")
        elif self.writer is not None:
            raise CoherenceTrafficError(
                "READ_SHARED must not declare a writer; got "
                f"writer={self.writer!r}")

        if self.writer is not None and self.writer in homes:
            raise CoherenceTrafficError(
                f"writer {self.writer} must not be one of the homes "
                f"{homes}: a home is never one of its own sharers")

        if self.sharers is not None:
            overlap = sorted(set(self.sharers) & set(homes))
            if overlap:
                raise CoherenceTrafficError(
                    f"home_rank(s) {overlap} must not appear among the "
                    f"declared sharers {self.sharers}")
            if self.writer is not None and self.writer not in self.sharers:
                raise CoherenceTrafficError(
                    f"writer {self.writer} is not among the declared "
                    f"sharers {self.sharers}")
        else:
            # Validate the derivation for every home now, not at generation
            # time: an unsatisfiable sharing_degree is a malformed spec.
            for home in homes:
                self.resolved_sharers(home)

    @property
    def intent_count(self) -> int:
        """Total intents this spec generates across homes/patterns/reps."""
        return (len(self.homes) * len(self.patterns)
                * self.intents_per_pattern)

    def resolved_sharers(self, home_rank: int) -> tuple[int, ...]:
        """The sharer set for one home, derived when ``sharers`` is None.

        See the module docstring for the exact derivation rule.  The
        explicit path returns the declared tuple unchanged.
        """
        home = _require_int("home_rank", home_rank, minimum=0)
        if home >= self.world_size:
            raise CoherenceTrafficError(
                f"home_rank {home} is outside [0, {self.world_size})")
        if self.sharers is not None:
            if home in self.sharers:
                raise CoherenceTrafficError(
                    f"home_rank {home} must not appear among the sharers "
                    f"{self.sharers}")
            return self.sharers
        if self.sharing_degree is None:
            raise CoherenceTrafficError(
                "sharing_degree is required when sharers is not declared")

        candidates = list(range(home + 1, self.world_size))
        candidates.extend(range(0, home))
        if self.writer is not None:
            candidates = [rank for rank in candidates
                          if rank != self.writer]
            selected = [self.writer, *candidates]
        else:
            selected = candidates
        if len(selected) < self.sharing_degree:
            raise CoherenceTrafficError(
                f"sharing_degree {self.sharing_degree} needs that many "
                f"sharers besides home {home}, but world_size "
                f"{self.world_size} provides only {len(selected)}")
        return tuple(sorted(selected[:self.sharing_degree]))


def generate_coherence_intents(
        spec: CoherenceTrafficSpec) -> tuple[CoherenceIntent, ...]:
    """Enumerate a spec into deterministic request-level coherence intents.

    Refuses a spec whose total intent count exceeds ``max_intents`` and
    refuses an empty result.  The generated intents share one sharer set,
    line size, line count, and traffic class; only home, pattern, and
    (for writes) writer differ.
    """
    if not isinstance(spec, CoherenceTrafficSpec):
        raise CoherenceTrafficError(
            f"spec must be a CoherenceTrafficSpec, got "
            f"{type(spec).__name__}")

    expected = spec.intent_count
    if expected > spec.max_intents:
        raise CoherenceTrafficError(
            f"coherence traffic would generate {expected} intents "
            f"({len(spec.homes)} home(s) x {len(spec.patterns)} pattern(s) "
            f"x {spec.intents_per_pattern} repetition(s)), exceeding "
            f"max_intents {spec.max_intents}")

    intents: list[CoherenceIntent] = []
    for home in spec.homes:
        sharers = spec.resolved_sharers(home)
        for pattern in spec.patterns:
            writer = spec.writer if pattern == WRITE_INVALIDATE else None
            for _ in range(spec.intents_per_pattern):
                try:
                    intents.append(CoherenceIntent(
                        pattern=CoherencePattern(pattern),
                        home_rank=home,
                        writer_rank=writer,
                        sharers=sharers,
                        line_bytes=spec.line_bytes,
                        lines=spec.lines,
                        traffic_class=spec.traffic_class,
                    ))
                except ValueError as exc:
                    raise CoherenceTrafficError(
                        f"generated coherence intent refuses: {exc}") from exc

    if not intents:
        raise CoherenceTrafficError(
            "coherence traffic generated zero intents; refusing an empty "
            "workload")
    return tuple(intents)


def apply_coherence_traffic(
        base: CompileRequestV4,
        spec: CoherenceTrafficSpec) -> CompileRequestV4:
    """Return a copy of ``base`` whose workload carries the generated intents.

    Every other request field (collectives, agents, requirements, topology,
    dependencies, controls, compute, address map, physical context) is
    preserved exactly.  Existing coherence intents are replaced.  A spec
    world smaller than the request world describes a coherence subset; a
    larger spec world is refused because it would address undeclared ranks.
    """
    if not isinstance(base, CompileRequestV4):
        raise CoherenceTrafficError(
            f"base must be a CompileRequestV4, got {type(base).__name__}")
    if not isinstance(spec, CoherenceTrafficSpec):
        raise CoherenceTrafficError(
            f"spec must be a CoherenceTrafficSpec, got "
            f"{type(spec).__name__}")
    if spec.world_size > base.workload.world_size:
        raise CoherenceTrafficError(
            f"spec world_size {spec.world_size} exceeds the request's "
            f"workload world_size {base.workload.world_size}; generated "
            "ranks would address participants the request does not declare")

    generated = generate_coherence_intents(spec)
    workload = replace(base.workload, coherence=generated)
    return replace(base, workload=workload)


__all__ = [
    "CoherenceTrafficError",
    "CoherenceTrafficSpec",
    "DEFAULT_TRAFFIC_CLASS",
    "PATTERNS",
    "READ_SHARED",
    "WRITE_INVALIDATE",
    "apply_coherence_traffic",
    "generate_coherence_intents",
]
