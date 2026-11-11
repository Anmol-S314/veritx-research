/** Constrained fabric advisor over the prototype's measured evidence.
 *
 *  Two evidence tiers are deliberately kept apart:
 *   - workload performance is measured BookSim trace replay at 64 endpoints;
 *   - power and area are the native BookSim 32nm model at a 16-endpoint
 *     reference, linearly scaled by endpoint count for screening only.
 *
 *  The advisor never turns an unavailable metric into a zero. A constraint on
 *  an unavailable metric excludes that candidate instead of silently passing
 *  it. Link/flit width is not varied by the measured sweep, so it is reported
 *  as a declared input and never presented as an optimized value.
 */
import type { SweepRow } from './analysisCurves';

export type AdvisorWorkload = {
  id: string;
  label: string;
  project: string | null;
  nodes: number;
  events: number | null;
  activeNodes: number | null;
  traceSha256: string | null;
};

export type AdvisorArm = {
  workload: string;
  workloadLabel: string;
  topology: string;
  topologyLabel: string;
  family: string;
  nodes: number;
  vcs: number | null;
  routing: string;
  support: string;
  latencyMean: number;
  latencyP95: number;
  latencyP99: number | null;
  throughput: number;
  hopsAvg: number | null;
  completionCycles: number | null;
  routers: number | null;
  crosspoints: number | null;
  storageFlits: number | null;
  traceSha256: string | null;
  binarySha256: string | null;
  simulatorSeed: number | null;
};

export type AdvisorEvidence = { workloads: AdvisorWorkload[]; arms: AdvisorArm[]; skipped: number };

export type SensitivityPoint = {
  workload: string;
  topology: string;
  depth: number;
  latencyMean: number;
  latencyP95: number;
  latencyP99: number | null;
  throughput: number;
  completionCycles: number | null;
  hopsAvg: number | null;
  storageFlits: number | null;
  routers: number | null;
  traceSha256: string | null;
  binarySha256: string | null;
  simulatorSeed: number | null;
  source: string;
};

export type SensitivityEvidence = {
  scope: string;
  common: Record<string, unknown>;
  points: SensitivityPoint[];
  skipped: number;
};

export type FabricModel = {
  family: string;
  referenceTopology: string;
  referenceEndpoints: number;
  referenceRouters: number;
  referenceLoad: number;
  powerW: number;
  areaMm2: number;
  powerPerEndpointW: number;
  areaPerEndpointMm2: number;
  modelId: string | null;
  technology: string | null;
  limitations: string | null;
};

export type DepthVariant = {
  depth: number;
  latencyMean: number;
  latencyP95: number;
  latencyP99: number | null;
  throughput: number;
  completionCycles: number | null;
  storageFlits: number | null;
  measured: boolean;
  traceSha256: string | null;
  binarySha256: string | null;
  simulatorSeed: number | null;
  identityVerified: boolean;
  identityNote: string | null;
  source: string;
};

export type ConstraintKey = 'maxLatencyP95' | 'minThroughput' | 'maxPowerW' | 'maxAreaMm2' | 'maxStorageFlits';
export type Priority = 'latency' | 'throughput' | 'power' | 'area' | 'balanced';

export type AdvisorConstraints = Record<ConstraintKey, number | null> & { includeResearch: boolean };

export type ConstraintVerdict = {
  key: ConstraintKey;
  label: string;
  op: '≤' | '≥';
  limit: number;
  value: number | null;
  pass: boolean;
  authority: 'MEASURED' | 'MODELED' | 'UNAVAILABLE';
  detail: string;
};

export type AdvisorCandidate = {
  id: string;
  arm: AdvisorArm;
  depth: number;
  depthReason: string;
  latencyMean: number;
  latencyP95: number;
  latencyP99: number | null;
  throughput: number;
  storageFlits: number | null;
  powerW: number | null;
  areaMm2: number | null;
  powerFormula: string | null;
  areaFormula: string | null;
  verdicts: ConstraintVerdict[];
  feasible: boolean;
  pareto: boolean;
  rank: number | null;
  score: number | null;
};

