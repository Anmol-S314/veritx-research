import { describe, expect, it } from 'vitest';
import { onOperatingFront, operatingPointsFor, type SweepRow } from './analysisCurves';

const row = (topology: string, injection_rate: number, status: string, latency: number | null, accepted = injection_rate): SweepRow => ({
  topology, injection_rate, status, latency_cycles: latency, accepted_rate: accepted,
});

describe('operatingPointsFor', () => {
  it('uses the last steady-state rate, not the first unstable window', () => {
    const points = operatingPointsFor([
      row('mesh', 0.01, 'ok', 20),
      row('mesh', 0.05, 'ok', 24),
      row('mesh', 0.1, 'ok', 40),
      row('mesh', 0.2, 'unstable', 800),
    ]);
    expect(points).toHaveLength(1);
    expect(points[0]).toMatchObject({ topology: 'mesh', rate: 0.1, latency: 40, firstUnstable: 0.2, zeroLoad: 20 });
  });

  it('does not substitute offered load for missing measured throughput', () => {
    const points = operatingPointsFor([{ ...row('mesh', 0.05, 'ok', 24), accepted_rate: null }]);
    expect(points).toEqual([]);
  });

  it('drops rows without numeric latency and arms without a stable window', () => {
    const points = operatingPointsFor([
      row('mesh', 0.01, 'no_output', null),
      row('mesh', 0.02, 'ok', 20),
      row('torus', 0.01, 'unstable', 500),
    ]);
    expect(points.map(point => point.topology)).toEqual(['mesh']);
  });

  it('sorts by accepted throughput', () => {
    const points = operatingPointsFor([
      row('slow', 0.01, 'ok', 20, 0.01),
      row('fast', 0.01, 'ok', 20, 0.12),
    ]);
    expect(points.map(point => point.topology)).toEqual(['slow', 'fast']);
  });
});

describe('onOperatingFront', () => {
  it('keeps a point only when no arm has both more throughput and less latency', () => {
    const points = operatingPointsFor([
      row('wide', 0.15, 'ok', 40, 0.14),
      row('fast-idle', 0.05, 'ok', 18, 0.04),
      row('dominated', 0.1, 'ok', 50, 0.09),
    ]);
    const front = points.filter(point => onOperatingFront(point, points)).map(point => point.topology);
    expect(front).toContain('wide');
    expect(front).toContain('fast-idle');
    expect(front).not.toContain('dominated');
  });

  it('does not treat equal points as dominating each other', () => {
    const points = operatingPointsFor([
      row('a', 0.1, 'ok', 30, 0.09),
      row('b', 0.1, 'ok', 30, 0.09),
    ]);
    expect(points.every(point => onOperatingFront(point, points))).toBe(true);
  });
});
