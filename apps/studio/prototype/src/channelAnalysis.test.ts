import { describe, expect, it } from 'vitest';
import { attributionSummary, channelCosts, directionShares, flitShares, median, utilizationBins, windowMetricRows, windowRows, windowSummary } from './channelAnalysis';
import type { SimLoad, SimSeries, Topology } from './gateway';

type LoadChannel = NonNullable<SimLoad['channels']>[number];

const loadChannel = (id: number, flits: number, extra: Partial<LoadChannel> = {}): LoadChannel => ({
  logical_channel_id: id, flits_total: flits, cycles_sampled: 100,
  utilization: 0.1, peak_window_utilization: 0.5, ...extra,
});

const series = (channels: { id: number; values: number[] }[], numWindows = 4): SimSeries => ({
  source: 'measured', num_windows: numWindows,
  channels: channels.map(channel => ({
    logical_channel_id: channel.id,
    flits_per_window: channel.values,
    window_cycles: channel.values.map(() => 100),
    queue_max_per_window: channel.values.map(value => value / 10),
    latency_max_per_window: channel.values.map(value => value / 100),
  })),
});

const topology: Topology = {
  family: 'mesh', counts: { routers: 2 },
  routers: [{ router_id: 0, coordinates: [0, 0] }, { router_id: 1, coordinates: [1, 0] }],
  channels: [
    { channel_id: 0, src_router: 0, src_port: 9, dst_router: 1, dst_port: 9, width_bits: 128, latency_cycles: 1 },
    { channel_id: 1, src_router: 1, src_port: 9, dst_router: 0, dst_port: 9, width_bits: 128, latency_cycles: 1 },
  ],
  endpoints: [],
};

