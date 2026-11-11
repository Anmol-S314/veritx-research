/** Positive log domain with human-readable 1/2/3/5 ticks, not exponent labels. */
export function chartLogScale(values: number[]) {
  const positive = values.filter(value => Number.isFinite(value) && value > 0);
  const low = positive.length ? Math.min(...positive) * 0.95 : 1;
  const high = positive.length ? Math.max(...positive) * 1.05 : 10;
  const firstPower = Math.floor(Math.log10(low)) - 1;
  const count = Math.ceil(Math.log10(high)) - firstPower + 2;
  const all = Array.from({ length: count }, (_, index) => [1, 2, 3, 5].map(factor => factor * 10 ** (firstPower + index))).flat();
  const min = all.filter(tick => tick <= low).slice(-1)[0] ?? low;
  const max = all.find(tick => tick >= high) ?? high;
  return { min, max, ticks: all.filter(tick => tick >= min && tick <= max) };
}

/** Small, finite data domains with readable ticks; never move the actual points. */
export function chartScale(values: number[], includeZero = false) {
  const finite = values.filter(Number.isFinite);
  let low = finite.length ? Math.min(...finite) : 0;
  let high = finite.length ? Math.max(...finite) : 1;
  if (includeZero) { low = Math.min(0, low); high = Math.max(0, high); }
  const span = high - low || Math.max(Math.abs(high) * 0.2, 0.001);
  const nonnegative = low >= 0;
  low -= span * 0.12; high += span * 0.12;
  if (nonnegative) low = Math.max(0, low);
  const rough = (high - low) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = ([1, 2, 5, 10].find(factor => factor * power >= rough) ?? 10) * power;
  const min = Math.floor(low / step) * step;
  const max = Math.ceil(high / step) * step;
  const ticks = Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => Number((min + i * step).toPrecision(12)));
  return { min, max, ticks, digits: Math.max(0, Math.min(9, -Math.floor(Math.log10(step)))) };
}
