import { describe, expect, it } from 'vitest';
import { identityIssue, latencyThroughputFront, parseAblationDocument, workloadArms } from './workloadExplorer';

const identity = {
  trace_sha256: 'sha256:trace-a', arm_sha256: 'sha256:arm', binary_sha256: 'sha256:bin', simulator_seed: 1,
};
const run = (topology: string, latency: number, throughput: number, overrides: Record<string, unknown> = {}) => ({
  workload: 'llm_transformer', workload_label: 'LLM transformer', topology, topology_label: topology.toUpperCase(),
  family: 'MESH', nodes: 64, vcs: 2, status: 'ok',
  latency_mean: latency, latency_p95: latency * 1.5, throughput_packets_per_cycle: throughput, hops_avg: 2.5,
  completion_cycles: 1000, resource_cost: { routers: 16, crosspoints: 320, storage_flits: 512 },
  ...identity, ...overrides,
});
const doc = (runs: unknown[]) => ({ schema: 'veritx/workload-ablation/1', generated_at: '2026-10-25T21:20:42Z', common: { seed: 1, comparison_scope: 'Network-only; unequal resource budgets.' }, runs });

describe('parseAblationDocument', () => {
  it('keeps measured cells and never zero-fills unsuccessful ones', () => {
    const evidence = parseAblationDocument(doc([
      run('mesh4x4', 40, 0.4),
      run('torus4x4', 30, 0.3, { status: 'unstable', latency_mean: null }),
      run('ring16', 0, 0, { status: 'error' }),
    ]));
    expect(evidence.points).toHaveLength(1);
    expect(evidence.skipped).toBe(2);
    expect(evidence.scope).toContain('unequal resource budgets');
    expect(evidence.seed).toBe(1);
  });

  it('requires a runs array', () => {
    expect(() => parseAblationDocument({ common: {} })).toThrow(/runs/);
    expect(() => parseAblationDocument(doc([run('mesh4x4', -1, 0.4)]))).toThrow(/no successful measured cell/);
  });

  it('groups workloads with their newest label', () => {
    const evidence = parseAblationDocument(doc([run('mesh4x4', 40, 0.4), run('torus4x4', 30, 0.3)]));
    expect(evidence.workloads).toEqual([{ id: 'llm_transformer', label: 'LLM transformer' }]);
    expect(workloadArms(evidence, 'llm_transformer').map(point => point.topology)).toEqual(['torus4x4', 'mesh4x4']);
  });
});

describe('identityIssue', () => {
  it('accepts arms that share trace, simulator binary and seed even though the fabric differs', () => {
    const evidence = parseAblationDocument(doc([
      run('mesh4x4', 40, 0.4), run('torus4x4', 30, 0.3, { arm_sha256: 'sha256:arm-torus' }),
    ]));
    expect(identityIssue(workloadArms(evidence, 'llm_transformer'))).toBeNull();
  });

  it('refuses a comparison when one arm replayed a different trace', () => {
    const evidence = parseAblationDocument(doc([
      run('mesh4x4', 40, 0.4), run('torus4x4', 30, 0.3, { trace_sha256: 'sha256:trace-b' }),
    ]));
    expect(identityIssue(workloadArms(evidence, 'llm_transformer'))).toMatch(/: Trace changed/);
  });

  it('refuses a comparison when the simulator seed differs', () => {
    const evidence = parseAblationDocument(doc([
      run('mesh4x4', 40, 0.4), run('torus4x4', 30, 0.3, { simulator_seed: 2 }),
    ]));
    expect(identityIssue(workloadArms(evidence, 'llm_transformer'))).toMatch(/seed changed/);
  });
});

describe('latencyThroughputFront', () => {
  it('keeps only arms that trade latency against throughput', () => {
    const evidence = parseAblationDocument(doc([
      run('mesh4x4', 40, 0.4),
      run('torus4x4', 30, 0.3),
      run('ring16', 50, 0.2),
      run('tree4', 30, 0.4),
    ]));
    expect([...latencyThroughputFront(workloadArms(evidence, 'llm_transformer'))]).toEqual(['tree4']);
    expect([...latencyThroughputFront(workloadArms(evidence, 'llm_transformer').filter(point => point.topology !== 'tree4'))])
      .toEqual(['torus4x4', 'mesh4x4']);
  });
});
