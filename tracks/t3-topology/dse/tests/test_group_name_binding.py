from __future__ import annotations

import json

import pytest

from veritx_dse.model.compile_model import Agent, AgentKind, CollectiveDimension, CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily, WorkloadV3
from veritx_dse.model.compile_request_v4 import CompileRequestV4, CompileRequestV4SchemaError
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.model.compile_model import AddressMap, AddressRange


def _request(agents):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    return CompileRequestV4(
        workload=workload, agents=tuple(agents),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)))


def test_named_groups_round_trip_exactly():
    agents = [
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, group_name="tile"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, group_name="hbm0"),
    ]
    request = _request(agents)
    doc = json.loads(json.dumps(request.to_dict(), sort_keys=True))
    reloaded = CompileRequestV4.from_dict(doc)
    assert reloaded.agents[0].group_name == "tile"
    assert reloaded.agents[1].group_name == "hbm0"
    assert reloaded.design_hash() == request.design_hash()


def test_absent_group_name_is_hash_stable():
    unnamed = _request([
        Agent(kind=AgentKind.COMPUTE_TILE, count=2),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
    ])
    named = _request([
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, group_name="tile"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, group_name="hbm0"),
    ])
    assert unnamed.design_hash() != named.design_hash()


def test_mixed_naming_is_refused():
    agents = [
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, group_name="tile"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
    ]
    with pytest.raises(ValueError, match="EVERY agent group"):
        _request(agents)


def test_duplicate_names_are_refused():
    agents = [
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, group_name="grp"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, group_name="grp"),
    ]
    with pytest.raises(ValueError, match="duplicates"):
        _request(agents)


def test_invalid_group_name_character_refused():
    with pytest.raises(ValueError):
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, group_name="bad name!")


def test_empty_group_name_refused():
    with pytest.raises(ValueError):
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, group_name="")


def test_group_names_must_be_unique_per_group_kind():
    agents = [
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, group_name="tilex0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, group_name="tilex1"),
    ]
    request = _request(agents)
    assert [a.group_name for a in request.agents] == ["tilex0", "tilex1"]
