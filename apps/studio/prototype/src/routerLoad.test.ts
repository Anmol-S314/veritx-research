import { describe, expect, it } from 'vitest';
import { aggregateRouterLoad } from './routerLoad';
import type { SimLoad, Topology } from './gateway';

const topology: Topology = {
  family: 'mesh',
  counts: { routers: 2 },
  routers: [{ router_id: 0, coordinates: [0, 0] }, { router_id: 1, coordinates: [1, 0] }],
  channels: [
    { channel_id: 0, src_router: 0, src_port: 1, dst_router: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 1, src_router: 1, src_port: 1, dst_router: 0, dst_port: 1, width_bits: 64, latency_cycles: 1 },
  ],
  endpoints: [],
};

const channel = (id: number, flits: number, extra: Partial<NonNullable<SimLoad['channels']>[number]> = {}) => ({
  logical_channel_id: id,
  flits_total: flits,
  cycles_sampled: 100,
  utilization: 0.3,
  peak_window_utilization: 0.5,
  ...extra,
});

describe('per-router measured load aggregation', () => {
  it('joins measured output ports to declared neighbours and attributes ingress', () => {
    const rows = aggregateRouterLoad([
      // BookSim port 0 is east. R0 is west of R1, so this is the declared
      // R0 -> R1 link even though the topology calls its src_port 1.
      channel(0, 100, { queue_cycles_total: 20, arb_wait_cycles_total: 2, per_hop_latency_mean_cycles: 2, peak_queued_flits: 4, has_stalls: true }),
      // R1 port 1 is west, the declared R1 -> R0 link.
      channel(10001, 40),
      // Port 4 is the local eject channel; it has no inter-router ingress.
      channel(4, 10, { peak_window_utilization: 0.8 }),
    ], topology);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      router: 0, channels: 2, flits: 110, declaredFlits: 100, localFlits: 10, unattributedFlits: 0,
      ingressFlits: 40, queueCycles: 20, arbCycles: 2, peakQueued: 4, stalledChannels: 1,
      peakUtilization: 0.8, meanUtilization: 0.3, weightedHopLatency: 2,
    });
    expect(rows[1]).toMatchObject({
      router: 1, channels: 1, flits: 40, declaredFlits: 40, localFlits: 0, ingressFlits: 100,
    });
  });

  it('does not treat a raw topology port number as a join key', () => {
    // R0 port 1 is west in BookSim. The declared topology's R0 src_port 1 is
    // east, so a raw-number join would invent ingress at R1.
    const rows = aggregateRouterLoad([channel(1, 25)], topology);
    expect(rows[0]).toMatchObject({
      router: 0, flits: 25, declaredFlits: 0, localFlits: 0, unattributedFlits: 25, ingressFlits: 0,
    });
  });

  it('keeps local eject flits in egress without inventing ingress', () => {
    const rows = aggregateRouterLoad([channel(4, 25)], topology);
    expect(rows[0]).toMatchObject({ router: 0, flits: 25, localFlits: 25, ingressFlits: 0 });
  });

  it('does not merge a non-zero subnet into the single declared topology', () => {
    const rows = aggregateRouterLoad([channel(100_000_000, 25)], topology);
    expect(rows[0]).toMatchObject({ router: 0, flits: 25, declaredFlits: 0, unattributedFlits: 25, ingressFlits: 0 });
  });

  it('ignores invalid measured ids rather than wrapping them onto a router', () => {
    expect(aggregateRouterLoad([channel(-1, 10), channel(1.5, 10)], topology)).toEqual([]);
  });
});
