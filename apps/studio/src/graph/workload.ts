/** Workload phases[] editor model (P5). Both WorkloadView and SimView read this. */
import { validationIssue, type ValidationIssue } from './validation';
export interface WorkloadPhase {
  id: string;
  name?: string;
  kind: string;
  startCycle?: number;
  durationCycles?: number;
  tokens: number;
  batch: number;
  tp: number;
  ep: number;
  pp: number;
  dp: number;
}

export interface WorkloadRankMapping {
  rank: number;
  role: string;
  nodeId: string;
}

export interface WorkloadRankConstraint {
  rank: number;
  pinnedNodeId?: string;
  allowedNodeIds?: string[];
  requiredRole?: string;
}

export interface WorkloadTrafficClassMapping {
  trafficClass: string;
  vcClass: number;
  qosClass: string;
}

export interface WorkloadCommunication {
  id: string;
  kind: 'allreduce' | 'allgather' | 'alltoall' | 'reduce-scatter' | 'custom' | 'point-to-point';
  /** Parallel dimension is declared intent; it does not imply a lowering. */
  dimension: 'tp' | 'ep' | 'pp' | 'dp' | 'custom';
  dimensionName?: string;
  payloadBytes: number;
  trafficClass: string;
  customName?: string;
  sourceNodeId?: string;
  targetNodeId?: string;
}

export interface WorkloadBlock {
  modelFamily: string;
  modelName?: string;
  paramsB?: number;
  hiddenSize?: number;
  layerCount?: number;
  seqLen: number;
  batch: number;
  precision: string;
  phases: WorkloadPhase[];
  communications?: WorkloadCommunication[];
  rankMappings?: WorkloadRankMapping[];
  rankConstraints?: WorkloadRankConstraint[];
  trafficClassMappings?: WorkloadTrafficClassMapping[];
  defaultTrafficClassMapping?: Omit<WorkloadTrafficClassMapping, 'trafficClass'>;
}

export const PHASE_KINDS = ['prefill', 'decode', 'allreduce', 'alltoall', 'memo'];
export const COLLECTIVE_KINDS: WorkloadCommunication['kind'][] = [
  'allreduce', 'allgather', 'alltoall', 'reduce-scatter', 'custom',
];
export const COMMUNICATION_KINDS: WorkloadCommunication['kind'][] = [
  ...COLLECTIVE_KINDS, 'point-to-point',
];

/** MoE starter is deliberately incomplete until the user declares exact ops/payloads. */
export function moeWorkloadSkeleton(workload: WorkloadBlock): WorkloadBlock {
  return {
    ...workload,
    modelFamily: 'moe',
    communications: [
      { id: 'moe-tp-operation', kind: 'custom', dimension: 'tp', payloadBytes: 0, trafficClass: '', customName: '' },
      { id: 'moe-ep-operation', kind: 'custom', dimension: 'ep', payloadBytes: 0, trafficClass: '', customName: '' },
    ],
  };
}

export function emptyWorkload(): WorkloadBlock {
  // Required schema values are visible/editable in the editor; do not smuggle
  // a model shape, phases, operations, or rank placement into a blank custom.
  return { modelFamily: 'custom', seqLen: 1, batch: 1, precision: 'fp16', phases: [], communications: [], rankMappings: [] };
}

export function requiredRankCount(w: Pick<WorkloadBlock, 'phases'>): number {
  return Math.max(0, ...w.phases.map((phase) => phase.tp * phase.ep * phase.pp * phase.dp));
}

/** Deterministic graph-order assignment. Null means rank demand is invalid or exceeds seats. */
export function autoRankMappings(
  w: Pick<WorkloadBlock, 'phases'>,
  nodeIds: readonly string[],
): WorkloadRankMapping[] | null {
  const count = requiredRankCount(w);
  if (!Number.isSafeInteger(count) || count < 1 || count > nodeIds.length) return null;
  return Array.from({ length: count }, (_, rank) => ({
    rank, role: 'rank', nodeId: nodeIds[rank]!,
  }));
}

