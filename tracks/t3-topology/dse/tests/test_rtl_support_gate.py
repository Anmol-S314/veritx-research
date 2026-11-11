"""The finalization seam names the RTL emitter's slice instead of failing generically.

The catalog can select fabrics the one product RTL emitter was never certified
for (GEC MECS / GEC hybrid multi-VC, SROTA shared-wire). Those must be refused
with a typed reason naming the family, VC count and shared-wire condition — and
a supported connected 2-VC fabric must still reach the existing emitter.
"""
from dataclasses import replace
import json
import subprocess
import sys

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.views import topology_view
from veritx_dse.core.paths import REPO
from veritx_dse.model.topology_intent import topology_intent_from_dict
from veritx_dse.product.catalog_evaluation import (
    RTL_EMITTER_VC_COUNT,
    RTL_SUPPORTED_CERTIFIED,
    RTL_UNSUPPORTED_SHARED_WIRE,
    RTL_UNSUPPORTED_TOPOLOGY,
    RTL_UNSUPPORTED_VC_SCHEME,
    catalog_for,
    rtl_support,
    rtl_support_reason,
)
from veritx_dse.product.rtl_export import run_rtl_preview
from test_catalog_evaluation import _client, _project_doc
from test_topology_search import _base


def _request(topology_id):
    base = _base()
    row = next(row for row in catalog_for(base) if row['topology_id'] == topology_id)
    return replace(base, topology=topology_intent_from_dict(row['topology']))


def _compiled_view(request):
    compilation = FabricCompiler().compile(request)
    assert compilation.status == 'COMPILED', compilation.error
    return topology_view(compilation)


def test_gec_mecs_reports_its_vc_count_and_the_missing_emitter():
    request = _request('gec_mecs')
    support = rtl_support(request, _compiled_view(request))
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_VC_SCHEME
    assert support.vc_count > RTL_EMITTER_VC_COUNT
    assert support.shared_wire_links > 0
    assert 'gec_mecs' in support.reason
    assert f'{support.vc_count} VCs' in support.reason
    assert 'shared (multi-drop)' in support.reason
    assert 'no matching RTL emitter exists' in support.reason
    assert 'RTL generation' in support.reason
    assert rtl_support_reason(request, _compiled_view(request)) == support.reason
    # The RTL preview path must never be asked to emit 2-VC RTL for it.
    assert support.matches_certified_vc_count is False


def test_gec_hybrid_reports_the_vc_scheme_not_a_generic_error():
    request = _request('gec_hybrid')
    support = rtl_support(request, _compiled_view(request))
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_VC_SCHEME
    assert support.vc_count > RTL_EMITTER_VC_COUNT
    assert f'{support.vc_count} VCs' in support.reason


def test_srota_reports_the_shared_wire_condition():
    request = _request('srota')
    support = rtl_support(request, _compiled_view(request))
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_SHARED_WIRE
    assert support.shared_wire_links > 0
    assert f'{support.shared_wire_links} shared' in support.reason
    assert 'point-to-point' in support.reason


def test_non_reciprocal_fabric_is_reported_as_a_topology_refusal():
    request = _request('fly_native')
    support = rtl_support(request, _compiled_view(request))
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_TOPOLOGY
    assert 'non-reciprocal' in support.reason


def test_no_compiled_topology_is_not_assumed_servable():
    support = rtl_support(_request('torus'), None)
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_TOPOLOGY
    assert 'no compiled topology' in support.reason


def test_uncompiled_gec_selection_already_names_its_vc_scheme():
    support = rtl_support(_request('gec_mecs'), None)
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_VC_SCHEME
    assert support.vc_count > RTL_EMITTER_VC_COUNT
    assert 'gec:multidrop' in support.reason


def test_certified_2vc_connected_fabric_still_reaches_the_existing_emitter(tmp_path):
    request = _request('torus')
    support = rtl_support(request, _compiled_view(request))
    assert support.supported is True, support.reason
    assert support.code == RTL_SUPPORTED_CERTIFIED
    assert support.vc_count == RTL_EMITTER_VC_COUNT
    assert support.connected and support.reciprocal

    result = run_rtl_preview(request.to_dict(), tmp_path, {'repo_root': str(REPO)})
    assert result['scope'] == 'TOPOLOGY_ONLY_PREVIEW'
    manifest = json.loads((tmp_path / 'rtl-preview.json').read_text())
    assert manifest['emitted_vcs'] == RTL_EMITTER_VC_COUNT
    assert (tmp_path / 'rtl' / 'noc_top.sv').is_file()
    assert (tmp_path / 'rtl' / 'addr_decode.sv').is_file()
    assert manifest['address_decode']['status'] == 'EMPTY'
    assert manifest['address_decode']['lint']['status'] in ('PASS', 'NOT_RUN')


