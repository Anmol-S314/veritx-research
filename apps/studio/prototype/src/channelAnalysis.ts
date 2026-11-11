import type { SimLoad, SimSeries, SimSeriesChannel, Topology } from './gateway';
import { buildChannelIndex, matchMeasuredChannel } from './channelTopology';

export type LoadChannel = NonNullable<SimLoad['channels']>[number];

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export type UtilizationBin = { low: number; high: number; sustained: number; peak: number };

/** One selected histogram bin, carried from the load-shape chart to the
 *  measured-channel list. `last` keeps the top boundary inclusive because
 *  utilizationBins clamps values above the final bin edge into that bin. */
export type UtilizationRange = { low: number; high: number; last: boolean; step: number };

export function utilizationRangeFor(bin: UtilizationBin, index: number, bins: UtilizationBin[], step: number): UtilizationRange {
  return { low: bin.low, high: bin.high, last: index === bins.length - 1, step };
}

export function utilizationInRange(value: number, range: UtilizationRange | null): boolean {
  if (!range) return true;
  if (!Number.isFinite(value)) return false;
  return value >= range.low && (value < range.high || range.last);
}

/** Equal-width bins shared by both series so the sustained/peak contrast is
 *  read on one axis. The step shrinks for low-load runs; it never splits a
 *  channel across bins. */
export function utilizationBins(channels: LoadChannel[], maxBins = 10): { bins: UtilizationBin[]; step: number } {
  const values = channels.flatMap(channel => [channel.utilization, channel.peak_window_utilization])
    .filter(value => Number.isFinite(value) && value >= 0);
  const max = values.length ? Math.max(...values) : 0;
  const rawStep = Math.max(max, 0.01) / maxBins;
  const step = [0.025, 0.05, 0.1, 0.2, 0.25].find(candidate => candidate >= rawStep) ?? 0.25;
  const count = Math.max(1, Math.ceil((max + 1e-9) / step));
  const bins: UtilizationBin[] = Array.from({ length: count }, (_, index) => ({
    low: index * step, high: (index + 1) * step, sustained: 0, peak: 0,
  }));
  for (const channel of channels) {
    if (Number.isFinite(channel.utilization)) bins[Math.min(count - 1, Math.floor(channel.utilization / step))].sustained += 1;
    if (Number.isFinite(channel.peak_window_utilization)) bins[Math.min(count - 1, Math.floor(channel.peak_window_utilization / step))].peak += 1;
  }
  return { bins, step };
}

export type ShareGroup = { label: string; channels: number; flits: number; share: number };

/** Flit share by descending channel rank. The groups are fixed cuts so the
 *  same four bars are comparable across runs; the last label adapts when a
 *  run has fewer than 100 active channels. */
export function flitShares(channels: LoadChannel[], cuts: [number, number, number] = [10, 40, 100]): ShareGroup[] {
  const active = channels.filter(channel => channel.flits_total > 0)
    .map(channel => channel.flits_total).sort((a, b) => b - a);
  const total = active.reduce((sum, value) => sum + value, 0);
  const ranges: [string, number, number][] = [
    [`Top ${cuts[0]}`, 0, cuts[0]],
    [`${cuts[0] + 1}–${cuts[1]}`, cuts[0], cuts[1]],
    [`${cuts[1] + 1}–${cuts[2]}`, cuts[1], cuts[2]],
    [`${cuts[2] + 1}–${active.length}`, cuts[2], active.length],
  ];
  return ranges.map(([label, start, end]) => {
    const values = active.slice(start, end);
    const flits = values.reduce((sum, value) => sum + value, 0);
    return { label, channels: values.length, flits, share: total ? flits / total : 0 };
  }).filter(group => group.channels > 0 || group.label.startsWith('Top'));
}

export type AttributionSummary = {
  grid: boolean;
  declaredChannels: number;
  declaredFlits: number;
  wireChannels: number;
  wireFlits: number;
  localChannels: number;
  localFlits: number;
  unattributedChannels: number;
  unattributedFlits: number;
  boundaryIdleChannels: number;
  totalFlits: number;
};