export function validateWorkload(w: WorkloadBlock, nodeCount: number, nodeIds?: readonly string[], vcClasses?: readonly number[]): string[] {
  const issues: string[] = [];
  const positiveInt = (value: number): boolean => Number.isSafeInteger(value) && value > 0;
  if (!w.modelFamily.trim()) issues.push('model family is required');
  if (w.modelName !== undefined && !w.modelName.trim()) issues.push('modelName: must be non-empty when set');
  if (w.paramsB !== undefined && (!Number.isFinite(w.paramsB) || w.paramsB <= 0)) issues.push('paramsB: must be a positive finite number');
  if (w.hiddenSize !== undefined && !positiveInt(w.hiddenSize)) issues.push('hiddenSize: must be a positive integer when set');
  if (w.layerCount !== undefined && !positiveInt(w.layerCount)) issues.push('layerCount: must be a positive integer when set');
  if (!positiveInt(w.seqLen)) issues.push('seqLen: must be a positive integer');
  if (!positiveInt(w.batch)) issues.push('batch: must be a positive integer');
  if (!['fp16', 'fp8', 'int8', 'bf16'].includes(w.precision)) {
    issues.push(`precision: unsupported value ${w.precision}`);
  }
  if (!Number.isSafeInteger(nodeCount) || nodeCount < 0) {
    issues.push('node count must be a non-negative integer');
  }
  if (!Array.isArray(w.phases) || w.phases.length === 0) {
    issues.push('at least one phase is required');
    return issues;
  }
  const ids = new Set<string>();
  let requiredSeats = 0;
  for (const [i, p] of w.phases.entries()) {
    if (typeof p.id !== 'string' || p.id.trim() === '') issues.push(`phases[${i}].id: must be a non-empty string`);
    else if (ids.has(p.id)) issues.push(`phases[${i}].id: duplicate id ${p.id}`);
    else ids.add(p.id);
    if (p.name !== undefined && !p.name.trim()) issues.push(`phases[${i}].name: must be non-empty when set`);
    if (!PHASE_KINDS.includes(p.kind)) issues.push(`phases[${i}].kind: unknown ${p.kind}`);
    if (p.startCycle !== undefined && (!Number.isSafeInteger(p.startCycle) || p.startCycle < 0)) {
      issues.push(`phases[${i}].startCycle: must be a non-negative integer`);
    }
    if (p.durationCycles !== undefined && !positiveInt(p.durationCycles)) {
      issues.push(`phases[${i}].durationCycles: must be a positive integer`);
    }
    if ((p.startCycle === undefined) !== (p.durationCycles === undefined)) {
      issues.push(`phases[${i}]: startCycle and durationCycles must be specified together`);
    }
    for (const key of ['tokens', 'batch', 'tp', 'ep', 'pp', 'dp'] as const) {
      if (!positiveInt(p[key])) issues.push(`phases[${i}].${key}: must be a positive integer`);
    }
    const seats = p.tp * p.ep * p.pp * p.dp;
    if (Number.isSafeInteger(seats)) requiredSeats = Math.max(requiredSeats, seats);
    else issues.push(`phases[${i}]: parallelism product exceeds the safe integer range`);
  }
  if (requiredSeats > nodeCount) {
    issues.push(`parallelism needs ${requiredSeats} nodes but the graph has ${nodeCount}`);
  }
  const ranks = new Set<number>();
  const nodeToRank = new Map<string, number>();
  const mappingRows = w.rankMappings ?? [];
  if (w.rankMappings !== undefined && requiredSeats > mappingRows.length) {
    issues.push(`parallelism needs ${requiredSeats} mapped rank seats but only ${mappingRows.length} are assigned`);
  }
  const availableIds = nodeIds ? new Set(nodeIds) : null;
  for (const [i, mapping] of mappingRows.entries()) {
    if (!Number.isSafeInteger(mapping.rank) || mapping.rank < 0) {
      issues.push(`rankMappings[${i}].rank: must be a non-negative integer`);
    } else if (ranks.has(mapping.rank)) {
      issues.push(`rankMappings[${i}].rank: duplicate rank ${mapping.rank}`);
    } else {
      ranks.add(mapping.rank);
      if (w.rankMappings !== undefined && mapping.rank >= requiredSeats) {
        issues.push(`rankMappings[${i}].rank: exceeds declared parallel demand (${requiredSeats})`);
      }
    }
    if (!mapping.role.trim()) issues.push(`rankMappings[${i}].role: required`);
    if (!mapping.nodeId.trim()) issues.push(`rankMappings[${i}].nodeId: required`);
    else if (availableIds && !availableIds.has(mapping.nodeId)) {
      issues.push(`rankMappings[${i}].nodeId: unknown graph node ${mapping.nodeId}`);
    } else if (nodeToRank.has(mapping.nodeId)) {
      issues.push(`rankMappings[${i}].nodeId: graph node ${mapping.nodeId} already assigned to rank ${nodeToRank.get(mapping.nodeId)}`);
    } else if (Number.isSafeInteger(mapping.rank) && mapping.rank >= 0) {
      nodeToRank.set(mapping.nodeId, mapping.rank);
    }
  }
  if (w.rankMappings !== undefined) {
    for (let rank = 0; rank < requiredSeats; rank++) {
      if (!ranks.has(rank)) issues.push(`rankMappings: missing rank ${rank}`);
    }
  }
  if (w.rankConstraints !== undefined && !Array.isArray(w.rankConstraints)) {
    issues.push('rankConstraints: must be an array');
  }
  const constraintRanks = new Set<number>();
  const constraints = Array.isArray(w.rankConstraints) ? w.rankConstraints : [];
  for (const [i, rawConstraint] of constraints.entries()) {
    const path = `rankConstraints[${i}]`;
    if (rawConstraint === null || typeof rawConstraint !== 'object' || Array.isArray(rawConstraint)) {
      issues.push(`${path}: must be an object`);
      continue;
    }
    const constraint = rawConstraint as WorkloadRankConstraint;
    if (!Number.isSafeInteger(constraint.rank) || constraint.rank < 0) {
      issues.push(`${path}.rank: must be a non-negative integer`);
      continue;
    }
    if (constraintRanks.has(constraint.rank)) issues.push(`${path}.rank: duplicate constraint for rank ${constraint.rank}`);
    constraintRanks.add(constraint.rank);
    if (constraint.rank >= requiredSeats) issues.push(`${path}.rank: exceeds declared parallel demand (${requiredSeats})`);
    if (constraint.requiredRole !== undefined && (typeof constraint.requiredRole !== 'string' || !constraint.requiredRole.trim())) issues.push(`${path}.requiredRole: must be a non-empty string when set`);
    if (constraint.pinnedNodeId !== undefined) {
      if (typeof constraint.pinnedNodeId !== 'string' || !constraint.pinnedNodeId.trim()) issues.push(`${path}.pinnedNodeId: must be a non-empty string when set`);
      else if (availableIds && !availableIds.has(constraint.pinnedNodeId)) issues.push(`${path}.pinnedNodeId: unknown graph node ${constraint.pinnedNodeId}`);
    }
    if (constraint.allowedNodeIds !== undefined) {
      if (!Array.isArray(constraint.allowedNodeIds)) issues.push(`${path}.allowedNodeIds: must be an array`);
      else {
        const allowed = new Set<string>();
        for (const [j, nodeId] of constraint.allowedNodeIds.entries()) {
          if (typeof nodeId !== 'string' || !nodeId.trim()) issues.push(`${path}.allowedNodeIds[${j}]: must be a non-empty graph node ID`);
          else if (allowed.has(nodeId)) issues.push(`${path}.allowedNodeIds[${j}]: duplicate graph node ${nodeId}`);
          else {
            allowed.add(nodeId);
            if (availableIds && !availableIds.has(nodeId)) issues.push(`${path}.allowedNodeIds[${j}]: unknown graph node ${nodeId}`);
          }
        }
        if (allowed.size === 0) issues.push(`${path}.allowedNodeIds: must contain at least one graph node when set`);
        if (typeof constraint.pinnedNodeId === 'string' && constraint.pinnedNodeId && allowed.size > 0 && !allowed.has(constraint.pinnedNodeId)) {
          issues.push(`${path}: pinned node is not in allowed node set`);
        }
        const mapping = mappingRows.find((row) => row.rank === constraint.rank);
        if (mapping && allowed.size > 0 && !allowed.has(mapping.nodeId)) {
          issues.push(`${path}: rank ${constraint.rank} maps to disallowed node ${mapping.nodeId}`);
        }
      }
    }
    const mapping = mappingRows.find((row) => row.rank === constraint.rank);
    if (mapping && typeof constraint.pinnedNodeId === 'string' && constraint.pinnedNodeId && mapping.nodeId !== constraint.pinnedNodeId) {
      issues.push(`${path}: rank ${constraint.rank} is pinned to ${constraint.pinnedNodeId}, not ${mapping.nodeId}`);
    }
    if (mapping && typeof constraint.requiredRole === 'string' && constraint.requiredRole && mapping.role !== constraint.requiredRole) {
      issues.push(`${path}: rank ${constraint.rank} requires role ${constraint.requiredRole}, not ${mapping.role}`);
    }
  }
  const trafficMappings = Array.isArray(w.trafficClassMappings) ? w.trafficClassMappings : [];
  if (w.trafficClassMappings !== undefined && !Array.isArray(w.trafficClassMappings)) issues.push('trafficClassMappings: must be an array');
  const trafficClasses = new Set<string>();
  const validateTrafficMapping = (mapping: WorkloadTrafficClassMapping, path: string, includeClass = true): void => {
    if (includeClass) {
      if (typeof mapping.trafficClass !== 'string' || !mapping.trafficClass.trim()) issues.push(`${path}.trafficClass: required`);
      else if (trafficClasses.has(mapping.trafficClass)) issues.push(`${path}.trafficClass: duplicate mapping ${mapping.trafficClass}`);
      else trafficClasses.add(mapping.trafficClass);
    }
    if (!Number.isSafeInteger(mapping.vcClass) || mapping.vcClass < 0) issues.push(`${path}.vcClass: must be a non-negative integer`);
    else if (vcClasses && !vcClasses.includes(mapping.vcClass)) issues.push(`${path}.vcClass: class ${mapping.vcClass} is not present on authored graph edges`);
    if (typeof mapping.qosClass !== 'string' || !mapping.qosClass.trim()) issues.push(`${path}.qosClass: required`);
  };
  trafficMappings.forEach((mapping, index) => {
    if (mapping === null || typeof mapping !== 'object' || Array.isArray(mapping)) issues.push(`trafficClassMappings[${index}]: must be an object`);
    else validateTrafficMapping(mapping, `trafficClassMappings[${index}]`);
  });
  if (w.defaultTrafficClassMapping !== undefined) {
    const rawFallback = w.defaultTrafficClassMapping as unknown;
    if (rawFallback === null || typeof rawFallback !== 'object' || Array.isArray(rawFallback)) {
      issues.push('defaultTrafficClassMapping: must be an object');
    } else {
      const fallback = rawFallback as Omit<WorkloadTrafficClassMapping, 'trafficClass'>;
      validateTrafficMapping({ ...fallback, trafficClass: '' }, 'defaultTrafficClassMapping', false);
    }
  }
  const operationIds = new Set<string>();
  for (const [i, op] of (w.communications ?? []).entries()) {
    if (!op.id.trim()) issues.push(`communications[${i}].id: must be non-empty`);
    else if (operationIds.has(op.id)) issues.push(`communications[${i}].id: duplicate id ${op.id}`);
    else operationIds.add(op.id);
    if (!COMMUNICATION_KINDS.includes(op.kind)) issues.push(`communications[${i}].kind: unsupported value ${op.kind}`);
    if (op.kind === 'point-to-point') {
      if (!op.sourceNodeId?.trim() || !op.targetNodeId?.trim()) {
        issues.push(`communications[${i}]: point-to-point requires source and target graph node IDs`);
      }
      if (availableIds && op.sourceNodeId && !availableIds.has(op.sourceNodeId)) {
        issues.push(`communications[${i}].sourceNodeId: unknown graph node ${op.sourceNodeId}`);
      }
      if (availableIds && op.targetNodeId && !availableIds.has(op.targetNodeId)) {
        issues.push(`communications[${i}].targetNodeId: unknown graph node ${op.targetNodeId}`);
      }
    }
    if (!['tp', 'ep', 'pp', 'dp', 'custom'].includes(op.dimension)) {
      issues.push(`communications[${i}].dimension: unsupported value ${op.dimension}`);
    }
    if (op.dimension === 'custom' && !op.dimensionName?.trim()) {
      issues.push(`communications[${i}].dimensionName: required for custom dimension`);
    }
    if (op.kind === 'custom' && !op.customName?.trim()) {
      issues.push(`communications[${i}].customName: required for custom operation`);
    }
    if (!positiveInt(op.payloadBytes)) {
      issues.push(`communications[${i}].payloadBytes: must be a positive integer`);
    }
    if (typeof op.trafficClass !== 'string' || !op.trafficClass.trim()) issues.push(`communications[${i}].trafficClass: required`);
    else if (!trafficMappings.some((mapping) => mapping !== null && typeof mapping === 'object' && mapping.trafficClass === op.trafficClass) && w.defaultTrafficClassMapping === undefined) {
      issues.push(`communications[${i}].trafficClass: no explicit VC/QoS mapping or default`);
    }
  }
  return issues;
}

