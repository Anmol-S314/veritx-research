/** Workload phases[] editor model (P5). Both WorkloadView and SimView read this. */
export interface WorkloadPhase {
  id: string;
  kind: string;
  tokens: number;
  batch: number;
  tp: number;
  ep: number;
  pp: number;
  dp: number;
}

export interface WorkloadBlock {
  modelFamily: string;
  paramsB: number;
  seqLen: number;
  batch: number;
  precision: string;
  phases: WorkloadPhase[];
}

export const PHASE_KINDS = ['prefill', 'decode', 'allreduce', 'alltoall', 'memo'];

export function emptyWorkload(): WorkloadBlock {
  return { modelFamily: 'Mixtral 8x7B', paramsB: 46.7, seqLen: 4096, batch: 8, precision: 'fp16', phases: [] };
}

export function validateWorkload(w: WorkloadBlock, nodeCount: number): string[] {
  const issues: string[] = [];
  if (!w.modelFamily.trim()) issues.push('model family is required');
  if (w.phases.length === 0) issues.push('at least one phase is required');
  const need = Math.max(...w.phases.map((p) => p.tp * p.ep * p.pp * p.dp), 0);
  if (w.phases.length && need > nodeCount) {
    issues.push(`parallelism needs ${need} nodes but the graph has ${nodeCount}`);
  }
  for (const [i, p] of w.phases.entries()) {
    if (!PHASE_KINDS.includes(p.kind)) issues.push(`phases[${i}].kind: unknown ${p.kind}`);
    if (p.tokens < 1) issues.push(`phases[${i}].tokens: must be ≥ 1`);
  }
  return issues;
}

export function mixtralTp8Ep8(): WorkloadBlock {
  return {
    modelFamily: 'Mixtral 8x7B', paramsB: 46.7, seqLen: 4096, batch: 8, precision: 'fp16',
    phases: [
      { id: 'ph-prefill', kind: 'prefill', tokens: 4096, batch: 8, tp: 8, ep: 8, pp: 1, dp: 1 },
      { id: 'ph-decode', kind: 'decode', tokens: 512, batch: 8, tp: 8, ep: 8, pp: 1, dp: 1 },
      { id: 'ph-ar', kind: 'allreduce', tokens: 512, batch: 8, tp: 8, ep: 1, pp: 1, dp: 1 },
    ],
  };
}
