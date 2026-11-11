import type { SimLoad, Topology } from './gateway';
import { buildChannelIndex, matchMeasuredChannel } from './channelTopology';

export type RouterLoad = {
  router: number; channels: number; flits: number;
  declaredFlits: number; localFlits: number; unattributedFlits: number;
  ingressFlits: number;
  peakUtilization: number; meanUtilization: number;
  queueCycles: number; arbCycles: number;
  weightedHopLatency: number | null; peakQueued: number; stalledChannels: number;
};

type RouterAccumulator = RouterLoad & {
  utilizationSum: number;
  latencyWeight: number;
  latencyTotal: number;
};

const emptyRouter = (router: number): RouterAccumulator => ({
  router, channels: 0, flits: 0, declaredFlits: 0, localFlits: 0, unattributedFlits: 0,
  ingressFlits: 0, peakUtilization: 0, meanUtilization: 0, queueCycles: 0, arbCycles: 0,
  weightedHopLatency: null, peakQueued: 0, stalledChannels: 0,
  utilizationSum: 0, latencyWeight: 0, latencyTotal: 0,
});

/** BookSim's measured channel id packs subnet, source router, and the
 *  router's local output port. For a 2-D mesh that port is E/W/S/N/eject,
 *  which is not the topology artifact's `src_port` numbering. The join is
 *  therefore done by declared neighbour; a raw port number is never used as
 *  a key. This remains a source-port view: the artifact carries no
 *  router-internal queue occupancy, per-initiator latency, or packet count. */
export function aggregateRouterLoad(channels: SimLoad['channels'], topology: Topology | null, portWires?: Map<string, { wire: number; taps: number[] }>): RouterLoad[] {
  const index = buildChannelIndex(topology, portWires);
  const byRouter = new Map<number, RouterAccumulator>();
  const getRouter = (router: number): RouterAccumulator => {
    const existing = byRouter.get(router);
    if (existing) return existing;
    const created = emptyRouter(router);
    byRouter.set(router, created);
    return created;
  };
  for (const channel of channels ?? []) {
    const match = matchMeasuredChannel(index, Number(channel.logical_channel_id));
    if (!match) continue;
    const entry = getRouter(match.measured.router);
    entry.channels += 1;
    entry.flits += channel.flits_total;
    entry.utilizationSum += channel.utilization;
    if (match.local) entry.localFlits += channel.flits_total;
    else if (match.channel || match.wire) entry.declaredFlits += channel.flits_total;
    else entry.unattributedFlits += channel.flits_total;
    // Ingress is the same measured flit arriving at the declared neighbour.
    // A shared wire names many taps from ONE driver port, so the landing is not
    // implied by the counter: wire egress is counted, wire ingress is not.
    if (match.channel) getRouter(match.channel.dst_router).ingressFlits += channel.flits_total;
    entry.peakUtilization = Math.max(entry.peakUtilization, channel.peak_window_utilization);
    entry.queueCycles += channel.queue_cycles_total ?? 0;
    entry.arbCycles += channel.arb_wait_cycles_total ?? 0;
    entry.peakQueued = Math.max(entry.peakQueued, channel.peak_queued_flits ?? 0);
    entry.stalledChannels += channel.has_stalls ? 1 : 0;
    if (typeof channel.per_hop_latency_mean_cycles === 'number') {
      entry.latencyWeight += channel.flits_total;
      entry.latencyTotal += channel.per_hop_latency_mean_cycles * channel.flits_total;
    }
  }
  return [...byRouter.values()].map(({ utilizationSum, latencyWeight, latencyTotal, ...entry }) => ({
    ...entry,
    meanUtilization: entry.channels ? utilizationSum / entry.channels : 0,
    weightedHopLatency: latencyWeight ? latencyTotal / latencyWeight : null,
  })).sort((a, b) => b.flits - a.flits);
}
