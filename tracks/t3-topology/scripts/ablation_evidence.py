"""Trace identity and explicit workload variants shared by ablation entry points.

No operation expands traffic to previously idle endpoints or infers compute.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import math
from pathlib import Path
import shutil


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def trace_records(path: Path):
    """Yield original fields plus their dialect's endpoint indices, strictly."""
    with path.open(newline='') as source:
        for number, line in enumerate(source, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            comma = ',' in line
            fields = next(csv.reader([line])) if comma else line.split()
            if comma and fields[0].strip() == 'timestamp':
                continue
            src_index, dst_index = 1, 2 if comma else 3
            try:
                timestamp, src, dst, size = (int(fields[i]) for i in (0, src_index, dst_index, 4))
                if min(timestamp, src, dst) < 0 or size < 1:
                    raise ValueError('negative timestamp/endpoint or nonpositive packet size')
            except (IndexError, ValueError) as error:
                raise ValueError(f'{path.name}:{number}: invalid trace event') from error
            yield fields, comma, src_index, dst_index, timestamp, src, dst, size


def trace_stats(path: Path) -> dict:
    if not path.is_file():
        return {'events': 0, 'active_nodes': 0, 'trace_sha256': None}
    nodes, sizes = set(), set()
    events = self_events = classes = 0
    first = last = None
    for fields, comma, _, _, timestamp, src, dst, size in trace_records(path):
        nodes.update((src, dst)); sizes.add(size)
        events += 1
        self_events += src == dst
        first = timestamp if first is None else min(first, timestamp)
        last = timestamp if last is None else max(last, timestamp)
        if not comma:
            traffic_class = int(fields[2])
            if traffic_class < 0:
                raise ValueError('negative traffic class')
            classes = max(classes, traffic_class)
    return {
        'events': events, 'active_nodes': len(nodes), 'active_endpoint_ids': sorted(nodes),
        'max_node': max(nodes) if nodes else None, 'self_events': self_events,
        'expected_network_packets': events - self_events,
        'packet_size_flits': sorted(sizes), 'classes': classes + 1,
        'first_request_cycle': first, 'last_request_cycle': last,
        'trace_sha256': sha256(path),
    }


def transform_trace(source: Path, destination: Path, nodes: int, *, packet_flits: int | None = None,
                    time_scale: str = '1', burst_window: int = 0,
                    rank_stride: int = 1, rank_offset: int = 0) -> dict:
    """Explicit variant: payload, temporal density/bursts, bijective placement.

    Rank placement preserves the number of active ranks, not fabric geometry.
    Payload changes are workload changes, never matched-trace router ablations.
    """
    scale = Fraction(str(time_scale))
    if nodes < 1 or not Fraction(1, 100) <= scale <= 100:
        raise ValueError('time scale must be between 0.01 and 100')
    if packet_flits is not None and not 1 <= packet_flits <= 1024:
        raise ValueError('trace packet size must be between 1 and 1024 flits')
    if burst_window < 0 or math.gcd(rank_stride, nodes) != 1:
        raise ValueError('burst window must be nonnegative; rank stride must be coprime to endpoints')
    destination.parent.mkdir(parents=True, exist_ok=True)
    identity = packet_flits is None and scale == 1 and burst_window == 0 and rank_stride == 1 and rank_offset % nodes == 0
    if identity:
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    else:
        if source.resolve() == destination.resolve():
            raise ValueError('a workload variant must not overwrite its source trace')
        with destination.open('w', newline='') as output:
            writer = csv.writer(output, lineterminator='\n')
            wrote_header = False
            for fields, comma, si, di, timestamp, src, dst, _ in trace_records(source):
                if max(src, dst) >= nodes:
                    raise ValueError('trace endpoint exceeds the declared fabric')
                stamp = int(timestamp * scale)
                fields[0] = str((stamp // burst_window) * burst_window if burst_window else stamp)
                fields[si] = str((src * rank_stride + rank_offset) % nodes)
                fields[di] = str((dst * rank_stride + rank_offset) % nodes)
                if packet_flits is not None:
                    fields[4] = str(packet_flits)
                if comma:
                    if not wrote_header:
                        with source.open() as original:
                            writer.writerow(next(csv.reader(original)))
                        wrote_header = True
                    writer.writerow(fields)
                else:
                    output.write(' '.join(fields) + '\n')
    stats = trace_stats(destination)
    if stats.get('max_node') is not None and stats['max_node'] >= nodes:
        raise ValueError('trace endpoint exceeds the declared fabric')
    return stats


def resource_cost(text: str) -> dict:
    import re
    match = re.search(r'Network cost: subnet=0 routers=(\d+) input_ports=(\d+) output_ports=(\d+) crosspoints=(\d+) storage_flits=(-?\d+)', text)
    if not match:
        return {'routers': None, 'input_ports': None, 'output_ports': None,
                'crosspoints': None, 'storage_flits': None}
    values = dict(zip(('routers', 'input_ports', 'output_ports', 'crosspoints', 'storage_flits'), map(int, match.groups())))
    if values['storage_flits'] < 0:
        values['storage_flits'] = None
    return values
