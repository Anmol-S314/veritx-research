#!/usr/bin/env python3
"""Pinned G1 trajectory ingestion and bounded simulator infrastructure.

This is sensor/trajectory projection, not yet a GR00T operator extractor.
Optional research dependencies are imported only by source export.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
DSE = ROOT / 'tracks/t3-topology/dse'
REVISION = 'ea7ac0b68f87da62f1e726771bba0fe74300802f'
REPO = 'nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim'
SUBSET = 'unitree_g1.LMPnPAppleToPlateDC'
HASHES = {
    'parquet_sha256': 'dbbcb8ac2831fb62f16425b3c7dfe7b57169a6a24960a8a743bbef903bd6fd32',
    'mp4_sha256': 'e3287f43ec3a8ea8b1f75453c2c559c75909cdd9128b0a147bb7fc936fc84e4d',
}
LEDGER_SHA = '0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96'
DEFAULT_LEDGER = ROOT / 'tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl'
FILES = {
    'episode_000000.parquet': ('data/chunk-000/episode_000000.parquet', HASHES['parquet_sha256'], 1651349),
    'episode_000000.mp4': ('videos/chunk-000/observation.images.ego_view/episode_000000.mp4', HASHES['mp4_sha256'], 1465034),
}
BOUNDARY = ('Dataset-derived source ledger only. Video sizes exclude MP4 container overhead; '
            'state/action byte counts are raw vector values, not serialized or wire sizes. '
            'No endpoints, packetization, network timing, or hardware performance are claimed.')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_new(path, data):
    """Exclusive creation: never replace a caller's file, including symlinks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data if isinstance(data, bytes) else data.encode('utf-8'))


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def checked_hash(path, expected):
    if sha(path) != expected:
        raise ValueError(f'{path}: SHA-256 mismatch')


def read_ledger(path):
    checked_hash(path, LEDGER_SHA)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    meta, frames = rows[0], rows[1:]
    source = meta['source']
    if (len(frames) != 683 or meta['schema'] != 'veritx/robotics-dataset-frame-ledger/1'
            or source['repo'] != REPO or source['revision'] != REVISION
            or source['subset'] != SUBSET or source['episode'] != 0
            or meta['inputs'] != HASHES):
        raise ValueError('ledger source/schema/count mismatch')
    last = -1.0
    for index, row in enumerate(frames, 1):
        t, pts = row['timestamp_s'], row['video_pts_s']
        if (row['record_type'] != 'frame' or row['frame_index'] != index
                or row['episode_index'] != 0 or row['task_index'] != 1
                or not math.isfinite(t) or not math.isfinite(pts)
                or t <= last or abs(t - pts) > 0.000002):
            raise ValueError(f'invalid frame/timestamp {index}')
        for key in ('state', 'action'):
            if row[key] != {'dtype': 'float64', 'elements': 43, 'raw_value_bytes': 344}:
                raise ValueError(f'invalid {key} summary {index}')
        if type(row['h264_demux_packet_bytes']) is not int or row['h264_demux_packet_bytes'] <= 0:
            raise ValueError(f'invalid video payload {index}')
        last = t
    return rows