export function validateWorkloadIssues(w: WorkloadBlock, nodeCount: number, nodeIds?: readonly string[], vcClasses?: readonly number[]): ValidationIssue[] {
  return validateWorkload(w, nodeCount, nodeIds, vcClasses).map((message) => {
    const match = /^(?:([^:]+): )?(.+)$/.exec(message);
    const path = match?.[1] ? `$.workload.${match[1]}` : '$.workload';
    return validationIssue('LOOM_WORKLOAD_INVALID', path, match?.[2] ?? message);
  });
}

export function parseWorkloadJson(json: string, nodeIds: readonly string[], vcClasses?: readonly number[]): { workload: WorkloadBlock | null; issues: string[] } {
  let value: unknown;
  try { value = JSON.parse(json) as unknown; }
  catch (error) {
    return { workload: null, issues: [`$: invalid JSON: ${error instanceof Error ? error.message : String(error)}`] };
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return { workload: null, issues: ['$: workload must be a JSON object'] };
  }
  const allowed = new Set(['workloadSchemaVersion', 'modelFamily', 'modelName', 'paramsB', 'hiddenSize', 'layerCount', 'seqLen', 'batch', 'precision', 'phases', 'communications', 'rankMappings', 'rankConstraints', 'trafficClassMappings', 'defaultTrafficClassMapping']);
  const record = value as Record<string, unknown>;
  const issues = Object.keys(record).filter((key) => !allowed.has(key)).map((key) => `$.${key}: unknown field`);
  if (record.workloadSchemaVersion !== undefined && record.workloadSchemaVersion !== 1) {
    issues.push('$.workloadSchemaVersion: unsupported version (expected 1)');
  }
  for (const key of ['modelFamily', 'seqLen', 'batch', 'precision', 'phases']) {
    if (!(key in record)) issues.push(`$.${key}: required field is missing`);
  }
  if (typeof record.modelFamily !== 'string') issues.push('$.modelFamily: must be a string');
  for (const key of ['seqLen', 'batch'] as const) {
    if (typeof record[key] !== 'number') issues.push(`$.${key}: must be a number`);
  }
  if (record.paramsB !== undefined && typeof record.paramsB !== 'number') issues.push('$.paramsB: must be a number when set');
  if (record.modelName !== undefined && typeof record.modelName !== 'string') issues.push('$.modelName: must be a string when set');
  for (const key of ['hiddenSize', 'layerCount'] as const) {
    if (record[key] !== undefined && typeof record[key] !== 'number') issues.push(`$.${key}: must be a number when set`);
  }
  if (typeof record.precision !== 'string') issues.push('$.precision: must be a string');
  if (!Array.isArray(record.phases)) issues.push('$.phases: must be an array');
  else record.phases.forEach((phase, i) => {
    const path = `$.phases[${i}]`;
    if (phase === null || typeof phase !== 'object' || Array.isArray(phase)) { issues.push(`${path}: must be an object`); return; }
    const row = phase as Record<string, unknown>;
    const allowedPhase = new Set(['id', 'name', 'kind', 'startCycle', 'durationCycles', 'tokens', 'batch', 'tp', 'ep', 'pp', 'dp']);
    Object.keys(row).filter((key) => !allowedPhase.has(key)).forEach((key) => issues.push(`${path}.${key}: unknown field`));
    for (const key of ['id', 'kind'] as const) if (typeof row[key] !== 'string') issues.push(`${path}.${key}: must be a string`);
    for (const key of ['tokens', 'batch', 'tp', 'ep', 'pp', 'dp'] as const) if (typeof row[key] !== 'number') issues.push(`${path}.${key}: must be a number`);
    if (row.name !== undefined && typeof row.name !== 'string') issues.push(`${path}.name: must be a string`);
    for (const key of ['startCycle', 'durationCycles'] as const) if (row[key] !== undefined && typeof row[key] !== 'number') issues.push(`${path}.${key}: must be a number`);
  });
  if (record.communications !== undefined && !Array.isArray(record.communications)) issues.push('$.communications: must be an array');
  else if (Array.isArray(record.communications)) record.communications.forEach((op, i) => {
    const path = `$.communications[${i}]`;
    if (op === null || typeof op !== 'object' || Array.isArray(op)) { issues.push(`${path}: must be an object`); return; }
    const row = op as Record<string, unknown>;
    const allowedOperation = new Set(['id', 'kind', 'dimension', 'dimensionName', 'payloadBytes', 'trafficClass', 'customName', 'sourceNodeId', 'targetNodeId']);
    Object.keys(row).filter((key) => !allowedOperation.has(key)).forEach((key) => issues.push(`${path}.${key}: unknown field`));
    for (const key of ['id', 'kind', 'dimension', 'trafficClass'] as const) if (typeof row[key] !== 'string') issues.push(`${path}.${key}: must be a string`);
    if (typeof row.payloadBytes !== 'number') issues.push(`${path}.payloadBytes: must be a number`);
    for (const key of ['dimensionName', 'customName', 'sourceNodeId', 'targetNodeId'] as const) if (row[key] !== undefined && typeof row[key] !== 'string') issues.push(`${path}.${key}: must be a string`);
  });
  if (record.defaultTrafficClassMapping !== undefined) {
    const mapping = record.defaultTrafficClassMapping;
    if (mapping === null || typeof mapping !== 'object' || Array.isArray(mapping)) issues.push('$.defaultTrafficClassMapping: must be an object');
    else {
      const row = mapping as Record<string, unknown>;
      Object.keys(row).filter((key) => !['vcClass', 'qosClass'].includes(key)).forEach((key) => issues.push(`$.defaultTrafficClassMapping.${key}: unknown field`));
      if (typeof row.vcClass !== 'number') issues.push('$.defaultTrafficClassMapping.vcClass: must be a number');
      if (typeof row.qosClass !== 'string') issues.push('$.defaultTrafficClassMapping.qosClass: must be a string');
    }
  }
  if (record.trafficClassMappings !== undefined && !Array.isArray(record.trafficClassMappings)) issues.push('$.trafficClassMappings: must be an array');
  else if (Array.isArray(record.trafficClassMappings)) record.trafficClassMappings.forEach((mapping, i) => {
    const path = `$.trafficClassMappings[${i}]`;
    if (mapping === null || typeof mapping !== 'object' || Array.isArray(mapping)) { issues.push(`${path}: must be an object`); return; }
    const row = mapping as Record<string, unknown>;
    Object.keys(row).filter((key) => !['trafficClass', 'vcClass', 'qosClass'].includes(key)).forEach((key) => issues.push(`${path}.${key}: unknown field`));
    if (typeof row.trafficClass !== 'string') issues.push(`${path}.trafficClass: must be a string`);
    if (typeof row.vcClass !== 'number') issues.push(`${path}.vcClass: must be a number`);
    if (typeof row.qosClass !== 'string') issues.push(`${path}.qosClass: must be a string`);
  });
  if (record.rankConstraints !== undefined && !Array.isArray(record.rankConstraints)) issues.push('$.rankConstraints: must be an array');
  else if (Array.isArray(record.rankConstraints)) record.rankConstraints.forEach((constraint, i) => {
    const path = `$.rankConstraints[${i}]`;
    if (constraint === null || typeof constraint !== 'object' || Array.isArray(constraint)) { issues.push(`${path}: must be an object`); return; }
    const row = constraint as Record<string, unknown>;
    Object.keys(row).filter((key) => !['rank', 'pinnedNodeId', 'allowedNodeIds', 'requiredRole'].includes(key)).forEach((key) => issues.push(`${path}.${key}: unknown field`));
    if (typeof row.rank !== 'number') issues.push(`${path}.rank: must be a number`);
    for (const key of ['pinnedNodeId', 'requiredRole'] as const) if (row[key] !== undefined && typeof row[key] !== 'string') issues.push(`${path}.${key}: must be a string when set`);
    if (row.allowedNodeIds !== undefined && (!Array.isArray(row.allowedNodeIds) || row.allowedNodeIds.some((id) => typeof id !== 'string'))) {
      issues.push(`${path}.allowedNodeIds: must be a string array when set`);
    }
  });
  if (record.rankMappings !== undefined && !Array.isArray(record.rankMappings)) issues.push('$.rankMappings: must be an array');
  else if (Array.isArray(record.rankMappings)) record.rankMappings.forEach((mapping, i) => {
    const path = `$.rankMappings[${i}]`;
    if (mapping === null || typeof mapping !== 'object' || Array.isArray(mapping)) { issues.push(`${path}: must be an object`); return; }
    const row = mapping as Record<string, unknown>;
    Object.keys(row).filter((key) => !['rank', 'role', 'nodeId'].includes(key)).forEach((key) => issues.push(`${path}.${key}: unknown field`));
    if (typeof row.rank !== 'number') issues.push(`${path}.rank: must be a number`);
    if (typeof row.role !== 'string') issues.push(`${path}.role: must be a string`);
    if (typeof row.nodeId !== 'string') issues.push(`${path}.nodeId: must be a string`);
  });
  if (issues.length) return { workload: null, issues };
  const result = record as unknown as WorkloadBlock;
  issues.push(...validateWorkload(result, nodeIds.length, nodeIds, vcClasses).map((message) => `$.workload: ${message}`));
  return issues.length ? { workload: null, issues } : { workload: result, issues: [] };
}

