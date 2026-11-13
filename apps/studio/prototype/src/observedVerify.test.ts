import { expect, it } from 'vitest';
import type { Topology } from './gateway';
import type { ObservedFlitFate, ObservedHopEvent } from './observedHops';
import { verifyObserved } from './observedVerify';
import type { Decision, SharedRouteTable } from './sharedRoutes';

const config = 'topology=srota; k=2; c=1; classes=2; class_subnet={0,1}; srota_planes=3;';
const topology = {
  family: 'srota', counts: {},
  routers: [0, 1, 2, 3].map(router_id => ({ router_id, coordinates: [router_id % 2, Math.floor(router_id / 2)], seat_capacity: 1 })),
  endpoints: [], channels: [],
  shared_links: [
    { shared_link_id: 70, src_router: 0, taps: [1], latency_cycles: 1, width_bits: 64 },
    { shared_link_id: 71, src_router: 1, taps: [3], latency_cycles: 1, width_bits: 64 },
    { shared_link_id: 72, src_router: 0, taps: [2], latency_cycles: 1, width_bits: 64 },
    { shared_link_id: 73, src_router: 2, taps: [3], latency_cycles: 1, width_bits: 64 },
    { shared_link_id: 74, src_router: 1, taps: [2], latency_cycles: 1, width_bits: 64 },
  ],
} as Topology;
const decision = (next_router: number, vc_partition: number, tap = 0): Decision => ({ resource: { kind: 'SHARED_LINK', resource_id: 999 }, next_router, vc_partition, tap });
const table: SharedRouteTable = {
  artifact_id: 'frozen', routing_class: 'SROTA_O1TURN_SHAPE_POLICY',
  terminal_to_router: [[0, 0], [1, 1], [2, 2], [3, 3]],
  shape_of_partition: { '0': 'row', '1': 'column' },
  choices: [[0, 3, [decision(1, 0), decision(2, 1)]], [1, 3, [decision(3, 0)]], [2, 3, [decision(3, 1)]]],
};
// The verified map only exists where the executed dump proved it, per family.
const portWires = new Map([['0:2', { wire: 70, taps: [1] }], ['1:2', { wire: 71, taps: [3] }], ['0:3', { wire: 72, taps: [2] }], ['2:2', { wire: 73, taps: [3] }]]);
const event = (cycle: number, router: number, flit: number, port: number, kind: 'receive' | 'send', subnet = 0): ObservedHopEvent => ({ cycle, subnet, router, flit, port, kind });

it('accepts either certified shape and names the one that ran', () => {
  const row = [event(1, 0, 7, 1, 'receive'), event(2, 0, 7, 2, 'send'), event(3, 1, 7, 1, 'receive'), event(4, 1, 7, 2, 'send'), event(5, 3, 7, 1, 'receive')];
  const column = [event(1, 0, 8, 1, 'receive'), event(2, 0, 8, 3, 'send'), event(3, 2, 8, 1, 'receive'), event(4, 2, 8, 2, 'send'), event(5, 3, 8, 1, 'receive')];
  const check = verifyObserved([...row, ...column], topology, table, config, portWires);
  expect(check.mismatched).toBe(0);
  expect(check.verified).toBe(2);
  expect(check.flits.find(flit => flit.flit === 7)?.shape).toBe('row');
  expect(check.flits.find(flit => flit.flit === 8)?.shape).toBe('column');
  expect(check.shapes).toEqual([{ shape: 'row', flits: 1 }, { shape: 'column', flits: 1 }]);
});

it('reports a hop that is not in the certified route set, and an unbound port', () => {
  // 0 → 1 is certified, but (1, 3) has no decision landing at R2, so the next
  // recorded hop is legally wired and still outside the certified route set.
  const wrong = [event(1, 0, 9, 1, 'receive'), event(2, 0, 9, 2, 'send'), event(3, 1, 9, 1, 'receive'), event(4, 1, 9, 2, 'send'), event(5, 2, 9, 1, 'receive')];
  const mismatch = verifyObserved(wrong, topology, table, config, new Map([['0:2', { wire: 70, taps: [1] }], ['1:2', { wire: 74, taps: [2] }]]));
  expect(mismatch.mismatched).toBe(1);
  expect(mismatch.firstMismatch).toContain('flit 9');
  const unbound = verifyObserved([event(1, 0, 10, 1, 'receive'), event(2, 0, 10, 9, 'send'), event(3, 1, 10, 1, 'receive')], topology, table, config, portWires);
  expect(unbound.unverified).toBe(1);
  expect(unbound.flits[0].reason).toContain('no verified wire binding');
});

