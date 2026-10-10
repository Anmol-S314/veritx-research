"""Knob sweep: spare native fabric seats must stay idle, not become errors."""
from types import SimpleNamespace

import pytest

from veritx_dse.backend.astra_execution import AstraExecutionError, AstraMoney, assert_astra_gate


@pytest.mark.parametrize(('k','c','nodes'), [(3,2,18), (4,2,32), (5,2,50), (4,4,64)])
def test_gec_native_node_count_uses_constructor_grid_not_attachment_count(k, c, nodes):
    from veritx_dse.backend.astra_machine import fabric_node_count
    prepared=SimpleNamespace(config_text=f'topology = gec;\nk = {k};\nn = 2;\nc = {c};\n', endpoint_count=16)
    assert fabric_node_count(prepared) == nodes


def test_sweep_mutations_do_not_carry_stale_serialized_identities():
    from tools.sweep_intent_knobs import specs
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    rows = specs()
    assert len({row['name'] for row in rows}) == len(rows)
    for row in rows:
        assert 'design_hash' not in row['request']
        assert 'guardrail_hash' not in row['request']
        try:
            CompileRequestV4.from_dict(row['request'])
        except ValueError as exc:
            # Invalid boundary probes may refuse, but never for stale hashes.
            assert 'hash mismatch' not in str(exc), row['name']


def machine():
    return SimpleNamespace(astra_sys_count=32, participant_count=16,
        expansion_authority='astra_comm_coll', workload_compute_floor=0,
        workload_payload_bytes=8192)


def money(extra_comm=0, rogue=False):
    ranks=range(33 if rogue else 32)
    return AstraMoney(cycles=tuple((r,100 if r<16 else 0) for r in ranks),
        exposed_comm=tuple((r,90 if r<16 else extra_comm) for r in ranks),
        compute=tuple((r,0) for r in ranks))


def test_unattached_native_nodes_are_allowed_only_when_idle():
    assert assert_astra_gate(money(), machine=machine(), injected=0,
        participant_endpoints=tuple(range(16)), endpoint_count=16) == ()


def test_spare_native_nodes_cannot_carry_unrequested_communication():
    with pytest.raises(AstraExecutionError, match='non-participant'):
        assert_astra_gate(money(extra_comm=1), machine=machine(), injected=0,
            participant_endpoints=tuple(range(16)), endpoint_count=16)


def test_nodes_outside_the_rendered_native_fabric_still_refuse():
    with pytest.raises(AstraExecutionError, match='neither participants nor canonical fabric nodes'):
        assert_astra_gate(money(rogue=True), machine=machine(), injected=0,
            participant_endpoints=tuple(range(16)), endpoint_count=16)