export type AdvisorResult = {
  medianLoad: number;
  referenceLoad: number;
  models: Map<string, FabricModel>;
  candidates: AdvisorCandidate[];
  ranked: AdvisorCandidate[];
  excluded: AdvisorCandidate[];
  paretoIds: Set<string>;
  winner: AdvisorCandidate | null;
  runnerUp: AdvisorCandidate | null;
  sensitivity: SensitivityNote[];
};

export type SensitivityNote = {
  key: ConstraintKey;
  label: string;
  op: '≤' | '≥';
  threshold: number;
  winnerId: string;
  winnerLabel: string;
  basis: string;
};

export const CONSTRAINT_LABELS: Record<ConstraintKey, string> = {
  maxLatencyP95: 'P95 packet latency',
  minThroughput: 'Delivered throughput',
  maxPowerW: 'Modeled power',
  maxAreaMm2: 'Modeled area',
  maxStorageFlits: 'Buffer storage',
};

export const CONSTRAINT_UNITS: Record<ConstraintKey, string> = {
  maxLatencyP95: 'cycles',
  minThroughput: 'packets/cycle',
  maxPowerW: 'W',
  maxAreaMm2: 'mm²',
  maxStorageFlits: 'flits',
};

export const PRIORITY_LABELS: Record<Priority, string> = {
  latency: 'Lowest P95 latency',
  throughput: 'Highest delivered throughput',
  power: 'Lowest modeled power',
  area: 'Lowest modeled area',
  balanced: 'Balanced (normalized ideal point)',
};

export const PRIORITY_HELP: Record<Priority, string> = {
  latency: 'Rank by measured P95 packet latency; break ties with throughput.',
  throughput: 'Rank by measured delivered packets/cycle; break ties with P95 latency.',
  power: 'Rank by endpoint-scaled native-model power; break ties with P95 latency.',
  area: 'Rank by endpoint-scaled native-model area; break ties with P95 latency.',
  balanced: 'Use measured latency/throughput and modeled power/area with equal normalized weight. The Pareto front is shown separately.',
};

const COMMON_LOADS = [0.005, 0.01, 0.02, 0.03, 0.05, 0.07, 0.1, 0.15];
const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const finitePositive = (value: unknown): number | null => {
  const number = finite(value);
  return number !== null && number >= 0 ? number : null;
};
const text = (value: unknown): string => typeof value === 'string' ? value : '';
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

export function parseAdvisorEvidence(value: unknown): AdvisorEvidence {
  const document = record(value);
  if (!Array.isArray(document.runs) || !Array.isArray(document.workloads)) {
    throw new Error('Workload evidence must carry runs and workloads arrays.');
  }
  const workloads = document.workloads.flatMap(raw => {
    const row = record(raw);
    const id = text(row.workload_id);
    if (!id) return [];
    return [{
      id,
      label: text(row.label) || id,
      project: text(row.project) || null,
      nodes: finite(row.nodes) ?? 0,
      events: finite(row.events),
      activeNodes: finite(row.active_nodes),
      traceSha256: text(row.trace_sha256) || null,
    }];
  });
  const supports = new Map<string, string>();
  if (Array.isArray(document.topologies)) {
    for (const raw of document.topologies) {
      const row = record(raw);
      if (text(row.topology_id)) supports.set(text(row.topology_id), text(row.support) || 'not reported');
    }
  }
  let skipped = 0;
  const arms = document.runs.flatMap(raw => {
    const row = record(raw);
    const latencyMean = finite(row.latency_mean);
    const latencyP95 = finite(row.latency_p95);
    const throughput = finite(row.throughput_packets_per_cycle);
    const cost = record(row.resource_cost);
    if (row.status !== 'ok' || !text(row.workload) || !text(row.topology)
      || latencyMean === null || latencyP95 === null || throughput === null
      || latencyMean < 0 || latencyP95 < 0 || throughput < 0) {
      skipped += 1;
      return [];
    }
    return [{
      workload: text(row.workload),
      workloadLabel: text(row.workload_label) || text(row.workload),
      topology: text(row.topology),
      topologyLabel: text(row.topology_label) || text(row.topology),
      family: text(row.family) || 'not reported',
      nodes: finite(row.nodes) ?? 0,
      vcs: finite(row.vcs),
      routing: text(row.routing) || 'not reported',
      support: supports.get(text(row.topology)) ?? 'not reported',
      latencyMean,
      latencyP95,
      latencyP99: finite(row.latency_p99),
      throughput,
      hopsAvg: finite(row.hops_avg),
      completionCycles: finite(row.completion_cycles),
      routers: finite(cost.routers),
      crosspoints: finite(cost.crosspoints),
      storageFlits: finite(cost.storage_flits),
      traceSha256: text(row.trace_sha256) || null,
      binarySha256: text(row.binary_sha256) || null,
      simulatorSeed: finite(row.simulator_seed),
    }];
  });
  if (!workloads.length || !arms.length) throw new Error('Workload evidence has no comparable measured cell.');
  return { workloads, arms, skipped };
}