/** Count measured flits by join class. `declaredFlits` are traversals on a
 *  declared inter-router link; `localFlits` left through port 4 (eject) and
 *  are egress-only. A boundary port with no declared neighbour is counted as
 *  idle when it carried nothing, rather than presented as lost traffic. */
export function attributionSummary(channels: LoadChannel[], topology: Topology | null, portWires?: Map<string, { wire: number; taps: number[] }>): AttributionSummary {
  const index = buildChannelIndex(topology, portWires);
  const summary: AttributionSummary = {
    grid: index.grid, declaredChannels: 0, declaredFlits: 0, wireChannels: 0, wireFlits: 0, localChannels: 0, localFlits: 0,
    unattributedChannels: 0, unattributedFlits: 0, boundaryIdleChannels: 0, totalFlits: 0,
  };
  for (const channel of channels) {
    const match = matchMeasuredChannel(index, Number(channel.logical_channel_id));
    if (!match) {
      summary.unattributedChannels += 1;
      summary.unattributedFlits += channel.flits_total;
      summary.totalFlits += channel.flits_total;
      if (channel.flits_total === 0) summary.boundaryIdleChannels += 1;
      continue;
    }
    summary.totalFlits += channel.flits_total;
    if (match.local) {
      summary.localChannels += 1;
      summary.localFlits += channel.flits_total;
    } else if (match.wire) {
      summary.wireChannels += 1;
      summary.wireFlits += channel.flits_total;
    } else if (match.channel) {
      summary.declaredChannels += 1;
      summary.declaredFlits += channel.flits_total;
    } else {
      summary.unattributedChannels += 1;
      summary.unattributedFlits += channel.flits_total;
      if (channel.flits_total === 0) summary.boundaryIdleChannels += 1;
    }
  }
  return summary;
}

export type DirectionKey = 'east' | 'west' | 'south' | 'north' | 'eject' | 'shared' | 'unmatched';
export type DirectionShare = { key: DirectionKey; label: string; flits: number; channels: number; share: number };

const DIRECTION_LABELS: Record<DirectionKey, string> = {
  east: 'East', west: 'West', south: 'South', north: 'North', eject: 'Local eject', shared: 'Shared wire', unmatched: 'No link',
};

/** Measured flits grouped by the source port's output class. This is a
 *  per-hop direction, not the packet's final destination, and it only counts
 *  a direction when the port joined a declared link; otherwise the flits land
 *  in "No link" rather than being assigned to a guessed neighbour. */
export function directionShares(channels: LoadChannel[], topology: Topology | null, portWires?: Map<string, { wire: number; taps: number[] }>): DirectionShare[] {
  const index = buildChannelIndex(topology, portWires);
  const buckets = new Map<DirectionKey, { flits: number; channels: number }>();
  for (const channel of channels) {
    if (channel.flits_total <= 0) continue;
    const match = matchMeasuredChannel(index, Number(channel.logical_channel_id));
    const key: DirectionKey = !match ? 'unmatched' : match.local ? 'eject' : match.wire ? 'shared' : match.channel && match.direction ? match.direction : 'unmatched';
    const bucket = buckets.get(key) ?? { flits: 0, channels: 0 };
    bucket.flits += channel.flits_total;
    bucket.channels += 1;
    buckets.set(key, bucket);
  }
  const total = [...buckets.values()].reduce((sum, bucket) => sum + bucket.flits, 0);
  return (Object.keys(DIRECTION_LABELS) as DirectionKey[])
    .filter(key => (buckets.get(key)?.flits ?? 0) > 0)
    .map(key => {
      const bucket = buckets.get(key)!;
      return { key, label: DIRECTION_LABELS[key], flits: bucket.flits, channels: bucket.channels, share: total ? bucket.flits / total : 0 };
    });
}

export type ChannelCost = {
  id: number;
  channel: LoadChannel;
  queuePerFlit: number | null;
  tailRatio: number | null;
};

/** Per-channel cost quotients. Both are derived from measured counters and
 *  remain null when the counter or denominator is absent. */
