import { describe, expect, it } from 'vitest';
import { fabricWorkBudget, runClockBudget, samplingAdvice } from './cycleBudget';
import type { SimSeries } from './gateway';

const span = { total: 12, firstCycle: 0, lastCycle: 400, flits: 300, sources: 4, destinations: 4, dialect: 'Whitespace' as const };

const series: SimSeries = {
  source: 'measured', num_windows: 4, sample_period_cycles: 100,
  channels: [
    {
      logical_channel_id: 0,
      flits_per_window: [1, 2, 0, 0],
      window_cycles: [100, 100, 100, 100],
      queue_cycles_per_window: [5, 10, 0, 0],
      arb_wait_cycles_per_window: [1, 2, 0, 0],
      tx_busy_cycles_per_window: [3, 4, 0, 0],
      tx_flits_per_window: [1, 2, 0, 0],
      occupancy_flit_cycles_per_window: [2, 6, 0, 0],
    },
    {
      logical_channel_id: 1,
      flits_per_window: [0, 1, 1, 0],
      window_cycles: [100, 100, 100, 100],
      queue_cycles_per_window: [0, 3, 0, 0],
      arb_wait_cycles_per_window: null,
      tx_busy_cycles_per_window: [0, 1, 1, 0],
      tx_flits_per_window: [0, 1, 1, 0],
      occupancy_flit_cycles_per_window: null,
    },
  ],
};

describe('cycle budget derivations', () => {
  it('splits the completion clock into injection span and drain', () => {
    const clock = runClockBudget(span, 500);
    expect(clock).toMatchObject({
      completion: 500, firstInjection: 0, lastInjection: 400, leadIn: 0,
      injectionSpan: 400, drain: 100, consistent: true, declaredPackets: 12, declaredFlits: 300,
    });
  });

  it('refuses to pretend a trace that outlasts completion is aligned', () => {
    expect(runClockBudget(span, 350)).toMatchObject({ drain: -50, consistent: false });
    expect(runClockBudget(null, 350)).toMatchObject({ injectionSpan: null, drain: null, consistent: true });
  });

  it('sums the measured work counters without treating missing channels as zero records', () => {
    const work = fabricWorkBudget(series);
    expect(work).not.toBeNull();
    expect(work).toMatchObject({
      queueCycles: 18, arbCycles: 3, txBusyCycles: 9, flits: 5, txFlits: 5,
      occupancy: 8, totalWork: 30, channels: 2, recordedChannels: 2, windows: 4,
      windowCycles: 800, samplePeriod: 100, hasQueue: true, hasArb: true, hasTx: true,
    });
    expect(work!.queueShare).toBeCloseTo(18 / 30, 6);
    expect(work!.arbShare).toBeCloseTo(3 / 30, 6);
    expect(work!.txShare).toBeCloseTo(9 / 30, 6);
  });

  it('flags a series with no timeline and names a usable sampling period', () => {
    const oneWindow: SimSeries = { ...series, num_windows: 1, sample_period_cycles: 10000 };
    const advice = samplingAdvice(oneWindow, 3271);
    expect(advice).toContain('1 window');
    expect(advice).toContain('cycles/window');
    expect(advice).toContain('50 cycles');
    expect(samplingAdvice(series, 3271)).toBeNull();
  });
});