export function parseSensitivity(value: unknown): SensitivityEvidence {
  const document = record(value);
  if (!Array.isArray(document.points)) throw new Error('Buffer sensitivity must carry a points array.');
  let skipped = 0;
  const points = document.points.flatMap(raw => {
    const row = record(raw);
    const depth = finite(row.depth);
    const latencyMean = finite(row.latency_mean);
    const latencyP95 = finite(row.latency_p95);
    const throughput = finite(row.throughput);
    if (!text(row.workload) || !text(row.topology) || depth === null
      || latencyMean === null || latencyP95 === null || throughput === null
      || depth < 1 || latencyMean < 0 || latencyP95 < 0 || throughput < 0) {
      skipped += 1;
      return [];
    }
    return [{
      workload: text(row.workload),
      topology: text(row.topology),
      depth,
      latencyMean,
      latencyP95,
      latencyP99: finite(row.latency_p99),
      throughput,
      completionCycles: finite(row.completion_cycles),
      hopsAvg: finite(row.hops_avg),
      storageFlits: finite(row.storage_flits),
      routers: finite(row.routers),
      traceSha256: text(row.trace_sha256) || null,
      binarySha256: text(row.binary_sha256) || null,
      simulatorSeed: finite(row.simulator_seed),
      source: text(row.source) || 'measured',
    }];
  });
  return { scope: text(document.scope), common: record(document.common), points, skipped };
}

/** Match the project's declared workload to a measured trace. The project id is
 *  not an evidence identity, so this is a transparent text match with a user
 *  override on the page. It never invents a trace. */
export function matchWorkload(workloads: AdvisorWorkload[], hints: (string | null | undefined)[]): string {
  if (!workloads.length) return '';
  const normalizedHints = hints.filter((hint): hint is string => typeof hint === 'string' && hint.trim().length > 0)
    .map(normalize);
  let best = { id: workloads[0].id, score: -1 };
  for (const workload of workloads) {
    const haystacks = [normalize(workload.id), normalize(workload.label), normalize(workload.project ?? '')];
    let score = 0;
    for (const hint of normalizedHints) {
      for (const hay of haystacks) {
        if (!hay) continue;
        if (hay === hint) score += 100;
        else if (hay.includes(hint) || hint.includes(hay)) score += 20;
        else score += sharedTokens(hint, hay) * 4;
      }
    }
    if (score > best.score) best = { id: workload.id, score };
  }
  return best.id;
}

const normalize = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const tokens = (value: string): string[] => normalize(value).split(' ').filter(token => token.length >= 2);
function sharedTokens(a: string, b: string): number {
  const right = new Set(tokens(b));
  return new Set(tokens(a).filter(token => right.has(token))).size;
}

/** Median delivered load across measured arms, expressed as packets/node/cycle.
 *  The sweep's offered-load axis uses the same unit, so the nearest common
 *  sweep load is a transparent place to read the native model. */
export function workloadReferenceLoad(arms: AdvisorArm[]): { median: number; load: number } {
  const loads = arms.map(arm => arm.nodes > 0 ? arm.throughput / arm.nodes : NaN)
    .filter(value => Number.isFinite(value) && value > 0).sort((a, b) => a - b);
  if (!loads.length) return { median: 0, load: COMMON_LOADS[0] };
  const median = loads[Math.floor(loads.length / 2)];
  const load = COMMON_LOADS.reduce((closest, candidate) =>
    Math.abs(candidate - median) < Math.abs(closest - median) ? candidate : closest, COMMON_LOADS[0]);
  return { median, load };
}

