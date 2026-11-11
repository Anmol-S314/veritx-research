"""veritx_dse.model.clock_power_cdc — M3 Clock, Power & CDC (STAGE 1 §4.3).

Rationale: docs/design/mesh-stage1-schema-compiler-scope.md §4.3.
Frozen input struct in -> Verdict out. No ``CompileRequestV4``, no
``topology_intent`` in the imports (module-isolation contract, §8.3).
Also governed by docs/design/mesh-stage3-rtl-params-scope.md §3.6 (CdcCell).

Owns domain-ref integrity (an agent-intent domain must exist and equal the
``Agent`` declaration when set, §5.8), the multi-domain gate, and the power
domain count check (§5.11). A multi-domain fabric compiles exactly when
every named insertion point is covered by a CdcCell (``cdc_cells``); an
uncovered crossing is a typed ``CDC_CELL_MISSING`` refusal, not a warning.
This module names and checks coverage; the hardware itself is built by the
``CdcCell`` deep module (``veritx_dse.product.cdc_cell_rtl``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.compile_model import Agent


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None
    findings: tuple[str, ...] = ()
    status: str = "INVALID"


@dataclass(frozen=True)
class EndpointDomain:
    agent_idx: int
    agent_clock_domain: str | None
    agent_power_domain: str | None
    intent_clock_domain: str | None
    intent_power_domain: str | None


@dataclass(frozen=True)
class DeclaredCrossing:
    src_domain: str
    dst_domain: str


@dataclass(frozen=True)
class ClockPowerInput:
    endpoints: tuple[EndpointDomain, ...]
    crossings: tuple[DeclaredCrossing, ...] = ()
    num_power_domains: int = 1
    agents: tuple[Agent, ...] = ()
    #: Insertion-point names a CdcCell covers (empty = no cell coverage).
    cdc_cells: tuple[str, ...] = ()


_DEFAULT_DOMAIN = "default"

#: Blocker id: a named crossing has no CdcCell.
CDC_CELL_MISSING = "CDC_CELL_MISSING"


@dataclass(frozen=True)
class CrossingPoint:
    """One named CDC insertion point (structured form of the name string)."""

    insertion_point: str
    src_domain: str
    dst_domain: str
    src_group: int | None = None
    dst_group: int | None = None
    declared: bool = False


def _effective(endpoint: EndpointDomain, kind: str) -> str:
    value = getattr(endpoint, f"intent_{kind}_domain") \
        or getattr(endpoint, f"agent_{kind}_domain")
    return value or _DEFAULT_DOMAIN


def crossing_points(inp: ClockPowerInput) -> tuple[CrossingPoint, ...]:
    """Structured insertion points: one per declared crossing and per pair
    of endpoints whose effective clock domains differ."""
    points: list[CrossingPoint] = []
    for crossing in inp.crossings:
        points.append(CrossingPoint(
            insertion_point=(
                f"cdc:declared:{crossing.src_domain}"
                f"->{crossing.dst_domain}"),
            src_domain=crossing.src_domain,
            dst_domain=crossing.dst_domain, declared=True))
    endpoints = list(inp.endpoints)
    for i, a in enumerate(endpoints):
        for b in endpoints[i + 1:]:
            da, db = _effective(a, "clock"), _effective(b, "clock")
            if da != db:
                first, second = sorted((da, db))
                declared = any(
                    {c.src_domain, c.dst_domain} == {first, second}
                    for c in inp.crossings)
                suffix = "" if declared else " (undeclared)"
                points.append(CrossingPoint(
                    insertion_point=(
                        f"cdc:attach:group{a.agent_idx}({da})->"
                        f"group{b.agent_idx}({db}){suffix}"),
                    src_domain=da, dst_domain=db,
                    src_group=a.agent_idx, dst_group=b.agent_idx,
                    declared=declared))
    by_name = {point.insertion_point: point for point in points}
    return tuple(sorted(by_name.values(),
                        key=lambda point: point.insertion_point))


def cdc_insertion_points(inp: ClockPowerInput) -> tuple[str, ...]:
    """Named CDC insertion points (endpoint/attachment names only)."""
    return tuple(point.insertion_point for point in crossing_points(inp))


def cdc_cells_for(inp: ClockPowerInput) -> tuple[str, ...]:
    """Factory coverage: every named insertion point gets a CdcCell.

    The CdcCell deep module (``veritx_dse.product.cdc_cell_rtl``) builds a
    real async-FIFO + synchronizer cell at each point; this is the coverage
    the compiler gate checks.
    """
    return cdc_insertion_points(inp)


def _cell_domain_pair(cell: str) -> tuple[str, str] | None:
    """The domain pair a cell name covers, if it is parseable."""
    body = cell.removesuffix(" (undeclared)")
    if "->" not in body:
        return None
    left, right = body.split("->", 1)
    if "(" in left and ")" in left and "(" in right and ")" in right:
        return (left.split("(", 1)[1].split(")", 1)[0],
                right.split("(", 1)[1].split(")", 1)[0])
    return (left.rsplit(":", 1)[-1], right)


def cdc_cells_for_agents(agents: tuple[Any, ...]) -> tuple[str, ...]:
    """Factory coverage from ``Agent``-shaped objects (duck-typed).

    One CdcCell per named crossing between the agents' clock domains;
    single-domain designs need none. Canonical/compiler paths derive their
    fabric coverage through this one helper.
    """
    agents = tuple(agents or ())
    if not agents:
        return ()
    endpoints = tuple(
        EndpointDomain(
            agent_idx=i,
            agent_clock_domain=getattr(agent, "clock_domain", None),
            agent_power_domain=getattr(agent, "power_domain", None),
            intent_clock_domain=None, intent_power_domain=None)
        for i, agent in enumerate(agents))
    domains = {endpoint.agent_clock_domain or _DEFAULT_DOMAIN
               for endpoint in endpoints}
    if len(domains) <= 1:
        return ()
    return cdc_cells_for(ClockPowerInput(endpoints=endpoints,
                                         agents=agents))


def cdc_crossing_covered(cdc_cells: tuple[str, ...], src_domain: str,
                         dst_domain: str) -> bool:
    """True when some cell name covers the unordered {src, dst} pair."""
    return any(
        pair is not None
        and {pair[0], pair[1]} == {src_domain, dst_domain}
        for pair in (_cell_domain_pair(cell) for cell in cdc_cells))


def check_clock_power_cdc(inp: ClockPowerInput) -> Verdict:
    """Validate domain refs; multi-domain is UNSUPPORTED (D5), not INVALID."""
    for endpoint in inp.endpoints:
        if endpoint.intent_clock_domain is not None \
                and endpoint.intent_clock_domain != endpoint.agent_clock_domain:
            return Verdict(
                ok=False,
                reason=f"agent group {endpoint.agent_idx} intent declares "
                f"clock domain "
                f"{endpoint.intent_clock_domain!r}, but Agent declares "
                f"{endpoint.agent_clock_domain!r} — the intent domain must "
                f"exist and equal the Agent declaration")
        if endpoint.intent_power_domain is not None \
                and endpoint.intent_power_domain != endpoint.agent_power_domain:
            return Verdict(
                ok=False,
                reason=f"agent group {endpoint.agent_idx} intent declares "
                f"power domain "
                f"{endpoint.intent_power_domain!r}, but Agent declares "
                f"{endpoint.agent_power_domain!r} — the intent domain must "
                f"exist and equal the Agent declaration")
        if inp.agents:
            idx = endpoint.agent_idx
            if not 0 <= idx < len(inp.agents):
                return Verdict(
                    ok=False,
                    reason=f"endpoint references agent group {idx}, "
                    f"outside the design's {len(inp.agents)} groups")
            agent = inp.agents[idx]
            if agent.clock_domain != endpoint.agent_clock_domain \
                    or agent.power_domain != endpoint.agent_power_domain:
                return Verdict(
                    ok=False,
                    reason=f"endpoint for group {idx} does not match the "
                    f"Agent declaration")
    clock_domains = {_effective(e, "clock") for e in inp.endpoints}
    if len(clock_domains) > 1:
        points = cdc_insertion_points(inp)
        point_set = set(points)
        cell_set = set(inp.cdc_cells)
        unknown = sorted(cell_set - point_set)
        if unknown:
            return Verdict(
                ok=False,
                reason=f"cdc_cells names insertion point(s) this design "
                f"does not declare: {unknown} — a cell for a nonexistent "
                f"crossing is INVALID, not ignored",
                status="INVALID")
        missing = sorted(point_set - cell_set)
        if missing:
            return Verdict(
                ok=False,
                reason=f"{CDC_CELL_MISSING}: endpoint groups span clock "
                f"domains {sorted(clock_domains)} but "
                f"{len(missing)} crossing(s) have no CdcCell: "
                f"{missing}. Every crossing must be covered by a CdcCell "
                f"(async FIFO + synchronizer); a missing cell is a refusal, "
                f"not a warning. CDC insertion points: "
                f"{list(points) if points else 'none named'}",
                findings=points,
                status="UNSUPPORTED")
        return Verdict(
            ok=True,
            reason=None,
            findings=tuple(
                f"cdc_cell covered at {point}" for point in points))
    findings: tuple[str, ...] = ()
    power_domains = {_effective(e, "power") for e in inp.endpoints}
    if len(power_domains) > inp.num_power_domains:
        findings = (
            f"physical context declares {inp.num_power_domains} power "
            f"domain(s) but the endpoints reference "
            f"{len(power_domains)} ({sorted(power_domains)}) — the "
            f"PhysicalContext under-declares the referenced domains",
        )
    return Verdict(ok=True, findings=findings)


__all__ = [
    "CDC_CELL_MISSING", "ClockPowerInput", "CrossingPoint",
    "DeclaredCrossing", "EndpointDomain", "Verdict",
    "cdc_cells_for", "cdc_cells_for_agents", "cdc_crossing_covered",
    "cdc_insertion_points", "check_clock_power_cdc", "crossing_points",
]
