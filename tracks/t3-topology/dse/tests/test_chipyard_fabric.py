"""Parameterized source contract tests. No hardware tools are invoked."""
from copy import deepcopy
import hashlib
import io
import json
import struct
import subprocess
from types import SimpleNamespace as NS
import zipfile

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.product.chipyard_fabric import (
    FabricSourceError, TARGET_IDS, binary_contract, contract_from_bundle,
    contract_hash, render_config, source_bundle, validate_contract,
)


def contract():
    return {
        'schema': 'veritx/compiled-fabric-source/1', 'topology_id': 'gec_mecs',
        'revision_id': 'p-test-r02', 'design_hash': 'test-design',
        'router_ids': [10, 20, 30],
        'ingress_routers': [0, 1], 'egress_routers': [0, 1],
        'resources': [
            {'native_id': 17, 'kind': 'SHARED_LINK', 'src': 0, 'taps': [1, 2], 'width_bits': 128, 'latency_cycles': 2},
            {'native_id': 81, 'kind': 'CHANNEL', 'src': 1, 'taps': [0], 'width_bits': 128, 'latency_cycles': 1},
        ],
        'packet_format': {'flit_width_bits': 128, 'fields': [
            {'name': 'destination_endpoint', 'lsb': 116, 'width': 7},
            {'name': 'vc_id', 'lsb': 125, 'width': 3},
            {'name': 'flit_type', 'lsb': 123, 'width': 2},
        ]},
        'vc_assignment': {'vc_count': 8},
        'router_behavior': {'input_buffer_depth_flits_per_vc': 8},
        'paths': [
            {'source': 0, 'destination': 0, 'hops': []},
            {'source': 0, 'destination': 1, 'hops': [[0, 1, [3, 5, 7]]]},
            {'source': 1, 'destination': 0, 'hops': [[1, 0, [0, 1]]]},
            {'source': 1, 'destination': 1, 'hops': []},
        ],
        'choices': [[0], [1], [2], [3]],
    }


@pytest.mark.parametrize('target', sorted(TARGET_IDS))
def test_all_target_ids_use_explicit_dimensions_not_catalog_defaults(target):
    # This checks the shared contract schema/serializer, not native route laws.
    doc = contract()
    doc['topology_id'] = target
    validate_contract(doc)
    assert binary_contract(doc)[:4] == struct.pack('>i', 0x56545831)
    assert 'FabricContract.load' in render_config(doc)
    assert '8x8' not in render_config(doc)


