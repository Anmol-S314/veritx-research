"""Torus/FlatFly concentration is a certified-profile boundary, not a knob.

``TorusIntent(concentration=1)`` and ``FlatFlyIntent(concentration=1)`` keep
their exact materialization and hashes. Both certified native profiles cover
concentration 1 only, so a declaration with more than one seat per router
stays loadable and hash-stable but materialization refuses with the family
name, the profile boundary and the supported alternatives. The declared
family is never silently normalized or rewritten.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, TopologyError, materialize_family, materialize_flatfly,
    materialize_topology, materialize_topology_intent,
)
from veritx_dse.model.topology_intent import (
    FlatFlyIntent, TorusIntent, topology_intent_from_dict,
)


def _inv(n: int):
    return SimpleNamespace(agent_count=n)


def _legacy_torus_request(n: int, *, concentration: int,
                          radix: int = 5) -> CompileRequest:
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1,
                          dp=1),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=n)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.TORUS,
                             radix=radix, concentration=concentration),
    )


@pytest.mark.parametrize("k", [3, 5])
def test_torus_concentration_one_keeps_the_exact_artifact(k):
    intent = TorusIntent(side_length=k, concentration=1)
    assert intent.to_dict() == {
        "kind": "torus", "side_length": k, "concentration": 1}
    assert topology_intent_from_dict(intent.to_dict()) == intent

    expected = materialize_family(
        MaterializedFamily.TORUS, endpoint_count=k * k,
        concentration=1, radix=k)
    actual = materialize_topology_intent(_inv(k * k), intent)
    assert actual.family is MaterializedFamily.TORUS
    assert {r.seat_capacity for r in actual.routers} == {1}
    assert actual.topology_hash() == expected.topology_hash()


@pytest.mark.parametrize("concentration", [2, 4])
def test_torus_concentration_above_one_gets_a_typed_native_profile_hint(
        concentration):
    intent = TorusIntent(side_length=5, concentration=concentration)
    before = intent.to_dict()
    identity = intent.intent_id()

    # The declaration stays lossless and loadable: refusing the certified
    # profile must not rewrite the torus family.
    assert topology_intent_from_dict(intent.to_dict()) == intent

    with pytest.raises(TopologyError) as excinfo:
        materialize_topology_intent(_inv(25), intent)
    message = str(excinfo.value)
    assert "TorusIntent" in message
    assert "torus family" in message
    assert "torus-DOR" in message
    assert "concentration 1 only" in message
    assert "no multi-seat native torus profile exists" in message
    assert "kind='concentrated_mesh'" in message
    assert "ConcentratedMeshIntent" in message
    assert f"concentration={concentration}" in message

    # No silent family or identity change.
    assert intent.to_dict() == before
    assert intent.intent_id() == identity
    assert intent.kind == "torus"
    assert intent.concentration == concentration
    assert topology_intent_from_dict(intent.to_dict()) == intent


@pytest.mark.parametrize("concentration", [2, 4])
def test_legacy_torus_spelling_gets_the_same_native_profile_hint(
        concentration):
    request = _legacy_torus_request(25, concentration=concentration)
    with pytest.raises(TopologyError) as excinfo:
        materialize_topology(build_inventory(request), request)
    message = str(excinfo.value)
    assert "TorusIntent" in message
    assert "torus-DOR" in message
    assert "concentration 1 only" in message
    assert "kind='concentrated_mesh'" in message


def test_flatfly_concentration_one_keeps_the_exact_artifact():
    intent = FlatFlyIntent(radix_per_dimension=4, dimension_count=2,
                           concentration=1)
    assert intent.to_dict() == {
        "kind": "flatfly", "radix_per_dimension": 4,
        "dimension_count": 2, "concentration": 1}
    assert topology_intent_from_dict(intent.to_dict()) == intent

    expected = materialize_flatfly(k=4, n=2, concentration=1)
    actual = materialize_topology_intent(_inv(16), intent)
    assert actual.family is MaterializedFamily.FLATFLY
    assert {r.seat_capacity for r in actual.routers} == {1}
    assert actual.topology_hash() == expected.topology_hash()


@pytest.mark.parametrize("concentration", [2, 4])
def test_flatfly_concentration_above_one_gets_a_typed_native_profile_hint(
        concentration):
    intent = FlatFlyIntent(radix_per_dimension=4, dimension_count=2,
                           concentration=concentration)
    before = intent.to_dict()
    identity = intent.intent_id()

    # The declaration stays lossless and loadable: refusing the certified
    # profile must not rewrite the flatfly family.
    assert topology_intent_from_dict(intent.to_dict()) == intent

    with pytest.raises(TopologyError) as excinfo:
        materialize_topology_intent(_inv(16), intent)
    message = str(excinfo.value)
    assert "FlatFlyIntent" in message
    assert "flatfly family" in message
    assert "flatfly-min" in message
    assert "concentration 1 only" in message
    assert "no multi-seat native flatfly profile exists" in message
    assert "kind='concentrated_mesh'" in message
    assert "ConcentratedMeshIntent" in message
    assert f"concentration={concentration}" in message

    # No silent family or identity change.
    assert intent.to_dict() == before
    assert intent.intent_id() == identity
    assert intent.kind == "flatfly"
    assert intent.concentration == concentration
    assert topology_intent_from_dict(intent.to_dict()) == intent
