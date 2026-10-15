import { makeIssue, type ProjectIssue } from './project';

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

export function validateWorkload(w: WorkloadBlock, nodeCount: number): ProjectIssue[] {
  const issues: ProjectIssue[] = [];
  if (!w.modelFamily.trim()) {
    issues.push(makeIssue({
      path: '$.modelFamily', message: 'model family is required',
      code: 'workload.model_family_required', objectRef: '$.modelFamily',
    }));
  }
  if (w.phases.length === 0) {
    issues.push(makeIssue({
      path: '$.phases', message: 'at least one phase is required',
      code: 'workload.no_phases', objectRef: '$.phases',
    }));
  }
  const need = Math.max(...w.phases.map((p) => p.tp * p.ep * p.pp * p.dp), 0);
  if (w.phases.length && need > nodeCount) {
    issues.push(makeIssue({
      path: '$.phases',
      message: `parallelism needs ${need} nodes but the graph has ${nodeCount}`,
      code: 'workload.parallelism_exceeds_nodes', objectRef: '$.phases',
    }));
  }
  for (const [i, p] of w.phases.entries()) {
    const objectRef = `$.phases[id=${p.id}]`;
    if (!PHASE_KINDS.includes(p.kind)) {
      issues.push(makeIssue({
        path: `$.phases[${i}].kind`, message: `unknown ${p.kind}`,
        code: 'workload.unknown_phase_kind', objectRef,
      }));
    }
    if (p.tokens < 1) {
      issues.push(makeIssue({
        path: `$.phases[${i}].tokens`, message: 'must be ≥ 1',
        code: 'workload.phase_tokens', objectRef,
      }));
    }
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
