/** Workload × backend compatibility preflight (tracker M5-26).
 *
 *  Classifies a workload block against a *declared* backend capability
 *  descriptor BEFORE any run is attempted, so the UI can distinguish:
 *
 *  - `blocked`     — the workload itself is invalid; no backend can run it yet.
 *  - `unsupported` — the workload is valid but the backend declares it cannot
 *                    represent a requested feature (precision/collective/ranks…).
 *  - `supported`   — every declared feature is representable by the backend.
 *
 *  This module produces NO metrics and NO run result. It never substitutes an
 *  estimate for an unavailable backend. Backend descriptors are *declared*
 *  authoring configuration, not measured capability statements; the UI labels
 *  them as such and a real run must still be attempted against the engine.
 */
import { requiredRankCount, validateWorkload, type WorkloadBlock, type WorkloadCommunication } from './workload';

export interface BackendCapability {
  /** Stable backend identifier, e.g. `booksim-standalone`. */
  id: string;
  displayName: string;
  /** Collective kinds this backend declares it can represent. */
  collectives: readonly WorkloadCommunication['kind'][];
  /** Precisions this backend declares it accepts. */
  precisions: readonly string[];
  /** Whether the backend declares it consumes per-phase cycle timing. */
  consumesPhaseCycles: boolean;
  /** Max representable ranks, or `null` when unbounded. */
  maxRanks: number | null;
  /** Provenance label for the descriptor; never `measured`. */
  provenance: 'declared';
}

export type WorkloadBackendState = 'supported' | 'unsupported' | 'blocked';

export interface WorkloadBackendReason {
  /** Stable, machine-checkable code. */
  code: string;
  message: string;
}

export interface WorkloadBackendVerdict {
  backendId: string;
  state: WorkloadBackendState;
  reasons: WorkloadBackendReason[];
}

const COLLECTIVE_KINDS: readonly WorkloadCommunication['kind'][] = [
  'allreduce', 'allgather', 'alltoall', 'reduce-scatter', 'custom',
];

/** Declared authoring defaults for the backends this repository references.
 *  These are NOT measured capability claims: the shipped engine manifest and a
 *  real run remain the authority. Kept intentionally permissive so an author
 *  sees the classifier, not a fabricated refusal. */
export const DECLARED_BACKENDS: readonly BackendCapability[] = [
  {
    id: 'booksim-standalone',
    displayName: 'BookSim (standalone)',
    collectives: COLLECTIVE_KINDS,
    precisions: ['fp16', 'fp8', 'int8', 'bf16'],
    consumesPhaseCycles: false,
    maxRanks: null,
    provenance: 'declared',
  },
  {
    id: 'astra-booksim',
    displayName: 'ASTRA + BookSim',
    collectives: COLLECTIVE_KINDS,
    precisions: ['fp16', 'fp8', 'int8', 'bf16'],
    consumesPhaseCycles: true,
    maxRanks: null,
    provenance: 'declared',
  },
];

export function findDeclaredBackend(id: string | undefined): BackendCapability | undefined {
  return id === undefined ? undefined : DECLARED_BACKENDS.find((backend) => backend.id === id);
}

/** Classify a workload against a declared backend. Deterministic and side
 *  effect free. `blocked` outranks `unsupported`; a workload that cannot
 *  validate is never reported as merely unsupported. */
export function classifyWorkloadBackend(
  workload: WorkloadBlock,
  nodeIds: readonly string[],
  backend: BackendCapability,
  vcClasses?: readonly number[],
): WorkloadBackendVerdict {
  const reasons: WorkloadBackendReason[] = [];

  const workloadIssues = validateWorkload(workload, nodeIds.length, nodeIds, vcClasses);
  if (workloadIssues.length > 0) {
    return {
      backendId: backend.id,
      state: 'blocked',
      reasons: [
        { code: 'workload.invalid', message: `workload has ${workloadIssues.length} validation issue(s); fix these before a backend check` },
        ...workloadIssues.slice(0, 8).map((issue) => ({ code: 'workload.invalid', message: issue.message })),
      ],
    };
  }

  if (!backend.precisions.includes(workload.precision)) {
    reasons.push({ code: 'workload.backend.precision', message: `backend declares no support for precision ${workload.precision}` });
  }

  const operations = workload.communications ?? [];
  for (const [index, op] of operations.entries()) {
    if (op.kind === 'point-to-point') continue;
    if (!backend.collectives.includes(op.kind)) {
      reasons.push({ code: 'workload.backend.collective', message: `backend declares no support for collective ${op.kind} (communications[${index}])` });
    }
  }

  const ranks = requiredRankCount(workload);
  if (backend.maxRanks !== null && ranks > backend.maxRanks) {
    reasons.push({ code: 'workload.backend.ranks', message: `rank demand ${ranks} exceeds the backend's declared limit ${backend.maxRanks}` });
  }

  if (!backend.consumesPhaseCycles) {
    const timed = workload.phases.filter((phase) => phase.startCycle !== undefined || phase.durationCycles !== undefined);
    if (timed.length > 0) {
      reasons.push({ code: 'workload.backend.phase_cycles', message: `backend ignores authored phase cycle timing on ${timed.length} phase(s); timing will not be represented` });
    }
  }

  return {
    backendId: backend.id,
    state: reasons.length > 0 ? 'unsupported' : 'supported',
    reasons,
  };
}
