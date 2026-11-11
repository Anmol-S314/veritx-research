from __future__ import annotations

from dataclasses import replace

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.agent_intent_v4 import TrafficClassVC, TrafficPolicyV4
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, Dependency, DependencyGraph, DepKind,
    ModelFamily, TrafficProfile, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent


def _request(dependencies=DependencyGraph(()), **kwargs):
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
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=3),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1)),
        dependencies=dependencies,
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),)),
    )
    args.update(kwargs)
    return CompileRequestV4(**args)


def _cycle() -> DependencyGraph:
    return DependencyGraph((
        Dependency(source="tp_collective", target="x", kind=DepKind.BLOCKING),
        Dependency(source="x", target="tp_collective", kind=DepKind.BLOCKING),
    ))


def _compile(request):
    return FabricCompiler().compile(request)


def test_unconstrained_desire_agrees_with_the_derived_assignment():
    compilation = _compile(_request(traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 0),))))
    assert compilation.status == "COMPILED"


def test_adding_a_cycle_rebinds_the_class_and_refuses_the_same_desire():
    compilation = _compile(_request(
        dependencies=_cycle(),
        traffic_policy=TrafficPolicyV4(
            traffic_class_vcs=(TrafficClassVC("tp_collective", 0),))))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "VC"
    assert "derived assignment binds it to VC" in compilation.error


def test_desire_matching_the_cycle_binding_is_accepted():
    compilation = _compile(_request(
        dependencies=_cycle(),
        traffic_policy=TrafficPolicyV4(
            traffic_class_vcs=(TrafficClassVC("tp_collective", 1),))))
    assert compilation.status != "INVALID" or compilation.stopped_at_stage != "VC"


def test_removing_the_cycle_makes_vc1_desire_unroutable():
    flat = _compile(_request(traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 1),))))
    assert flat.status == "INVALID"
    assert flat.stopped_at_stage == "VC"
    assert "only 1 VC" in flat.error


def test_desired_vc_beyond_the_fabric_maximum_is_refused():
    compilation = _compile(_request(
        traffic_policy=TrafficPolicyV4(
            traffic_class_vcs=(TrafficClassVC("tp_collective", 8),))))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "VC"


def test_directed_toggle_of_the_desire_alone_flips_the_verdict():
    base = _request(dependencies=_cycle(), traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 1),)))
    assert _compile(base).status != "INVALID" or _compile(base).stopped_at_stage != "VC"
    flipped = replace(base, traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 0),)))
    invalid = _compile(flipped)
    assert invalid.status == "INVALID"
    assert invalid.stopped_at_stage == "VC"
