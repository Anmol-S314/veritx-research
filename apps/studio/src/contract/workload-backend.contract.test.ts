/** Workload × backend preflight classification (tracker M5-26).
 *
 *  The classifier must report `unsupported` vs `blocked` BEFORE a run and must
 *  never fabricate a metric for a backend that cannot represent the workload. */
import { describe, expect, it } from 'vitest';
import {
  classifyWorkloadBackend,
  findDeclaredBackend,
  type BackendCapability,
} from '../graph/workloadBackend';
import type { WorkloadBlock } from '../graph/workload';

const ALL_KINDS = ['allreduce', 'allgather', 'alltoall', 'reduce-scatter', 'custom'] as const;

const backend = (over: Partial<BackendCapability> = {}): BackendCapability => ({
  id: 'test-backend',
  displayName: 'Test backend',
  collectives: [...ALL_KINDS],
  precisions: ['fp16'],
  consumesPhaseCycles: true,
  maxRanks: null,
  provenance: 'declared',
  ...over,
});

const workload = (over: Partial<WorkloadBlock> = {}): WorkloadBlock => ({
  modelFamily: 'custom',
  seqLen: 1,
  batch: 1,
  precision: 'fp16',
  phases: [{ id: 'p0', kind: 'prefill', tokens: 1, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1 }],
  ...over,
});

const nodes = ['n1', 'n2', 'n3', 'n4'];

describe('M5-26: workload × backend preflight', () => {
  it('reports supported when every declared feature is representable', () => {
    const verdict = classifyWorkloadBackend(workload(), nodes, backend());
    expect(verdict).toEqual({ backendId: 'test-backend', state: 'supported', reasons: [] });
  });

  it('reports blocked (not unsupported) when the workload itself is invalid', () => {
    const verdict = classifyWorkloadBackend(workload({ phases: [] }), nodes, backend());
    expect(verdict.state).toBe('blocked');
    expect(verdict.reasons[0]!.code).toBe('workload.invalid');
  });

  it('reports unsupported with a stable code for a collective the backend cannot represent', () => {
    const w = workload({
      communications: [{ id: 'c0', kind: 'alltoall', dimension: 'tp', payloadBytes: 8, trafficClass: 'default' }],
      defaultTrafficClassMapping: { vcClass: 0, qosClass: 'default' },
    });
    const verdict = classifyWorkloadBackend(w, nodes, backend({ collectives: ['allreduce'] }));
    expect(verdict.state).toBe('unsupported');
    expect(verdict.reasons.map((r) => r.code)).toContain('workload.backend.collective');
  });

  it('reports unsupported for an unrepresentable precision', () => {
    const verdict = classifyWorkloadBackend(workload({ precision: 'fp8' }), nodes, backend({ precisions: ['fp16'] }));
    expect(verdict.state).toBe('unsupported');
    expect(verdict.reasons.map((r) => r.code)).toContain('workload.backend.precision');
  });

  it('reports unsupported when authored phase cycles would be silently dropped', () => {
    const w = workload({ phases: [{ id: 'p0', kind: 'prefill', tokens: 1, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1, startCycle: 0, durationCycles: 10 }] });
    const verdict = classifyWorkloadBackend(w, nodes, backend({ consumesPhaseCycles: false }));
    expect(verdict.state).toBe('unsupported');
    expect(verdict.reasons.map((r) => r.code)).toContain('workload.backend.phase_cycles');
  });

  it('reports unsupported when rank demand exceeds the declared backend limit', () => {
    const w = workload({ phases: [{ id: 'p0', kind: 'prefill', tokens: 1, batch: 1, tp: 4, ep: 1, pp: 1, dp: 1 }] });
    const verdict = classifyWorkloadBackend(w, nodes, backend({ maxRanks: 2 }));
    expect(verdict.state).toBe('unsupported');
    expect(verdict.reasons.map((r) => r.code)).toContain('workload.backend.ranks');
  });

  it('is deterministic and fabricates no metric fields', () => {
    const a = classifyWorkloadBackend(workload(), nodes, backend());
    const b = classifyWorkloadBackend(workload(), nodes, backend());
    expect(a).toEqual(b);
    expect(Object.keys(a).sort()).toEqual(['backendId', 'reasons', 'state']);
  });

  it('exposes only declared-provenance backends', () => {
    expect(findDeclaredBackend('booksim-standalone')?.provenance).toBe('declared');
    expect(findDeclaredBackend('does-not-exist')).toBeUndefined();
  });
});
