import { expect, it } from 'vitest';
import { decodeObservedHops, observedPositions, observedWireFlights, type ObservedHopEvent } from './observedHops';
import { bucketWindows } from './windowBuckets';
import { buildChannelIndex, matchMeasuredChannel } from './channelTopology';
import type { Topology } from './gateway';
const topology: Topology = { family: 'srota', counts: {}, planes: ['c', 'd'], routers: [{ router_id: 0, coordinates: [0, 0], seat_capacity: 2 }, { router_id: 1, coordinates: [1, 0], seat_capacity: 2 }], channels: [], endpoints: [] };
it('keeps observed planes separate and never invents in-flight positions', () => {
  const events = decodeObservedHops('2 | network_1/srota_router_0_0 | Received flit 0 from channel at input 0.\n5 | network_1/srota_router_0_0 | Sending flit 0 to channel at output 2.\n7 | network_1/srota_router_0_1 | Received flit 0 from channel at input 2.\n8 | network_0/unknown | Received flit 1 from channel at input 0.', topology);
  expect(events).toHaveLength(3);
  expect(observedPositions(events, 3, 1)[0].router).toBe(0);
  expect(observedPositions(events, 6, 1)).toHaveLength(0);
  expect(observedPositions(events, 7, 0)).toHaveLength(0);
  expect(observedPositions(events, 7, 1)[0].router).toBe(1);
});
it('counts only sends without a subsequent receipt by the playback cycle', () => {
  const event = (cycle: number, flit: number, kind: 'send' | 'receive', subnet = 1): ObservedHopEvent => ({ cycle, flit, kind, subnet, router: 0, port: 2 });
  const events = [event(1, 0, 'receive'), event(2, 0, 'send'), event(3, 1, 'send'), event(4, 1, 'receive'), event(5, 2, 'send', 0), event(6, 0, 'receive'), event(7, 0, 'send')];
  const wires = new Map([['0:2', { wire: 7, taps: [1] }]]);
  expect([...observedWireFlights(events, 4, 1, wires)]).toEqual([[7, 1]]);
  expect([...observedWireFlights(events, 6, 1, wires)]).toEqual([]);
  expect([...observedWireFlights(events, 7, 1, wires)]).toEqual([[7, 1]]);
  expect([...observedWireFlights(events, 7, 0, wires)]).toEqual([[7, 1]]);
  expect([...observedWireFlights(events, 7, 1)]).toEqual([]);
});
it('matches the original flight classification across cycles, planes and repeated hops', () => {
  const wires = new Map([['0:2', { wire: 7, taps: [1] }], ['1:2', { wire: 8, taps: [0] }]]);
  const events: ObservedHopEvent[] = Array.from({ length: 100 }, (_, i) => ({
    cycle: i % 31, flit: i % 13, subnet: i % 2, router: i % 3, port: 2,
    kind: i % 3 ? 'send' : 'receive',
  }));
  for (let cycle = 0; cycle <= 32; cycle += 1) for (const subnet of [0, 1]) {
    const expected = new Map<number, number>();
    for (const event of events) {
      if (event.subnet !== subnet || event.kind !== 'send' || event.cycle > cycle) continue;
      const wire = wires.get(`${event.router}:${event.port}`);
      if (!wire) continue;
      const landed = events.some(other => other.flit === event.flit && other.kind === 'receive' && other.cycle >= event.cycle && other.cycle <= cycle);
      if (!landed) expected.set(wire.wire, (expected.get(wire.wire) ?? 0) + 1);
    }
    expect(observedWireFlights(events, cycle, subnet, wires)).toEqual(expected);
  }
});
it('keeps playback event work linear as captures grow', () => {
  let reads = 0;
  const events: ObservedHopEvent[] = Array.from({ length: 2000 }, (_, flit) => ({
    cycle: flit, subnet: 1, router: 0, port: 2, kind: 'send',
    get flit() { reads += 1; return flit; },
  }));
  expect(observedWireFlights(events, 2000, 1, new Map([['0:2', { wire: 7, taps: [1] }]])).get(7)).toBe(2000);
  expect(reads).toBeLessThanOrEqual(events.length * 4);
});
it('bounds display windows without losing flits or peak values', () => {
  const values = Array.from({ length: 995 }, (_, i) => i % 9);
  const grouped = bucketWindows(values);
  expect(grouped.values.length).toBeLessThanOrEqual(80);
  expect(grouped.values.reduce((a, b) => a + b, 0)).toBe(values.reduce((a, b) => a + b, 0));
  expect(Math.max(...bucketWindows(values, 80, 'max').values)).toBe(8);
});
it('SROTA local ports come first, and a wire port is only joined when the dump proves it', () => {
  const index = buildChannelIndex(topology);
  // subnet 0 = Plane D, subnet 1 = Plane C; ids pack subnet * 1e8 + router * 1e4 + port.
  expect(matchMeasuredChannel(index, 1)?.local).toBe(true);
  expect(matchMeasuredChannel(index, 100_000_001)?.local).toBe(true);
  // Without an executed routing dump the port is named, never guessed into a direction.
  const unproven = matchMeasuredChannel(index, 2);
  expect(unproven?.direction).toBe(null);
  expect(unproven?.unmatched).toBe(true);
  expect(unproven?.resourceLabel).toContain('no verified port-to-wire join');
  expect(unproven?.channel).toBe(null);
  // With the verified join the same counter resolves to the wire it drove.
  const joined = buildChannelIndex(topology, new Map([['0:2', { wire: 7, taps: [1] }]]));
  const wire = matchMeasuredChannel(joined, 2);
  expect(wire?.wire).toEqual({ id: 7, taps: [1] });
  expect(wire?.unmatched).toBe(false);
  expect(wire?.resourceLabel).toContain('wire 7 driver R0');
  // Plane C port order is a control-plane property no bundle here certifies.
  expect(matchMeasuredChannel(index, 100_000_002)?.resourceLabel).toContain('control-plane port order is not certified');
});
