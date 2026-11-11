"""Mesh concentration is a family choice, not a free mesh knob.

`MeshIntent(concentration=1)` is the mesh family and keeps its exact old
materialization. A k x k router grid whose routers seat more than one
endpoint is `ConcentratedMeshIntent` (kind `concentrated_mesh`), which owns
the cmesh-DOR proof. The declaration stays loadable and hash-stable, but
materialization refuses the mismatch with a precise hint instead of
silently rewriting the user's design family.
"""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, TopologyError, materialize_family,
    materialize_topology, materialize_topology_intent,
)
from veritx_dse.model.topology_intent import (
    ConcentratedMeshIntent, MeshIntent, topology_intent_from_dict,
)


def _request(n: int, *, concentration: int | None = None,
             radix: int | None = None) -> CompileRequest:
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1,
                          dp=1),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=n)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH,
                             radix=radix, concentration=concentration),
    )


def _inventory(n: int):
    return build_inventory(_request(n))


def test_mesh_concentration_one_is_unchanged():
    intent = MeshIntent(side_length=4, concentration=1)
    assert intent.to_dict() == {
        "kind": "mesh", "side_length": 4, "concentration": 1}
    assert topology_intent_from_dict(intent.to_dict()) == intent

    expected = materialize_family(
        MaterializedFamily.MESH, endpoint_count=16, concentration=1, radix=4)
    actual = materialize_topology_intent(_inventory(16), intent)
    assert actual.family is MaterializedFamily.MESH
    assert {r.seat_capacity for r in actual.routers} == {1}
    assert actual.topology_hash() == expected.topology_hash()


@pytest.mark.parametrize("concentration", [2, 4])
def test_mesh_concentration_above_one_gets_a_typed_family_hint(concentration):
    intent = MeshIntent(side_length=4, concentration=concentration)

    # The declaration remains lossless and loadable: refusing the physical
    # family must not silently rewrite the user's intent to concentrated_mesh.
    assert topology_intent_from_dict(intent.to_dict()) == intent

    with pytest.raises(TopologyError, match="concentrated_mesh") as excinfo:
        materialize_topology_intent(_inventory(16), intent)
    message = str(excinfo.value)
    assert "ConcentratedMeshIntent" in message
    assert "seat_capacity 1" in message
    assert f"concentration={concentration}" in message


@pytest.mark.parametrize("concentration", [2, 4])
def test_legacy_mesh_spelling_gets_the_same_family_hint(concentration):
    request = _request(16, concentration=concentration, radix=4)
    with pytest.raises(TopologyError, match="concentrated_mesh") as excinfo:
        materialize_topology(build_inventory(request), request)
    assert "ConcentratedMeshIntent" in str(excinfo.value)


@pytest.mark.parametrize("concentration", [2, 4])
def test_concentrated_mesh_intent_still_materializes(concentration):
    intent = ConcentratedMeshIntent(side_length=4,
                                    concentration=concentration)
    assert intent.to_dict() == {
        "kind": "concentrated_mesh", "side_length": 4,
        "concentration": concentration}
    assert topology_intent_from_dict(intent.to_dict()) == intent

    endpoints = 16 * concentration
    actual = materialize_topology_intent(_inventory(endpoints), intent)
    assert actual.family is MaterializedFamily.CONCENTRATED_MESH
    assert {r.seat_capacity for r in actual.routers} == {concentration}
    expected = materialize_family(
        MaterializedFamily.CONCENTRATED_MESH, endpoint_count=endpoints,
        concentration=concentration, radix=4)
    assert actual.topology_hash() == expected.topology_hash()
