import { describe, expect, it } from 'vitest';
import { constrainedSweep, parseSweepRows, sweepCohort, type SweepRow } from './analysisCurves';

const point = (topology: string, latency: number, hops: number, throughput: number): SweepRow => ({
  topology, injection_rate: 0.1, status: 'ok', latency_cycles: latency, accepted_rate: throughput,
  hops_avg: hops, traffic: 'uniform', endpoints: 16,
});
const a = point('a', 20, 3, 0.08), b = point('b', 30, 2, 0.09), c = point('c', 40, 4, 0.07);
const cohort = sweepCohort(a);

describe('load-matched constrained Pareto', () => {
  it('computes strict dominance and keeps ties', () => {
    const result = constrainedSweep([a, b, c, { ...a, topology: 'tie' }], 0.1, cohort, ['latency_cycles', 'hops_avg']);
    expect(result.filter(p => p.front).map(p => p.topology)).toEqual(['a', 'b', 'tie']);
  });
  it('applies constraints before dominance and maximizes throughput', () => {
    const result = constrainedSweep([a, b, c], 0.1, cohort, ['latency_cycles', 'accepted_rate'], [
      { metric: 'latency_cycles', op: 'MAX', value: 30 },
      { metric: 'accepted_rate', op: 'MIN', value: 0.085 },
    ]);
    expect(result.filter(p => p.front).map(p => p.topology)).toEqual(['b']);
    expect(result.find(p => p.topology === 'a')?.reasons).toContain('Accepted throughput below 0.085');
  });
  it('keeps unavailable constraints, unstable and failed arms out of the front', () => {
    const result = constrainedSweep([a, { ...b, status: 'unstable' }, { ...c, status: 'timeout' }], 0.1, cohort,
      ['latency_cycles', 'hops_avg'], [{ metric: 'crosspoints', op: 'MAX', value: 1000 }]);
    expect(result.every(p => !p.eligible && !p.front)).toBe(true);
    expect(result[0].reasons).toContain('Crossbar cost unavailable for constraint');
  });
  it('never compares different rates, endpoint counts or traffic, or imputes accepted rate', () => {
    const result = constrainedSweep([
      a, { ...b, injection_rate: 0.2 }, { ...c, endpoints: 64 },
      { ...c, topology: 'other-traffic', traffic: 'transpose' },
      { ...a, topology: 'missing-throughput', accepted_rate: null },
    ], 0.1, cohort, ['latency_cycles', 'accepted_rate']);
    expect(result.map(p => p.topology)).toEqual(['a', 'b', 'missing-throughput']);
    expect(result.filter(p => p.front).map(p => p.topology)).toEqual(['a']);
    expect(result[1].reasons).toContain('No observation at this load');
  });
  it('refuses duplicate observations and points beyond first instability', () => {
    const result = constrainedSweep([a, a, b, { ...b, injection_rate: 0.05, status: 'unstable' }], 0.1, cohort, ['latency_cycles', 'hops_avg']);
    expect(result.every(p => !p.front)).toBe(true);
    expect(result[0].reasons).toContain('Duplicate observations at this load');
    expect(result[1].reasons).toContain('At or beyond first unstable window');
  });
  it('uses additional objectives, not only the two plotted axes', () => {
    const rows = [a, b, { ...c, accepted_rate: 0.099 }];
    expect(constrainedSweep(rows, 0.1, cohort, ['latency_cycles', 'hops_avg']).filter(p => p.front)).toHaveLength(2);
    expect(constrainedSweep(rows, 0.1, cohort, ['latency_cycles', 'hops_avg', 'accepted_rate']).filter(p => p.front)).toHaveLength(3);
  });
  it('uses only available native evidence and excludes unsupported candidates', () => {
    const modeled = { ...a, native_area_mm2: 0.2, native_model: { status: 'AVAILABLE', model_id: 'm1' } };
    const unsupported = { ...b, native_area_mm2: 0.01, native_model: { status: 'UNSUPPORTED', reason: 'Shared-wire accounting absent' } };
    const result = constrainedSweep([modeled, unsupported], 0.1, cohort, ['latency_cycles', 'native_area_mm2']);
    expect(result.filter(p => p.front).map(p => p.topology)).toEqual(['a']);
    expect(result[1].reasons).toContain('Shared-wire accounting absent');
    expect(constrainedSweep([modeled], 0.1, cohort, ['latency_cycles', 'hops_avg'], [{ metric: 'native_area_mm2', op: 'MAX', value: 0.1 }])[0].eligible).toBe(false);
  });
  it('refuses native comparisons between different model identities', () => {
    const rows = [a, b].map((row, index) => ({ ...row, native_area_mm2: 0.2, native_model: { status: 'AVAILABLE', model_id: `m${index}` } }));
    expect(constrainedSweep(rows, 0.1, cohort, ['latency_cycles', 'native_area_mm2']).every(p => !p.eligible)).toBe(true);
  });
  it('does not mix different packet or flit widths', () => {
    const rows = [{ ...a, packet_size_flits: 5, channel_width_bits: 128 }, { ...b, packet_size_flits: 1, channel_width_bits: 128 }, { ...c, packet_size_flits: 5, channel_width_bits: 64 }];
    expect(constrainedSweep(rows, 0.1, sweepCohort(rows[0]), ['latency_cycles', 'hops_avg'])).toHaveLength(1);
  });
  it('rejects malformed input and does not plot non-finite or negative metrics', () => {
    expect(() => parseSweepRows([null])).toThrow();
    expect(() => parseSweepRows([{ topology: 'a', injection_rate: Infinity }])).toThrow();
    expect(constrainedSweep([{ ...a, hops_avg: NaN }, { ...b, hops_avg: -1 }], 0.1, cohort, ['latency_cycles', 'hops_avg']).every(p => !p.front)).toBe(true);
  });
});