export function channelCosts(channels: LoadChannel[]): ChannelCost[] {
  return channels.filter(channel => channel.flits_total > 0).map(channel => {
    const mean = channel.per_hop_latency_mean_cycles;
    const peak = channel.peak_per_hop_latency_cycles;
    return {
      id: Number(channel.logical_channel_id),
      channel,
      queuePerFlit: typeof channel.queue_cycles_total === 'number' ? channel.queue_cycles_total / channel.flits_total : null,
      tailRatio: typeof mean === 'number' && typeof peak === 'number' && mean > 0 ? peak / mean : null,
    };
  });
}

export type WindowMetric = 'flits' | 'queue' | 'arb' | 'tx' | 'occupancy';

export type WindowMetricDefinition = {
  id: WindowMetric;
  label: string;
  short: string;
  unit: string;
  /** The counter each cell sums, named the way the artifact names it. */
  field: keyof Pick<SimSeriesChannel,
    'flits_per_window' | 'queue_cycles_per_window' | 'arb_wait_cycles_per_window'
    | 'tx_busy_cycles_per_window' | 'occupancy_flit_cycles_per_window'>;
  description: string;
};

export const WINDOW_METRICS: WindowMetricDefinition[] = [
  { id: 'flits', label: 'Flits', short: 'Flits', unit: 'flits', field: 'flits_per_window', description: 'Crossbar traversals per window.' },
  { id: 'queue', label: 'Queue wait', short: 'Queue', unit: 'cyc', field: 'queue_cycles_per_window', description: 'Head flit present but not grantable: credit or buffer stalls.' },
  { id: 'arb', label: 'Arbitration wait', short: 'Arb', unit: 'cyc', field: 'arb_wait_cycles_per_window', description: 'Grantable but ungranted: lost VC or switch arbitration.' },
  { id: 'tx', label: 'Transmit busy', short: 'Tx busy', unit: 'cyc', field: 'tx_busy_cycles_per_window', description: 'Cycles the output transmitted or held a staged flit.' },
  { id: 'occupancy', label: 'Queued occupancy', short: 'Occupancy', unit: 'flit·cyc', field: 'occupancy_flit_cycles_per_window', description: 'Per-output queued-flit integral.' },
];

const metricDefinition = (metric: WindowMetric): WindowMetricDefinition =>
  WINDOW_METRICS.find(entry => entry.id === metric) ?? WINDOW_METRICS[0];

/** The metric array for one channel, or null when the artifact did not record
 *  it. Null stays null; a missing counter is never turned into zeros. */
export function windowMetricValues(channel: SimSeriesChannel, metric: WindowMetric): number[] | null {
  const values = channel[metricDefinition(metric).field];
  return Array.isArray(values) ? values : null;
}

/** Whether any channel in the series carries the counter. A partially
 *  recorded series is still displayed, and the component names the gap. */
export function windowMetricRecorded(series: SimSeries, metric: WindowMetric): { recorded: number; total: number } {
  let recorded = 0;
  for (const channel of series.channels) if (windowMetricValues(channel, metric)) recorded += 1;
  return { recorded, total: series.channels.length };
}

export type WindowRow = { id: string; total: number; centroid: number; activeWindows: number; values: number[] };
export type WindowMatrix = {
  rows: WindowRow[];
  windowTotals: number[];
  numWindows: number;
  activeChannels: number;
  recordedChannels: number;
  totalChannels: number;
};

/** Rows for the channel-by-window matrix for one measured counter. `time`
 *  order sorts by the value-weighted window centroid so phase-shifted flows
 *  line up as bands; `load` order is plain descending volume. Totals always
 *  cover every channel in the series, not only the rows shown. */
