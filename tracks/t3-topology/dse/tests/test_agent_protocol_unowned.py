from __future__ import annotations

from dataclasses import replace

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.agent_intent_v4 import AgentIntentV4, ProtocolFamily
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    PhysicalContext, TrafficProfile, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent


def _request(**kwargs) -> CompileRequestV4:
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),),
        traffic_profiles=(TrafficProfile(
            src_rank=0, dst_rank=1, traffic_class="tp_collective",
            payload_bytes=64),))
    args = dict(
        workload=workload,
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=2, protocol="AXI"),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1, protocol="CHI")),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
    )
    args.update(kwargs)
    return CompileRequestV4(**args)


def _compile(request):
    return FabricCompiler().compile(request)


def test_unowned_literal_is_reported_not_consumed():
    compilation = _compile(_request())
    assert compilation.status == "COMPILED"
    rows = [f for f in compilation.findings if "AGENT_PROTOCOL_UNOWNED" in f]
    assert len(rows) == 1
    assert "group 0" in rows[0] and "group 1" in rows[0]
    assert "no adapter is generated" in rows[0]


def test_owned_groups_emit_no_unowned_finding():
    compilation = _compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5),
        AgentIntentV4(1, protocol=ProtocolFamily.CHI))))
    assert compilation.status == "COMPILED"
    assert not any("AGENT_PROTOCOL_UNOWNED" in f for f in compilation.findings)


def test_partial_ownership_names_only_the_unowned_groups():
    compilation = _compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5),)))
    rows = [f for f in compilation.findings if "AGENT_PROTOCOL_UNOWNED" in f]
    assert len(rows) == 1
    assert "group 1" in rows[0] and "group 0" not in rows[0]