it('collapses repeated receipts at one router into one visit', () => {
  // A flit waiting in a queue is received again every cycle, so three receipts at R0 are one visit.
  const flits = [event(1, 0, 21, 1, 'receive'), event(1, 0, 21, 1, 'receive'), event(1, 0, 21, 1, 'receive'), event(2, 0, 21, 2, 'send'), event(2, 0, 21, 2, 'send'), event(3, 1, 21, 1, 'receive'), event(3, 1, 21, 1, 'receive'), event(4, 1, 21, 2, 'send'), event(5, 3, 21, 1, 'receive')];
  const check = verifyObserved(flits, topology, table, config, portWires);
  expect(check.verified).toBe(1);
  expect(check.flits[0].receipts).toHaveLength(3);
  expect(check.flits[0].observedWires).toEqual([70, 71]);
});

it('verifies a Plane C route by router sequence and refuses the wire claim it cannot make', () => {
  // Subnet 1 has no certified port-to-wire map, so a legal XY route must not be
  // reported as a wire mismatch.
  const crossed = [event(1, 0, 31, 9, 'receive', 1), event(2, 0, 31, 9, 'send', 1), event(3, 1, 31, 9, 'receive', 1), event(4, 1, 31, 9, 'send', 1), event(5, 3, 31, 9, 'receive', 1)];
  const check = verifyObserved(crossed, topology, table, config, portWires);
  expect(check.mismatched).toBe(0);
  expect(check.verified).toBe(1);
  expect(check.wireVerified).toBe(0);
  expect(check.flits[0].wireVerified).toBe(false);
  expect(check.flits[0].shape).toBe('XY');
});

it('confirms a local delivery from the retirement record instead of leaving it ambiguous', () => {
  // R0 serves terminals 0 and 1, so 0 → 1 never leaves R0. The retirement line
  // names both endpoints, which is what turns "one receipt" into a verdict.
  const fates = new Map<number, ObservedFlitFate>([[13, { flit: 13, packet: 4, sourceTerminal: 0, destinationTerminal: 0, hops: 1 }]]);
  const check = verifyObserved([event(1, 0, 13, 1, 'receive'), event(2, 0, 13, 2, 'send')], topology, table, config, portWires, fates);
  expect(check.local).toBe(1);
  expect(check.unverified).toBe(0);
  expect(check.flits[0].verdict).toBe('local');
});

it('fails a flit whose native hop counter contradicts the matched route', () => {
  const fates = new Map<number, ObservedFlitFate>([[17, { flit: 17, packet: 8, sourceTerminal: 0, destinationTerminal: 3, hops: 4 }]]);
  const rows = [event(1, 0, 17, 1, 'receive'), event(2, 0, 17, 2, 'send'), event(3, 1, 17, 1, 'receive'), event(4, 1, 17, 2, 'send'), event(5, 3, 17, 1, 'receive')];
  const check = verifyObserved(rows, topology, table, config, portWires, fates);
  expect(check.mismatched).toBe(1);
  expect(check.flits[0].reason).toContain('hop counter');
});

it('reports a single receipt on a foreign router and a flit crossing planes as unverifiable, not verified', () => {
  const single = verifyObserved([event(1, 1, 11, 1, 'receive')], topology, table, config, portWires);
  expect(single.flits[0].verdict).toBe('unverified');
  expect(single.flits[0].reason).toContain('indistinguishable');
  const crossed = verifyObserved([event(1, 0, 12, 1, 'receive', 0), event(2, 1, 12, 1, 'receive', 1)], topology, table, config, portWires);
  expect(crossed.flits[0].verdict).toBe('unverified');
  expect(crossed.flits[0].reason).toContain('more than one native subnet');
});