/** Native-model family references at one common offered load. Values are kept
 *  per endpoint so a 16-endpoint reference can be compared with a 64-endpoint
 *  measured arm without pretending the model ran at that size. */
export function fabricModels(rows: SweepRow[], load: number): Map<string, FabricModel> {
  const grouped = new Map<string, SweepRow[]>();
  for (const row of rows) {
    if (row.native_model?.status !== 'AVAILABLE' || row.status !== 'ok') continue;
    if (finitePositive(row.native_power_w) === null || finitePositive(row.native_area_mm2) === null) continue;
    const family = row.family ?? 'not reported';
    const list = grouped.get(family) ?? [];
    list.push(row);
    grouped.set(family, list);
  }
  const models = new Map<string, FabricModel>();
  for (const [family, rowsForFamily] of grouped) {
    const chosen = [...rowsForFamily].sort((a, b) => {
      const loadDelta = Math.abs(a.injection_rate - load) - Math.abs(b.injection_rate - load);
      if (loadDelta !== 0) return loadDelta;
      return a.topology.localeCompare(b.topology);
    })[0];
    const power = finitePositive(chosen.native_power_w);
    const area = finitePositive(chosen.native_area_mm2);
    const endpoints = finitePositive(chosen.endpoints);
    const routers = finitePositive(chosen.routers);
    if (power === null || area === null || !endpoints || endpoints <= 0 || !routers || routers <= 0) continue;
    models.set(family, {
      family,
      referenceTopology: chosen.topology,
      referenceEndpoints: endpoints,
      referenceRouters: routers,
      referenceLoad: chosen.injection_rate,
      powerW: power,
      areaMm2: area,
      powerPerEndpointW: power / endpoints,
      areaPerEndpointMm2: area / endpoints,
      modelId: chosen.native_model?.model_id ?? null,
      technology: chosen.native_model?.technology ?? null,
      limitations: chosen.native_model?.limitations ?? null,
    });
  }
  return models;
}

/** One row per topology, with the depth variants measured for that workload.
 *  A depth point is only usable when trace, simulator binary and seed match the
 *  reference arm. A mismatch falls back to the reference depth instead of
 *  mixing two experiments into one recommendation. */
export function depthVariants(arm: AdvisorArm, sensitivity: SensitivityEvidence | null): DepthVariant[] {
  const reference: DepthVariant = {
    depth: 8,
    latencyMean: arm.latencyMean,
    latencyP95: arm.latencyP95,
    latencyP99: arm.latencyP99,
    throughput: arm.throughput,
    completionCycles: arm.completionCycles,
    storageFlits: arm.storageFlits,
    measured: false,
    traceSha256: arm.traceSha256,
    binarySha256: arm.binarySha256,
    simulatorSeed: arm.simulatorSeed,
    identityVerified: false,
    identityNote: null,
    source: 'reference arm; depth sweep not measured for this topology',
  };
  const points = (sensitivity?.points ?? []).filter(point =>
    point.workload === arm.workload && point.topology === arm.topology);
  if (!points.length) return [reference];
  const issues: string[] = [];
  for (const point of points) {
    if (!point.traceSha256 || !arm.traceSha256 || point.traceSha256 !== arm.traceSha256) {
      issues.push(`depth ${point.depth}: trace identity does not match the reference arm`);
    }
    if (!point.binarySha256 || !arm.binarySha256 || point.binarySha256 !== arm.binarySha256) {
      issues.push(`depth ${point.depth}: simulator binary does not match the reference arm`);
    }
    if (point.simulatorSeed === null || arm.simulatorSeed === null || point.simulatorSeed !== arm.simulatorSeed) {
      issues.push(`depth ${point.depth}: simulator seed does not match the reference arm`);
    }
  }
  if (issues.length) {
    return [{ ...reference, identityNote: issues[0], source: `Depth slice rejected: ${issues[0]}` }];
  }
  const byDepth = new Map<number, SensitivityPoint>();
  for (const point of points) if (!byDepth.has(point.depth)) byDepth.set(point.depth, point);
  return [...byDepth.values()].sort((a, b) => a.depth - b.depth).map(point => ({
    depth: point.depth,
    latencyMean: point.latencyMean,
    latencyP95: point.latencyP95,
    latencyP99: point.latencyP99,
    throughput: point.throughput,
    completionCycles: point.completionCycles,
    storageFlits: point.storageFlits,
    measured: true,
    traceSha256: point.traceSha256,
    binarySha256: point.binarySha256,
    simulatorSeed: point.simulatorSeed,
    identityVerified: true,
    identityNote: null,
    source: point.source,
  }));
}

