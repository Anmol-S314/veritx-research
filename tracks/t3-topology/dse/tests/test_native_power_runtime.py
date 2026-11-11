"""Opt-in, actual BookSim activity/area/energy checks for newly audited families."""
import csv
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import ablate_workloads as runner
from native_power import power_evidence

BINARY = os.environ.get('VERITX_POWER_AUDIT_BIN')
pytestmark = pytest.mark.skipif(not BINARY, reason='Set VERITX_POWER_AUDIT_BIN to the instrumented BookSim binary')


@pytest.mark.parametrize('topology_id', ['ring', 'qtree', 'tree4', 'fly64', 'srota8x8', 'gec_mecs', 'gec_hybrid'])
def test_native_costs_follow_real_activity_and_preserve_area(topology_id, tmp_path):
    topology = next(t for t in runner.TOPOLOGIES if t.topology_id == topology_id)
    workload = runner.Workload('load-check', 'Load check', Path('unused.yaml'), 64)
    results = []
    for label, burst_cycle in [('dense', 1), ('sparse', 10000)]:
        root = tmp_path / label
        trace = runner.trace_path(workload, root)
        trace.parent.mkdir(parents=True)
        with trace.open('w') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'src', 'dst', 'type', 'packet_size'])
            for cycle in [0, burst_cycle]:
                for src in range(64):
                    writer.writerow([cycle, src, (src + 1) % 64, 'WRITE', 8])
        row = runner.run_cell(workload, topology, root, BINARY, 60, True,
            {'packet_size': 5, 'vc_buf_size': 8, 'use_noc_latency': 0}, {'sim_power': '1'}, {})
        assert row['status'] == 'ok', row
        assert row['delivered_packets'] == 128
        assert row['native_model']['status'] == 'AVAILABLE', row['native_model']
        assert row['native_model']['coverage_audit']['status'] == 'COMPLETE'
        assert row['native_model']['coverage_audit']['counts']['Unmodeled Outputs'] == 0
        assert row['power_cycles'] > row['completion_cycles']
        assert row['total_energy_pj'] == pytest.approx(row['native_power_w'] * row['power_cycles'] / row['native_model']['clock_hz'] * 1e12)
        results.append(row)
    dense, sparse = results
    assert sparse['native_area_mm2'] == pytest.approx(dense['native_area_mm2'])
    assert sparse['native_power_w'] < dense['native_power_w']
    assert sparse['total_energy_pj'] > dense['total_energy_pj']


@pytest.mark.parametrize('topology_id', ['srota8x8', 'gec_mecs', 'gec_hybrid'])
def test_shared_wire_models_require_live_v2_electrical_coverage(topology_id, tmp_path):
    topology = next(t for t in runner.TOPOLOGIES if t.topology_id == topology_id)
    workload = runner.Workload('shared-check', 'Shared-wire check', Path('unused.yaml'), 64)
    trace = runner.trace_path(workload, tmp_path)
    trace.parent.mkdir(parents=True)
    trace.write_text('timestamp,src,dst,type,packet_size\n0,0,63,WRITE,8\n')
    row = runner.run_cell(workload, topology, tmp_path, BINARY, 60, True,
        {'packet_size': 5, 'vc_buf_size': 8, 'use_noc_latency': 0}, {'sim_power': '1'}, {})
    assert row['status'] == 'ok', row
    assert row['native_model']['status'] == 'AVAILABLE', row['native_model']
    counts = row['native_model']['coverage_audit']['counts']
    expected = {'srota8x8': (224, 896, 1792), 'gec_mecs': (32, 96, 192), 'gec_hybrid': (32, 96, 192)}[topology_id]
    assert counts['Unmodeled Outputs'] == counts['Unmodeled Inputs'] == 0
    assert (counts['Shared Wires'], counts['Shared Taps']) == expected[:2]
    assert counts['Shared Segments'] == counts['Shared Taps']
    text = (tmp_path / row['log']).read_text()
    import re
    length = float(re.search(r'^- Shared Wire Length mm: ([\d.eE+-]+)', text, re.M)[1])
    assert length == expected[2]
    # Removing the v2 contract cannot turn old partial shared output into a full cost.
    old = text.replace('Power Coverage Version: 2', 'Power Coverage Version: 1')
    assert power_evidence(old, topology.family, 'ok', 0, row['native_model'])['native_model']['status'] == 'UNSUPPORTED'