/** Deterministic, version-stamped JSON for workload intent; not a run artifact. */
export function serializeWorkloadJson(workload: WorkloadBlock): string {
  return `${JSON.stringify({ workloadSchemaVersion: 1, ...workload }, null, 2)}\n`;
}

/** Produce a deterministic, fully authored workload intent payload. This is
 * not a backend RunInput contract and is never evidence that a run executed. */
export function buildWorkloadRunIntent(
  workload: WorkloadBlock,
  nodeIds: readonly string[],
  vcClasses?: readonly number[],
): { json: string | null; issues: string[] } {
  const issues = validateWorkload(workload, nodeIds.length, nodeIds, vcClasses);
  workload.phases.forEach((phase, index) => {
    if (phase.startCycle === undefined || phase.durationCycles === undefined) {
      issues.push(`phases[${index}]: explicit startCycle and durationCycles are required for run intent`);
    }
  });
  const demand = requiredRankCount(workload);
  const mappings = workload.rankMappings ?? [];
  if (mappings.length !== demand) {
    issues.push(`rankMappings: expected ${demand} explicit rank assignments, found ${mappings.length}`);
  }
  if (issues.length) return { json: null, issues };
  return {
    json: `${JSON.stringify({ runIntentSchemaVersion: 1, workload }, null, 2)}\n`,
    issues: [],
  };
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
