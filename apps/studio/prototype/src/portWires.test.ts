import { expect, it } from 'vitest';
import type { Topology } from './gateway';
import { buildPortWireMap, parseRoutingDump, portWiresUsable } from './portWires';

const topology = {
  family: 'srota', counts: {},
  routers: [{ router_id: 0, coordinates: [0, 0], seat_capacity: 1 }, { router_id: 1, coordinates: [1, 0], seat_capacity: 1 }],
  endpoints: [], channels: [],
  shared_links: [
    { shared_link_id: 70, src_router: 0, taps: [1], latency_cycles: 1, width_bits: 64 },
    { shared_link_id: 71, src_router: 1, taps: [0], latency_cycles: 1, width_bits: 64 },
  ],
} as Topology;
const line = (src: number, dst: number, next: number, port: number, drop: number) => `src_router ${src} dst_node ${dst} next_router ${next} port ${port} drop ${drop} vc_start 0 vc_end 1`;

it('parses the executed routing dump and reads drop=-1 as a local eject', () => {
  const rows = parseRoutingDump(`# header\n${line(0, 0, 0, 0, -1)}\n${line(0, 1, 1, 1, 0)}\n`);
  expect(rows).toEqual([{ src: 0, dst: 0, next: 0, port: 0, drop: -1 }, { src: 0, dst: 1, next: 1, port: 1, drop: 0 }]);
  expect(() => parseRoutingDump('src_router 0 dst_node 0')).toThrow(/14 fields/);
  expect(() => parseRoutingDump(line(0, 0, -1, 0, 0))).toThrow(/next_router/);
});

it('binds one driver port to one wire and covers every declared wire', () => {
  const rows = parseRoutingDump([line(0, 0, 0, 0, -1), line(0, 1, 1, 1, 0), line(1, 1, 1, 0, -1), line(1, 0, 0, 1, 0)].join('\n'));
  const map = buildPortWireMap(topology, rows);
  expect(map.problems).toEqual([]);
  expect(portWiresUsable(map)).toBe(true);
  expect(map.ports.get('0:1')).toEqual({ wire: 70, taps: [1] });
  expect(map.ports.get('1:1')).toEqual({ wire: 71, taps: [0] });
  expect(map.locals.get('0:0')).toBe(0);
});

it('refuses a partial, ambiguous or duplicated port-to-wire binding', () => {
  // One wire never driven: coverage must fail rather than leave a silent gap.
  const partial = buildPortWireMap(topology, parseRoutingDump([line(0, 0, 0, 0, -1), line(0, 1, 1, 1, 0), line(1, 1, 1, 0, -1)].join('\n')));
  expect(partial.problems.join(' ')).toMatch(/never driven/);
  // Two ports claiming the same wire.
  const duplicate = buildPortWireMap(topology, parseRoutingDump([line(0, 0, 0, 0, -1), line(0, 1, 1, 1, 0), line(1, 1, 1, 0, -1), line(1, 0, 0, 1, 0), line(1, 0, 0, 2, 0)].join('\n')));
  expect(duplicate.problems.join(' ')).toMatch(/both port/);
  // A landing that is not a tap of any wire.
  const wrong = buildPortWireMap(topology, parseRoutingDump([line(0, 0, 0, 0, -1), line(0, 1, 1, 1, 1), line(1, 1, 1, 0, -1), line(1, 0, 0, 1, 0)].join('\n')));
  expect(wrong.problems.join(' ')).toMatch(/expected exactly one/);
  // Local port count disagreeing with the declared seat capacity.
  const seats = buildPortWireMap(topology, parseRoutingDump([line(0, 1, 1, 1, 0), line(1, 0, 0, 1, 0)].join('\n')));
  expect(seats.problems.join(' ')).toMatch(/local eject ports/);
});
