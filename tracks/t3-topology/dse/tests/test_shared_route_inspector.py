"""Shared playback must consume the certified v3 relation, not silently drop it."""
from copy import deepcopy

from veritx_dse.application.compile_result_view import (
    _routing, compile_result_is_current,
)
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import build_typed_preset_request


def test_shared_inspector_preserves_artifact_choices_and_rejects_legacy_projection():
    compilation = FabricCompiler().compile(build_typed_preset_request('srota32_plane_c'))
    assert compilation.status == 'COMPILED', compilation.error
    route = compilation.bundle.router_route
    group = _routing(compilation.bundle, compilation.certificate)
    assert group['routing_classes'] == [route.routing_class]
    expected = {**route.canonical_dict(), 'artifact_id': route.route_artifact_id()}
    assert group['shared_route'] == expected
    assert group['entries'] == []  # Never disguise v3 wires as v2 channel IDs.
    payload = {
        'contract_version': 1,
        'groups': {'routing': group, 'fabric': {'topology': {'shared_links': [{'id': 0}]}}},
    }
    assert compile_result_is_current(payload)
    legacy = deepcopy(payload)
    del legacy['groups']['routing']['shared_route']
    assert not compile_result_is_current(legacy)
