#!/usr/bin/env python3
"""Run the pinned GR00T ROI transfer trace across every declared topology preset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
DSE = ROOT / 'tracks/t3-topology/dse'
sys.path.insert(0, str(DSE))
from veritx_dse.core.logging import Ctx
from veritx_dse.model.presets import SWEEP_TOPOS, topo_size
from veritx_dse.simulation.booksim import build_config, run_booksim, find_booksim_bin
from gr00t_pipeline import check_packet_log

SHARED_OVERRIDES = {'num_vcs': 8, 'vc_buf_size': 8}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def rankings(variants):
    groups = {}
    for row in variants:
        if row['status'] == 'completed':
            groups.setdefault(str(row['topology']['endpoints']), []).append(row)
    return {count: [row['topology']['name'] for row in sorted(rows,
                key=lambda item: (item['observed']['request_latency_avg'],
                                  item['observed']['request_latency_p95'],
                                  item['topology']['name']))]
            for count, rows in sorted(groups.items(), key=lambda item: int(item[0]))}


def run_sweep(roi_result, output, *, timeout=120):
    roi_path = Path(roi_result).resolve()
    roi = json.loads(roi_path.read_text())
    expected_trace_sha = roi['traffic']['trace_sha256']
    source_trace = roi_path.parent / 'workload.trace'
    if digest(source_trace) != expected_trace_sha:
        raise ValueError('saved ROI trace does not match the pinned ROI result digest')
    trace_rows = [tuple(map(int, line.split())) for line in source_trace.read_text().splitlines() if line.strip()]
    if not trace_rows or any(len(row) != 5 for row in trace_rows):
        raise ValueError('ROI trace is empty or malformed')
    max_endpoint = max(max(row[1], row[3]) for row in trace_rows)
    output = Path(output).resolve()
    if any(ch.isspace() for ch in str(output)):
        raise ValueError('output path must not contain whitespace')
    output.mkdir(parents=True, exist_ok=False)
    trace = output / 'workload.trace'
    shutil.copyfile(source_trace, trace)
    variants = []
    for topo in SWEEP_TOPOS:
        endpoints, edges = topo_size(topo)
        if endpoints <= max_endpoint:
            raise ValueError(f'{topo.name} has only {endpoints} endpoints for trace endpoint {max_endpoint}')
        name = topo.name
        directory = output / name
        directory.mkdir()
        packet_log = directory / 'packets.csv'
        config = build_config(topo, str(trace), sim_type='trace', seed=0,
            overrides={**SHARED_OVERRIDES, 'trace_file': str(trace), 'sample_period': 10000,
                        'sim_count': 1, 'trace_packet_log': str(packet_log)})
        config_path = directory / 'booksim.cfg'
        config_path.write_text(config)

        def capture(command, cwd, timeout):
            completed = subprocess.run(command, cwd=cwd, timeout=timeout,
                stdin=subprocess.DEVNULL, capture_output=True, text=True)
            (directory / 'stdout.log').write_text(completed.stdout)
            (directory / 'stderr.log').write_text(completed.stderr)
            if completed.returncode:
                raise RuntimeError(f'BookSim exited {completed.returncode}')
            return completed

        meta = {'name': name, 'backend': topo.backend, 'routing': topo.routing,
                'params': topo.params, 'endpoints': endpoints, 'edges': edges}
        row = {'topology': meta, 'config_sha256': digest(config_path),
               'trace_sha256': expected_trace_sha}
        try:
            metrics = run_booksim(Ctx(verbosity=0), config, repo_root=ROOT,
                                  timeout=timeout, label=name, runner=capture)
            observed = check_packet_log(packet_log, trace)
            expected_packets = len(trace_rows)
            expected_flits = sum(request[-1] for request in trace_rows)
            if observed['packets'] != expected_packets or observed['flits'] != expected_flits:
                raise ValueError(f'{name} did not retire the exact shared trace')
            row.update({'status': 'completed', 'metrics': metrics, 'observed': observed,
                        'packet_log_sha256': digest(packet_log)})
        except Exception as exc:
            row.update({'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'})
        variants.append(row)
    result = {'schema': 'veritx/gr00t-topology-sweep/1',
        'qualification': 'DIAGNOSTIC_OPEN_LOOP_ROI_TOPOLOGY_COMPARISON',
        'source_roi_result_sha256': digest(roi_path), 'trace_sha256': expected_trace_sha,
        'reproduction': {'tool_sha256': digest(__file__),
            'booksim_binary_sha256': digest(find_booksim_bin(ROOT)),
            'command': 'python3 tracks/t3-topology/tools/gr00t_topology_sweep.py --roi-result <action-head-roi-simulation/result.json> --output <new-directory>'},
        'trace_packets': len(trace_rows), 'trace_flits': sum(row[-1] for row in trace_rows),
        'endpoint_binding': {'0': 'memory', '1': 'compute', '2': 'consumer',
            'policy': 'fixed endpoint IDs from the source ROI trace; no placement optimization'},
        'shared_router_overrides': SHARED_OVERRIDES,
        'ranking_metric': 'request_latency_avg then request_latency_p95 from exact retired packet logs; grouped by endpoint count',
        'rankings_by_endpoint_count': rankings(variants), 'variants': variants,
        'limitations': [
            'Covers only the same bounded MatMul ROI transfer trace, not full-model traffic.',
            'Topology rankings are diagnostic for this fixed endpoint placement and injection schedule.',
            'The 16-endpoint and 64-endpoint groups are not directly size-matched.',
            'Topology presets do not represent calibrated physical hardware.',
            'BookSim request-latency cycles are not combined with Timeloop cycles or interpreted as end-to-end latency.']}
    (output / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'variants': len(variants),
        'completed': sum(row['status'] == 'completed' for row in variants),
        'rankings_by_endpoint_count': result['rankings_by_endpoint_count']}, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roi-result', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    run_sweep(args.roi_result, args.output, timeout=args.timeout)


if __name__ == '__main__':
    main()
