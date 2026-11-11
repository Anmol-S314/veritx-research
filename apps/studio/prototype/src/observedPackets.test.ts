import { describe, expect, it } from 'vitest';
import type { Topology } from './gateway';
import { decodeObservedPackets, packetGroupTotals } from './observedPackets';
import { sampledBudget } from './cycleBudget';

const topology: Topology = {
  family: 'mesh', counts: { routers: 2 },
  routers: [{ router_id: 0, coordinates: [0, 0] }, { router_id: 1, coordinates: [1, 0] }],
  channels: [], endpoints: [],
};

const packet7 = [
  '5 | node0 | Enqueuing packet 7 at time 3.',
  '5 | node0 | Enqueuing flit 10 (packet 7) at time 3.',
  '5 | node0 | Enqueuing flit 11 (packet 7) at time 3.',
  '8 | node0 | Injecting flit 10 into subnet 0 at time 8 with priority 0.',
  '10 | network_0/router_0_0 | Received flit 10 from channel at input 4.',
  '11 | network_0/router_0_0 | Beginning routing for VC 0 at input 4 (front: 10).',
  '11 | network_0/router_0_0 | Completed routing for VC 0 at input 4 (front: 10).',
  '12 | network_0/router_0_0 | Beginning VC allocation for VC 0 at input 4 (front: 10).',
  '13 | network_0/router_0_0 | Completed VC allocation for VC 0 at input 4 (front: 10).',
  '14 | network_0/router_0_0 | Beginning switch allocation for VC 0 at input 4 (front: 10).',
  '15 | network_0/router_0_0 | Completed switch allocation for VC 0 at input 4 (front: 10).',
  '16 | network_0/router_0_0 | Beginning crossbar traversal for flit 10 from input 4.0 to output 0.0.',
  '16 | network_0/router_0_0 | Completed crossbar traversal for flit 10 from input 4.0 to output 0.0.',
  '16 | network_0/router_0_0 | Sending flit 10 to channel at output 0.',
  '18 | network_0/router_0_1 | Received flit 10 from channel at input 1.',
  '18 | network_0/router_0_1 | Beginning routing for VC 0 at input 1 (front: 10).',
  '18 | network_0/router_0_1 | Completed routing for VC 0 at input 1 (front: 10).',
  '19 | network_0/router_0_1 | Beginning VC allocation for VC 0 at input 1 (front: 10).',
  '19 | network_0/router_0_1 | Completed VC allocation for VC 0 at input 1 (front: 10).',
  '20 | network_0/router_0_1 | Beginning switch allocation for VC 0 at input 1 (front: 10).',
  '20 | network_0/router_0_1 | Completed switch allocation for VC 0 at input 1 (front: 10).',
  '21 | network_0/router_0_1 | Beginning crossbar traversal for flit 10 from input 1.0 to output 4.0.',
  '21 | network_0/router_0_1 | Completed crossbar traversal for flit 10 from input 1.0 to output 4.0.',
  '21 | network_0/router_0_1 | Sending flit 10 to channel at output 4.',
  '23 | node1 | Ejecting flit 10 (packet 7) from VC 0.',
  '24 | node1 | Retiring flit 10 (packet 7, src = 0, dest = 1, hops = 2, flat = 16).',
  '30 | node1 | Retiring packet 7 (plat = 27, nlat = 22, frag = 0, src = 0, dest = 1).',
].join('\n');

describe('watched packet paths', () => {
  it('splits the head flit pipeline and closes the row at the tail retire', () => {
    const capture = decodeObservedPackets(packet7, topology);
    expect(capture.packets).toHaveLength(1);
    const path = capture.packets[0];
    expect(path).toMatchObject({
      packet: 7, subnet: 0, source: 0, destination: 1, headFlit: 10, flits: 2,
      requestTime: 3, enqueueCycle: 5, injectionCycle: 8, retireCycle: 30, total: 27,
      hops: 2, complete: true,
    });
    expect(path.phases.map(phase => phase.kind)).toEqual([
      'source', 'ingress', 'buffer', 'vc', 'switch', 'crossbar', 'link',
      'vc', 'switch', 'crossbar', 'eject', 'tail',
    ]);
    expect(packetGroupTotals(path)).toEqual({
      source: 5, queue: 1, arbitration: 6, transmission: 8, drain: 7, total: 27,
    });
    expect(sampledBudget([path])).toMatchObject({
      count: 1, completeCount: 1, incompleteCount: 0, total: 27, median: 27, p95: 27,
    });
  });

  it('keeps an incomplete path out of the sampled totals instead of guessing a phase', () => {
    const truncated = packet7.split('\n').filter(line => !line.includes('Retiring packet')).join('\n');
    const capture = decodeObservedPackets(truncated, topology);
    expect(capture.packets).toHaveLength(1);
    expect(capture.packets[0].complete).toBe(false);
    const budget = sampledBudget(capture.packets);
    expect(budget).toMatchObject({ count: 1, completeCount: 0, incompleteCount: 1, total: 0, longest: null });
  });
});