function depthScore(variant: DepthVariant, baseline: DepthVariant | null, priority: Priority): number {
  if (!baseline) return 0;
  const latency = baseline.latencyP95 > 0 ? variant.latencyP95 / baseline.latencyP95 : 1;
  const throughput = baseline.throughput > 0 ? baseline.throughput / Math.max(1e-12, variant.throughput) : 1;
  if (priority === 'latency') return latency;
  if (priority === 'throughput') return throughput;
  if (priority === 'power' || priority === 'area') {
    // Buffer depth is the only buffer-cost axis measured here. Keep a shallow
    // buffer only when it stays within 1% of the reference performance.
    const acceptable = variant.latencyP95 <= baseline.latencyP95 * 1.01
      && variant.throughput >= baseline.throughput * 0.99;
    return acceptable ? variant.depth : 100 + variant.depth;
  }
  return (latency + throughput) / 2;
}

export function selectDepth(variants: DepthVariant[], priority: Priority, constraints: AdvisorConstraints): { variant: DepthVariant; reason: string } {
  const baseline = variants.find(variant => variant.depth === 8) ?? variants[0];
  const satisfies = (variant: DepthVariant): boolean =>
    (constraints.maxLatencyP95 === null || variant.latencyP95 <= constraints.maxLatencyP95)
    && (constraints.minThroughput === null || variant.throughput >= constraints.minThroughput)
    && (constraints.maxStorageFlits === null || (variant.storageFlits !== null && variant.storageFlits <= constraints.maxStorageFlits));
  const allowed = variants.filter(satisfies);
  const violationCount = (variant: DepthVariant): number =>
    (constraints.maxLatencyP95 === null || variant.latencyP95 <= constraints.maxLatencyP95 ? 0 : 1)
    + (constraints.minThroughput === null || variant.throughput >= constraints.minThroughput ? 0 : 1)
    + (constraints.maxStorageFlits === null || (variant.storageFlits !== null && variant.storageFlits <= constraints.maxStorageFlits) ? 0 : 1);
  const pool = allowed.length ? allowed : variants;
  const selected = [...pool].sort((a, b) =>
    violationCount(a) - violationCount(b)
    || depthScore(a, baseline, priority) - depthScore(b, baseline, priority)
    || a.depth - b.depth)[0] ?? baseline;
  const delta = baseline && baseline.latencyP95 > 0
    ? (baseline.latencyP95 - selected.latencyP95) / baseline.latencyP95 * 100
    : 0;
  const throughputDelta = baseline && baseline.throughput > 0
    ? (selected.throughput - baseline.throughput) / baseline.throughput * 100
    : 0;
  if (!selected.measured) {
    return { variant: selected, reason: 'Depth 8 is the reference arm; no depth sweep is available for this topology.' };
  }
  if (selected.depth === 8) {
    const reason = priority === 'power' || priority === 'area'
      ? 'Depth 8 keeps measured P95 within 1% and throughput within 1% of the reference; shallower buffers did not meet that screening rule. The buffer power/area benefit is not measured.'
      : `Depth 8 remains the measured reference for ${PRIORITY_LABELS[priority].toLowerCase()}.`;
    return { variant: selected, reason };
  }
  const direction = delta >= 0 ? `${delta.toFixed(1)}% lower P95` : `${Math.abs(delta).toFixed(1)}% higher P95`;
  const throughputText = Math.abs(throughputDelta) < 0.05 ? 'throughput unchanged' : `${throughputDelta > 0 ? '+' : ''}${throughputDelta.toFixed(1)}% throughput`;
  return {
    variant: selected,
    reason: `Depth ${selected.depth} flits/VC is measured at ${direction} and ${throughputText} versus depth 8.`,
  };
}

