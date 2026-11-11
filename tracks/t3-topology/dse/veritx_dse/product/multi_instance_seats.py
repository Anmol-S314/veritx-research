"""Per-endpoint seat planning for the composed family path.

The compiler already seats every agent INSTANCE on its own router
(`bundle.attachment.endpoints` carries `agent.group_index`,
`agent.instance_index`, `router_id`, `port_id`). The composed builder used to
keep only the first endpoint per group, which silently dropped the remaining
instances. This module computes the endpoint plan the builder must emit:
one initiator per endpoint, with the group identity kept for permissions and
address-decode request ids.

Two endpoints on the SAME router (a co-seated concentrator fabric) need an
arbitration primitive that does not exist yet; those designs are refused with
a named blocker instead of being emitted with a multiplied driver.
"""
from __future__ import annotations

from dataclasses import dataclass


class MultiSeatUnsupported(ValueError):
    """Two endpoints share one router and no concentrator arbiter exists."""


@dataclass(frozen=True)
class EndpointSeat:
    endpoint_index: int
    endpoint_id: int
    group_index: int
    instance_index: int
    router_id: int
    port_id: int


@dataclass(frozen=True)
class SeatPlan:
    initiators: tuple[EndpointSeat, ...]
    memory_group: int
    memory_router: int

    def by_group(self) -> dict[int, tuple[EndpointSeat, ...]]:
        out: dict[int, list[EndpointSeat]] = {}
        for seat in self.initiators:
            out.setdefault(seat.group_index, []).append(seat)
        return {group: tuple(seats) for group, seats in out.items()}


def plan_endpoint_seats(request, compiled, allow_co_seated: bool = False) -> SeatPlan:
    """One seat per compiled agent instance, memory group excluded.

    ``allow_co_seated`` keeps a plan whose endpoints share a router instead of
    refusing it; the caller is then responsible for placing a concentrator
    between those seats and the router local port.
    """
    if compiled is None or getattr(compiled, "bundle", None) is None:
        raise ValueError("compile did not produce a bundle")
    bundle = compiled.bundle
    endpoints = list(getattr(bundle.attachment, "endpoints", ()) or ())
    if not endpoints:
        raise ValueError("the compiled attachment carries no endpoints")
    groups = list(request.agents)
    memory_groups = [i for i, agent in enumerate(groups)
                     if getattr(agent, "kind", None) is not None
                     and getattr(agent.kind, "value", agent.kind) == "hbm_controller"]
    if len(memory_groups) != 1:
        raise ValueError(
            "exactly one hbm_controller group is required, got "
            f"{len(memory_groups)}")
    memory_group = memory_groups[0]
    memory_seats = [e for e in endpoints if int(e.agent.group_index) == memory_group]
    if len(memory_seats) != 1:
        raise ValueError(
            "the memory group must seat exactly one endpoint, got "
            f"{len(memory_seats)}")
    memory_router = int(memory_seats[0].router_id)
    ordered = sorted(endpoints, key=lambda e: (int(e.agent.group_index),
                                                int(getattr(e.agent, "instance_index", 0))))
    initiators: list[EndpointSeat] = []
    endpoint_index = 0
    for endpoint in ordered:
        group_index = int(endpoint.agent.group_index)
        if group_index == memory_group:
            continue
        initiators.append(EndpointSeat(
            endpoint_index=endpoint_index,
            endpoint_id=int(endpoint.endpoint_id),
            group_index=group_index,
            instance_index=int(getattr(endpoint.agent, "instance_index", 0)),
            router_id=int(endpoint.router_id),
            port_id=int(getattr(endpoint, "port_id", 0)),
        ))
        endpoint_index += 1
    if not initiators:
        raise ValueError("no initiator endpoints in the compiled attachment")
    plan = SeatPlan(initiators=tuple(initiators),
                     memory_group=memory_group,
                     memory_router=memory_router)
    if not allow_co_seated:
        _refuse_co_seated(plan)
    return plan


def co_seated_routers(plan: SeatPlan) -> tuple[int, ...]:
    """Routers that host more than one initiator endpoint."""
    counts: dict[int, int] = {}
    for seat in plan.initiators:
        counts[seat.router_id] = counts.get(seat.router_id, 0) + 1
    return tuple(sorted(router for router, count in counts.items() if count > 1))


def _refuse_co_seated(plan: SeatPlan) -> None:
    shared = co_seated_routers(plan)
    if shared:
        raise MultiSeatUnsupported(
            "multiple endpoint seats on one router are not yet connected by the "
            "composed wrapper: this family's multi-seat concentrator is not wired "
            "(seats on router(s) " + str(list(shared)) + "; the concentrator "
            "primitive exists and is proven, the wiring does not — see "
            "docs/product/proposals/multi-seat-concentrator.md)")
