from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
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
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=2),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1)),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),
            AddressRange(name="HBM1", base=0x2000, size=0x1000,
                         target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
    )
    args.update(kwargs)
    return CompileRequestV4(**args)


def _compile(request):
    return FabricCompiler().compile(request)


def _decode_hash(compilation):
    bundle = getattr(compilation, "bundle", None)
    decode = getattr(bundle, "address_decode", None)
    return getattr(decode, "address_decode_hash", None) if decode else None


def _attachment_hash(compilation):
    bundle = getattr(compilation, "bundle", None)
    return bundle.attachment.attachment_hash() if getattr(bundle, "attachment", None) else None


GOLDEN = _request()


@pytest.mark.parametrize("mutation", [
    ("agents.count", lambda req: replace(req, agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=3),) + req.agents[1:])),
    ("workload.model_family", lambda req: replace(req, workload=replace(req.workload, model_family=ModelFamily.MOE))),
    ("topology.side_length", lambda req: replace(req, topology=MeshIntent(side_length=3, concentration=1))),
    ("physical.clock", lambda req: replace(req, physical=PhysicalContext(default_clock_freq_mhz=2000.0))),
    ("workload.payload", lambda req: replace(req, workload=replace(req.workload, traffic_profiles=(
        TrafficProfile(src_rank=0, dst_rank=1, traffic_class="tp_collective", payload_bytes=128),)))),
])
def test_design_identity(mutation):
    baseline = _compile(GOLDEN)
    mutated = _compile(mutation[1](GOLDEN))
    assert baseline.status == "COMPILED"
    assert mutated.status == "COMPILED"
    assert mutated.request.design_hash() != GOLDEN.design_hash()


def test_agent_count_changes_the_attachment():
    baseline = _compile(GOLDEN)
    mutated = _compile(replace(
        GOLDEN, agents=(
            Agent(kind=AgentKind.COMPUTE_TILE, count=3),
            GOLDEN.agents[1])))
    assert mutated.status == "COMPILED"
    assert _attachment_hash(mutated) != _attachment_hash(baseline)


def test_address_base_changes_the_decode():
    baseline = _compile(GOLDEN)
    ranges = [replace(r, base=r.base + 0x1000) for r in GOLDEN.address_map.ranges]
    mutated = _compile(replace(GOLDEN, address_map=AddressMap(ranges=tuple(ranges))))
    assert mutated.status == "COMPILED"
    assert _decode_hash(mutated) != _decode_hash(baseline)


def test_address_size_changes_the_decode():
    baseline = _compile(GOLDEN)
    ranges = [GOLDEN.address_map.ranges[0],
              replace(GOLDEN.address_map.ranges[1], size=0x2000)]
    mutated = _compile(replace(GOLDEN, address_map=AddressMap(ranges=tuple(ranges))))
    assert mutated.status == "COMPILED"
    assert _decode_hash(mutated) != _decode_hash(baseline)


def test_recompiling_the_same_request_keeps_identity():
    assert GOLDEN.design_hash() == _request().design_hash()


def test_interleave_byte_change_flips_the_decode_artifact():
    agents = (Agent(kind=AgentKind.COMPUTE_TILE, count=2),
              Agent(kind=AgentKind.HBM_CONTROLLER, count=2))
    first = _compile(_request(
        agents=agents,
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x0, size=0x2000,
                         selection_policy="STRIPED",
                         interleave_bytes=0x1000,
                         target_agent_idx=1),))))
    second = _compile(_request(
        agents=agents,
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x0, size=0x2000,
                         selection_policy="STRIPED",
                         interleave_bytes=0x2000,
                         target_agent_idx=1),))))
    assert first.status == "COMPILED"
    assert second.status == "COMPILED"
    assert _decode_hash(first) != _decode_hash(second)
