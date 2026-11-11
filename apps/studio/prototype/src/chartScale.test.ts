import { describe, expect, it } from 'vitest';
import { chartLogScale, chartScale } from './chartScale';

describe('chartScale', () => {
  it('fits observed values with finite, readable ticks instead of forcing zero', () => {
    const scale = chartScale([19.3, 19.4, 19.5]);
    expect(scale.min).toBeGreaterThan(0);
    expect(scale.min).toBeLessThan(19.3);
    expect(scale.max).toBeGreaterThan(19.5);
    expect(scale.ticks.length).toBeLessThan(10);
    expect(scale.ticks.every(Number.isFinite)).toBe(true);
  });
  it('can include zero without clipping points', () => {
    const scale = chartScale([0.158104, 0.483687], true);
    expect(scale.min).toBe(0);
    expect(scale.max).toBeGreaterThan(0.483687);
  });
  it('handles empty, singleton, equal and zero-valued observations', () => {
    for (const values of [[], [0], [20], [3, 3], [NaN, Infinity]]) {
      const scale = chartScale(values);
      expect(scale.max).toBeGreaterThan(scale.min);
      expect(scale.ticks.every(Number.isFinite)).toBe(true);
      for (const value of values.filter(Number.isFinite)) {
        expect(value).toBeGreaterThanOrEqual(scale.min);
        expect(value).toBeLessThanOrEqual(scale.max);
      }
    }
  });
  it('keeps logarithmic ticks in raw units and handles equal positive values', () => {
    for (const values of [[23, 163], [20, 20], [], [0, -1, NaN]]) {
      const scale = chartLogScale(values);
      expect(scale.min).toBeGreaterThan(0);
      expect(scale.max).toBeGreaterThan(scale.min);
      expect(scale.ticks.every(value => value >= scale.min && value <= scale.max)).toBe(true);
      for (const value of values.filter(value => Number.isFinite(value) && value > 0)) {
        expect(value).toBeGreaterThan(scale.min);
        expect(value).toBeLessThan(scale.max);
      }
    }
    expect(chartLogScale([23, 163]).ticks).toEqual([20, 30, 50, 100, 200]);
  });
  it('keeps enough precision to distinguish small throughput values', () => {
    const scale = chartScale([0.00473371, 0.00470873]);
    expect(scale.digits).toBeGreaterThanOrEqual(5);
    expect(new Set(scale.ticks.map(value => value.toFixed(scale.digits))).size).toBe(scale.ticks.length);
  });
});
