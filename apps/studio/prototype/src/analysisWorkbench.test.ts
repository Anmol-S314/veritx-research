import { describe, expect, it } from 'vitest';
import { genericFront, requirementMargin, type WorkbenchMetric, type WorkbenchObservation } from './analysisWorkbench';

const metrics = new Map<string, WorkbenchMetric>([
  ['latency', { key: 'latency', label: 'Latency', direction: 'MIN' }],
  ['hops', { key: 'hops', label: 'Hops', direction: 'MIN' }],
  ['throughput', { key: 'throughput', label: 'Throughput', direction: 'MAX' }],
  ['order', { key: 'order', label: 'Order' }],
]);
const observation = (id: string, values: Record<string, number>, excluded?: string): WorkbenchObservation => ({ id, label: id, values, excluded });

describe('genericFront', () => {
  it('uses the plotted objectives and keeps equal observations', () => {
    const points = [
      observation('a', { latency: 20, hops: 3 }),
      observation('b', { latency: 30, hops: 2 }),
      observation('c', { latency: 40, hops: 4 }),
      observation('tie', { latency: 20, hops: 3 }),
    ];
    expect(genericFront(points, metrics, ['latency', 'hops'])).toEqual(['a', 'b', 'tie']);
  });

  it('maximizes throughput and excludes observations that are not plotted', () => {
    const points = [
      observation('a', { latency: 20, throughput: 0.08 }),
      observation('b', { latency: 20, throughput: 0.09 }),
      observation('failed', { latency: 20, throughput: 0.2 }, 'Not steady-state'),
    ];
    expect(genericFront(points, metrics, ['latency', 'throughput'])).toEqual(['b']);
  });

  it('does not invent a front when an objective has no direction', () => {
    const points = [observation('a', { latency: 20, order: 1 }), observation('b', { latency: 30, order: 2 })];
    expect(genericFront(points, metrics, ['latency', 'order'])).toEqual([]);
  });
});

describe('requirementMargin', () => {
  it('computes ceiling headroom', () => {
    const margin = requirementMargin({ measured: 4676, required: 50000, verdict: 'SATISFIED', reason: 'measured 4676 cycles <= ceiling 50000 cycles' });
    expect(margin?.direction).toBe('MAX_ALLOWED');
    expect(margin?.headroomPercent).toBeCloseTo(90.648, 3);
  });

  it('computes floor headroom', () => {
    const margin = requirementMargin({ measured: 12, required: 10, verdict: 'SATISFIED', reason: 'measured 12 GB/s >= floor 10 GB/s' });
    expect(margin?.direction).toBe('MIN_REQUIRED');
    expect(margin?.headroomPercent).toBeCloseTo(20, 3);
  });

  it('returns no margin for a missing or directionless requirement', () => {
    expect(requirementMargin({ measured: 1, required: 2 })).toBeNull();
    expect(requirementMargin({ measured: 1, required: null, reason: 'measured 1 <= ceiling 2' })).toBeNull();
    expect(requirementMargin({ measured: 1, required: 0, reason: 'measured 1 <= ceiling 0' })).toBeNull();
  });
});
