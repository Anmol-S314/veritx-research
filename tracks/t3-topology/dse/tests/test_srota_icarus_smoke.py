import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / 'scripts/prepare_srota_icarus_smoke.py'
spec = importlib.util.spec_from_file_location('srota_smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def header():
    lines = ['module CandidateNoCTop(', 'input clock,', 'input reset,']
    for i in range(64):
        for prefix, last in [('ingress', 'egress_id'), ('egress', 'ingress_id')]:
            for field in ['ready', 'valid', 'bits_head', 'bits_tail', 'bits_route_tag', 'bits_payload', f'bits_{last}']:
                direction = 'input' if (prefix == 'ingress') != (field == 'ready') else 'output'
                width = '[127:0]' if field == 'bits_payload' else '[5:0]' if field == f'bits_{last}' else '[1:0]' if field == 'bits_route_tag' else ''
                lines.append(f'{direction} {width} io_{prefix}_{i}_flit_{field},')
    return '\n'.join(lines) + '\n);'


def test_full_design_smoke_drives_all_inputs_and_checks_payload_stalls_conservation():
    tb = smoke.testbench(header())
    assert tb.count('.io_ingress_') == 64 * 7
    assert tb.count('.io_egress_') == 64 * 7
    assert 'io_ingress_63_flit_valid=0;' in tb
    assert 'io_ingress_0_flit_bits_egress_id=63;' in tb
    assert 'stall stability' in tb
    assert 'accepted!=1 || delivered!=1' in tb
    assert 'packet corruption' in tb
    assert '$fatal(1,"test deadline")' in tb
    assert 'dut.force' not in tb


def test_missing_real_terminal_is_refused():
    with pytest.raises(ValueError, match='interface mismatch'):
        smoke.testbench(header().replace('io_ingress_42_flit_valid', 'wrong_signal'))
