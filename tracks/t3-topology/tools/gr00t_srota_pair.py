#!/usr/bin/env python3
"""Compare the checked-in 64-terminal SROTA config with a matched mesh control."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
DSE = ROOT / 'tracks/t3-topology/dse'
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from veritx_dse.core.logging import Ctx
from veritx_dse.model.presets import Topology
from veritx_dse.simulation.booksim import build_config, run_booksim, find_booksim_bin
from gr00t_pipeline import check_packet_log

SROTA_CONFIG = ROOT / 'tracks/t3-topology/configs/srota64_rowcol.cfg'
COMMON = {
    'num_vcs': 4, 'vc_buf_size': 8, 'packet_size': 5,
    'use_noc_latency': 0, 'routing_delay': 1,
    'vc_allocator': 'islip', 'sw_allocator': 'islip', 'alloc_iters': 1,
    'vc_alloc_delay': 1, 'sw_alloc_delay': 1, 'credit_delay': 1,
    'st_prepare_delay': 0, 'st_final_delay': 1,
    'wait_for_tail_credit': 0, 'hold_switch_for_packet': 0,
    'buffer_policy': 'private',
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def config_from_template(template, overrides):
    lines = []
    for line in Path(template).read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(('//', '#')) or '=' not in stripped:
            lines.append(line)
            continue
        key = stripped.split('=', 1)[0].strip()
        if key not in overrides:
            lines.append(line)
    lines.extend(f'{key} = {value};' for key, value in overrides.items())
    return '\n'.join(lines) + '\n'


def run_pair(roi_result, output, *, timeout=120):
    roi_path = Path(roi_result).resolve()
    roi = json.loads(roi_path.read_text())
    trace_path = roi_path.parent / 'workload.trace'
    trace_sha = digest(trace_path)
    if trace_sha != roi['traffic']['trace_sha256']:
        raise ValueError('saved trace does not match pinned ROI result')
    rows = [tuple(map(int, line.split())) for line in trace_path.read_text().splitlines() if line.strip()]
    if not rows or any(len(row) != 5 for row in rows):
        raise ValueError('ROI trace is empty or malformed')
    if max(max(row[1], row[3]) for row in rows) >= 64:
        raise ValueError('trace endpoint IDs exceed the 64-terminal pair')
    output = Path(output).resolve()
    if any(ch.isspace() for ch in str(output)):
        raise ValueError('output path must not contain whitespace')
    output.mkdir(parents=True, exist_ok=False)
    trace = output / 'workload.trace'
    trace.write_bytes(trace_path.read_bytes())
    variants = [
        ('mesh_8x8_vc4', {'backend': 'mesh', 'routing': 'min_adapt', 'params': {'k': 8, 'n': 2}},
         build_config(Topology('mesh_8x8_vc4', 'mesh', 'min_adapt', {'k': 8, 'n': 2}), str(trace),
            sim_type='trace', seed=0, overrides={**COMMON, 'trace_file': str(trace),
            'trace_packet_log': str(output / 'mesh_8x8_vc4' / 'packets.csv'),
            'sample_period': 10000, 'sim_count': 1})),
        ('srota_8x8', {'backend': 'srota', 'routing': 'o1turn', 'params': {
            'k': 8, 'c': 1, 'srota_mecs': 3, 'srota_path_en': 3,
            'srota_vc_policy': 'rank', 'srota_cong_thresh': 8,
            'srota_epoch_len': 1024, 'srota_cdg_radix': 4}},
         None),
    ]
    variants[1] = (variants[1][0], variants[1][1], config_from_template(SROTA_CONFIG, {
        **COMMON, 'sim_type': 'trace', 'trace_file': str(trace),
        'trace_packet_log': str(output / 'srota_8x8' / 'packets.csv'),
        'sample_period': 10000, 'sim_count': 1, 'seed': 0,
    }))

    results = []
    for name, topology, config in variants:
        directory = output / name
        directory.mkdir()
        # The config was built before directory creation, but every output path is deterministic.
        config = config.replace(str(output / name / 'packets.csv'), str(directory / 'packets.csv'))
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

        metrics = run_booksim(Ctx(verbosity=0), config, repo_root=ROOT,
            timeout=timeout, label=name, runner=capture)
        packet_log = directory / 'packets.csv'
        observed = check_packet_log(packet_log, trace)
        if observed['packets'] != len(rows) or observed['flits'] != sum(row[-1] for row in rows):
            raise ValueError(f'{name} did not retire the exact source trace')
        results.append({'name': name, 'topology': topology, 'endpoints': 64,
            'config_sha256': digest(config_path), 'packet_log_sha256': digest(packet_log),
            'trace_sha256': trace_sha, 'observed': observed, 'metrics': metrics})

    result = {'schema': 'veritx/gr00t-srota-paired-comparison/1',
        'qualification': 'DIAGNOSTIC_OPEN_LOOP_ROI_PAIR',
        'source_roi_result_sha256': digest(roi_path), 'trace_sha256': trace_sha,
        'reproduction': {'tool_sha256': digest(__file__),
            'srota_template_sha256': digest(SROTA_CONFIG),
            'booksim_binary_sha256': digest(find_booksim_bin(ROOT))},
        'trace_packets': len(rows), 'trace_flits': sum(row[-1] for row in rows),
        'endpoint_binding': {'0': 'memory', '1': 'compute', '2': 'consumer',
            'policy': 'fixed source-trace IDs; no placement optimization'},
        'shared_router_settings': COMMON, 'variants': results,
        'limitations': ['Both networks have 64 terminals and use the same open-loop trace.',
            'Preset routing differs (mesh min_adapt; SROTA o1turn) and SROTA-specific MECS settings remain enabled.',
            'This is a diagnostic simulator comparison, not calibrated hardware or end-to-end model latency.']}
    (output / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'variants': len(results), 'packets': len(rows), 'flits': sum(row[-1] for row in rows),
        'mean_request_latency': {v['name']: v['observed']['request_latency_avg'] for v in results}}, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roi-result', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    run_pair(args.roi_result, args.output, timeout=args.timeout)


if __name__ == '__main__':
    main()