describe('measured channel analysis helpers', () => {
  it('uses one axis for sustained and peak-window histograms', () => {
    const { bins, step } = utilizationBins([
      loadChannel(0, 10, { utilization: 0.02, peak_window_utilization: 0.52 }),
      loadChannel(1, 10, { utilization: 0.18, peak_window_utilization: 0.78 }),
    ]);
    expect(step).toBe(0.1);
    expect(bins).toHaveLength(8);
    expect(bins[0].sustained).toBe(1);
    expect(bins[1].sustained).toBe(1);
    expect(bins[5].peak).toBe(1);
    expect(bins[7].peak).toBe(1);
    expect(bins.reduce((sum, bin) => sum + bin.sustained, 0)).toBe(2);
    expect(bins.reduce((sum, bin) => sum + bin.peak, 0)).toBe(2);
  });

  it('reports rank shares that add to one over active channels', () => {
    const shares = flitShares([loadChannel(0, 100), loadChannel(1, 50), loadChannel(2, 25), loadChannel(3, 0)]);
    expect(shares.map(group => group.label)).toEqual(['Top 10']);
    expect(shares[0]).toMatchObject({ channels: 3, flits: 175, share: 1 });
    const many = flitShares(Array.from({ length: 120 }, (_, index) => loadChannel(index, 120 - index)));
    expect(many.map(group => group.label)).toEqual(['Top 10', '11–40', '41–100', '101–120']);
    expect(many.reduce((sum, group) => sum + group.share, 0)).toBeCloseTo(1, 6);
  });

  it('splits declared network flits from local eject and unmatched ports', () => {
    const summary = attributionSummary([
      loadChannel(0, 100), // R0 east -> R1 declared
      loadChannel(4, 30), // R0 local eject
      loadChannel(1, 0), // R0 west boundary, idle
    ], topology);
    expect(summary).toMatchObject({
      grid: true, declaredChannels: 1, declaredFlits: 100, localChannels: 1, localFlits: 30,
      unattributedChannels: 1, unattributedFlits: 0, boundaryIdleChannels: 1, totalFlits: 130,
    });
  });

  it('groups measured flits by declared output direction and keeps unmatched flits separate', () => {
    const shares = directionShares([
      loadChannel(0, 100), // R0 east -> R1 declared
      loadChannel(10001, 40), // R1 west -> R0 declared
      loadChannel(4, 30), // R0 local eject
      loadChannel(1, 20), // R0 west boundary, no declared link
      loadChannel(-1, 15), // invalid packed id, still shown rather than dropped
    ], topology);
    expect(shares.map(share => [share.key, share.flits, share.channels])).toEqual([
      ['east', 100, 1], ['west', 40, 1], ['eject', 30, 1], ['unmatched', 35, 2],
    ]);
    expect(shares.reduce((sum, share) => sum + share.share, 0)).toBeCloseTo(1, 6);
  });

  it('derives queue cost and latency tail without inventing missing counters', () => {
    const costs = channelCosts([
      loadChannel(0, 100, { queue_cycles_total: 250, per_hop_latency_mean_cycles: 2.5, peak_per_hop_latency_cycles: 25 }),
      loadChannel(1, 10, { per_hop_latency_mean_cycles: 0, peak_per_hop_latency_cycles: 9 }),
      loadChannel(2, 0, { queue_cycles_total: 10 }),
    ]);
    expect(costs).toHaveLength(2);
    expect(costs[0]).toMatchObject({ id: 0, queuePerFlit: 2.5, tailRatio: 10 });
    expect(costs[1]).toMatchObject({ id: 1, queuePerFlit: null, tailRatio: null });
  });

  it('keeps the busiest rows, orders them by phase or load, and totals every channel', () => {
    const input = series([
      { id: 0, values: [1, 1, 0, 0] }, // total 2, centroid 0.5
      { id: 1, values: [0, 0, 5, 5] }, // total 10, centroid 2.5
      { id: 2, values: [0, 9, 0, 0] }, // total 9, centroid 1
      { id: 3, values: [0, 0, 0, 0] },
    ]);
    // The first cut is by volume; phase order only orders the retained sample.
    const byTime = windowRows(input, 2, 'time');
    expect(byTime.rows.map(row => row.id)).toEqual(['2', '1']);
    expect(byTime.rows.map(row => row.centroid)).toEqual([1, 2.5]);
    expect(byTime.windowTotals).toEqual([1, 10, 5, 5]);
    expect(byTime.activeChannels).toBe(3);
    const allTime = windowRows(input, 3, 'time');
    expect(allTime.rows.map(row => row.id)).toEqual(['0', '2', '1']);
    const byLoad = windowRows(input, 2, 'load');
    expect(byLoad.rows.map(row => row.id)).toEqual(['1', '2']);
  });

  it('counts separate active runs and finds the fabric busiest window', () => {
    const summary = windowSummary(series([
      { id: 0, values: [1, 0, 0, 2] },
      { id: 1, values: [0, 3, 0, 0] },
      { id: 2, values: [0, 0, 0, 0] },
    ]));
    expect(summary).toMatchObject({
      activeChannels: 2, medianActiveWindows: 1.5, twoPhaseChannels: 1,
      busiestWindow: 1, busiestFlits: 3, totalFlits: 6, numWindows: 4,
    });
  });

  it('computes a stable median for odd and even samples', () => {
    expect(median([])).toBeNull();
    expect(median([3, 1, 2])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });

  it('builds the same matrix for a wait counter and keeps missing channels explicit', () => {
    const input: SimSeries = {
      source: 'measured', num_windows: 4,
      channels: [
        { logical_channel_id: 0, flits_per_window: [0, 0, 0, 0], window_cycles: [10, 10, 10, 10], queue_cycles_per_window: [0, 4, 0, 0] },
        { logical_channel_id: 1, flits_per_window: [0, 0, 0, 0], window_cycles: [10, 10, 10, 10], queue_cycles_per_window: [2, 0, 0, 0] },
        { logical_channel_id: 2, flits_per_window: [0, 0, 0, 0], window_cycles: [10, 10, 10, 10], queue_cycles_per_window: null },
      ],
    };
    const matrix = windowMetricRows(input, 'queue', 2, 'load');
    expect(matrix.rows.map(row => [row.id, row.total])).toEqual([['0', 4], ['1', 2]]);
    expect(matrix.windowTotals).toEqual([2, 4, 0, 0]);
    expect(matrix.activeChannels).toBe(2);
    expect(matrix.recordedChannels).toBe(2);
    expect(matrix.totalChannels).toBe(3);
    const summary = windowSummary(input, 'queue');
    expect(summary).toMatchObject({
      activeChannels: 2, medianActiveWindows: 1, twoPhaseChannels: 0,
      busiestWindow: 1, busiestFlits: 4, totalFlits: 6, numWindows: 4,
    });
  });

  it('keeps a measured zero visible instead of dropping the whole matrix', () => {
    const input: SimSeries = {
      source: 'measured', num_windows: 3,
      channels: [
        { logical_channel_id: 0, flits_per_window: [2, 0, 0], window_cycles: [10, 10, 10], arb_wait_cycles_per_window: [0, 0, 0] },
        { logical_channel_id: 1, flits_per_window: [0, 1, 0], window_cycles: [10, 10, 10], arb_wait_cycles_per_window: [0, 0, 0] },
        { logical_channel_id: 2, flits_per_window: [0, 0, 0], window_cycles: [10, 10, 10], arb_wait_cycles_per_window: [0, 0, 0] },
      ],
    };
    const matrix = windowMetricRows(input, 'arb', 24);
    expect(matrix.rows.map(row => row.id)).toEqual(['0', '1']);
    expect(matrix.rows.every(row => row.total === 0)).toBe(true);
    expect(matrix.activeChannels).toBe(0);
    expect(windowSummary(input, 'arb')).toMatchObject({ busiestWindow: -1, busiestFlits: 0, totalFlits: 0 });
  });
});
