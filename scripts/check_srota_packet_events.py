#!/usr/bin/env python3
"""Independently check packet-driver events against the complete input payloads."""
import argparse
import json
from pathlib import Path


def check_events(stimulus, events):
    tokens = iter(stimulus.split())
    packets = {}
    for token in tokens:
        ident, src, dst, release, count = map(int, [token, next(tokens), next(tokens), next(tokens), next(tokens)])
        if ident in packets or not (0 <= src < 64 and 0 <= dst < 64) or release < 0 or count < 1:
            raise ValueError('invalid or duplicate packet header')
        payloads = [tuple(int(next(tokens)) for _ in range(4)) for _ in range(count)]
        if any(not 0 <= word < 2**32 for payload in payloads for word in payload):
            raise ValueError('invalid payload word')
        packets[ident] = (src, dst, release, payloads)
    if not packets:
        raise ValueError('empty stimulus')
    sent, received, tags = {}, {}, {}
    last_cycle = -1
    for line in events.splitlines():
        fields = line.split()
        if len(fields) != 13 or fields[0] not in ('A', 'D'):
            raise ValueError('invalid event record')
        edge = fields[0]
        cycle, ident, src, dst, pos, tag, head, tail, *words = map(int, fields[1:])
        if ident not in packets:
            raise ValueError('unexpected packet')
        expected_src, expected_dst, release, payloads = packets[ident]
        if cycle < last_cycle or cycle < release:
            raise ValueError('event precedes release or prior event')
        last_cycle = cycle
        if (src, dst) != (expected_src, expected_dst) or not 0 <= pos < len(payloads):
            raise ValueError('source, destination or flit position mismatch')
        if tuple(words) != payloads[pos] or (head, tail) != (int(pos == 0), int(pos == len(payloads) - 1)):
            raise ValueError('payload or framing mismatch')
        counts = sent if edge == 'A' else received
        if pos != counts.get(ident, 0):
            raise ValueError('duplicate or out-of-order flit')
        if edge == 'D':
            if pos >= sent.get(ident, 0):
                raise ValueError('delivery without acceptance')
            if tag not in (0, 1) or tag != tags.setdefault(ident, tag):
                raise ValueError('illegal or unstable route tag')
        elif tag != 0:
            raise ValueError('unexpected injected route tag')
        counts[ident] = pos + 1
    if any(sent.get(ident) != len(packet[3]) or received.get(ident) != len(packet[3])
           for ident, packet in packets.items()):
        raise ValueError('incomplete packet acceptance or delivery')
    return {'packets': len(packets), 'accepted_flits': sum(sent.values()),
            'delivered_flits': sum(received.values()),
            'ordered_pairs': len({(p[0], p[1]) for p in packets.values()})}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stimulus', type=Path)
    p.add_argument('events', type=Path)
    a = p.parse_args()
    print(json.dumps(check_events(a.stimulus.read_text(), a.events.read_text()), sort_keys=True))


if __name__ == '__main__':
    main()
