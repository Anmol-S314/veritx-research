/** Readability helpers for enumerated payload values.
 *
 *  A trace-audit payload likes to spell everything out: twelve VC ids, twelve
 *  identical class bindings, six taps per wire. Printing them verbatim turns a
 *  page into a dump, so these collapse the shape without dropping any value.
 */

/** `[0..11]` → `"0–11"`, `[0,1,3]` → `"0, 1, 3"`. */
export function listRanges(values: number[], separator = ', '): string {
  const sorted = [...new Set(values)].sort((a, b) => a - b);
  if (!sorted.length) return '';
  const parts: string[] = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (const value of sorted.slice(1)) {
    if (value === previous + 1) { previous = value; continue; }
    parts.push(start === previous ? String(start) : `${start}–${previous}`);
    start = value;
    previous = value;
  }
  parts.push(start === previous ? String(start) : `${start}–${previous}`);
  return parts.join(separator);
}

/** `[[0,'A'],[1,'A'],[2,'B']]` → `"0–1 → A · 2 → B"`. */
export function groupByValue(pairs: [number, string][], separator = ' · '): string {
  const groups = new Map<string, number[]>();
  for (const [key, value] of pairs) {
    const keys = groups.get(value) ?? [];
    keys.push(key);
    groups.set(value, keys);
  }
  return [...groups].map(([value, keys]) => `${listRanges(keys)} → ${value}`).join(separator);
}

/** `[1,2,3,4,5,6]` → `"R1–R6"`; scattered or long lists stay explicit. */
export function routerSpan(taps: number[]): string {
  if (!taps.length) return '—';
  const sorted = [...new Set(taps)].sort((a, b) => a - b);
  const contiguous = sorted.every((tap, index) => index === 0 || tap === sorted[index - 1] + 1);
  if (sorted.length > 2 && contiguous) return `R${sorted[0]}–R${sorted[sorted.length - 1]}`;
  return sorted.map(tap => `R${tap}`).join(' · ');
}