def fetch(output_dir, cache_dir=None):
    """Fetch exactly the two pinned files; total payload is under 4 MB.

    cache_dir is accepted for compatibility; existing HF downloads can be
    passed directly to export instead. Downloads have a 30 s socket timeout.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    for name, (relative, expected, size) in FILES.items():
        url = f'https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{SUBSET}/{relative}'
        request = urllib.request.Request(url, headers={'User-Agent': 'Srota-G1-Audit/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(size + 1)
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'{name}: source size/hash mismatch')
        write_new(out / name, data)
    return out


def export_ledger(parquet, video, output):
    """Reproduce the pinned ledger from real source rows/video PTS, offline."""
    checked_hash(parquet, HASHES['parquet_sha256'])
    checked_hash(video, HASHES['mp4_sha256'])
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError('export requires optional pyarrow; see requirements-source.txt') from exc
    table = pq.read_table(parquet, columns=[
        'timestamp', 'frame_index', 'episode_index', 'task_index', 'observation.state', 'action'])
    rows = table.to_pylist()
    if len(rows) != 683:
        raise ValueError('source must contain 683 rows')
    for index, row in enumerate(rows, 1):
        if row['frame_index'] != index or row['episode_index'] != 0 or row['task_index'] != 1:
            raise ValueError('source frame/episode/task index mismatch')
        for name in ('observation.state', 'action'):
            values = row[name]
            if len(values) != 43 or not all(math.isfinite(v) for v in values):
                raise ValueError(f'invalid source vector {name} at {index}')
        t = row['timestamp']
        if not math.isfinite(t) or abs(t - (index - 1) / 50) > 0.000002:
            raise ValueError('source timestamps differ from audited 50 Hz timeline')
    probe = shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('ffprobe is required to inspect/decode video')
    result = subprocess.run([
        probe, '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_packets', '-show_streams', '-show_entries',
        'packet=pts_time,size:stream=codec_name,width,height,nb_read_frames,avg_frame_rate',
        '-of', 'json', str(Path(video).resolve()),
    ], capture_output=True, text=True, check=True, timeout=60)
    parsed = json.loads(result.stdout)
    stream = parsed['streams'][0]
    if (stream['codec_name'], stream['width'], stream['height'],
            stream['avg_frame_rate'], int(stream['nb_read_frames'])) != ('h264', 640, 480, '50/1', 683):
        raise ValueError('decoded video does not match audited dimensions/count/fps')
    # H.264 decode/demux order differs from presentation order (B-frames).
    packets = sorted(parsed['packets'], key=lambda packet: float(packet['pts_time']))
    if len(packets) != len(rows):
        raise ValueError('video packet/row count mismatch')
    last_pts = -1.0
    frames = []
    for row, packet in zip(rows, packets):
        pts, size = float(packet['pts_time']), int(packet['size'])
        if not math.isfinite(pts) or pts <= last_pts or abs(pts - row['timestamp']) > 0.000002 or size <= 0:
            raise ValueError('video presentation timestamps/payloads do not align')
        frames.append({
            'record_type': 'frame', 'frame_index': row['frame_index'], 'episode_index': 0,
            'task_index': 1, 'timestamp_s': row['timestamp'], 'video_pts_s': pts,
            'h264_demux_packet_bytes': size,
            'state': {'dtype': 'float64', 'elements': 43, 'raw_value_bytes': 344},
            'action': {'dtype': 'float64', 'elements': 43, 'raw_value_bytes': 344},
        })
        last_pts = pts
    meta = {
        'record_type': 'metadata', 'schema': 'veritx/robotics-dataset-frame-ledger/1',
        'source': {'repo': REPO, 'revision': REVISION, 'subset': SUBSET, 'episode': 0,
                   'license': 'CC-BY-4.0', 'task': 'pick up the apple, walk left, and place the apple on the plate'},
        'inputs': dict(HASHES),
        'summary': {'frames': 683, 'duration_s': frames[-1]['timestamp_s'] - frames[0]['timestamp_s'],
                    'fps': 50, 'video': 'H.264 demux packet sizes from MP4, sorted by presentation timestamp',
                    'state_shape': [43], 'action_shape': [43], 'state_action_dtype': 'float64',
                    'state_action_value_bytes_each': 344, 'frame_index_origin': 1},
        'evidence_boundary': BOUNDARY,
    }
    data = ''.join(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n'
                   for row in [meta, *frames]).encode()
    if hashlib.sha256(data).hexdigest() != LEDGER_SHA:
        raise ValueError('source export does not reproduce audited ledger hash')
    write_new(output, data)
    return {'frames': len(frames), 'ledger_sha256': LEDGER_SHA}


def dse_imports():
    if str(DSE) not in sys.path:
        sys.path.insert(0, str(DSE))
    from veritx_dse.workload.traffic_profile import scan_trace
    from veritx_dse.simulation.booksim import build_config, run_booksim, find_booksim_bin
    from veritx_dse.model.presets import Topology
    from veritx_dse.core.logging import Ctx
    return scan_trace, build_config, run_booksim, find_booksim_bin, Topology, Ctx


def project(ledger, trace, manifest, *, frames=1, flit_bytes=32, max_packet_flits=16,
            clock_hz=1000000000, max_cycles=1000000):
    if any(type(n) is not int or n <= 0 for n in
           (frames, flit_bytes, max_packet_flits, clock_hz, max_cycles)):
        raise ValueError('frame/packet/clock/cycle parameters must be positive integers')
    if frames > 683:
        raise ValueError('only the pinned 683-frame episode is available')
    destinations = [Path(trace), Path(manifest)]
    if (destinations[0].resolve() == destinations[1].resolve()
            or any(path.exists() or path.is_symlink() for path in destinations)):
        raise ValueError('trace/manifest must be distinct new files')
    rows = read_ledger(ledger)
    mapping = {'camera_h264': [0, 1], 'state': [2, 1], 'action_demonstration': [1, 3]}
    packets, transfers, ready = [], [], {}
    selected = rows[1:frames + 1]
    origin = selected[0]['timestamp_s']
    for frame in selected:
        release = round((frame['timestamp_s'] - origin) * clock_hz)
        for kind, payload in [('camera_h264', frame['h264_demux_packet_bytes']),
                              ('state', frame['state']['raw_value_bytes']),
                              ('action_demonstration', frame['action']['raw_value_bytes'])]:
            src, dst = mapping[kind]
            flits = (payload + flit_bytes - 1) // flit_bytes
            remaining, cycle, count = flits, max(release, ready.get(src, 0)), 0
            while remaining:
                size = min(max_packet_flits, remaining)
                packets.append((cycle, src, 0, dst, size))
                remaining -= size
                cycle += size  # authored source serialization: one flit/cycle
                count += 1
            ready[src] = cycle
            transfers.append({'frame_index': frame['frame_index'], 'source_timestamp_s': frame['timestamp_s'],
                              'kind': kind, 'src': src, 'dst': dst, 'payload_bytes': payload,
                              'flits': flits, 'packets': count, 'release_cycle': release})
    packets.sort()
    if max(ready.values()) > max_cycles:
        raise ValueError('native-rate replay exceeds --max-cycles; select fewer frames or explicitly raise the bound')
    data = ''.join('%d %d %d %d %d\n' % row for row in packets).encode()
    scan_trace, *_ = dse_imports()
    scan_trace(data, endpoint_count=4, max_packet_flits=max_packet_flits)
    result = {
        'qualification': 'DIAGNOSTIC_SENSOR_TRAJECTORY_PROJECTION',
        'label': 'dataset-derived sensor/trajectory projection; NOT model execution traffic',
        'ledger_sha256': sha(ledger), 'source_revision': REVISION, 'frames': frames,
        'mapping': mapping, 'mapping_authority': 'authored hypothetical sensor/policy/controller endpoints',
        'clock_hz': clock_hz, 'flit_bytes': flit_bytes, 'max_packet_flits': max_packet_flits,
        'max_cycles': max_cycles, 'source_origin_s': origin,
        'time_mapping': 'native source timestamp differences rounded to cycles; selected first observation rebased to cycle 0',
        'serialization': 'one source flit/cycle, packet requests separated by packet flit count; padded tails',
        'limitations': ['No wire/transport headers modeled.', 'H264 demux sizes are not decoded tensor sizes.',
                        'Action demonstrations are independent recorded payloads, not simulated policy outputs.',
                        'No neural weights/activations, compute timing or GR00T task success claimed.'],
        'packets': len(packets), 'flits': sum(row[4] for row in packets),
        'payload_bytes': sum(row['payload_bytes'] for row in transfers),
        'padded_bytes': sum(row[4] for row in packets) * flit_bytes,
        'last_request_cycle': packets[-1][0], 'transfers': transfers,
        'trace_sha256': hashlib.sha256(data).hexdigest(),
    }
    write_new(trace, data)
    write_new(manifest, json_bytes(result))
    return result


def check_packet_log(packet_log, trace):
    """Reconcile every retired packet against input, including source issue time."""
    expected = Counter((int(p[0]), int(p[1]), int(p[3]), int(p[4]))
                       for p in (line.split() for line in Path(trace).read_text().splitlines()))
    with Path(packet_log).open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    observed, ids, latencies = Counter(), set(), []
    for row in rows:
        packet_id = int(row['packet_id'])
        request, injection, arrival = (int(row[k]) for k in
                                       ('request_time', 'injection_time', 'arrival_time'))
        if packet_id in ids or packet_id < 0 or not 0 <= request <= injection <= arrival:
            raise ValueError('invalid/duplicate observed packet or timestamp')
        ids.add(packet_id)
        observed[(request, int(row['src']), int(row['dst']), int(row['packet_size_flits']))] += 1
        latencies.append(arrival - request)
    if not rows or observed != expected:
        raise ValueError('retired packet log does not conserve exact trace packets')
    latencies.sort()
    return {'packets': len(rows), 'flits': sum(int(r['packet_size_flits']) for r in rows),
            'request_latency_avg': sum(latencies) / len(latencies),
            'request_latency_p50': latencies[math.ceil(len(latencies) * .50) - 1],
            'request_latency_p95': latencies[math.ceil(len(latencies) * .95) - 1],
            'request_latency_p99': latencies[math.ceil(len(latencies) * .99) - 1],
            'percentile_method': 'nearest rank over all retired input packets',
            'last_arrival_cycle': max(int(r['arrival_time']) for r in rows)}


def run_booksim_smoke(ledger, run_dir, *, timeout=60):
    out = Path(run_dir).resolve()
    if any(ch.isspace() for ch in str(out)):
        raise ValueError('BookSim run paths must not contain whitespace')
    out.mkdir(parents=True, exist_ok=False)
    trace = out / 'workload.trace'
    manifest = project(ledger, trace, out / 'projection.json')
    _, build_config, run_booksim, find_bin, Topology, Ctx = dse_imports()
    binary = find_bin(ROOT).resolve()
    # Native sim_type=trace selects TraceTrafficManager, which replaces the
    # base traffic pattern and loads trace_file (tracetrafficmanager.cpp:8-28).
    # Do NOT switch to sim_type=latency: that selects a different manager.
    config = build_config(Topology(name='G1-smoke-mesh2x2', backend='mesh', routing='dim_order',
                                   params={'k': 2, 'n': 2}), str(trace), sim_type='trace', seed=0,
                          overrides={'trace_file': str(trace), 'sample_period': 10000,
                                     'sim_count': 1, 'trace_packet_log': str(out / 'packets.csv')})
    write_new(out / 'booksim.cfg', config)
    def capture(command, cwd, timeout):
        completed = subprocess.run(command, cwd=cwd, timeout=timeout, stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True)
        write_new(out / 'stdout.log', completed.stdout)
        write_new(out / 'stderr.log', completed.stderr)
        if completed.returncode:
            raise RuntimeError(f'BookSim exited {completed.returncode}; see {out}')
        return completed
    metrics = run_booksim(Ctx(verbosity=0), config, repo_root=ROOT, timeout=timeout, runner=capture)
    observed = check_packet_log(out / 'packets.csv', trace)
    if (metrics.get('unstable') or observed['packets'] != manifest['packets']
            or observed['flits'] != manifest['flits']):
        raise ValueError('BookSim packet/flit delivery failed conservation; see raw logs')
    # Older vendored binaries omit aggregate counters. The complete per-packet
    # retirement log remains the authority, not a guessed replacement counter.
    for key, expected in [('delivered', manifest['packets']),
                          ('flits_injected', manifest['flits']), ('flits_accepted', manifest['flits'])]:
        if key in metrics and metrics[key] != expected:
            raise ValueError(f'BookSim {key} disagrees with retired packet log')
    result = {'qualification': manifest['qualification'], 'exact_fabric_eligible': False,
              'exit_status': 0, 'observed_packet_metrics_cycles': observed,
              'legacy_stdout_metrics_cycles': metrics, 'clock_hz': manifest['clock_hz'],
              'binary': str(binary), 'binary_sha256': sha(binary),
              'config_sha256': sha(out / 'booksim.cfg'), 'trace_sha256': sha(trace),
              'projection_sha256': sha(out / 'projection.json'), 'packet_log_sha256': sha(out / 'packets.csv'),
              'limitations': manifest['limitations'] + [
                  'Diagnostic legacy mesh config; not a certified Thor fabric.',
                  'Use packet-log request latencies; stock stdout mean can use a different timing population.']}
    write_new(out / 'result.json', json_bytes(result))
    return result


def timeloop_binary(binary=None):
    candidate = binary or os.environ.get('TIMELOOP_MAPPER') or shutil.which('timeloop-mapper')
    if not candidate:
        candidate = ROOT / 'third_party/timeloop/bin/timeloop-mapper'
    path = Path(candidate).resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError('Timeloop unavailable: provide --binary or TIMELOOP_MAPPER; see README build instructions')
    return path


def require_timeloop_precision(stats_text, expected_bits):
    """Check resolved arithmetic/storage widths, not merely input YAML."""
    # Timeloop repeats generic 'Word bits' in its later Network sections.
    # Validate the arithmetic/storage hierarchy rather than counting networks
    # as additional storage levels.
    levels = re.split(r'^Networks\s*$', stats_text, maxsplit=1, flags=re.MULTILINE)[0]
    widths = [int(value) for value in re.findall(
        r'^\s*(?:Data )?Word bits\s*:\s*(\d+)\s*$', levels, re.MULTILINE | re.IGNORECASE)]
    if type(expected_bits) is not int or expected_bits <= 0 or len(widths) != 4 or any(
            width != expected_bits for width in widths):
        raise ValueError(f'Timeloop resolved word widths {widths} do not match {expected_bits} bits at all four levels')
    return widths


def timeloop_smoke(run_dir, binary=None, timeout=60):
    binary = timeloop_binary(binary)
    out = Path(run_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    vendor = ROOT / 'third_party/timeloop'
    config = ((vendor / 'arch.yaml').read_text() + '\n'
              + (vendor / 'problem_library/gemm.yaml').read_text() + '\n'
              + 'mapper:\n  algorithm: exhaustive\n  optimization-metrics: [delay]\n'
                '  num-threads: 1\n  search-size: 16\n  victory-condition: 4\n  timeout: 16\n')
    write_new(out / 'smoke.yaml', config)
    env = dict(os.environ)
    # Dynamic library from the same explicit source build as the binary.
    lib = binary.parent.parent / 'lib'
    env['LD_LIBRARY_PATH'] = str(lib) + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    completed = subprocess.run([str(binary), str(out / 'smoke.yaml')], cwd=out, env=env,
                               timeout=timeout, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    write_new(out / 'stdout.log', completed.stdout)
    write_new(out / 'stderr.log', completed.stderr)
    stats = out / 'timeloop-mapper.stats.txt'
    if completed.returncode or not stats.is_file() or not stats.read_text().strip():
        raise RuntimeError(f'Timeloop smoke failed (exit {completed.returncode}); see {out}')
    text = stats.read_text()
    cycles = re.search(r'^Cycles: (\d+)$', text, re.MULTILINE)
    computes = re.search(r'^Actual Computes = (\d+)$', text, re.MULTILINE)
    if not cycles or int(cycles[1]) <= 0 or not computes or int(computes[1]) != 4096:
        raise ValueError('Timeloop did not report valid cycles and the expected 16^3 computes')
    result = {'qualification': 'TIMELOOP_INFRASTRUCTURE_GEMM_SMOKE', 'exit_status': 0,
              'modeled_cycles': int(cycles[1]), 'actual_computes': int(computes[1]),
              'problem': {'M': 16, 'N': 16, 'K': 16}, 'binary': str(binary), 'binary_sha256': sha(binary),
              'config_sha256': sha(out / 'smoke.yaml'), 'stats_sha256': sha(stats),
              'limitations': ['Not a GR00T operator trace or Thor architecture.',
                              'PAT energy/area is uncalibrated; no calibrated power claim.',
                              'No aggregation with BookSim timing.']}
    write_new(out / 'result.json', json_bytes(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('--ledger', type=Path, default=DEFAULT_LEDGER)
    download = sub.add_parser('fetch')
    download.add_argument('--output-dir', type=Path, required=True)
    download.add_argument('--cache-dir', help='compatibility argument; fetch is a bounded direct download')
    export = sub.add_parser('export')
    export.add_argument('--parquet', type=Path, required=True)
    export.add_argument('--video', type=Path, required=True)
    export.add_argument('--output', type=Path, required=True)
    projection = sub.add_parser('project')
    projection.add_argument('--ledger', type=Path, default=DEFAULT_LEDGER)
    projection.add_argument('--trace', type=Path, required=True)
    projection.add_argument('--manifest', type=Path, required=True)
    for name, default in [('frames', 1), ('flit-bytes', 32), ('max-packet-flits', 16),
                          ('clock-hz', 1000000000), ('max-cycles', 1000000)]:
        projection.add_argument('--' + name, type=int, default=default)
    run = sub.add_parser('run-booksim')
    run.add_argument('--ledger', type=Path, default=DEFAULT_LEDGER)
    run.add_argument('--run-dir', type=Path, required=True)
    run.add_argument('--timeout', type=int, default=60)
    for name in ('timeloop-doctor', 'timeloop-smoke'):
        command = sub.add_parser(name)
        command.add_argument('--binary', type=Path)
        if name.endswith('smoke'):
            command.add_argument('--run-dir', type=Path, required=True)
            command.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'verify':
            result = {'frames': len(read_ledger(args.ledger)) - 1, 'sha256': sha(args.ledger)}
        elif args.cmd == 'fetch':
            result = {'downloaded': str(fetch(args.output_dir, args.cache_dir)), 'revision': REVISION}
        elif args.cmd == 'export':
            result = export_ledger(args.parquet, args.video, args.output)
        elif args.cmd == 'project':
            result = project(args.ledger, args.trace, args.manifest, frames=args.frames,
                             flit_bytes=args.flit_bytes, max_packet_flits=args.max_packet_flits,
                             clock_hz=args.clock_hz, max_cycles=args.max_cycles)
        elif args.cmd == 'run-booksim':
            if args.timeout <= 0:
                raise ValueError('timeout must be positive')
            result = run_booksim_smoke(args.ledger, args.run_dir, timeout=args.timeout)
        elif args.cmd == 'timeloop-smoke':
            if args.timeout <= 0:
                raise ValueError('timeout must be positive')
            result = timeloop_smoke(args.run_dir, args.binary, args.timeout)
        else:
            result = {'binary': str(timeloop_binary(args.binary)),
                      'note': 'Executable found only; use timeloop-smoke to prove execution.'}
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'gr00t_pipeline: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
