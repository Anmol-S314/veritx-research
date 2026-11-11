"""New topology families need live coverage, not merely positive cost totals."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from native_power import coverage_audit, power_evidence

MODEL = {'model_id': 'fixture', 'clock_hz': 1e9, 'area_coefficients': {
    'input_flit_mm2': .001, 'crosspoint_mm2': .002, 'output_port_mm2': .003,
}}
COUNTS = {'Config Supported': 1, 'Routers': 4, 'Modeled Channels': 24,
          'Duplicate Channels': 0, 'Unmodeled Inputs': 0, 'Unmodeled Outputs': 0,
          'Endpoint Errors': 0, 'Non-IQ Routers': 0, 'Monitor Errors': 0,
          'Total Inputs': 20, 'Total Outputs': 20, 'Crosspoints': 100, 'Buffer Slots': 320}
PARTS = ['Channel Wire Power', 'Channel Clock Power', 'Channel Retiming Power', 'Channel Leakage Power',
         'Input Read Power', 'Input Write Power', 'Input Leakage Power', 'Switch Power',
         'Switch Control Power', 'Switch Leakage Power', 'Output DFF Power', 'Output Clk Power', 'Output Control Power']
SUMMARY = ('Network cost: subnet=0 routers=4 input_ports=20 output_ports=20 crosspoints=100 storage_flits=320\n'
           '- Power Coverage Version: 1\n' + ''.join(f'- Power {k}: {v}\n' for k, v in COUNTS.items())
           + ''.join(f'- {name}: 1\n' for name in PARTS)
           + '- Total Power: 13\n- Channel Area: 1\n- Switch  Area: .2\n- Input  Area: .32\n- Output  Area: .06\n- Total Area: 1.58\n')


@pytest.mark.parametrize('family', ['RING', 'QTREE', 'TREE4', 'FLY'])
def test_new_families_require_complete_runtime_coverage(family):
    row = power_evidence(SUMMARY, family, 'ok', 0, MODEL)
    assert row['native_model']['status'] == 'AVAILABLE'
    assert row['native_model']['coverage_audit']['status'] == 'COMPLETE'
    assert row['native_power_w'] == 13
    old = power_evidence('- Total Power: 13\n- Total Area: 1.58\n', family, 'ok', 0, MODEL)
    assert old['native_model']['status'] == 'UNSUPPORTED'
    assert old['native_power_w'] is None


@pytest.mark.parametrize('label,value', [('Unmodeled Inputs', 7), ('Unmodeled Outputs', 1),
    ('Duplicate Channels', 1), ('Endpoint Errors', 1), ('Non-IQ Routers', 1), ('Monitor Errors', 1),
    ('Config Supported', 0), ('Buffer Slots', 321), ('Crosspoints', 101), ('Total Inputs', 21), ('Routers', 5)])
def test_coverage_errors_block_even_previously_supported_families(label, value):
    broken = SUMMARY.replace(f'- Power {label}: {COUNTS[label]}\n', f'- Power {label}: {value}\n')
    row = power_evidence(broken, 'MESH', 'ok', 0, MODEL)
    assert row['native_model']['status'] != 'AVAILABLE'
    assert row['native_power_w'] is None


@pytest.mark.parametrize('label,value', [('Total Power', 14), ('Total Area', 2),
    ('Input  Area', .33), ('Switch  Area', .21), ('Output  Area', .07)])
def test_independent_component_reconciliation(label, value):
    import re
    broken = re.sub(rf'^- {label}: .*$', f'- {label}: {value}', SUMMARY, flags=re.M)
    assert coverage_audit(broken, MODEL)['status'] == 'INCOMPLETE'


def test_shared_wire_omission_is_explicit_and_stays_blocked():
    text = SUMMARY.replace('- Power Unmodeled Outputs: 0', '- Power Unmodeled Outputs: 32')
    row = power_evidence(text, 'GEC_MECS', 'ok', 0, MODEL)
    assert row['native_model']['status'] == 'UNSUPPORTED'
    assert 'omits 32 shared-wire outputs' in row['native_model']['reason']
    assert row['native_power_w'] is None


def test_duplicate_or_missing_coverage_cannot_certify():
    for text in (SUMMARY + '- Power Routers: 4\n', SUMMARY.replace('- Power Crosspoints: 100\n', '')):
        assert coverage_audit(text, MODEL)['status'] == 'INCOMPLETE'


SHARED_MODEL = {**MODEL, 'shared_wire_model': {'router_pitch_mm': 2},
                'shared_coefficients': {'tap_bank_mm2': .01, 'tap_dynamic_w_per_rate': 2,
                                        'tap_bank_leakage_w': .01}}
SHARED_SUMMARY = (SUMMARY.replace('Power Coverage Version: 1', 'Power Coverage Version: 2')
    .replace('input_ports=20', 'input_ports=21').replace('storage_flits=320', 'storage_flits=336')
    .replace('Power Total Inputs: 20', 'Power Total Inputs: 21')
    .replace('Power Buffer Slots: 320', 'Power Buffer Slots: 336')
    .replace('Input  Area: .32', 'Input  Area: .336').replace('Total Area: 1.58', 'Total Area: 1.596')
    + '- Completion Time: 100\n- Power Shared Model Version: 1\n- Power Shared Wires: 1\n'
      '- Power Shared Taps: 2\n- Power Shared Segments: 2\n- Power Shared Active Tap Flits: 10\n'
      '- Power Shared Geometry Errors: 0\n- Shared Wire Length mm: 4\n'
      '- Shared Trunk Area: .1\n- Shared Tap Area: .02\n- Shared Total Area: .12\n'
      '- Shared Trunk Power: .5\n- Shared Tap Power: .2\n- Shared Tap Leakage: .02\n- Shared Total Power: .72\n')


@pytest.mark.parametrize('family', ['SROTA', 'GEC_MECS', 'GEC_HYBRID'])
def test_shared_family_requires_the_electrical_proof_not_an_allowlist(family):
    assert power_evidence(SHARED_SUMMARY, family, 'ok', 0, SHARED_MODEL)['native_model']['status'] == 'AVAILABLE'
    assert power_evidence(SUMMARY, family, 'ok', 0, MODEL)['native_model']['status'] == 'UNSUPPORTED'


@pytest.mark.parametrize('label,value', [('Power Shared Model Version', 0), ('Power Shared Segments', 3),
    ('Power Shared Taps', 3), ('Power Shared Geometry Errors', 1), ('Shared Wire Length mm', 1),
    ('Shared Tap Area', .03), ('Shared Tap Power', .3), ('Shared Tap Leakage', .03),
    ('Shared Total Area', 2), ('Shared Total Power', 2), ('Power Shared Active Tap Flits', 11)])
def test_shared_component_or_geometry_errors_cannot_be_promoted(label, value):
    import re
    broken = re.sub(rf'^- {label}: .*$', f'- {label}: {value}', SHARED_SUMMARY, flags=re.M)
    row = power_evidence(broken, 'GEC_MECS', 'ok', 0, SHARED_MODEL)
    assert row['native_model']['status'] != 'AVAILABLE'
    assert row['native_power_w'] is None


def test_shared_missing_technology_or_component_output_refuses():
    assert coverage_audit(SHARED_SUMMARY, MODEL)['status'] == 'INCOMPLETE'
    for line in ('- Shared Tap Leakage: .02\n', '- Power Shared Taps: 2\n'):
        assert coverage_audit(SHARED_SUMMARY.replace(line, ''), SHARED_MODEL)['status'] == 'INCOMPLETE'
