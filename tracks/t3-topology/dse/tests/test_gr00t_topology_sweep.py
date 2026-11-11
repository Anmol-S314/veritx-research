from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parents[2] / 'tools'
DSE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS), str(DSE)]
from gr00t_topology_sweep import rankings


def row(name, endpoints, average, p95, status='completed'):
    return {'status': status, 'topology': {'name': name, 'endpoints': endpoints},
            'observed': {'request_latency_avg': average, 'request_latency_p95': p95}}


def test_rankings_group_sizes_and_exclude_failed_runs():
    result = rankings([
        row('mesh64', 64, 20.0, 25), row('torus64', 64, 18.0, 30),
        row('mesh16', 16, 7.0, 9), row('failed', 64, 1.0, 1, 'failed'),
    ])
    assert result == {'16': ['mesh16'], '64': ['torus64', 'mesh64']}


def test_ranking_breaks_latency_ties_by_p95_then_name():
    result = rankings([row('z', 64, 10.0, 20), row('b', 64, 10.0, 18),
                       row('a', 64, 10.0, 18)])
    assert result['64'] == ['a', 'b', 'z']
