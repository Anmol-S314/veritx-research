"""veritx_dse.model.placement_contract — P1.10 fixed placement, allowed
movement and locality restrictions.

Scope, explicitly: this contract speaks in LOGICAL rank -> agent-seat
coordinates only. Seat coordinates are AgentInstance coordinates
(group_index, instance_index) from NodeInventory (veritx_dse.model.placement).
This module represents NO cell coordinates, macro placements, die bounds,
keepouts, row/site geometry, PDK, timing, congestion, chiplet/package
hierarchy or floorplan shape. Logical rank mapping and physical cell/macro
positions remain distinct by construction; the geometric router-footprint
model in veritx_dse.model.physical_placement is not consumed here. Pinning a
rank to a seat is not a claim that the agent occupies any physical rectangle.

Gate semantics (the P1.10 pass condition): declared restrictions are enforced
against a provided MappingArtifact and NodeInventory before any expensive
downstream work. An unverifiable restriction refuses the verdict; no
restriction is ever silently satisfied, dropped or guessed. Restrictions are
checked, never solved: this module places nothing and computes no floorplan.

Locality domains are declared data. The author partitions seats into named
domains (for example SROTA island columns); the checker never invents,
imports or derives a topology. Any restriction whose seats land outside every
declared domain is unverifiable and refuses (fail-closed).

Mapped-rank eligibility follows the same law as veritx_dse.model.mapping:
only COMPUTE_TILE instances may host workload ranks.

Exact integer arithmetic only. No floats appear in this module.

Construction-time errors (PlacementContractError) cover shape-invalid data.
Semantic legality against an inventory/mapping is reported through the
Verdict as named Reason codes, never through exceptions, so one pass reports
every blocking problem. The verdict refuses (ok=False) iff at least one
reason is present; Verdict(ok=True, reasons=(...)) is unconstructible.

Not wired into derive_mapping, mapping.py, fabric_compiler.py or any
compiler stage; a placement contract is a standalone gate artifact checked
before compile stages consume placement freedom.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.errors import SemanticError

from .compile_model import AgentKind
from .mapping import MappingArtifact
from .placement import AgentInstance, NodeInventory

PLACEMENT_CONTRACT_SCHEMA_VERSION = 1


class PlacementContractError(ValueError, SemanticError):
    """Shape-invalid placement declaration (fail-closed at construction)."""


class ReasonCode(str, Enum):
    DUPLICATE_PIN_RULE = "DUPLICATE_PIN_RULE"
    DUPLICATE_SEAT_PIN = "DUPLICATE_SEAT_PIN"
    MOVEMENT_WITHOUT_PIN = "MOVEMENT_WITHOUT_PIN"
    DUPLICATE_MOVEMENT_RULE = "DUPLICATE_MOVEMENT_RULE"
    DUPLICATE_DOMAIN = "DUPLICATE_DOMAIN"
    OVERLAPPING_DOMAINS = "OVERLAPPING_DOMAINS"
    UNKNOWN_RANK = "UNKNOWN_RANK"
    UNKNOWN_SEAT = "UNKNOWN_SEAT"
    UNKNOWN_DOMAIN = "UNKNOWN_DOMAIN"
    PIN_SEAT_NOT_COMPUTE = "PIN_SEAT_NOT_COMPUTE"
    AFFINITY_CAPACITY_BLOCKED = "AFFINITY_CAPACITY_BLOCKED"
    SPREAD_TOO_FEW_SEATS = "SPREAD_TOO_FEW_SEATS"
    MAPPING_INCOMPLETE = "MAPPING_INCOMPLETE"
    MAPPING_RANK_OUT_OF_INVENTORY = "MAPPING_RANK_OUT_OF_INVENTORY"
    MAPPING_AGENT_NOT_IN_INVENTORY = "MAPPING_AGENT_NOT_IN_INVENTORY"
    PIN_MISMATCH = "PIN_MISMATCH"
    MOVEMENT_RADIUS_EXCEEDED = "MOVEMENT_RADIUS_EXCEEDED"
    AFFINITY_UNVERIFIED = "AFFINITY_UNVERIFIED"
    AFFINITY_DOMAIN_CONFLICT = "AFFINITY_DOMAIN_CONFLICT"
    SPREAD_UNVERIFIED = "SPREAD_UNVERIFIED"
    ANTI_AFFINITY_CONFLICT = "ANTI_AFFINITY_CONFLICT"


def _exact_int(name: str, value: Any, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise PlacementContractError(
            f"{name} must be an exact int >= {minimum}, got {value!r}")
    return value


def _exact_str(name: str, value: Any) -> str:
    if type(value) is not str or not value:
        raise PlacementContractError(
            f"{name} must be a nonempty str, got {value!r}")
    return value


def _rank_tuple(name: str, value: Any) -> tuple[int, ...]:
    if not isinstance(value, tuple) or len(value) < 2:
        raise PlacementContractError(
            f"{name} must be a tuple of at least two ranks, got {value!r}")
    for r in value:
        _exact_int(f"{name} rank", r)
    if len(set(value)) != len(value):
        raise PlacementContractError(f"{name} ranks must be unique")
    return value


def _seat_str(seat: "SeatCoordinate") -> str:
    return f"({seat.group_index},{seat.instance_index})"


@dataclass(frozen=True)
class SeatCoordinate:
    """One agent seat in the inventory coordinate space; no geometry implied."""

    group_index: int
    instance_index: int

    def __post_init__(self):
        _exact_int("group_index", self.group_index)
        _exact_int("instance_index", self.instance_index)

    def key(self) -> tuple[int, int]:
        return (self.group_index, self.instance_index)

    def to_dict(self) -> dict[str, int]:
        return {"group_index": self.group_index,
                "instance_index": self.instance_index}


@dataclass(frozen=True)
class LocalityDomain:
    """A named, author-declared partition of seats (e.g. one router island)."""

    name: str
    seats: tuple[SeatCoordinate, ...]

    def __post_init__(self):
        _exact_str("name", self.name)
        if not isinstance(self.seats, tuple) or not self.seats:
            raise PlacementContractError(
                "domain seats must be a nonempty tuple of SeatCoordinate")
        for i, s in enumerate(self.seats):
            if not isinstance(s, SeatCoordinate):
                raise PlacementContractError(
                    f"seats[{i}] must be a SeatCoordinate, got "
                    f"{type(s).__name__}")
        keys = [s.key() for s in self.seats]
        if len(set(keys)) != len(keys):
            raise PlacementContractError(
                f"domain {self.name!r} declares the same seat twice")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name,
                "seats": [s.to_dict() for s in self.seats]}


@dataclass(frozen=True)
class FixedPlacement:
    """Pin one logical rank to one seat; one seat admits one rank."""

    rank: int
    seat: SeatCoordinate

    def __post_init__(self):
        _exact_int("rank", self.rank)
        if not isinstance(self.seat, SeatCoordinate):
            raise PlacementContractError(
                f"seat must be a SeatCoordinate, got {type(self.seat).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "seat": self.seat.to_dict()}


class MovementPolicy(str, Enum):
    PINNED = "pinned"
    RADIUS = "radius"
    UNPINNED = "unpinned"


@dataclass(frozen=True)
class AllowedMovement:
    """Movement freedom relative to this rank's FixedPlacement pin.

    radius is an exact count of seat steps measured as Manhattan distance
    in the (group_index, instance_index) coordinate space; it is not a
    distance, delay or floorplan quantity. A RADIUS rule licenses the rank
    to land anywhere within radius of the pin; PINNED and UNPINNED leave
    the pin exact (radius must be 0). A movement rule without a pin for
    the same rank refuses the verdict.
    """

    rank: int
    policy: MovementPolicy
    radius: int = 0

    def __post_init__(self):
        _exact_int("rank", self.rank)
        if not isinstance(self.policy, MovementPolicy):
            raise PlacementContractError(
                f"policy must be a MovementPolicy, got {self.policy!r}")
        _exact_int("radius", self.radius)
        if self.policy is not MovementPolicy.RADIUS and self.radius != 0:
            raise PlacementContractError(
                f"{self.policy.value} requires radius == 0, got {self.radius}")

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "policy": self.policy.value,
                "radius": self.radius}


@dataclass(frozen=True)
class CoLocate:
    """All referenced ranks must land in one shared declared locality domain.

    domain=None leaves the domain to the mapper (any single declared domain
    will do); a named domain mandates that domain as the blocking
    constraint. Never a soft preference; unverifiable placement refuses.
    """

    ranks: tuple[int, ...]
    domain: str | None = None

    def __post_init__(self):
        _rank_tuple("co_locate ranks", self.ranks)
        if self.domain is not None:
            _exact_str("domain", self.domain)

    def to_dict(self) -> dict[str, Any]:
        return {"ranks": list(self.ranks), "domain": self.domain}


@dataclass(frozen=True)
class AntiAffinity:
    """All referenced ranks must land in distinct declared locality domains."""

    ranks: tuple[int, ...]

    def __post_init__(self):
        _rank_tuple("anti_affinity ranks", self.ranks)

    def to_dict(self) -> dict[str, Any]:
        return {"ranks": list(self.ranks)}


Affinity = CoLocate
Spread = AntiAffinity


@dataclass(frozen=True)
class Prefer:
    """Soft preference: recorded in the verdict, never enforced, never refuses."""

    rank: int
    domain: str | None = None
    seat: SeatCoordinate | None = None

    def __post_init__(self):
        _exact_int("rank", self.rank)
        if (self.domain is None) == (self.seat is None):
            raise PlacementContractError(
                "prefer requires exactly one of domain or seat")
        if self.domain is not None:
            _exact_str("domain", self.domain)
        if self.seat is not None and not isinstance(self.seat, SeatCoordinate):
            raise PlacementContractError(
                f"seat must be a SeatCoordinate, got {type(self.seat).__name__}")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"rank": self.rank}
        if self.domain is not None:
            d["domain"] = self.domain
        else:
            d["seat"] = self.seat.to_dict()
        return d


@dataclass(frozen=True)
class PlacementContract:
    """The declared placement restriction set for one candidate mapping."""

    placements: tuple[FixedPlacement, ...] = ()
    movements: tuple[AllowedMovement, ...] = ()
    domains: tuple[LocalityDomain, ...] = ()
    co_locates: tuple[CoLocate, ...] = ()
    anti_affinities: tuple[AntiAffinity, ...] = ()
    prefers: tuple[Prefer, ...] = ()
    schema_version: int = PLACEMENT_CONTRACT_SCHEMA_VERSION

    def __post_init__(self):
        if type(self.schema_version) is not int or (
                self.schema_version != PLACEMENT_CONTRACT_SCHEMA_VERSION):
            raise PlacementContractError(
                f"unsupported placement contract schema_version "
                f"{self.schema_version!r} (this build implements "
                f"v{PLACEMENT_CONTRACT_SCHEMA_VERSION})")
        for field_name, typ in (
            ("placements", FixedPlacement),
            ("movements", AllowedMovement),
            ("domains", LocalityDomain),
            ("co_locates", CoLocate),
            ("anti_affinities", AntiAffinity),
            ("prefers", Prefer),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple):
                raise PlacementContractError(
                    f"{field_name} must be a tuple of {typ.__name__}")
            for i, item in enumerate(value):
                if not isinstance(item, typ):
                    raise PlacementContractError(
                        f"{field_name}[{i}] must be a {typ.__name__}, got "
                        f"{type(item).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scope": "LOGICAL_RANK_TO_AGENT_SEAT_COORDINATES_NO_GEOMETRY",
            "placements": [p.to_dict() for p in self.placements],
            "movements": [m.to_dict() for m in self.movements],
            "domains": [d.to_dict() for d in self.domains],
            "co_locates": [c.to_dict() for c in self.co_locates],
            "anti_affinities": [c.to_dict() for c in self.anti_affinities],
            "prefers": [p.to_dict() for p in self.prefers],
        }


@dataclass(frozen=True)
class Reason:
    """One named, machine-readable refusal reason with exact-integer detail."""

    code: ReasonCode
    detail: str
    witnesses: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.code, ReasonCode):
            raise PlacementContractError(
                f"code must be a ReasonCode, got {self.code!r}")
        _exact_str("detail", self.detail)
        if not isinstance(self.witnesses, tuple) or any(
                type(w) is not str for w in self.witnesses):
            raise PlacementContractError("witnesses must be a tuple of str")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail,
                "witnesses": list(self.witnesses)}


@dataclass(frozen=True)
class PreferenceReport:
    """The recorded outcome of one soft preference; never a refusal."""

    rank: int
    target: str
    satisfied: bool
    detail: str

    def __post_init__(self):
        _exact_int("rank", self.rank)
        _exact_str("target", self.target)
        _exact_str("detail", self.detail)
        if type(self.satisfied) is not bool:
            raise PlacementContractError(
                f"satisfied must be a bool, got {self.satisfied!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "target": self.target,
                "satisfied": self.satisfied, "detail": self.detail}


@dataclass(frozen=True)
class Verdict:
    """ok=True iff no reasons; preferences are always recorded, never enforced."""

    ok: bool
    reasons: tuple[Reason, ...] = ()
    preferences: tuple[PreferenceReport, ...] = ()
    ranks_mapped: int = 0
    world_size: int = 0
    schema_version: int = PLACEMENT_CONTRACT_SCHEMA_VERSION

    def __post_init__(self):
        if type(self.ok) is not bool:
            raise PlacementContractError(f"ok must be a bool, got {self.ok!r}")
        if not isinstance(self.reasons, tuple) or any(
                not isinstance(r, Reason) for r in self.reasons):
            raise PlacementContractError("reasons must be a tuple of Reason")
        if not isinstance(self.preferences, tuple) or any(
                not isinstance(p, PreferenceReport) for p in self.preferences):
            raise PlacementContractError(
                "preferences must be a tuple of PreferenceReport")
        _exact_int("ranks_mapped", self.ranks_mapped)
        _exact_int("world_size", self.world_size)
        if type(self.schema_version) is not int or (
                self.schema_version != PLACEMENT_CONTRACT_SCHEMA_VERSION):
            raise PlacementContractError(
                f"unsupported verdict schema_version {self.schema_version!r}")
        if self.ok != (not self.reasons):
            raise PlacementContractError(
                "ok must be True iff reasons is empty; a verdict never "
                "silently passes and never falsely refuses")

    def __bool__(self) -> bool:
        return self.ok

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        return tuple(r.code for r in self.reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scope": "LOGICAL_RANK_TO_AGENT_SEAT_COORDINATES_NO_GEOMETRY",
            "ok": self.ok,
            "ranks_mapped": self.ranks_mapped,
            "world_size": self.world_size,
            "reasons": [r.to_dict() for r in self.reasons],
            "preferences": [p.to_dict() for p in self.preferences],
        }


def check_placement_contract(contract: PlacementContract,
                             inventory: NodeInventory,
                             mapping: MappingArtifact) -> Verdict:
    """Enforce a placement contract against an inventory and a mapping.

    Checks run before any expensive downstream work: contract-internal
    coherence, then capacity preflights against the inventory, then the
    mapping itself (completeness, membership, eligibility), then the
    declared pins, movement radii and locality rules. All failures are
    collected; nothing is guessed or silently satisfied. Soft preferences
    are recorded in the verdict and never affect ok.
    """
    if not isinstance(contract, PlacementContract):
        raise TypeError(
            f"contract must be a PlacementContract, got {type(contract).__name__}")
    if not isinstance(inventory, NodeInventory):
        raise TypeError(
            f"inventory must be a NodeInventory, got {type(inventory).__name__}")
    if not isinstance(mapping, MappingArtifact):
        raise TypeError(
            f"mapping must be a MappingArtifact, got {type(mapping).__name__}")

    reasons: list[Reason] = []
    preferences: list[PreferenceReport] = []
    world = inventory.parallelism.world_size
    agents_by_coord = {
        (a.group_index, a.instance_index): a for a in inventory.agents}

    def _coord_str(coord: tuple[int, int]) -> str:
        return f"({coord[0]},{coord[1]})"

    domains_by_name: dict[str, LocalityDomain] = {}
    for d in contract.domains:
        if d.name not in domains_by_name:
            domains_by_name[d.name] = d
        else:
            reasons.append(Reason(
                ReasonCode.DUPLICATE_DOMAIN,
                f"locality domain {d.name!r} is declared more than once",
                (d.name,)))
    domain_seat_entries = tuple(
        (d, tuple((s, s.key()) for s in d.seats)) for d in contract.domains
    )

    domain_of: dict[tuple[int, int], str] = {}
    for d, entries in domain_seat_entries:
        for s, key in entries:
            prior = domain_of.get(key)
            if prior is not None:
                reasons.append(Reason(
                    ReasonCode.OVERLAPPING_DOMAINS,
                    f"seat {_seat_str(s)} is declared in both domain "
                    f"{prior!r} and domain {d.name!r}; domains must partition "
                    f"seats",
                    (_seat_str(s), prior, d.name)))
            else:
                domain_of[key] = d.name

    eligible_in_domain: dict[str, int] = {}
    for d, entries in domain_seat_entries:
        eligible_in_domain[d.name] = sum(
            1 for _seat, key in entries
            if (agent := agents_by_coord.get(key)) is not None
            and agent.kind is AgentKind.COMPUTE_TILE)

    placement_seat_entries = tuple(
        (p, p.seat.key()) for p in contract.placements)

    pins_by_rank: dict[int, list[FixedPlacement]] = {}
    for p, _seat_key in placement_seat_entries:
        pins_by_rank.setdefault(p.rank, []).append(p)
    for rank, pins in pins_by_rank.items():
        if len(pins) > 1:
            reasons.append(Reason(
                ReasonCode.DUPLICATE_PIN_RULE,
                f"rank {rank} declares {len(pins)} fixed placement pins; "
                f"exactly one pin per rank is allowed",
                (str(rank),) + tuple(_seat_str(p.seat) for p in pins)))
    first_pin = {rank: pins[0] for rank, pins in pins_by_rank.items()}

    seat_to_pin_ranks: dict[tuple[int, int], list[int]] = {}
    for p, seat_key in placement_seat_entries:
        seat_to_pin_ranks.setdefault(seat_key, []).append(p.rank)
    for seat_key, ranks in seat_to_pin_ranks.items():
        if len(ranks) > 1:
            ordered = sorted(ranks)
            reasons.append(Reason(
                ReasonCode.DUPLICATE_SEAT_PIN,
                f"seat {_coord_str(seat_key)} is pinned by {len(ranks)} "
                f"ranks {ordered}; one seat admits exactly one rank",
                (_coord_str(seat_key),) + tuple(str(r) for r in ordered)))

    movements_by_rank: dict[int, list[AllowedMovement]] = {}
    for m in contract.movements:
        movements_by_rank.setdefault(m.rank, []).append(m)
    for rank, movements in movements_by_rank.items():
        if len(movements) > 1:
            reasons.append(Reason(
                ReasonCode.DUPLICATE_MOVEMENT_RULE,
                f"rank {rank} declares {len(movements)} movement rules; "
                f"exactly one is allowed",
                (str(rank),)))
        if rank not in first_pin:
            reasons.append(Reason(
                ReasonCode.MOVEMENT_WITHOUT_PIN,
                f"rank {rank} declares an allowed movement but no fixed "
                f"placement pin; movement radius is relative to a pin",
                (str(rank),)))

    referenced_ranks = sorted({
        *(p.rank for p in contract.placements),
        *(m.rank for m in contract.movements),
        *(r for c in contract.co_locates for r in c.ranks),
        *(r for c in contract.anti_affinities for r in c.ranks),
        *(p.rank for p in contract.prefers),
    })
    for rank in referenced_ranks:
        if rank >= world:
            reasons.append(Reason(
                ReasonCode.UNKNOWN_RANK,
                f"rank {rank} is referenced but the inventory declares "
                f"world_size {world}",
                (str(rank), str(world))))

    for p, seat_key in placement_seat_entries:
        agent = agents_by_coord.get(seat_key)
        if agent is None:
            reasons.append(Reason(
                ReasonCode.UNKNOWN_SEAT,
                f"rank {p.rank} is pinned to seat {_seat_str(p.seat)}, which "
                f"is not present in the inventory",
                (str(p.rank), _seat_str(p.seat))))
        elif agent.kind is not AgentKind.COMPUTE_TILE:
            reasons.append(Reason(
                ReasonCode.PIN_SEAT_NOT_COMPUTE,
                f"rank {p.rank} is pinned to seat {_seat_str(p.seat)}, which "
                f"hosts a {agent.kind.value} agent; only compute_tile "
                f"instances may host workload ranks",
                (str(p.rank), _seat_str(p.seat), agent.kind.value)))

    for d, entries in domain_seat_entries:
        for s, key in entries:
            if key not in agents_by_coord:
                reasons.append(Reason(
                    ReasonCode.UNKNOWN_SEAT,
                    f"domain {d.name!r} names seat {_seat_str(s)}, which is "
                    f"not present in the inventory",
                    (d.name, _seat_str(s))))

    open_domains = sum(1 for d in contract.domains
                       if eligible_in_domain[d.name] >= 1)
    if any(c.domain is None for c in contract.co_locates) and contract.domains:
        best_domain_name, best_domain_eligible = max(
            ((d.name, eligible_in_domain[d.name])
             for d in contract.domains),
            key=lambda item: item[1])
    else:
        best_domain_name, best_domain_eligible = None, 0

    for c in contract.co_locates:
        required = len(c.ranks)
        if c.domain is not None:
            domain = domains_by_name.get(c.domain)
            if domain is None:
                reasons.append(Reason(
                    ReasonCode.UNKNOWN_DOMAIN,
                    f"co_locate for ranks {list(c.ranks)} mandates domain "
                    f"{c.domain!r} as the blocking constraint, but no such "
                    f"domain is declared",
                    (c.domain,) + tuple(str(r) for r in c.ranks)))
            else:
                eligible = eligible_in_domain[domain.name]
                if eligible < required:
                    reasons.append(Reason(
                        ReasonCode.AFFINITY_CAPACITY_BLOCKED,
                        f"domain {domain.name!r} is the mandated blocking "
                        f"constraint: {eligible} eligible compute seat(s), "
                        f"{required} rank(s) must land there",
                        (domain.name, str(eligible), str(required))))
        else:
            if not contract.domains:
                reasons.append(Reason(
                    ReasonCode.AFFINITY_CAPACITY_BLOCKED,
                    f"no declared locality domain can admit the {required} "
                    f"co-located rank(s); the blocking constraint is the "
                    f"absence of any declared domain",
                    (str(required),)))
            else:
                best_name, best = best_domain_name, best_domain_eligible
                if best < required:
                    reasons.append(Reason(
                        ReasonCode.AFFINITY_CAPACITY_BLOCKED,
                        f"no single declared locality domain admits the "
                        f"{required} co-located rank(s); the best domain is "
                        f"{best_name!r} with {best} eligible compute "
                        f"seat(s)",
                        (best_name, str(best), str(required))))

    for c in contract.anti_affinities:
        required = len(c.ranks)
        if open_domains < required:
            reasons.append(Reason(
                ReasonCode.SPREAD_TOO_FEW_SEATS,
                f"spread group of {required} rank(s) requires {required} "
                f"distinct declared locality domains with at least one "
                f"eligible compute seat; only {open_domains} declared",
                (str(open_domains), str(required))))

    out_of_range = tuple(sorted({p.rank for p in mapping.placements
                                 if p.rank >= world}))
    if out_of_range:
        reasons.append(Reason(
            ReasonCode.MAPPING_RANK_OUT_OF_INVENTORY,
            f"mapping names rank(s) {list(out_of_range)} beyond inventory "
            f"world_size {world}",
            tuple(str(r) for r in out_of_range)))
    if mapping.rank_count < world:
        missing = tuple(range(mapping.rank_count, world))
        shown = missing[:16]
        witnesses = tuple(str(r) for r in shown)
        if len(missing) > 16:
            witnesses = witnesses + (
                f"+{len(missing) - 16} more (total missing {len(missing)})",)
        reasons.append(Reason(
            ReasonCode.MAPPING_INCOMPLETE,
            f"mapping covers {mapping.rank_count} of {world} inventory "
            f"ranks; missing rank(s) {list(shown)}"
            + (f" and {len(missing) - 16} more" if len(missing) > 16 else ""),
            witnesses))

    mapped_agent: dict[int, AgentInstance] = {}
    ranks_mapped = 0
    for p in mapping.placements:
        if p.rank >= world:
            continue
        ranks_mapped += 1
        coord = (p.agent.group_index, p.agent.instance_index)
        agent = agents_by_coord.get(coord)
        if agent is None:
            reasons.append(Reason(
                ReasonCode.MAPPING_AGENT_NOT_IN_INVENTORY,
                f"rank {p.rank} is mapped to {p.agent.instance_id}, which is "
                f"not a member of the provided inventory",
                (str(p.rank), p.agent.instance_id)))
        elif agent.kind is not p.agent.kind:
            reasons.append(Reason(
                ReasonCode.MAPPING_AGENT_NOT_IN_INVENTORY,
                f"rank {p.rank} is mapped to {p.agent.instance_id}, but the "
                f"inventory holds a {agent.kind.value} at that coordinate",
                (str(p.rank), p.agent.instance_id, agent.kind.value)))
        else:
            mapped_agent[p.rank] = agent

    for rank, pin in first_pin.items():
        agent = mapped_agent.get(rank)
        if agent is None:
            continue
        coord = (agent.group_index, agent.instance_index)
        distance = (abs(coord[0] - pin.seat.group_index)
                    + abs(coord[1] - pin.seat.instance_index))
        movements = movements_by_rank.get(rank)
        movement = movements[0] if movements else None
        if movement is not None and movement.policy is MovementPolicy.RADIUS:
            if distance > movement.radius:
                reasons.append(Reason(
                    ReasonCode.MOVEMENT_RADIUS_EXCEEDED,
                    f"rank {rank} maps at distance {distance} seat-step(s) "
                    f"from pin {_seat_str(pin.seat)}, exceeding the allowed "
                    f"radius {movement.radius}",
                    (str(rank), str(movement.radius), str(distance))))
        elif distance != 0:
            reasons.append(Reason(
                ReasonCode.PIN_MISMATCH,
                f"rank {rank} is pinned to seat {_seat_str(pin.seat)} but "
                f"the mapping places it at {_coord_str(coord)}",
                (str(rank), _seat_str(pin.seat), _coord_str(coord))))

    for c in contract.co_locates:
        mandated = c.domain if (c.domain is not None
                                and c.domain in domains_by_name) else None
        member_domains: list[tuple[int, str | None]] = []
        for r in c.ranks:
            agent = mapped_agent.get(r)
            if agent is None:
                continue
            coord = (agent.group_index, agent.instance_index)
            dname = domain_of.get(coord)
            member_domains.append((r, dname))
            if dname is None:
                reasons.append(Reason(
                    ReasonCode.AFFINITY_UNVERIFIED,
                    f"co_locate member rank {r} maps to seat "
                    f"{_coord_str(coord)}, which lies outside every declared "
                    f"locality domain; the shared-domain guarantee is "
                    f"unverifiable",
                    (str(r), _coord_str(coord))))
        if mandated is not None:
            for r, dname in member_domains:
                if dname is not None and dname != mandated:
                    agent = mapped_agent[r]
                    coord = (agent.group_index, agent.instance_index)
                    reasons.append(Reason(
                        ReasonCode.AFFINITY_DOMAIN_CONFLICT,
                        f"co_locate mandates domain {mandated!r} as the "
                        f"blocking constraint; rank {r} maps to seat "
                        f"{_coord_str(coord)} in domain {dname!r}",
                        (str(r), _coord_str(coord), mandated, dname)))
        elif c.domain is None:
            present = {d for _, d in member_domains if d is not None}
            if len(present) > 1:
                ordered_domains = sorted(present)
                reasons.append(Reason(
                    ReasonCode.AFFINITY_DOMAIN_CONFLICT,
                    f"co_locate ranks {list(c.ranks)} must share one declared "
                    f"locality domain; they land in domains "
                    f"{ordered_domains}",
                    tuple(ordered_domains)))

    for c in contract.anti_affinities:
        first_in_domain: dict[str, int] = {}
        for r in c.ranks:
            agent = mapped_agent.get(r)
            if agent is None:
                continue
            coord = (agent.group_index, agent.instance_index)
            dname = domain_of.get(coord)
            if dname is None:
                reasons.append(Reason(
                    ReasonCode.SPREAD_UNVERIFIED,
                    f"anti_affinity member rank {r} maps to seat "
                    f"{_coord_str(coord)}, which lies outside every declared "
                    f"locality domain; the spread guarantee is unverifiable",
                    (str(r), _coord_str(coord))))
                continue
            prior = first_in_domain.get(dname)
            if prior is None:
                first_in_domain[dname] = r
            else:
                reasons.append(Reason(
                    ReasonCode.ANTI_AFFINITY_CONFLICT,
                    f"ranks {prior} and {r} of the spread group both map "
                    f"into domain {dname!r}; anti-affinity requires distinct "
                    f"domains",
                    (str(prior), str(r), dname)))

    for pref in contract.prefers:
        agent = mapped_agent.get(pref.rank)
        coord = ((agent.group_index, agent.instance_index)
                 if agent is not None else None)
        if pref.domain is not None:
            target = f"domain:{pref.domain}"
            if agent is None:
                satisfied, detail = False, (
                    "rank not mapped; preference recorded only")
            elif pref.domain not in domains_by_name:
                satisfied, detail = False, (
                    f"domain {pref.domain!r} is not declared; preference "
                    f"recorded only")
            else:
                landed = domain_of.get(coord)
                satisfied = landed == pref.domain
                detail = ("mapped seat lies in the preferred domain"
                          if satisfied else
                          f"mapped seat lies in domain {landed!r}")
        else:
            target = f"seat:({pref.seat.group_index},{pref.seat.instance_index})"
            if agent is None:
                satisfied, detail = False, (
                    "rank not mapped; preference recorded only")
            else:
                satisfied = coord == pref.seat.key()
                detail = ("mapped seat equals the preferred seat"
                          if satisfied else
                          f"mapped seat is {_coord_str(coord)}")
        preferences.append(PreferenceReport(
            rank=pref.rank, target=target, satisfied=satisfied,
            detail=detail))

    return Verdict(ok=not reasons, reasons=tuple(reasons),
                   preferences=tuple(preferences),
                   ranks_mapped=ranks_mapped, world_size=world)