def test_shared_resource_is_not_expanded_and_sparse_ids_and_vcs_are_retained(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Source export must not start a compiler or process')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    doc = contract()
    with zipfile.ZipFile(io.BytesIO(source_bundle(doc, REPO))) as archive:
        saved = json.loads(archive.read('contract.json'))
        assert saved['router_ids'] == [10, 20, 30]
        assert len(saved['resources']) == 2
        assert saved['resources'][0]['taps'] == [1, 2]
        assert saved['paths'][1]['hops'][0][2] == [3, 5, 7]
        manifest = json.loads(archive.read('source-manifest.json'))
        assert manifest['contract_hash'] == contract_hash(doc)
        assert manifest['generation'] == manifest['lint'] == manifest['simulation'] == 'NOT_RUN'
        assert manifest['final_implementation'] is False
        for path, digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == digest
    assert render_config(doc) == render_config(deepcopy(doc))


def test_concentration_and_asymmetric_fly_endpoint_maps_are_preserved():
    doc = contract()
    doc['topology_id'] = 'fly64'
    doc['egress_routers'] = [2, 2]
    doc['resources'][1]['taps'] = [2]
    doc['paths'] = [
        {'source': s, 'destination': d, 'hops': [[s, 2, [0]]]}
        for s in range(2) for d in range(2)]
    validate_contract(doc)
    assert doc['ingress_routers'] != doc['egress_routers']
    doc['topology_id'] = 'cmesh'
    doc['ingress_routers'] = doc['egress_routers'] = [0, 0]
    for path in doc['paths']:
        path['hops'] = []
    validate_contract(doc)


@pytest.mark.parametrize('change, message', [
    (lambda d: d['resources'][0].update(kind='CHANNEL'), 'point-to-point'),
    (lambda d: d['paths'][1]['hops'][0].__setitem__(1, 0), 'physical resource'),
    (lambda d: d['paths'][1]['hops'][0].__setitem__(2, [8]), 'VC identity'),
    (lambda d: d['choices'].__setitem__(1, []), 'Missing'),
    (lambda d: d['choices'].__setitem__(1, [2]), 'another endpoint pair'),
    (lambda d: d.update(topology_id='unknown'), 'topology ID'),
])
def test_lossy_or_invalid_source_contract_is_refused(change, message):
    doc = contract()
    change(doc)
    with pytest.raises(FabricSourceError, match=message):
        validate_contract(doc)


def test_compiler_adapter_reads_existing_bundle_without_recompiling():
    class Artifact:
        def __init__(self, **values):
            self.__dict__.update(values)
        def to_dict(self):
            return self.document
    endpoints = [NS(endpoint_id=i, router_id=r, port_id=0, egress_port_id=None)
                 for i, r in enumerate([10, 20])]
    channels = [NS(channel_id=17, src_router=10, dst_router=20, width_bits=128, latency_cycles=1),
                NS(channel_id=81, src_router=20, dst_router=10, width_bits=128, latency_cycles=1)]
    bundle = NS(
        design=NS(topology=NS(kind='mesh'), design_hash=lambda: 'existing-design'),
        topology=Artifact(routers=[NS(router_id=10), NS(router_id=20)], channels=channels,
                          shared_links=[], document={'family': 'mesh'}),
        attachment=NS(endpoints=endpoints),
        resolved_route=NS(routing_pairs=lambda: [(0, 10), (1, 20)]),
        router_route=Artifact(entries={('XY', 10, 20): 17, ('XY', 20, 10): 81}, document={}),
        vc_assignment=Artifact(vc_count=2, vc_to_routing_class=((0, 'XY'), (1, 'XY')),
                               document={'vc_count': 2}),
        packet_format=Artifact(document=contract()['packet_format']),
        router_behavior=Artifact(document={'input_buffer_depth_flits_per_vc': 13}),
    )
    doc = contract_from_bundle(bundle, topology_id='mesh8x8', revision_id='frozen-r03')
    assert doc['router_ids'] == [10, 20]
    assert doc['router_behavior']['input_buffer_depth_flits_per_vc'] == 13
    assert doc['paths'][1]['hops'] == [[0, 1, [0, 1]]]
    with pytest.raises(FabricSourceError, match='does not match'):
        contract_from_bundle(bundle, topology_id='torus8x8', revision_id='frozen-r03')


def test_revision_export_checks_snapshot_identity_without_compiling(monkeypatch):
    from veritx_dse.application.errors import ControlPlaneError
    from veritx_dse.product.service import ProductService
    doc = contract()
    revision = {'revision_id': doc['revision_id'], 'design_hash': 'sha256:' + doc['design_hash'],
                'chipyard_source_contract': doc, 'chipyard_source_contract_hash': contract_hash(doc)}
    service = object.__new__(ProductService)
    service.store = NS(load_revision_global=lambda _id: ('p-test', revision))
    service.config = NS(repo_root=REPO)
    def forbidden(*args, **kwargs):
        raise AssertionError('Source download must not compile or run a process')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    with zipfile.ZipFile(io.BytesIO(service.revision_chipyard_source_archive(doc['revision_id']))) as archive:
        assert json.loads(archive.read('contract.json'))['revision_id'] == doc['revision_id']
    revision['chipyard_source_contract_hash'] = 'changed'
    with pytest.raises(ControlPlaneError, match='identity changed'):
        service.revision_chipyard_source_archive(doc['revision_id'])
    revision.pop('chipyard_source_contract')
    with pytest.raises(ControlPlaneError, match='No compile was launched'):
        service.revision_chipyard_source_archive(doc['revision_id'])