it('verifies a deterministic route artifact that declares no shape policy', () => {
  // RouteArtifactV3 carries one `decision` per pair and NO shape_of_partition;
  // only ShapePolicyRoute declares shapes. Reading the shape list from a key the
  // artifact never wrote left zero candidates, so every subnet-0 flit was
  // reported as 'no certified decision exists for this router pair' against a
  // route the artifact does certify. The neutral shape is not a claim about
  // adaptivity — it is the absence of a selector.
  const deterministic: SharedRouteTable = {
    artifact_id: 'frozen-deterministic', routing_class: 'SROTA_O1TURN',
    terminal_to_router: [[0, 0], [1, 1], [2, 2], [3, 3]],
    decisions: [[0, 3, decision(1, 0)], [1, 3, decision(3, 0)]],
  };
  const rows = [event(1, 0, 41, 1, 'receive'), event(2, 0, 41, 2, 'send'), event(3, 1, 41, 1, 'receive'), event(4, 1, 41, 2, 'send'), event(5, 3, 41, 1, 'receive')];
  const check = verifyObserved(rows, topology, deterministic, config, portWires);
  expect(check.mismatched).toBe(0);
  expect(check.verified).toBe(1);
  expect(check.firstMismatch).toBeNull();
  expect(check.flits[0].shape).toBe('DETERMINISTIC');
  // The refusal still works: the same table must reject a route it does not certify.
  const offRoute = [event(1, 0, 42, 1, 'receive'), event(2, 0, 42, 2, 'send'), event(3, 1, 42, 1, 'receive'), event(4, 1, 42, 2, 'send'), event(5, 2, 42, 1, 'receive')];
  expect(verifyObserved(offRoute, topology, deterministic, config, new Map([['0:2', { wire: 70, taps: [1] }], ['1:2', { wire: 74, taps: [2] }]])).mismatched).toBe(1);
});

// A rank-policy artifact: decisions carry a hop RANK, and there is no
// `shape_of_partition`. Two decisions for one pair can share a rank, which is
// exactly what broke playback: the shape-labelled walk took the first one.
const rankTable: SharedRouteTable = {
  artifact_id: 'frozen-rank', routing_class: 'SROTA_O1TURN_RANK',
  terminal_to_router: [[0, 0], [1, 1], [2, 2], [3, 3]],
  partition_to_vcs: { '0': [0], '1': [1] },
  choices: [
    [0, 3, [decision(1, 0), decision(2, 0)]],
    [1, 3, [decision(3, 0)]],
    [2, 3, [decision(3, 1)]],
  ],
};
const rankWires = new Map([['0:3', { wire: 72, taps: [2] }], ['2:2', { wire: 73, taps: [3] }]]);
const rankRow = (flit: number) => [event(1, 0, flit, 1, 'receive'), event(2, 0, flit, 3, 'send'), event(3, 2, flit, 1, 'receive'), event(4, 2, flit, 2, 'send'), event(5, 3, flit, 1, 'receive')];

it('verifies a recorded hop the rank union admits but no single shape walks', () => {
  // R0 > R2 is the SECOND rank-0 decision at R0. A shape-labelled walk takes the
  // first (R0 > R1), so equality against it reported a false mismatch for a path
  // the certified union admits — "recorded R5 > R9 > R4 ... certified R5 > R0 > R4".
  const check = verifyObserved(rankRow(520), topology, rankTable, config, rankWires);
  expect(check.mismatched).toBe(0);
  expect(check.verified).toBe(1);
  expect(check.firstMismatch).toBeNull();
  expect(check.flits[0].shape).toBe('UNION');
  expect(check.flits[0].observedWires).toEqual([72, 73]);
  expect(check.flits[0].wireVerified).toBe(true);
});

it('still refuses a recorded hop the rank union does not admit', () => {
  // Legally wired (R2 -> R1 exists as a declared wire) but not a certified
  // decision for terminal 3, so the union is what refuses it — not the wire map.
  const wiredTopology = { ...topology, shared_links: [...topology.shared_links!, { shared_link_id: 75, src_router: 2, taps: [1], latency_cycles: 1, width_bits: 64 }] } as Topology;
  const offUnion = [event(1, 0, 521, 1, 'receive'), event(2, 0, 521, 3, 'send'), event(3, 2, 521, 1, 'receive'), event(4, 2, 521, 2, 'send'), event(5, 1, 521, 1, 'receive')];
  // The retirement record pins the endpoints, so the union is asked the right
  // question: terminal 0 -> terminal 3. The last hop is still off the union.
  const fates = new Map([[521, { flit: 521, packet: 5, sourceTerminal: 0, destinationTerminal: 3, hops: 3 }]]);
  const check = verifyObserved(offUnion, wiredTopology, rankTable, config, new Map([['0:3', { wire: 72, taps: [2] }], ['2:2', { wire: 75, taps: [1] }]]), fates);
  expect(check.mismatched).toBe(1);
  expect(check.firstMismatch).toContain('flit 521');
  expect(check.firstMismatch).toContain('leaves the certified union at R2 > R1');
});
