"""Trace power must use its own counters, technology and power-counter interval."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import ablate_workloads as runner

SUMMARY = '- Total Power: 2\n- Total Area: 0.25\n- Completion Time: 30\n'


class AblationPowerTest(unittest.TestCase):
    def test_power_run_gets_frozen_technology_and_matching_energy_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            topology = runner.Topology('mesh', 'MESH', 'Mesh', root / 'arm.cfg', 4, 2, 'dor')
            topology.config.write_text('topology=mesh;\nk=2;\nn=2;\n')
            workload = runner.Workload('test', 'Test', None, 4)
            trace = runner.trace_path(workload, root)
            trace.parent.mkdir()
            trace.write_text('0 0 0 3 8\n')
            binary = root / 'booksim'
            binary.write_bytes(b'fixture binary')
            def execute(command, **kwargs):
                config = runner.read_knobs(Path(command[1]))
                tech = Path(config['tech_file'])
                self.assertTrue(tech.is_file())
                self.assertTrue(tech.is_relative_to(root))
                self.assertEqual(config['channel_width'], '128')
                (root / 'cells/test/mesh/packets_out.csv').write_text(
                    'total_latency,hops,packet_size_flits,arrival_time\n12,2,8,20\n')
                return SimpleNamespace(stdout=SUMMARY, stderr='', returncode=0)
            with patch.object(runner.subprocess, 'run', side_effect=execute):
                row = runner.run_cell(workload, topology, root, str(binary), 2, False,
                    {'packet_size': 5, 'vc_buf_size': 8, 'use_noc_latency': 0}, {'sim_power': '1'}, {})
            self.assertEqual(row['status'], 'ok')
            self.assertEqual(row['native_power_w'], 2)
            self.assertEqual(row['native_area_mm2'], .25)
            self.assertEqual(row['native_model']['status'], 'AVAILABLE')
            self.assertEqual(row['power_cycles'], 30)
            self.assertEqual(row['completion_cycles'], 20)
            self.assertAlmostEqual(row['total_energy_pj'], 2 * 30 / row['native_model']['clock_hz'] * 1e12)

    def test_unaudited_family_is_not_promoted_to_available(self):
        model = {'clock_hz': 1e9, 'model_id': 'test'}
        row = runner.trace_power_evidence(SUMMARY, 'GEC_MECS', 'ok', 0, model)
        self.assertNotEqual(row['native_model']['status'], 'AVAILABLE')
        self.assertIsNone(row['total_energy_pj'])
        self.assertEqual(row['native_output']['status'], 'UNAUDITED')
        self.assertEqual(row['native_output']['power_w'], 2)
        self.assertEqual(row['native_output']['area_mm2'], .25)
        self.assertAlmostEqual(row['native_output']['total_energy_pj'], 60000)

    def test_failed_process_does_not_publish_costs(self):
        row = runner.trace_power_evidence(SUMMARY, 'MESH', 'failed', 255, {'clock_hz': 1e9, 'model_id': 'test'})
        self.assertIsNone(row['native_power_w'])
        self.assertIsNone(row['total_energy_pj'])
        self.assertNotIn('native_output', row)

    def test_ambiguous_native_summary_is_not_published_as_diagnostics(self):
        row = runner.trace_power_evidence(SUMMARY + '- Total Power: 3\n', 'GEC_MECS', 'ok', 0,
                                          {'clock_hz': 1e9, 'model_id': 'test'})
        self.assertNotIn('native_output', row)

    def test_missing_or_ambiguous_interval_never_uses_packet_arrival(self):
        for text in ('- Total Power: 2\n- Total Area: 0.25\n', SUMMARY + '- Completion Time: 30\n'):
            row = runner.trace_power_evidence(text, 'MESH', 'ok', 0, {'clock_hz': 1e9, 'model_id': 'test'})
            self.assertIsNone(row['total_energy_pj'])


if __name__ == '__main__':
    unittest.main()
