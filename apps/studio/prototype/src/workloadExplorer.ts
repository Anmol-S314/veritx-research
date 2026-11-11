/** Measured workload × topology evidence for the curves explorer.
 *
 *  These rows come from a trace-replay ablation document, not from the uniform
 *  injection-rate sweep: there is no offered-load axis, so they are a workload
 *  selection, not another sweep cohort. An arm label is not experimental
 *  identity, so a comparison is only verified when trace, fabric, binary and
 *  seed agree. */
import type { AblationIdentity } from './ablationEvidence';

export type AblationPoint = {
  workload: string; workloadLabel: string;
  topology: string; topologyLabel: string; family: string;
  nodes: number; vcs: number | null;
  latencyMean: number; latencyP95: number | null;
  throughput: number; hopsAvg: number | null;
  completionCycles: number | null;
  routers: number | null; crosspoints: number | null; storageFlits: number | null;
} & AblationIdentity;

export type AblationEvidence = {
  generatedAt: string | null;
  scope: string;
  seed: number | null;
  workloads: { id: string; label: string }[];
  points: AblationPoint[];
  skipped: number;
};

const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const text = (value: unknown): string => (typeof value === 'string' ? value : '');

export function parseAblationDocument(value: unknown): AblationEvidence {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Ablation evidence must be a document object');
  }
  const doc = value as Record<string, unknown>;
  if (!Array.isArray(doc.runs)) throw new Error('Ablation evidence has no runs array');
  const common = (doc.common ?? {}) as Record<string, unknown>;
  const points: AblationPoint[] = [];
  let skipped = 0;
  for (const raw of doc.runs) {
    const row = (raw ?? {}) as Record<string, unknown>;
    const latencyMean = finite(row.latency_mean);
    const throughput = finite(row.throughput_packets_per_cycle);
    const workload = text(row.workload);
    const topology = text(row.topology);
    // Failed, incomplete or negative cells never become a comparison point.
    if (row.status !== 'ok' || !workload || !topology || latencyMean === null
      || throughput === null || latencyMean < 0 || throughput < 0) {
      skipped += 1;
      continue;
    }
    const cost = (row.resource_cost ?? {}) as Record<string, unknown>;
    points.push({
      workload, workloadLabel: text(row.workload_label) || workload,
      topology, topologyLabel: text(row.topology_label) || topology,
      family: text(row.family) || 'not reported',
      nodes: finite(row.nodes) ?? 0,
      vcs: finite(row.vcs),
      latencyMean, latencyP95: finite(row.latency_p95),
      throughput, hopsAvg: finite(row.hops_avg),
      completionCycles: finite(row.completion_cycles),
      routers: finite(cost.routers), crosspoints: finite(cost.crosspoints),
      storageFlits: finite(cost.storage_flits),
      trace_sha256: text(row.trace_sha256) || undefined,
      arm_sha256: text(row.arm_sha256) || undefined,
      binary_sha256: text(row.binary_sha256) || undefined,
      simulator_seed: finite(row.simulator_seed) ?? undefined,
    });
  }
  if (!points.length) throw new Error('Ablation evidence carries no successful measured cell');
  const seen = new Map<string, string>();
  for (const point of points) if (!seen.has(point.workload)) seen.set(point.workload, point.workloadLabel);
  return {
    generatedAt: text(doc.generated_at) || null,
    scope: text(common.comparison_scope),
    seed: finite(common.seed),
    workloads: [...seen].map(([id, label]) => ({ id, label })),
    points, skipped,
  };
}

/** Cross-arm comparison holds trace, simulator binary and seed constant; the
 *  fabric definition is the variable under comparison, so it may differ. Returns
 *  the first violated constraint, or null. */
export function identityIssue(points: AblationPoint[]): string | null {
  const [head, ...rest] = points;
  if (!head) return 'No observation to compare.';
  for (const point of rest) {
    for (const [key, label] of [
      ['trace_sha256', 'Trace'],
      ['binary_sha256', 'Simulator binary'],
    ] as const) {
      if (!head[key] || !point[key]) return `${point.topology}: ${label} identity is missing; this comparison is not verified.`;
      if (head[key] !== point[key]) return `${point.topology}: ${label} changed; this is not a matched-workload comparison.`;
    }
    if (head.simulator_seed === undefined || point.simulator_seed === undefined) {
      return `${point.topology}: Simulator seed is missing; this comparison is not verified.`;
    }
    if (head.simulator_seed !== point.simulator_seed) return `${point.topology}: Simulator seed changed; this is not a matched-workload comparison.`;
  }
  return null;
}

/** Non-dominated set over mean latency (lower) and accepted throughput (higher). */
export function latencyThroughputFront(points: AblationPoint[]): Set<string> {
  const front = new Set<string>();
  for (const point of points) {
    const dominated = points.some(other => other !== point
      && other.latencyMean <= point.latencyMean && other.throughput >= point.throughput
      && (other.latencyMean < point.latencyMean || other.throughput > point.throughput));
    if (!dominated) front.add(point.topology);
  }
  return front;
}

/** Workloads that measured more than one arm; a single-arm workload is not a comparison. */
export function workloadArms(evidence: AblationEvidence, workload: string): AblationPoint[] {
  return evidence.points.filter(point => point.workload === workload)
    .sort((a, b) => a.latencyMean - b.latencyMean || a.topology.localeCompare(b.topology));
}
