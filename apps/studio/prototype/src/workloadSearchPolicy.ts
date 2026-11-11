export type SearchMetric = 'latency' | 'throughput' | 'power' | 'area' | 'energy' | 'routers' | 'crosspoints' | 'storage';
export type SearchRow = {
  id: string; topology: string; status: string; latency: number | null; throughput: number | null;
  power: number | null; area: number | null; energy: number | null; modelId: string | null;
  model?: any; request: Record<string, any>; raw: Record<string, any>; source: string;
  routers: number | null; crosspoints: number | null; storage: number | null;
};
export const searchProfiles = [
  { id: 'balanced', label: 'Balanced', description: 'Trade speed against replay energy and area.', metrics: ['latency', 'throughput', 'energy', 'area'] as SearchMetric[] },
  { id: 'performance', label: 'Performance', description: 'Lowest P95 latency; throughput breaks ties.', metrics: ['latency', 'throughput'] as SearchMetric[] },
  { id: 'efficient', label: 'Efficient', description: 'Lowest replay energy; speed breaks ties.', metrics: ['energy', 'latency', 'throughput'] as SearchMetric[] },
  { id: 'compact', label: 'Compact', description: 'Smallest modeled area; speed breaks ties.', metrics: ['area', 'latency', 'throughput'] as SearchMetric[] },
];
const minimize = new Set<SearchMetric>(['latency', 'power', 'area', 'energy', 'routers', 'crosspoints', 'storage']);
export const finiteValue = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export function searchObservation(row: Record<string, any>, request: Record<string, any>, source: string, index: number): SearchRow {
  const model = row.native_model;
  const modeled = model?.status === 'AVAILABLE' && typeof model.model_id === 'string' && model.model_id.length > 0;
  const get = (v: unknown) => finiteValue(v) ? v : null;
  return {
    id: `${source}:${index}`, topology: row.topology, status: row.status,
    latency: get(row.latency_p95), throughput: get(row.throughput_packets_per_cycle),
    power: modeled ? get(row.native_power_w) : null, area: modeled ? get(row.native_area_mm2) : null,
    energy: modeled ? get(row.total_energy_pj) : null, modelId: modeled ? model.model_id : null,
    model, request, source, raw: row, routers: get(row.resource_cost?.routers),
    crosspoints: get(row.resource_cost?.crosspoints), storage: get(row.resource_cost?.storage_flits),
  };
}
export function constraintFailures(row: SearchRow, limits: Partial<Record<SearchMetric, number | null>>): string[] {
  const failures = [];
  if (row.status !== 'ok') failures.push(`Simulation ${row.status || 'status unavailable'}`);
  if (row.latency === null) failures.push('P95 latency unavailable');
  for (const [metric, limit] of Object.entries(limits) as [SearchMetric, number | null][]) {
    if (limit == null) continue;
    if (!finiteValue(limit)) throw new Error(`Invalid ${metric} limit`);
    const value = row[metric];
    if (value === null) failures.push(`${metric} unavailable for constraint`);
    else if (metric === 'throughput' ? value < limit : value > limit) failures.push(`${metric} limit failed`);
  }
  return failures;
}
function dominates(a: SearchRow, b: SearchRow, metrics: SearchMetric[]) {
  return metrics.every(metric => a[metric] !== null && b[metric] !== null)
    && metrics.every(metric => minimize.has(metric) ? a[metric]! <= b[metric]! : a[metric]! >= b[metric]!)
    && metrics.some(metric => minimize.has(metric) ? a[metric]! < b[metric]! : a[metric]! > b[metric]!);
}
export function recommendSearch(rows: SearchRow[], limits: Partial<Record<SearchMetric, number | null>>) {
  const feasible = rows.filter(row => constraintFailures(row, limits).length === 0);
  return searchProfiles.map(profile => {
    const complete = feasible.filter(row => profile.metrics.every(metric => row[metric] !== null));
    const needsModel = profile.metrics.some(metric => ['energy', 'power', 'area'].includes(metric))
      || Object.entries(limits).some(([metric, limit]) => limit != null && ['energy', 'power', 'area'].includes(metric));
    const modelIds = new Set(complete.map(row => row.modelId));
    if (!complete.length || (needsModel && (modelIds.size !== 1 || modelIds.has(null)))) {
      return { ...profile, winner: null, frontier: [] as SearchRow[], reason: !complete.length ? 'No candidate has all required measurements/models and passes your limits.' : 'Model identities differ or are absent; cost comparisons are not valid.' };
    }
    const frontier = complete.filter(row => !complete.some(other => dominates(other, row, profile.metrics)));
    const ranges = Object.fromEntries(profile.metrics.map(metric => [metric, [Math.min(...frontier.map(row => row[metric]!)), Math.max(...frontier.map(row => row[metric]!))]])) as Record<SearchMetric, [number, number]>;
    const score = (row: SearchRow) => profile.metrics.reduce((sum, metric) => {
      const [low, high] = ranges[metric];
      return sum + (high === low ? 0 : (minimize.has(metric) ? row[metric]! - low : high - row[metric]!) / (high - low));
    }, 0);
    const ranked = [...frontier].sort((a, b) => {
      if (profile.id === 'balanced') return score(a) - score(b) || a.latency! - b.latency! || a.id.localeCompare(b.id);
      for (const metric of profile.metrics) { const delta = minimize.has(metric) ? a[metric]! - b[metric]! : b[metric]! - a[metric]!; if (delta) return delta; }
      return a.id.localeCompare(b.id);
    });
    return { ...profile, winner: ranked[0], frontier, reason: profile.id === 'balanced'
      ? 'Equal-weight normalized latency, throughput, replay energy and area on the feasible non-dominated frontier.'
      : profile.id === 'performance' ? 'Lowest measured P95 latency, then highest throughput. Area and watts are limits, not ranking penalties.'
        : profile.id === 'efficient' ? 'Lowest comparable modeled energy for the full replay, then latency and throughput—not lowest average watts.'
          : 'Smallest comparable modeled area, then latency and throughput. Your limits exclude designs that are too slow.' };
  });
}
export function searchTradeoff(winner: SearchRow | null, reference: SearchRow | null, label: string) {
  if (!winner || !reference) return '';
  if (winner.id === reference.id) return `Same configuration as ${label}.`;
  const notes: string[] = [];
  for (const [metric, name] of [['latency', 'P95 latency'], ['area', 'area'], ['energy', 'replay energy'], ['throughput', 'throughput']] as [SearchMetric, string][]) {
    if (['area', 'energy'].includes(metric) && (!winner.modelId || winner.modelId !== reference.modelId)) continue;
    const value = winner[metric], base = reference[metric]; if (value === null || base === null || base <= 0) continue;
    const ratio = value / base, change = Math.abs(ratio - 1) * 100; if (change < 1) continue;
    notes.push(ratio >= 2 ? `${Number(ratio.toFixed(1))}× ${name}` : `${Math.round(change)}% ${value < base ? 'less' : 'more'} ${name}`);
  }
  return `vs ${label}: ${notes.length ? notes.slice(0, 3).join('; ') : 'no quantified trade-off available'}.`;
}
export function expandSearchGrid(axes: Record<string, (string | number | boolean)[]>, allowed: Set<string>, budget: number, topologyCount: number) {
  if (!Number.isInteger(budget) || budget < 1) throw new Error('Evaluation budget must be a positive integer.');
  let count = topologyCount;
  for (const [key, values] of Object.entries(axes)) {
    if (!allowed.has(key)) throw new Error(`Unsupported knob: ${key}`);
    if (!Array.isArray(values) || !values.length || values.length > 64) throw new Error(`${key} needs 1–64 explicit values.`);
    if (new Set(values.map(String)).size !== values.length) throw new Error(`Duplicate values for ${key}.`);
    if (values.some(value => !['string', 'number', 'boolean'].includes(typeof value) || !/^[A-Za-z0-9_.+-]+$/.test(String(value)))) throw new Error(`Invalid values for ${key}.`);
    if (key === 'vc_buf_size' && values.some(value => !Number.isInteger(value) || Number(value) < 1 || Number(value) > 4096)) throw new Error('Buffer depth must be 1–4096 flits.');
    count *= values.length;
    if (!Number.isSafeInteger(count) || count > budget) throw new Error(`Declared grid exceeds the ${budget}-evaluation budget. Narrow the values; no silent truncation.`);
  }
  if (count > budget) throw new Error('Topology count exceeds the evaluation budget.');
  let grid: Record<string, string | number | boolean>[] = [{}];
  for (const [key, values] of Object.entries(axes)) grid = grid.flatMap(item => values.map(value => ({ ...item, [key]: value })));
  return { grid, count };
}
