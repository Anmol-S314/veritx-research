"""Actual-simulator checks for the declared shared-wire electrical assumptions."""
import csv
from dataclasses import replace
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import ablate_workloads as runner
from native_power import prepare_model, power_evidence, _summary_value

BINARY = os.environ.get('VERITX_POWER_AUDIT_BIN')
pytestmark = pytest.mark.skipif(not BINARY, reason='Set VERITX_POWER_AUDIT_BIN to the shared-wire candidate')


def run_small(root, topology_id, side=None, overrides=None):
    topology = next(t for t in runner.TOPOLOGIES if t.topology_id == topology_id)
    if side:
        config = root / 'topology.cfg'
        root.mkdir(parents=True, exist_ok=True)
        config.write_text(topology.config.read_text() + f'\nk = {side};\n')
        topology = replace(topology, config=config, nodes=side * side)
    workload = runner.Workload('electrical', 'Electrical check', Path('unused.yaml'), topology.nodes)
    trace = runner.trace_path(workload, root)
    trace.parent.mkdir(parents=True, exist_ok=True)
    with trace.open('w') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'src', 'dst', 'type', 'packet_size'])
        for cycle in (0, 1):
            for src in range(topology.nodes):
                writer.writerow([cycle, src, (src + 1) % topology.nodes, 'WRITE', 8])
    row = runner.run_cell(workload, topology, root, BINARY, 60, True,
        {'packet_size': 5, 'vc_buf_size': 8, 'use_noc_latency': 0}, {'sim_power': '1', **(overrides or {})}, {})
    return row, topology


def variant(root, original_root, topology, key, value):
    tech = runner.REPO / 'third_party/booksim2/src/power/techfile.txt'
    fake_repo = root / 'repo'
    modified = fake_repo / 'third_party/booksim2/src/power/techfile.txt'
    modified.parent.mkdir(parents=True)
    modified.write_text(re.sub(rf'(?m)^(\s*{key}\s*=\s*)[^;]+', rf'\g<1>{float(value)}', tech.read_text()))
    model = prepare_model(fake_repo, root / 'model', Path(BINARY))
    cfg = original_root / 'cells/electrical' / topology.topology_id / 'run.cfg'
    result = subprocess.run([BINARY, str(cfg), f'tech_file={root}/model/native-model/techfile.txt',
                             f'trace_packet_log={root}/packets.csv'], cwd=runner.BOOKSIM_BASE,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout[-1000:]
    evidence = power_evidence(result.stdout, topology.family, 'ok', 0, model)
    assert evidence['native_model']['status'] == 'AVAILABLE', evidence
    assert runner.parse_packets(root / 'packets.csv')['delivered_packets'] == topology.nodes * 2
    return evidence, result.stdout


@pytest.mark.parametrize('topology_id', ['srota8x8', 'gec_mecs', 'gec_hybrid'])
def test_tap_load_voltage_scaling_and_geometric_pitch(topology_id, tmp_path):
    root = tmp_path / 'base'
    base, topology = run_small(root, topology_id)
    assert base['native_model']['status'] == 'AVAILABLE', base
    text = (root / base['log']).read_text()
    # The electrical optimizer must actually include the receiver load.
    assert 'tap_load=D2' in text
    higher_v, vtext = variant(tmp_path / 'voltage', root, topology, 'Vdd', 1.1)
    assert higher_v['native_area_mm2'] == pytest.approx(base['native_area_mm2'])
    assert _summary_value(vtext, 'Shared Tap Power') / _summary_value(text, 'Shared Tap Power') == pytest.approx((1.1 / .9) ** 2)
    assert _summary_value(vtext, 'Shared Tap Leakage') / _summary_value(text, 'Shared Tap Leakage') == pytest.approx(1.1 / .9)
    wider, wtext = variant(tmp_path / 'pitch', root, topology, 'wire_length', 4)
    assert _summary_value(wtext, 'Shared Wire Length mm') == 2 * _summary_value(text, 'Shared Wire Length mm')
    assert _summary_value(wtext, 'Shared Tap Area') == _summary_value(text, 'Shared Tap Area')
    assert _summary_value(wtext, 'Shared Total Area') > _summary_value(text, 'Shared Total Area')
    assert _summary_value(wtext, 'Shared Total Power') > _summary_value(text, 'Shared Total Power')
    for label in ('Input  Area', 'Switch  Area', 'Output  Area'):
        assert _summary_value(wtext, label) == _summary_value(text, label)


def test_srota_scaling_counts_physical_trunks_and_taps_without_duplicate_wires(tmp_path):
    small, _ = run_small(tmp_path / 'small', 'srota8x8', side=4)
    large, _ = run_small(tmp_path / 'large', 'srota8x8')
    for row, root, wires, taps, length in [(small, tmp_path / 'small', 48, 96, 192),
                                          (large, tmp_path / 'large', 224, 896, 1792)]:
        assert row['native_model']['status'] == 'AVAILABLE', row
        counts = row['native_model']['coverage_audit']['counts']
        assert counts['Shared Wires'] == wires
        assert counts['Shared Taps'] == taps
        assert _summary_value((root / row['log']).read_text(), 'Shared Wire Length mm') == length
    assert large['native_area_mm2'] > small['native_area_mm2']


def test_special_sidebuffer_storage_cannot_silently_use_plain_iq_cost(tmp_path):
    row, _ = run_small(tmp_path, 'srota8x8', overrides={'srota_router': 'sidebuf', 'srota_sb_depth': '8'})
    assert row['native_model']['status'] != 'AVAILABLE', row
    assert row['native_power_w'] is None
