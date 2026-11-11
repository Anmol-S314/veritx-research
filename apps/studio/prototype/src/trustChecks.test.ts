import { describe, expect, it } from 'vitest';
import { deriveTrustChecks, trustSummary } from './trustChecks';

// The fixture mirrors the known-bad shape: 48 layers × attention/MoE, one
// owner rank per stage, and a makespan that only covers 12 stages per rank.
function fixture() {
  const stages = Array.from({ length: 96 }, (_, index) => ({
    stage_id: `layer${Math.floor(index / 2)}_${index % 2 === 0 ? 'attn' : 'moe'}`,
    owner: Math.floor(index / 2) % 8,
    duration_ns: 1000,
    input_bytes: 4096,
    output_bytes: 4096,
  }));
  const project = {
    detail: { active_revision_id: 'p-test-r01' },
    request: { workload: { tp: 2, dp: 1, ep: 4, pp: 1 }, compute: { stages } },
    draftMeta: { dirty: false },
  } as any;
  const run = {
    detail: {
      run_id: 'run-test', revision_id: 'p-test-r01', bundle_id: 'bundle', evidence: { evidence_id: 'evidence' },
      evaluation: { metrics: { completion_cycles: 3722 } },
      requirements: { entries: [{ measured: 3722, required: 50000, metric_authority: 'authority', performance_result_id: 'result' }] },
      analyses: [
        { question: 'NETWORK_COMPLETION', backend_id: 'BOOKSIM_STANDALONE', status: 'EVALUATED', model_fidelity: 'NETWORK_PACKET_SIMULATION', qualification: 'QUALIFIED', normalized_metrics: [{ key: 'completion_cycles', value: 3722 }] },
        { question: 'DRAM_TIMING', backend_id: 'RAMULATOR2_HBM3_V1', status: 'EVALUATED', model_fidelity: 'MEMORY_CYCLE_SIMULATION', qualification: 'PASS', normalized_metrics: [{ key: 'completion_cycles', value: 149185 }] },
        { question: 'SYSTEM_MAKESPAN', backend_id: 'ASTRA2_EMBEDDED_BOOKSIM', status: 'EVALUATED', model_fidelity: 'SYSTEM_SIMULATION', qualification: 'QUALIFIED', native_summary: { aggregate_cycles: 14401, aggregate_exposed_comm: 2401 } },
      ],
    },
    integrity: null,
  } as any;
  return { project, run };
}

describe('trust checks', () => {
  it('flags a single-owner placement on a TP/EP-sharded model', () => {
    const { project, run } = fixture();
    const checks = deriveTrustChecks(project, run);
    expect(checks.find(check => check.id === 'placement-parallelism')?.result).toBe('FAIL');
    expect(checks.find(check => check.id === 'makespan-floor')?.result).toBe('FAIL');
    const counts = trustSummary(checks);
    expect(counts.fail).toBe(2);
    expect(counts.pass).toBeGreaterThan(5);
  });

  it('flags a draft that is not the evaluated revision', () => {
    const { project, run } = fixture();
    project.detail.active_revision_id = 'p-test-r02';
    expect(deriveTrustChecks(project, run).find(check => check.id === 'draft-revision')?.result).toBe('REVIEW');
  });

  it('surfaces a recompiled system root instead of claiming identity', () => {
    const { project, run } = fixture();
    expect(deriveTrustChecks(project, run).find(check => check.id === 'compilation-parity')?.result).toBe('PASS');
    run.detail.compilation_parity = 'RECOMPILED_CERTIFICATE_IDENTITY';
    run.detail.stored_compiled_system_hash = 'a'.repeat(64);
    run.detail.executed_compiled_system_hash = 'b'.repeat(64);
    run.detail.compilation_parity_note = 'Only certificate labels changed.';
    const check = deriveTrustChecks(project, run).find(entry => entry.id === 'compilation-parity');
    expect(check?.result).toBe('REVIEW');
    expect(check?.evidence).toContain('RECOMPILED_CERTIFICATE_IDENTITY');
    expect(check?.evidence).toContain('bbbbbbbbbbbb');
    expect(check?.detail).toBe('Only certificate labels changed.');
  });
});
