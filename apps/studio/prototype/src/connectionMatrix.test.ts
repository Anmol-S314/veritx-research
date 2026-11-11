import { describe, expect, it } from 'vitest';
import { incidenceMatrix } from './connectionMatrix';
import type { Topology } from './gateway';

const topology = (overrides: Partial<Topology> = {}): Topology => ({
  family: 'mesh',
  routers: [0, 1, 2].map(router_id => ({ router_id, coordinates: [router_id, 0], seat_capacity: 2 })),
  channels: [],
  endpoints: [],
  counts: { routers: 3, channels: 0, seats: 6, endpoints: 0 },
  ...overrides,
});

describe('connection incidence matrix', () => {
  it('counts both directions of a declared channel as one undirected pair', () => {
    const matrix = incidenceMatrix(topology({
      channels: [
        { channel_id: 0, src_router: 0, dst_router: 1, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
        { channel_id: 1, src_router: 1, dst_router: 0, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
      ],
    }), 'channels');
    expect(matrix.ids).toEqual([0, 1, 2]);
    expect(matrix.pairs).toBe(1);
    expect(matrix.max).toBe(2);
    expect(matrix.counts[0][1]).toBe(2);
    expect(matrix.counts[1][0]).toBe(2);
    expect(matrix.counts[0][0]).toBe(0);
  });

  it('counts one driver-to-tap incidence per tap without making it point-to-point', () => {
    const matrix = incidenceMatrix(topology({
      shared_links: [
        { shared_link_id: 0, src_router: 0, taps: [1, 2], width_bits: 64, latency_cycles: 1 },
        { shared_link_id: 1, src_router: 0, taps: [1], width_bits: 64, latency_cycles: 1 },
      ],
    }), 'shared');
    expect(matrix.pairs).toBe(2);
    expect(matrix.max).toBe(2);
    expect(matrix.counts[0][1]).toBe(2);
    expect(matrix.counts[0][2]).toBe(1);
  });

  it('does not invent a cell for an absent channel or shared wire', () => {
    const matrix = incidenceMatrix(topology(), 'channels');
    expect(matrix.max).toBe(0);
    expect(matrix.pairs).toBe(0);
    expect(matrix.counts.flat().every(value => value === 0)).toBe(true);
  });
});
