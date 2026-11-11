import type { SimSeries } from './gateway';
import type { InjectionSpan } from './trace';
import { packetGroupTotals, type ObservedPacketPath, type ObservedPhaseGroup } from './observedPackets';

export type RunClockBudget = {
  completion: number | null;
  firstInjection: number | null;
  lastInjection: number | null;
  leadIn: number | null;
  injectionSpan: number | null;
  drain: number | null;
  consistent: boolean;
  declaredPackets: number;
  declaredFlits: number;
};

/** Split the completion clock at its two recorded boundaries: the first and
 *  last requested injections from the trace, and the last ejection from the
 *  run stats. The middle span is when traffic was still being offered; the
 *  drain is the interval after the last request. */
export function runClockBudget(span: InjectionSpan | null, completion: number | null | undefined): RunClockBudget {
  const end = typeof completion === 'number' && Number.isFinite(completion) && completion >= 0 ? completion : null;
  if (!span) {
    return {
      completion: end, firstInjection: null, lastInjection: null, leadIn: null,
      injectionSpan: null, drain: null, consistent: true, declaredPackets: 0, declaredFlits: 0,
    };
  }
  const leadIn = span.firstCycle;
  const injectionSpan = span.lastCycle - span.firstCycle;
  const drain = end === null ? null : end - span.lastCycle;
  return {
    completion: end,
    firstInjection: span.firstCycle,
    lastInjection: span.lastCycle,
    leadIn,
    injectionSpan,
    drain,
    consistent: end === null || end >= span.lastCycle,
    declaredPackets: span.total,
    declaredFlits: span.flits,
  };
}

export type FabricWorkBudget = {
  queueCycles: number;
  arbCycles: number;
  txBusyCycles: number;
  occupancy: number;
  flits: number;
  txFlits: number;
  totalWork: number;
  queueShare: number;
  arbShare: number;
  txShare: number;
  channels: number;
  recordedChannels: number;
  windows: number;
  windowCycles: number;
  samplePeriod: number | null;
  hasQueue: boolean;
  hasArb: boolean;
  hasTx: boolean;
};

const sumWindowArray = (series: SimSeries, field: 'queue_cycles_per_window' | 'arb_wait_cycles_per_window' | 'tx_busy_cycles_per_window' | 'tx_flits_per_window' | 'occupancy_flit_cycles_per_window' | 'flits_per_window') => {
  let total = 0, recorded = 0;
  for (const channel of series.channels) {
    const values = channel[field];
    if (!Array.isArray(values)) continue;
    recorded += 1;
    for (const value of values) if (Number.isFinite(value)) total += value;
  }
  return { total, recorded };
};

/** Aggregate measured per-channel counters into one fabric work account. These
 *  are flit-cycle sums, not elapsed cycles: queue, arbitration and transmit
 *  counters measure different events and can overlap. */
export function fabricWorkBudget(series: SimSeries | null | undefined): FabricWorkBudget | null {
  if (!series || !series.channels.length) return null;
  const queue = sumWindowArray(series, 'queue_cycles_per_window');
  const arb = sumWindowArray(series, 'arb_wait_cycles_per_window');
  const tx = sumWindowArray(series, 'tx_busy_cycles_per_window');
  const txFlits = sumWindowArray(series, 'tx_flits_per_window');
  const occupancy = sumWindowArray(series, 'occupancy_flit_cycles_per_window');
  const flits = sumWindowArray(series, 'flits_per_window');
  const totalWork = queue.total + arb.total + tx.total;
  const windowCycles = series.channels.reduce((sum, channel) => sum + (channel.window_cycles ?? []).reduce((inner, value) => inner + (Number.isFinite(value) ? value : 0), 0), 0);
  const recordedChannels = Math.max(queue.recorded, arb.recorded, tx.recorded);
  return {
    queueCycles: queue.total, arbCycles: arb.total, txBusyCycles: tx.total,
    occupancy: occupancy.total, flits: flits.total, txFlits: txFlits.total,
    totalWork,
    queueShare: totalWork ? queue.total / totalWork : 0,
    arbShare: totalWork ? arb.total / totalWork : 0,
    txShare: totalWork ? tx.total / totalWork : 0,
    channels: series.channels.length,
    recordedChannels,
    windows: series.num_windows ?? Math.max(0, ...series.channels.map(channel => channel.flits_per_window?.length ?? 0)),
    windowCycles,
    samplePeriod: series.sample_period_cycles ?? null,
    hasQueue: queue.recorded > 0,
    hasArb: arb.recorded > 0,
    hasTx: tx.recorded > 0,
  };
}

/** A one-window series cannot show a timeline. Name the period that would have
 *  covered this run instead of drawing a single unreadable column. */
export function samplingAdvice(series: SimSeries | null | undefined, completion: number | null | undefined): string | null {
  if (!series || !series.channels.length || typeof completion !== 'number' || completion <= 0) return null;
  const windows = series.num_windows ?? Math.max(0, ...series.channels.map(channel => channel.flits_per_window?.length ?? 0));
  const period = series.sample_period_cycles;
  if (windows > 1 && (period === undefined || period < completion)) return null;
  const suggested = Math.max(10, Math.min(500, Math.round(completion / 64 / 10) * 10));
  return `The sampled series has ${windows} window${windows === 1 ? '' : 's'} for a ${completion.toLocaleString()}-cycle run${period ? ` at ${period.toLocaleString()} cycles/window` : ''}. A period near ${suggested.toLocaleString()} cycles would give roughly ${Math.max(1, Math.floor(completion / suggested))} windows and an actual timeline.`;
}

export type SampledBudget = {
  count: number;
  completeCount: number;
  incompleteCount: number;
  total: number;
  groups: Record<ObservedPhaseGroup, number>;
  shares: Record<ObservedPhaseGroup, number>;
  median: number | null;
  p95: number | null;
  longest: ObservedPacketPath | null;
};

const percentile = (sorted: number[], q: number): number | null => {
  if (!sorted.length) return null;
  const at = (sorted.length - 1) * q;
  const low = Math.floor(at), high = Math.ceil(at);
  return sorted[low] + (sorted[high] - sorted[low]) * (at - low);
};

/** The same five buckets over the bounded watch sample. Only complete paths
 *  enter the totals; a packet with a missing event is counted as incomplete,
 *  never filled with a guessed phase. */
export function sampledBudget(packets: ObservedPacketPath[]): SampledBudget {
  const groups: SampledBudget['groups'] = { source: 0, queue: 0, arbitration: 0, transmission: 0, drain: 0 };
  const complete = packets.filter(path => path.complete && path.total !== null && path.total >= 0);
  const lengths: number[] = [];
  let longest: ObservedPacketPath | null = null;
  for (const path of complete) {
    const totals = packetGroupTotals(path);
    for (const key of Object.keys(groups) as ObservedPhaseGroup[]) groups[key] += totals[key];
    const total = path.total ?? totals.total;
    lengths.push(total);
    if (!longest || total > (longest.total ?? 0)) longest = path;
  }
  lengths.sort((a, b) => a - b);
  const total = lengths.reduce((sum, value) => sum + value, 0);
  const shares = Object.fromEntries((Object.keys(groups) as ObservedPhaseGroup[]).map(key => [key, total ? groups[key] / total : 0])) as Record<ObservedPhaseGroup, number>;
  return {
    count: packets.length,
    completeCount: complete.length,
    incompleteCount: packets.length - complete.length,
    total,
    groups,
    shares,
    median: percentile(lengths, 0.5),
    p95: percentile(lengths, 0.95),
    longest,
  };
}
