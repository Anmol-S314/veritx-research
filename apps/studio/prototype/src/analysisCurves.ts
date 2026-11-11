/** Derived views over a topology sweep. Kept out of the page component so the
 *  "last stable operating point" rule can be tested against fixture rows. */

export type SweepRow = {
  topology: string; injection_rate: number; traffic?: string;
  latency_cycles?: number | null; hops_avg?: number | null;
  accepted_rate?: number | null;
  family?: string; routing?: string; num_vcs?: number;
  status?: string | null;
  endpoints?: number; qualification?: string; log?: string;
  routers?: number | null; crosspoints?: number | null; storage_flits?: number | null;
  packet_size_flits?: number; channel_width_bits?: number; vc_buf_size?: number;
  native_power_w?: number | null; native_area_mm2?: number | null; native_energy_pj_per_cycle?: number | null;
  native_model?: {
    status: string; reason?: string; model_id?: string; fidelity?: string;
    technology?: string; clock_hz?: number; clock_rule?: string; channel_width_bits?: number;
    wire_length_mm_per_latency_cycle?: number; tech_source?: string;
    tech_sha256?: string; booksim_sha256?: string; energy_definition?: string; limitations?: string;
  };
};

export type SweepEvidence = { source_path: string; sha256?: string; scope: string; rows: SweepRow[] };

export function parseSweepRows(value: unknown): SweepRow[] {
  if (!Array.isArray(value) || !value.every(row => row && typeof row === 'object'
    && typeof row.topology === 'string' && row.topology.length > 0
    && typeof row.injection_rate === 'number' && Number.isFinite(row.injection_rate) && row.injection_rate >= 0)) {
    throw new Error('Sweep must contain topology names and finite, non-negative injection rates');
  }
  return value;
}

export const SWEEP_METRICS = {
  latency_cycles: { label: 'Packet latency', unit: 'cycles', direction: 'MIN' },
  hops_avg: { label: 'Hops', unit: 'hops/packet', direction: 'MIN' },
  accepted_rate: { label: 'Accepted throughput', unit: 'packets/node/cycle', direction: 'MAX' },
  routers: { label: 'Router count', unit: 'routers', direction: 'MIN' },
  crosspoints: { label: 'Crossbar cost', unit: 'crosspoints', direction: 'MIN' },
  storage_flits: { label: 'Buffer capacity', unit: 'flits', direction: 'MIN' },
  native_power_w: { label: 'Native modeled power', unit: 'W', direction: 'MIN' },
  native_area_mm2: { label: 'Native modeled area', unit: 'mm²', direction: 'MIN' },
  native_energy_pj_per_cycle: { label: 'Native modeled energy/cycle', unit: 'pJ/cycle', direction: 'MIN' },
} as const;
export type SweepMetric = keyof typeof SWEEP_METRICS;
export type SweepLimit = { metric: SweepMetric; op: 'MIN' | 'MAX'; value: number };
export const nativeMetric = (metric: SweepMetric) => metric.startsWith('native_');
export const sweepNumber = (row: SweepRow, metric: SweepMetric): number | null => {
  if (nativeMetric(metric) && (row.native_model?.status !== 'AVAILABLE' || !row.native_model.model_id)) return null;
  const value = row[metric];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
};
export const sweepCohort = (row: SweepRow): string => `${row.traffic ?? 'unspecified traffic'} · ${row.endpoints ?? 'unspecified'} endpoints · ${row.packet_size_flits ?? '?'} flits/packet · ${row.channel_width_bits ?? '?'}-bit flits`;

export function dominatesSweep(a: SweepRow, b: SweepRow, objectives: SweepMetric[]): boolean {
  const comparisons = objectives.map(metric => {
    const av = sweepNumber(a, metric), bv = sweepNumber(b, metric);
    if (av === null || bv === null) return null;
    return SWEEP_METRICS[metric].direction === 'MIN' ? bv - av : av - bv;
  });
  return comparisons.length > 0 && comparisons.every(value => value !== null && value >= 0)
    && comparisons.some(value => value !== null && value > 0);
}

/** Compare observed points at exactly one offered load, within one workload/size
 * cohort. Constraints are exploratory filters, not product qualification. */
