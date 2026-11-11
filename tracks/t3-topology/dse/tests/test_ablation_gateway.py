"""Bounded ablation requests replay catalog traces, never arbitrary client paths."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.gateway import ablations

CATALOG = {'workloads': [{'workload_id': 'w', 'nodes': 64}], 'topologies': [{'topology_id': 't'}]}


class AblationGatewayTest(unittest.TestCase):
    def test_invalid_axes_refuse_without_starting_a_process(self):
        cases = [[], {'packet_size': True}, {'vc_buf_size': 1.5}, {'seed': None}, {'jobs': 17},
                 {'time_scale': float('nan')}, {'rank_stride': 2}, {'trace_packet_size': 0},
                 {'workloads': ['unknown']}, {'overrides': {'seed': '2'}}, {'overrides': {'k': '8'}}]
        with patch.object(ablations, '_catalog', return_value=CATALOG), patch.object(ablations.subprocess, 'run') as execute:
            for body in cases:
                with self.subTest(body=body):
                    self.assertEqual(ablations.run_ablation(body).status_code, 400)
            execute.assert_not_called()

    def test_valid_request_passes_frozen_catalog_and_explicit_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / 'catalog.json'
            catalog.write_text(json.dumps(CATALOG))
            commands = []
            def execute(command, **kwargs):
                commands.append(command)
                out = Path(command[command.index('--out') + 1])
                out.mkdir(parents=True)
                (out / 'ablation.json').write_text(json.dumps({'runs': [{'status': 'ok'}]}))
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            with patch.multiple(ablations, REPO=root, CATALOG=catalog, OUT_ROOT=root/'runs'), patch.object(ablations.subprocess, 'run', side_effect=execute):
                result = ablations.run_ablation({'workloads': ['w'], 'topologies': ['t'], 'trace_packet_size': 16,
                                                 'time_scale': 0.5, 'burst_window': 8, 'rank_stride': 9, 'rank_offset': 3})
            self.assertEqual(result['failed_cells'], 0)
            command = commands[0]
            self.assertEqual(command[command.index('--replay-catalog') + 1], str(catalog))
            self.assertEqual(command[command.index('--trace-packet-size') + 1], '16')
            self.assertEqual(command[command.index('--rank-stride') + 1], '9')
            self.assertEqual(command[command.index('--time-scale') + 1], '0.5')


if __name__ == '__main__':
    unittest.main()