export function windowMetricRows(series: SimSeries, metric: WindowMetric = 'flits', limit = 24, order: 'time' | 'load' = 'time'): WindowMatrix {
  const arrays = series.channels.map(channel => windowMetricValues(channel, metric));
  const numWindows = Math.max(0, series.num_windows ?? Math.max(0,
    ...series.channels.map(channel => channel.flits_per_window?.length ?? 0),
    ...arrays.map(values => values?.length ?? 0)));
  const all = series.channels.map((channel, index) => {
    const source = arrays[index];
    const values = Array.from({ length: numWindows }, (_, window) => source?.[window] ?? 0);
    const total = values.reduce((sum, value) => sum + value, 0);
    const centroid = total ? values.reduce((sum, value, window) => sum + value * window, 0) / total : 0;
    return {
      id: String(channel.logical_channel_id), total, centroid,
      activeWindows: values.filter(value => value > 0).length, values,
    };
  });
  const active = all.filter(row => row.total > 0);
  // Keep the matrix focused on the busiest channels, then order that sample by
  // phase or load. Sorting the whole set first and slicing would show only the
  // earliest phases and could hide the busiest channels entirely.
  //
  // A measured zero is still a measurement: when no channel records this
  // counter, fall back to the busiest flit channels so the zero rows stay
  // visible instead of the whole matrix disappearing.
  const top = active.length
    ? [...active].sort((a, b) => b.total - a.total).slice(0, limit)
    : (() => {
      const byFlits = series.channels.map((channel, index) => ({
        index,
        flits: (channel.flits_per_window ?? []).reduce((sum, value) => sum + value, 0),
      })).sort((a, b) => b.flits - a.flits || all[a.index].total - all[b.index].total);
      const carrying = byFlits.filter(entry => entry.flits > 0);
      return (carrying.length ? carrying : byFlits).slice(0, limit).map(entry => all[entry.index]);
    })();
  const rows = [...top].sort((a, b) => order === 'time'
    ? (a.centroid - b.centroid) || (b.total - a.total)
    : (b.total - a.total) || (a.centroid - b.centroid));
  const windowTotals = Array.from({ length: numWindows }, (_, index) => all.reduce((sum, row) => sum + (row.values[index] ?? 0), 0));
  return {
    rows, windowTotals, numWindows, activeChannels: active.length,
    recordedChannels: arrays.filter(values => values !== null).length,
    totalChannels: series.channels.length,
  };
}

/** Flit rows are the historical default and remain the matrix entry point. */
export function windowRows(series: SimSeries, limit = 24, order: 'time' | 'load' = 'time'): WindowMatrix {
  return windowMetricRows(series, 'flits', limit, order);
}

export type WindowSummary = {
  activeChannels: number;
  medianActiveWindows: number | null;
  twoPhaseChannels: number;
  busiestWindow: number;
  busiestFlits: number;
  totalFlits: number;
  numWindows: number;
};

/** Fabric-level time facts for one measured counter. A channel is two-phase
 *  when its non-zero windows form at least two separate runs, which is what the
 *  matrix makes visible. Field names keep the historical flit vocabulary; the
 *  component labels the unit for the selected metric. */
export function windowSummary(series: SimSeries, metric: WindowMetric = 'flits'): WindowSummary {
  const arrays = series.channels.map(channel => windowMetricValues(channel, metric));
  const numWindows = Math.max(0, series.num_windows ?? Math.max(0,
    ...series.channels.map(channel => channel.flits_per_window?.length ?? 0),
    ...arrays.map(values => values?.length ?? 0)));
  const rows = series.channels.map((_, index) => Array.from({ length: numWindows }, (_, window) => arrays[index]?.[window] ?? 0));
  const active = rows.filter(values => values.some(value => value > 0));
  const activeCounts: number[] = [];
  let twoPhase = 0;
  for (const values of active) {
    activeCounts.push(values.filter(value => value > 0).length);
    let runs = 0, previous = false;
    for (const value of values) {
      if (value > 0 && !previous) runs += 1;
      previous = value > 0;
    }
    if (runs >= 2) twoPhase += 1;
  }
  const windowTotals = Array.from({ length: numWindows }, (_, index) => rows.reduce((sum, values) => sum + (values[index] ?? 0), 0));
  const busiestFlits = windowTotals.length ? Math.max(...windowTotals) : 0;
  return {
    activeChannels: active.length,
    medianActiveWindows: median(activeCounts),
    twoPhaseChannels: twoPhase,
    busiestWindow: busiestFlits > 0 ? windowTotals.indexOf(busiestFlits) : -1,
    busiestFlits,
    totalFlits: windowTotals.reduce((sum, value) => sum + value, 0),
    numWindows,
  };
}
