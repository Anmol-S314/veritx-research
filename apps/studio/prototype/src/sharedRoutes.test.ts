import { expect, it } from 'vitest';
import type { Topology } from './gateway';
import { projectSharedTrace, sharedResourceLoads, type Decision, type SharedRouteTable } from './sharedRoutes';
const config = 'topology=srota; k=2; c=1; classes=2; class_subnet={0,1}; srota_planes=3;';
const topology = { family: 'srota', counts: {}, routers: [0, 1, 2, 3].map(router_id => ({ router_id, coordinates: [router_id % 2, Math.floor(router_id / 2)], seat_capacity: 1 })), endpoints: [], channels: [], shared_links: [
  { shared_link_id: 70, src_router: 0, taps: [1], latency_cycles: 1, width_bits: 64 },
  { shared_link_id: 71, src_router: 1, taps: [3], latency_cycles: 1, width_bits: 64 },
  { shared_link_id: 72, src_router: 0, taps: [2], latency_cycles: 1, width_bits: 64 },
  { shared_link_id: 73, src_router: 2, taps: [3], latency_cycles: 1, width_bits: 64 },
] } as Topology;
const decision = (next_router: number, vc_partition: number): Decision => ({ resource: { kind: 'SHARED_LINK', resource_id: 999 }, next_router, vc_partition, tap: 0 });
const table: SharedRouteTable = { artifact_id: 'frozen', routing_class: 'SROTA_O1TURN_SHAPE_POLICY', terminal_to_router: [[0, 0], [1, 1], [2, 2], [3, 3]], shape_of_partition: { '0': 'ROW_FIRST', '1': 'COL_FIRST' }, choices: [[0, 3, [decision(1, 0), decision(2, 1)]], [1, 3, [decision(3, 0)]], [2, 3, [decision(3, 1)]]] };
const rows = [0, 1].map(trafficClass => ({ line: trafficClass + 1, cycle: 0, source: 0, destination: 3, trafficClass: String(trafficClass), flits: 4 }));
it('binds v3 port resources to topology wires, and preserves adaptive shape end-to-end', () => {
  const row = projectSharedTrace(topology, table, config, rows, 'ROW_FIRST');
  const column = projectSharedTrace(topology, table, config, rows, 'COL_FIRST');
  expect(row.rejected).toEqual([]);
  expect(row.packets[0].hops.map(hop => hop.key)).toEqual(['D:70', 'D:71']);
  expect(column.packets[0].hops.map(hop => hop.key)).toEqual(['D:72', 'D:73']);
  // Plane C is always the native private XY mesh, never an express-wire alias.
  expect(column.packets[1].hops.map(hop => hop.key)).toEqual(['C:0:1', 'C:1:3']);
});
it('does not guess broken bindings, missing choices, unknown endpoints or invalid classes', () => {
  expect(projectSharedTrace(topology, table, config, rows, 'NONEXISTENT').rejected).toHaveLength(1);
  expect(projectSharedTrace({ ...topology, shared_links: [] }, table, config, rows, 'ROW_FIRST').rejected).toHaveLength(1);
  expect(projectSharedTrace(topology, table, config, [{ ...rows[0], source: 99 }], 'ROW_FIRST').rejected).toHaveLength(1);
  expect(projectSharedTrace(topology, table, config, [{ ...rows[0], trafficClass: '9' }], 'ROW_FIRST').rejected).toHaveLength(1);
});
it('aggregates distinct landing taps onto one contending wire and conserves resource-hop counts', () => {
  const wireTopology = { ...topology, shared_links: [{ shared_link_id: 70, src_router: 0, taps: [1, 3], latency_cycles: 1, width_bits: 64 }] };
  const wireTable: SharedRouteTable = { ...table, choices: [[0, 1, [decision(1, 0)]], [0, 3, [{ ...decision(3, 0), tap: 1 }]]] };
  const result = projectSharedTrace(wireTopology, wireTable, config, [{ ...rows[0], destination: 1 }, rows[0]], 'ROW_FIRST');
  expect(result.rejected).toEqual([]);
  const loads = sharedResourceLoads(result.packets);
  expect(loads).toHaveLength(1);
  expect(loads[0].flits).toBe(8);
  expect([...loads[0].taps]).toEqual([[0, 4], [1, 4]]);
  expect(result.packets.map(packet => packet.duration)).toEqual([1, 2]);
});
