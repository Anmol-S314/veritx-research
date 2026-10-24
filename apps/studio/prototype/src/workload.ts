import type { Draft } from './model';

export const PARTICIPANTS = ['COMPUTE_A', 'COMPUTE_B', 'MEMORY_A', 'MEMORY_B'] as const;
export type Participant = typeof PARTICIPANTS[number];
export type Operation = { id: string; kind: 'transfer' | 'compute-delay' | 'memory-access'; source: Participant; destination: Participant; bytes: number; durationNs: number; phase: string; dependsOn: string[] };
export type WorkingInputs = { name: string; sourceRevision: string; revision: number; requirementsRevision: number; assumptionsRevision: number; bindingsRevision: number; operations: Operation[]; bindings: Record<Participant, string>; transactionLimitNs: number; deliveryFloorGBps: number; computeDurationNs: number; memoryServiceNs: number | null };
export function initialInputs(): WorkingInputs {
  return {
    name: 'ResNet50_Burst · working approximation', sourceRevision: 'w12', revision: 1, requirementsRevision: 1, assumptionsRevision: 1, bindingsRevision: 1,
    bindings: { COMPUTE_A: 'EP_NPU_0', COMPUTE_B: 'EP_NPU_1', MEMORY_A: 'EP_HBM_0', MEMORY_B: 'EP_HBM_1' },
    transactionLimitNs: 25, deliveryFloorGBps: 18, computeDurationNs: 2000, memoryServiceNs: null,
    operations: [
      { id: 'OP_RD_A', kind: 'memory-access', source: 'COMPUTE_A', destination: 'MEMORY_A', bytes: 4 * 2 ** 20, durationNs: 0, phase: 'Phase 2', dependsOn: [] },
      { id: 'OP_RD_B', kind: 'memory-access', source: 'COMPUTE_B', destination: 'MEMORY_B', bytes: 4 * 2 ** 20, durationNs: 0, phase: 'Phase 2', dependsOn: [] },
      { id: 'OP_COMPUTE', kind: 'compute-delay', source: 'COMPUTE_A', destination: 'COMPUTE_A', bytes: 0, durationNs: 2000, phase: 'Phase 2', dependsOn: ['OP_RD_A'] },
      { id: 'OP_WRITE', kind: 'transfer', source: 'COMPUTE_A', destination: 'MEMORY_A', bytes: 2 * 2 ** 20, durationNs: 0, phase: 'Phase 2', dependsOn: ['OP_COMPUTE'] },
    ],
  };
}
export function validInputs(value: unknown): value is WorkingInputs {
  if (!value || typeof value !== 'object') return false;
  const w = value as WorkingInputs;
  if (typeof w.name !== 'string' || w.name.length > 120 || typeof w.sourceRevision !== 'string' || w.sourceRevision.length > 64 || ![w.revision, w.requirementsRevision, w.assumptionsRevision, w.bindingsRevision].every(n => Number.isSafeInteger(n) && n > 0)) return false;
  if (![w.transactionLimitNs, w.deliveryFloorGBps, w.computeDurationNs].every(n => Number.isFinite(n) && n > 0 && n <= 1e12) || (w.memoryServiceNs !== null && (!Number.isFinite(w.memoryServiceNs) || w.memoryServiceNs <= 0 || w.memoryServiceNs > 1e12))) return false;
  if (!w.bindings || !PARTICIPANTS.every(p => typeof w.bindings[p] === 'string' && w.bindings[p].length <= 80)) return false;
  return Array.isArray(w.operations) && w.operations.length <= 200 && w.operations.every(o => o && typeof o.id === 'string' && /^[A-Z][A-Z0-9_]{1,40}$/.test(o.id) && ['transfer', 'compute-delay', 'memory-access'].includes(o.kind) && PARTICIPANTS.includes(o.source) && PARTICIPANTS.includes(o.destination) && Number.isSafeInteger(o.bytes) && o.bytes >= 0 && o.bytes <= 2 ** 40 && Number.isFinite(o.durationNs) && o.durationNs >= 0 && o.durationNs <= 1e12 && typeof o.phase === 'string' && o.phase.length <= 80 && Array.isArray(o.dependsOn) && o.dependsOn.length <= 200 && o.dependsOn.every(d => typeof d === 'string' && /^[A-Z][A-Z0-9_]{1,40}$/.test(d)));
}
export function workloadIssues(w: WorkingInputs, draft: Draft) {
  const issues: { level: 'error' | 'warning'; operation: string; message: string }[] = [];
  if (!w.operations.length) issues.push({ level: 'error', operation: 'Workload', message: 'No operations declared. Add primitives before requesting evaluation.' });
  const ids = new Set(w.operations.map(o => o.id));
  if (ids.size !== w.operations.length) issues.push({ level: 'error', operation: 'Workload', message: 'Operation identifiers must be unique.' });
  for (const p of PARTICIPANTS) {
    const e = draft.endpoints.find(e => e.id === w.bindings[p]);
    if (!e) issues.push({ level: 'error', operation: p, message: `Binding ${p} references an unavailable endpoint.` });
    else if ((p.startsWith('MEMORY') && e.role === 'Initiator') || (p.startsWith('COMPUTE') && e.role === 'Target')) issues.push({ level: 'error', operation: p, message: 'Participant role conflicts with the declared endpoint role.' });
  }
  for (const o of w.operations) {
    if (o.kind !== 'compute-delay' && o.bytes <= 0) issues.push({ level: 'error', operation: o.id, message: 'Data movement requires a positive byte count.' });
    if (o.kind === 'compute-delay' && o.durationNs <= 0) issues.push({ level: 'error', operation: o.id, message: 'Declared compute delay must be positive.' });
    for (const dep of o.dependsOn) if (!ids.has(dep)) issues.push({ level: 'error', operation: o.id, message: `Dependency ${dep} does not exist.` });
  }
  const visiting = new Set<string>(), done = new Set<string>(); let cycle = false;
  function visit(id: string) { if (visiting.has(id)) { cycle = true; return; } if (done.has(id)) return; visiting.add(id); for (const dep of w.operations.find(o => o.id === id)?.dependsOn ?? []) if (ids.has(dep)) visit(dep); visiting.delete(id); done.add(id); }
  for (const id of ids) visit(id);
  if (cycle) issues.push({ level: 'error', operation: 'Dependencies', message: 'Dependency graph contains a cycle.' });
  if (w.memoryServiceNs === null && w.operations.some(o => o.kind === 'memory-access')) issues.push({ level: 'warning', operation: 'Memory model', message: 'Memory service duration is unspecified. Complete transaction behavior cannot be inferred.' });
  issues.push({ level: 'warning', operation: 'Backend adapter', message: 'No simulator lowering adapter is connected. Preview semantics are not an executable backend contract.' });
  return issues;
}
export function operationPreview(o: Operation, w: WorkingInputs) {
  return { sourceOperation: o.id, type: o.kind, sourceEndpoint: w.bindings[o.source], destinationEndpoint: o.kind === 'compute-delay' ? undefined : w.bindings[o.destination], requestedBytes: o.kind === 'compute-delay' ? undefined : o.bytes, minimum128BitDataFlits: o.kind === 'compute-delay' ? undefined : Math.ceil(o.bytes / 16), declaredDelayNs: o.kind === 'compute-delay' ? o.durationNs : undefined, phase: o.phase, dependencies: o.dependsOn, limitation: 'Intent preview only; packet headers, adapter timing, protocol semantics, and execution are not supplied.' };
}