export function constrainedSweep(rows: SweepRow[], rate: number, cohort: string,
  objectives: SweepMetric[], limits: SweepLimit[] = []) {
  const scoped = rows.filter(row => sweepCohort(row) === cohort);
  const needsNative = [...objectives, ...limits.map(limit => limit.metric)].some(nativeMetric);
  const modelIds = new Set(scoped.filter(row => row.injection_rate === rate && row.native_model?.status === 'AVAILABLE').map(row => row.native_model?.model_id));
  const candidates = [...new Set(scoped.map(row => row.topology))].map(topology => {
    const arm = scoped.filter(row => row.topology === topology);
    const matches = arm.filter(row => row.injection_rate === rate);
    const row = matches.length === 1 ? matches[0] : null;
    const reasons: string[] = [];
    if (!row) reasons.push(matches.length ? 'Duplicate observations at this load' : 'No observation at this load');
    if (row && row.status !== 'ok') reasons.push(`Not steady-state: ${row.status ?? 'status absent'}`);
    if (row && arm.some(point => point.injection_rate <= rate && point.status === 'unstable')) reasons.push('At or beyond first unstable window');
    if (row) {
      if (needsNative && modelIds.size > 1) reasons.push('Incompatible native technology/binary models at this load');
      if (needsNative && row.native_model?.status !== 'AVAILABLE') reasons.push(row.native_model?.reason ?? 'Native model evidence unavailable');
      for (const metric of objectives) if (sweepNumber(row, metric) === null) reasons.push(`${SWEEP_METRICS[metric].label} unavailable`);
      for (const limit of limits) {
        const value = sweepNumber(row, limit.metric);
        const label = SWEEP_METRICS[limit.metric].label;
        if (value === null) reasons.push(`${label} unavailable for constraint`);
        else if (limit.op === 'MAX' ? value > limit.value : value < limit.value) reasons.push(`${label} ${limit.op === 'MAX' ? 'above' : 'below'} ${limit.value}`);
      }
    }
    return { topology, row, reasons, eligible: reasons.length === 0, front: false };
  });
  for (const point of candidates) {
    if (!point.eligible || !point.row || !objectives.length) continue;
    point.front = !candidates.some(other => {
      if (other === point || !other.eligible || !other.row) return false;
      return dominatesSweep(other.row, point.row!, objectives);
    });
  }
  return candidates;
}

export type OperatingPoint = {
  topology: string; rate: number; accepted: number; latency: number;
  firstUnstable: number | null; zeroLoad: number;
  family: string; routing: string; vcs: number | null; zeroHops: number | null;
};

/** The last offered rate whose window BookSim did not flag `unstable`. Its
 *  accepted rate is a lower bound on saturation throughput, and its latency
 *  is the load-dependent cost of reaching that throughput. The flag is not a
 *  latency SLA, so a point can still be heavily loaded; the table shows the
 *  accepted/offered gap rather than filtering it. */
export function operatingPointsFor(rows: SweepRow[]): OperatingPoint[] {
  const byTopology = new Map<string, SweepRow[]>();
  for (const row of rows) {
    if (sweepNumber(row, 'latency_cycles') === null || !Number.isFinite(row.injection_rate)) continue;
    const list = byTopology.get(row.topology) ?? [];
    list.push(row); byTopology.set(row.topology, list);
  }
  const points: OperatingPoint[] = [];
  for (const [topology, list] of byTopology) {
    const sorted = [...list].sort((a, b) => a.injection_rate - b.injection_rate);
    const unstable = sorted.find(row => row.status === 'unstable');
    const stable = sorted.filter(row => row.status === 'ok' && sweepNumber(row, 'accepted_rate') !== null
      && (!unstable || row.injection_rate < unstable.injection_rate));
    if (stable.length === 0) continue;
    const last = stable[stable.length - 1];
    points.push({
      topology,
      rate: last.injection_rate,
      accepted: last.accepted_rate as number,
      latency: last.latency_cycles as number,
      firstUnstable: unstable ? unstable.injection_rate : null,
      zeroLoad: sorted[0].latency_cycles as number,
      family: last.family ?? '—',
      routing: last.routing ?? '—',
      vcs: typeof last.num_vcs === 'number' ? last.num_vcs : null,
      zeroHops: typeof sorted[0].hops_avg === 'number' ? sorted[0].hops_avg : null,
    });
  }
  return points.sort((a, b) => a.accepted - b.accepted);
}

/** A point dominates another when it carries at least as much throughput at
 *  no more latency. */
export function onOperatingFront(point: OperatingPoint, points: OperatingPoint[]): boolean {
  return !points.some(other => other !== point
    && other.accepted >= point.accepted && other.latency <= point.latency
    && (other.accepted > point.accepted || other.latency < point.latency));
}