export function estimatePower(model: FabricModel | undefined, endpoints: number): { value: number | null; formula: string | null } {
  if (!model || !Number.isFinite(endpoints) || endpoints <= 0) return { value: null, formula: null };
  return {
    value: model.powerPerEndpointW * endpoints,
    formula: `${model.powerW.toFixed(3)} W × ${endpoints}/${model.referenceEndpoints} endpoints = ${(model.powerPerEndpointW * endpoints).toFixed(2)} W`,
  };
}

export function estimateArea(model: FabricModel | undefined, endpoints: number): { value: number | null; formula: string | null } {
  if (!model || !Number.isFinite(endpoints) || endpoints <= 0) return { value: null, formula: null };
  return {
    value: model.areaPerEndpointMm2 * endpoints,
    formula: `${model.areaMm2.toFixed(4)} mm² × ${endpoints}/${model.referenceEndpoints} endpoints = ${(model.areaPerEndpointMm2 * endpoints).toFixed(3)} mm²`,
  };
}

export function buildCandidates(
  arms: AdvisorArm[],
  models: Map<string, FabricModel>,
  sensitivity: SensitivityEvidence | null,
  constraints: AdvisorConstraints,
  priority: Priority,
): AdvisorCandidate[] {
  return arms.map(arm => {
    const variants = depthVariants(arm, sensitivity);
    const selected = selectDepth(variants, priority, constraints);
    const model = models.get(arm.family);
    const power = estimatePower(model, arm.nodes);
    const area = estimateArea(model, arm.nodes);
    const candidate: AdvisorCandidate = {
      id: `${arm.topology}@${selected.variant.depth}`,
      arm,
      depth: selected.variant.depth,
      depthReason: selected.reason,
      latencyMean: selected.variant.latencyMean,
      latencyP95: selected.variant.latencyP95,
      latencyP99: selected.variant.latencyP99,
      throughput: selected.variant.throughput,
      storageFlits: selected.variant.storageFlits,
      powerW: power.value,
      areaMm2: area.value,
      powerFormula: power.formula,
      areaFormula: area.formula,
      verdicts: [],
      feasible: true,
      pareto: false,
      rank: null,
      score: null,
    };
    candidate.verdicts = constraintVerdicts(candidate, constraints);
    candidate.feasible = candidate.verdicts.every(verdict => verdict.pass);
    return candidate;
  });
}

export function constraintVerdicts(candidate: AdvisorCandidate, constraints: AdvisorConstraints): ConstraintVerdict[] {
  const rows: ConstraintVerdict[] = [];
  const add = (
    key: ConstraintKey, op: '≤' | '≥', limit: number | null,
    value: number | null, authority: ConstraintVerdict['authority'],
    detail: string,
  ) => {
    if (limit === null) return;
    rows.push({
      key, label: CONSTRAINT_LABELS[key], op, limit, value,
      pass: value !== null && (op === '≤' ? value <= limit : value >= limit),
      authority: value === null ? 'UNAVAILABLE' : authority,
      detail: value === null ? detail : '',
    });
  };
  add('maxLatencyP95', '≤', constraints.maxLatencyP95,
    candidate.latencyP95, 'MEASURED', 'No measured P95 latency for this arm.');
  add('minThroughput', '≥', constraints.minThroughput,
    candidate.throughput, 'MEASURED', 'No measured delivered throughput for this arm.');
  add('maxPowerW', '≤', constraints.maxPowerW,
    candidate.powerW, 'MODELED', 'No native-model family reference covers this fabric.');
  add('maxAreaMm2', '≤', constraints.maxAreaMm2,
    candidate.areaMm2, 'MODELED', 'No native-model family reference covers this fabric.');
  add('maxStorageFlits', '≤', constraints.maxStorageFlits,
    candidate.storageFlits, 'MEASURED', 'Declared buffer storage is unavailable for this arm.');
  return rows;
}

type Objective = { key: 'latencyP95' | 'throughput' | 'powerW' | 'areaMm2' | 'storageFlits'; direction: 'MIN' | 'MAX' };

