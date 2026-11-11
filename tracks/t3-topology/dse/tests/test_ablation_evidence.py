"""Ablation provenance must reflect the executed trace, not a workload label."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import ablate_workloads as runner
from ablation_evidence import transform_trace, sha256


class AblationEvidenceTest(unittest.TestCase):
    def test_active_nodes_counts_distinct_endpoints_not_highest_id(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'input.trace'
            trace.write_text('0 0 0 63 8\n10 63 0 0 8\n')
            stats = runner.trace_stats(trace)
            self.assertEqual(stats['active_nodes'], 2)
            self.assertEqual(stats['max_node'], 63)
            self.assertTrue(stats['trace_sha256'].startswith('sha256:'))
            self.assertEqual(stats['packet_size_flits'], [8])

    def test_zero_endpoint_is_one_active_node(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'input.trace'
            trace.write_text('0 0 0 0 4\n')
            self.assertEqual(runner.trace_stats(trace)['active_nodes'], 1)

    def test_effective_packet_sizes_come_from_packet_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'packets.csv'
            output.write_text('total_latency,hops,packet_size_flits,arrival_time\n12,2,8,12\n14,3,16,20\n')
            evidence = runner.parse_packets(output)
            self.assertEqual(evidence['effective_packet_size_flits'], [8, 16])
            self.assertEqual(evidence['delivered_flits'], 24)

    def test_malformed_packet_output_is_not_silently_partially_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'packets.csv'
            output.write_text('total_latency,hops,packet_size_flits,arrival_time\n12,2,8,12\n14,broken,8,20\n')
            self.assertEqual(runner.parse_packets(output)['status'], 'invalid_packets_out')

    def test_workload_variants_preserve_classes_and_rank_count(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.trace', Path(directory) / 'variant.trace'
            source.write_text('10 0 3 1 8\n30 1 3 0 8\n')
            original_hash = sha256(source)
            stats = transform_trace(source, output, 64, packet_flits=16, time_scale='0.5', burst_window=8, rank_stride=9, rank_offset=3)
            self.assertEqual(stats['active_nodes'], 2)
            self.assertEqual(stats['active_endpoint_ids'], [3, 12])
            self.assertEqual(stats['classes'], 4)
            self.assertEqual(stats['packet_size_flits'], [16])
            self.assertEqual(output.read_text(), '0 3 3 12 16\n8 12 3 3 16\n')
            self.assertEqual(sha256(source), original_hash)
            self.assertNotEqual(stats['trace_sha256'], original_hash)

    def test_identity_transform_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.csv', Path(directory) / 'copy.csv'
            source.write_bytes(b'timestamp,src,dst,type,packet_size\r\n0,0,63,WRITE,8\r\n')
            transform_trace(source, output, 64)
            self.assertEqual(source.read_bytes(), output.read_bytes())

    def test_invalid_placement_and_out_of_range_endpoints_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.trace', Path(directory) / 'copy.trace'
            source.write_text('0 0 0 64 8\n')
            with self.assertRaisesRegex(ValueError, 'coprime'):
                transform_trace(source, output, 64, rank_stride=2)
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                transform_trace(source, output, 64)

    def _run_cell(self, directory, response_code=0, rows=2, depth=8):
        root = Path(directory)
        workload = runner.Workload('test', 'Test', None, 4)
        topology = runner.Topology('mesh', 'MESH', 'Mesh', root / 'arm.cfg', 4, 2, 'dor')
        topology.config.write_text('topology=mesh;\nk=2;\nn=2;\n')
        trace = runner.trace_path(workload, root)
        trace.parent.mkdir(exist_ok=True)
        trace.write_text('0 0 0 3 8\n10 3 0 0 8\n')
        binary = root / 'booksim'
        binary.write_text('test binary')
        def execute(*args, **kwargs):
            packets = root / 'cells/test/mesh/packets_out.csv'
            packets.write_text('total_latency,hops,packet_size_flits,arrival_time\n' + '12,2,8,20\n' * rows)
            return SimpleNamespace(stdout='', stderr='', returncode=response_code)
        with patch.object(runner.subprocess, 'run', side_effect=execute) as run:
            result = runner.run_cell(workload, topology, root, str(binary), 2, False,
                                     {'packet_size': 5, 'vc_buf_size': depth, 'use_noc_latency': 0}, {}, {'seed': '1'})
            return result, run.call_count

    def test_nonzero_process_exit_is_never_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run_cell(directory, response_code=3)
            self.assertEqual(result['status'], 'failed')

    def test_partial_output_is_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run_cell(directory, rows=1)
            self.assertEqual(result['status'], 'incomplete')

    def test_seeded_trace_generation_is_repeatable(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / 'a.csv', Path(directory) / 'b.csv']
            workload = runner.REPO / 'third_party/booksim2/src/examples/ai_workloads/moe.yaml'
            for output in paths:
                subprocess.run([sys.executable, str(SCRIPTS / 'gen_trace.py'), str(workload), str(output), '--seed', '42'], check=True, capture_output=True)
            self.assertEqual(sha256(paths[0]), sha256(paths[1]))

    def test_cache_binds_config_trace_binary_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            first, calls = self._run_cell(directory)
            self.assertEqual(first['status'], 'ok')
            self.assertEqual(calls, 1)
            cached, calls = self._run_cell(directory)
            self.assertTrue(cached['cached'])
            self.assertEqual(calls, 0)
            changed, calls = self._run_cell(directory, depth=16)
            self.assertEqual(calls, 1)
            self.assertEqual(changed['declared_buffer_flits_per_input'], 32)
            packets = Path(directory) / 'cells/test/mesh/packets_out.csv'
            packets.write_text(packets.read_text() + '12,2,8,20\n')
            _, calls = self._run_cell(directory, depth=16)
            self.assertEqual(calls, 1)
            (Path(directory) / 'cells/test/mesh/result.json').write_text('{interrupted')
            _, calls = self._run_cell(directory, depth=16)
            self.assertEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()