def test_a_resolved_address_map_reaches_the_emitted_decoder(tmp_path):
    from dataclasses import replace

    from veritx_dse.model.compile_model import (
        AddressMap, AddressRange, Agent, AgentKind,
    )
    base = _request('torus')
    request = replace(
        base,
        agents=(
            Agent(kind=AgentKind.COMPUTE_TILE, count=31, protocol='AXI',
                  data_width=256, addr_width=64),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=1, protocol='CHI',
                  data_width=512, addr_width=48),
        ),
        address_map=AddressMap(ranges=(
            AddressRange(name='HBM0', base=0x1000_0000, size=0x1000_0000,
                         target_agent_idx=1),
        )),
    )
    result = run_rtl_preview(request.to_dict(), tmp_path, {'repo_root': str(REPO)})
    assert result['address_decode'] == 'EMITTED'
    manifest = json.loads((tmp_path / 'rtl-preview.json').read_text())
    decode = manifest['address_decode']
    assert decode['status'] == 'EMITTED'
    assert decode['entry_count'] == 1
    assert decode['lint']['status'] in ('PASS', 'NOT_RUN')
    if decode['lint']['status'] == 'PASS':
        assert decode['lint']['clean'] is True, decode['lint']
        assert result['address_decode_lint_clean'] is True
    assert len(decode['endpoints']) == 32
    assert any(endpoint['agent_kind'] == 'hbm_controller'
               for endpoint in decode['endpoints'])
    meta = json.loads((tmp_path / 'rtl' / 'meta.json').read_text())
    assert 'addr_decode.sv' in meta['files']
    assert 'lint-addr-decode:' in (tmp_path / 'rtl' / 'Makefile').read_text()
    source = (tmp_path / 'rtl' / 'addr_decode.sv').read_text()
    assert 'HBM0' in source
    assert "64'h0000000010000000" in source
    assert "64'h000000001fffffff" in source


_TINY4 = """\
router 0 node 0 router 1 router 2
router 1 node 1 router 0 router 3
router 2 node 2 router 0 router 3
router 3 node 3 router 1 router 2
"""


@pytest.mark.parametrize('declaration, expected', [
    (('--selected-vcs', '5', '--selected-family', 'gec_mecs'), '5 VCs'),
    (('--shared-wires', '72', '--selected-family', 'srota'), '72 shared'),
])
def test_emitter_seam_refuses_a_selected_fabric_outside_its_slice(
        tmp_path, declaration, expected):
    anynet = tmp_path / 'tiny4.anynet'
    anynet.write_text(_TINY4)
    outdir = tmp_path / 'rtl'
    proc = subprocess.run(
        [sys.executable, str(REPO / 'tracks/t3-topology/scripts/rtlgen/gen_rtl.py'),
         '--anynet', str(anynet), '--outdir', str(outdir), *declaration],
        capture_output=True, text=True)
    assert proc.returncode == 2, proc.stderr
    assert expected in proc.stderr
    assert 'no matching RTL emitter exists' in proc.stderr
    assert not outdir.exists(), 'refusing must not emit artifacts'


def test_readiness_exposes_the_typed_reason_for_a_selected_gec_fabric(tmp_path):
    request = _request('gec_mecs')
    with _client(tmp_path) as client:
        pid, draft = _project_doc(client, request.to_dict())
        compiled = client.post(
            f'/api/v1/projects/{pid}/compile',
            json={'expected_draft_design_hash': draft['design_hash']})
        assert compiled.status_code == 200, compiled.text
        readiness = client.get(f'/api/v1/projects/{pid}/rtl-readiness')
        assert readiness.status_code == 200, readiness.text
        body = readiness.json()
        support = body['preview_support']
        assert support['supported'] is False
        assert support['code'] == RTL_UNSUPPORTED_VC_SCHEME
        assert support['vc_count'] > RTL_EMITTER_VC_COUNT
        assert support['reason'] in body['preview_blockers']
        assert body['preview_available'] is False
        # Submitting must carry the same typed reason, not a generic failure.
        refused = client.post(
            f'/api/v1/projects/{pid}/rtl-previews',
            json={'expected_draft_design_hash': draft['design_hash'],
                  'acknowledge_preview': True})
        assert refused.status_code in (400, 409, 422), refused.text
        assert refused.json()['code'] == 'POLICY_REJECTED'
        assert 'no matching RTL emitter exists' in refused.json()['detail']
        assert 'gec_mecs' in refused.json()['detail']


def test_class_vcs_singleton_on_two_vc_emitter_is_same_scheme():
    from types import SimpleNamespace
    request = _request('mesh')
    assignment = SimpleNamespace(
        vc_ids=(0, 1),
        traffic_class_to_vcs=(('tp_collective', (0,)), ('ep_dispatch', (1,))),
    )
    support = rtl_support(request, None, assignment)
    assert support.code != RTL_UNSUPPORTED_VC_SCHEME


def test_multi_vc_subset_isolation_stays_refused():
    from types import SimpleNamespace
    request = _request('mesh')
    assignment = SimpleNamespace(
        vc_ids=(0, 1, 2),
        traffic_class_to_vcs=(('tp_collective', (0, 1)), ('ep_dispatch', (2,))),
    )
    support = rtl_support(request, None, assignment)
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_VC_SCHEME


def test_class_vc_subsets_are_refused_even_at_two_vcs():
    from types import SimpleNamespace
    request = _request('mesh')
    assignment = SimpleNamespace(
        vc_ids=(0, 1),
        traffic_class_to_vcs=(('tp_collective', (2,)), ('ep_dispatch', (0,))),
    )
    support = rtl_support(request, None, assignment)
    assert support.supported is False
    assert support.code == RTL_UNSUPPORTED_VC_SCHEME
