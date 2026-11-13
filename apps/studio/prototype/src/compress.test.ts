import { describe, expect, it } from 'vitest';
import { groupByValue, listRanges, routerSpan } from './compress';

describe('payload compression', () => {
  it('collapses consecutive ids into ranges and keeps gaps explicit', () => {
    expect(listRanges([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])).toBe('0–11');
    expect(listRanges([0, 1, 3, 4, 7])).toBe('0–1, 3–4, 7');
    expect(listRanges([5, 3, 4, 3])).toBe('3–5');
    expect(listRanges([])).toBe('');
  });

  it('groups identical class bindings instead of repeating every VC', () => {
    const pairs: [number, string][] = Array.from({ length: 12 }, (_, vc) => [vc, 'UNION']);
    expect(groupByValue(pairs)).toBe('0–11 → UNION');
    expect(groupByValue([[0, 'A'], [1, 'A'], [2, 'B']])).toBe('0–1 → A · 2 → B');
    expect(groupByValue([])).toBe('');
  });

  it('prints a tap list as a span only when it is genuinely contiguous', () => {
    expect(routerSpan([1, 2, 3, 4, 5, 6])).toBe('R1–R6');
    expect(routerSpan([0, 7, 14, 21, 28, 35])).toBe('R0 · R7 · R14 · R21 · R28 · R35');
    expect(routerSpan([2, 3])).toBe('R2 · R3');
    expect(routerSpan([])).toBe('—');
  });
});
