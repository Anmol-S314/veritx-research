from __future__ import annotations

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    PhysicalContext, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.multi_instance_seats import (
    MultiSeatUnsupported, co_seated_routers, plan_endpoint_seats,
)


def _request(compute_count: int, side: int = 4):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=compute_count, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG,
                      max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1),
    )
    return CompileRequestV4(
        workload=workload, agents=agents, dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=side, concentration=1),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)


def _compiled(compute_count: int, side: int = 4):
    compiled = FabricCompiler().compile(_request(compute_count, side))
    assert compiled.status == "COMPILED", compiled.error
    return compiled


def test_every_instance_gets_its_own_seat():
    compiled = _compiled(3)
    plan = plan_endpoint_seats(_request(3), compiled)
    assert [seat.instance_index for seat in plan.initiators] == [0, 1, 2]
    assert [seat.group_index for seat in plan.initiators] == [0, 0, 0]
    assert len({seat.router_id for seat in plan.initiators}) == 3
    assert [seat.endpoint_index for seat in plan.initiators] == [0, 1, 2]


def test_memory_group_is_excluded_and_identified():
    compiled = _compiled(2)
    plan = plan_endpoint_seats(_request(2), compiled)
    assert plan.memory_group == 1
    assert all(seat.group_index != plan.memory_group for seat in plan.initiators)
    assert len(plan.initiators) == 2


def test_plan_matches_the_compiled_attachment_exactly():
    request = _request(3)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED"
    plan = plan_endpoint_seats(request, compiled)
    attachment = compiled.bundle.attachment
    expected = sorted(
        (int(e.agent.group_index), int(getattr(e.agent, "instance_index", 0)),
         int(e.router_id), int(getattr(e, "port_id", 0)))
        for e in attachment.endpoints
        if int(e.agent.group_index) != plan.memory_group)
    actual = sorted((seat.group_index, seat.instance_index, seat.router_id,
                      seat.port_id) for seat in plan.initiators)
    assert actual == expected


def test_by_group_indexes_the_instances_of_one_group():
    compiled = _compiled(2)
    plan = plan_endpoint_seats(_request(2), compiled)
    grouped = plan.by_group()
    assert set(grouped) == {0}
    assert len(grouped[0]) == 2


def test_compiler_refuses_a_group_without_an_instance_seat():
    request = _request(2)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED"
    plan = plan_endpoint_seats(request, compiled)
    assert co_seated_routers(plan) == ()


def test_seat_plan_refuses_when_no_bundle_is_present():
    with pytest.raises(ValueError, match="bundle"):
        plan_endpoint_seats(_request(1), None)


def test_co_seated_refusal_names_the_concentrator():
    from veritx_dse.product.multi_instance_seats import EndpointSeat, SeatPlan
    plan = SeatPlan(
        initiators=(EndpointSeat(0, 0, 0, 0, 2, 0),
                    EndpointSeat(1, 1, 0, 1, 2, 1)),
        memory_group=1, memory_router=3)
    assert co_seated_routers(plan) == (2,)
    from veritx_dse.product.multi_instance_seats import _refuse_co_seated
    with pytest.raises(MultiSeatUnsupported, match="concentrator"):
        _refuse_co_seated(plan)