function objectivesFor(priority: Priority): Objective[] {
  switch (priority) {
    case 'throughput': return [{ key: 'throughput', direction: 'MAX' }, { key: 'latencyP95', direction: 'MIN' }];
    case 'power': return [{ key: 'powerW', direction: 'MIN' }, { key: 'latencyP95', direction: 'MIN' }];
    case 'area': return [{ key: 'areaMm2', direction: 'MIN' }, { key: 'latencyP95', direction: 'MIN' }];
    case 'balanced': return [
      { key: 'latencyP95', direction: 'MIN' }, { key: 'throughput', direction: 'MAX' },
      { key: 'powerW', direction: 'MIN' }, { key: 'areaMm2', direction: 'MIN' },
    ];
    default: return [{ key: 'latencyP95', direction: 'MIN' }, { key: 'throughput', direction: 'MAX' }];
  }
}

const objectiveValue = (candidate: AdvisorCandidate, key: Objective['key']): number | null => {
  const value = key === 'powerW' ? candidate.powerW : key === 'areaMm2' ? candidate.areaMm2 : candidate[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
};

function dominates(a: AdvisorCandidate, b: AdvisorCandidate, objectives: Objective[]): boolean {
  let strictly = false;
  for (const objective of objectives) {
    const av = objectiveValue(a, objective.key), bv = objectiveValue(b, objective.key);
    if (av === null || bv === null) return false;
    const better = objective.direction === 'MIN' ? av <= bv : av >= bv;
    const strict = objective.direction === 'MIN' ? av < bv : av > bv;
    if (!better) return false;
    if (strict) strictly = true;
  }
  return strictly;
}

function normalizedScore(candidate: AdvisorCandidate, pool: AdvisorCandidate[], objectives: Objective[]): number | null {
  let total = 0;
  for (const objective of objectives) {
    const values = pool.map(row => objectiveValue(row, objective.key)).filter((value): value is number => value !== null);
    const value = objectiveValue(candidate, objective.key);
    if (value === null || !values.length) return null;
    const min = Math.min(...values), max = Math.max(...values);
    const normalized = max === min ? 0 : (value - min) / (max - min);
    total += objective.direction === 'MIN' ? normalized : 1 - normalized;
  }
  return total;
}

export function rankCandidates(candidates: AdvisorCandidate[], priority: Priority): {
  ranked: AdvisorCandidate[];
  excluded: AdvisorCandidate[];
  paretoIds: Set<string>;
  winner: AdvisorCandidate | null;
  runnerUp: AdvisorCandidate | null;
} {
  const objectives = objectivesFor(priority);
  const feasible = candidates.filter(candidate => candidate.feasible);
  const rankable = feasible.filter(candidate => objectives.every(objective => objectiveValue(candidate, objective.key) !== null));
  const paretoIds = new Set<string>();
  for (const candidate of rankable) {
    if (!rankable.some(other => other.id !== candidate.id && dominates(other, candidate, objectives))) {
      paretoIds.add(candidate.id);
    }
  }
  const scored = rankable.map(candidate => ({
    candidate,
    score: priority === 'balanced'
      ? normalizedScore(candidate, rankable, objectives)
      : objectiveValue(candidate, objectives[0].key),
  })).filter((row): row is { candidate: AdvisorCandidate; score: number } => row.score !== null);
  scored.sort((a, b) => {
    if (Math.abs(a.score - b.score) > 1e-12) {
      const direction = priority === 'throughput' ? -1 : 1;
      return direction * (a.score - b.score);
    }
    return a.candidate.latencyP95 - b.candidate.latencyP95 || a.candidate.depth - b.candidate.depth;
  });
  for (const candidate of candidates) {
    candidate.pareto = paretoIds.has(candidate.id);
    candidate.rank = null;
    candidate.score = null;
  }
  scored.forEach((row, index) => { row.candidate.rank = index + 1; row.candidate.score = row.score; });
  const excluded = candidates.filter(candidate => !candidate.feasible);
  return {
    ranked: scored.map(row => row.candidate),
    excluded,
    paretoIds,
    winner: scored[0]?.candidate ?? null,
    runnerUp: scored[1]?.candidate ?? null,
  };
}

/** Thresholds that would replace the current winner. Each note is computed by
 *  re-ranking the exact measured/modeled candidate set, never by extrapolating. */
export function sensitivityNotes(
  candidates: AdvisorCandidate[],
  priority: Priority,
  constraints: AdvisorConstraints,
  rebuild?: (next: AdvisorConstraints) => AdvisorCandidate[],
): SensitivityNote[] {
  const current = rankCandidates(candidates, priority);
  const winner = current.winner;
  if (!winner) return [];
  const definitions: { key: ConstraintKey; op: '≤' | '≥'; metric: (candidate: AdvisorCandidate) => number | null }[] = [
    { key: 'maxLatencyP95', op: '≤', metric: candidate => candidate.latencyP95 },
    { key: 'minThroughput', op: '≥', metric: candidate => candidate.throughput },
    { key: 'maxPowerW', op: '≤', metric: candidate => candidate.powerW },
    { key: 'maxAreaMm2', op: '≤', metric: candidate => candidate.areaMm2 },
    { key: 'maxStorageFlits', op: '≤', metric: candidate => candidate.storageFlits },
  ];
  const notes: { note: SensitivityNote; distance: number }[] = [];
  for (const definition of definitions) {
    const winnerValue = definition.metric(winner);
    if (winnerValue === null) continue;
    const values = [...new Set(candidates.map(definition.metric)
      .filter((value): value is number => value !== null))].sort((a, b) => a - b);
    const thresholds = definition.op === '≤'
      ? values.filter(value => value < winnerValue).sort((a, b) => b - a)
      : values.filter(value => value > winnerValue).sort((a, b) => a - b);
    for (const threshold of thresholds) {
      const nextConstraints: AdvisorConstraints = { ...constraints, [definition.key]: threshold };
      const rescored = rebuild ? rebuild(nextConstraints) : candidates.map(candidate => {
        const verdicts = constraintVerdicts(candidate, nextConstraints);
        return { ...candidate, verdicts, feasible: verdicts.every(verdict => verdict.pass) };
      });
      const next = rankCandidates(rescored, priority);
      if (next.winner && next.winner.id !== winner.id) {
        notes.push({
          note: {
            key: definition.key,
            label: CONSTRAINT_LABELS[definition.key],
            op: definition.op,
            threshold,
            winnerId: next.winner.id,
            winnerLabel: `${next.winner.arm.topologyLabel} at ${next.winner.depth} flits/VC`,
            basis: `${winner.arm.topologyLabel} at ${winner.depth} flits/VC has ${winnerValue.toFixed(3)}; the alternate winner has ${(definition.metric(next.winner) ?? 0).toFixed(3)}.`,
          },
          distance: Math.abs(threshold - winnerValue),
        });
        break;
      }
    }
  }
  return notes.sort((a, b) => a.distance - b.distance).slice(0, 3).map(entry => entry.note);
}

export function advise(
  arms: AdvisorArm[],
  sweepRows: SweepRow[],
  sensitivity: SensitivityEvidence | null,
  constraints: AdvisorConstraints,
  priority: Priority,
): AdvisorResult {
  const { median, load } = workloadReferenceLoad(arms);
  const models = fabricModels(sweepRows, load);
  const build = (next: AdvisorConstraints): AdvisorCandidate[] => buildCandidates(arms, models, sensitivity, next, priority)
    .filter(candidate => next.includeResearch || candidate.arm.support === 'product');
  const all = build(constraints);
  const ranked = rankCandidates(all, priority);
  return {
    medianLoad: median,
    referenceLoad: load,
    models,
    candidates: all,
    ranked: ranked.ranked,
    excluded: ranked.excluded,
    paretoIds: ranked.paretoIds,
    winner: ranked.winner,
    runnerUp: ranked.runnerUp,
    sensitivity: sensitivityNotes(all, priority, constraints, build),
  };
}

export const emptyConstraints = (): AdvisorConstraints => ({
  maxLatencyP95: null,
  minThroughput: null,
  maxPowerW: null,
  maxAreaMm2: null,
  maxStorageFlits: null,
  includeResearch: false,
});
