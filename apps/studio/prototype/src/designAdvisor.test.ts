import { describe, expect, it } from 'vitest';
import realWorkloads from '../public/data/workload_ablation.json';
import realSensitivity from '../public/data/design_sensitivity.json';
import {
  advise, buildCandidates, depthVariants, emptyConstraints, estimateArea, estimatePower, fabricModels,
  matchWorkload, parseAdvisorEvidence, parseSensitivity, selectDepth, sensitivityNotes,
  workloadReferenceLoad, type AdvisorArm, type AdvisorConstraints, type AdvisorEvidence,
  type SensitivityEvidence,
} from './designAdvisor';
import type { SweepRow } from './analysisCurves';

const ablation = {
  runs: [
    { workload: 'mixtral-8x7b-64tiles', workload_label: 'Mixtral 8×7B', topology: 'mesh8x8', topology_label: '8×8 mesh', family: 'MESH', nodes: 64, vcs: 2, routing: 'dor', status: 'ok', latency_mean: 500, latency_p95: 620, latency_p99: 700, throughput_packets_per_cycle: 0.9345, hops_avg: 3.2, completion_cycles: 12000, resource_cost: { routers: 64, storage_flits: 5120, crosspoints: 1600 }, trace_sha256: 'trace-a', binary_sha256: 'bin-a', simulator_seed: 1 },
    { workload: 'mixtral-8x7b-64tiles', workload_label: 'Mixtral 8×7B', topology: 'torus8x8', topology_label: '8×8 torus', family: 'TORUS', nodes: 64, vcs: 4, routing: 'dor', status: 'ok', latency_mean: 480, latency_p95: 587, latency_p99: 650, throughput_packets_per_cycle: 0.9384, hops_avg: 2.8, completion_cycles: 11800, resource_cost: { routers: 64, storage_flits: 5120, crosspoints: 1600 }, trace_sha256: 'trace-a', binary_sha256: 'bin-a', simulator_seed: 1 },
    { workload: 'mixtral-8x7b-64tiles', workload_label: 'Mixtral 8×7B', topology: 'gec_mecs', topology_label: 'GEC MECS', family: 'GEC_MECS', nodes: 64, vcs: 2, routing: 'mecs', status: 'ok', latency_mean: 200, latency_p95: 232, latency_p99: 300, throughput_packets_per_cycle: 0.9748, hops_avg: 1.8, completion_cycles: 9000, resource_cost: { routers: 16, storage_flits: 8192, crosspoints: 800 }, trace_sha256: 'trace-a', binary_sha256: 'bin-a', simulator_seed: 1 },
    { workload: 'mixtral-8x7b-64tiles', workload_label: 'Mixtral 8×7B', topology: 'failed', topology_label: 'Failed arm', family: 'MESH', nodes: 64, vcs: 2, routing: 'dor', status: 'failed', latency_mean: 1, latency_p95: 1, throughput_packets_per_cycle: 1 },
  ],
  workloads: [
    { workload_id: 'mixtral-8x7b-64tiles', label: 'Mixtral 8×7B', project: 'Mixtral demo', nodes: 64, events: 11200, active_nodes: 64, trace_sha256: 'trace-a' },
    { workload_id: 'moe', label: 'MoE · dispatch/combine', project: null, nodes: 64, events: 30192, active_nodes: 64, trace_sha256: 'trace-b' },
  ],
  topologies: [
    { topology_id: 'mesh8x8', family: 'MESH', support: 'product' },
    { topology_id: 'torus8x8', family: 'TORUS', support: 'product' },
    { topology_id: 'gec_mecs', family: 'GEC_MECS', support: 'research' },
    { topology_id: 'failed', family: 'MESH', support: 'product' },
  ],
} as const;

const sensitivity: SensitivityEvidence = {
  scope: 'measured buffer-depth slice',
  common: { channel_width_bits: 128 },
  skipped: 0,
  points: [
    { workload: 'mixtral-8x7b-64tiles', topology: 'mesh8x8', depth: 4, latencyMean: 510, latencyP95: 630, latencyP99: 710, throughput: 0.9340, completionCycles: 12100, hopsAvg: 3.2, storageFlits: 2560, routers: 64, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, source: 'depth 4' },
    { workload: 'mixtral-8x7b-64tiles', topology: 'mesh8x8', depth: 8, latencyMean: 500, latencyP95: 620, latencyP99: 700, throughput: 0.9345, completionCycles: 12000, hopsAvg: 3.2, storageFlits: 5120, routers: 64, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, source: 'depth 8' },
    { workload: 'mixtral-8x7b-64tiles', topology: 'mesh8x8', depth: 16, latencyMean: 450, latencyP95: 558, latencyP99: 640, throughput: 0.9360, completionCycles: 11700, hopsAvg: 3.2, storageFlits: 10240, routers: 64, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, source: 'depth 16' },
    { workload: 'mixtral-8x7b-64tiles', topology: 'torus8x8', depth: 4, latencyMean: 481, latencyP95: 589, latencyP99: 652, throughput: 0.9380, completionCycles: 11810, hopsAvg: 2.8, storageFlits: 2560, routers: 64, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, source: 'depth 4' },
    { workload: 'mixtral-8x7b-64tiles', topology: 'torus8x8', depth: 8, latencyMean: 480, latencyP95: 587, latencyP99: 650, throughput: 0.9384, completionCycles: 11800, hopsAvg: 2.8, storageFlits: 5120, routers: 64, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, source: 'depth 8' },
    { workload: 'mixtral-8x7b-64tiles', topology: 'torus8x8', depth: 16, latencyMean: 478, latencyP95: 585, latencyP99: 648, throughput: 0.9385, completionCycles: 11790, hopsAvg: 2.8, storageFlits: 10240, routers: 64, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, source: 'depth 16' },
  ],
};

const sweep: SweepRow[] = [
  { topology: 'mesh4x4', family: 'MESH', injection_rate: 0.005, status: 'ok', endpoints: 16, routers: 16, native_power_w: 4.11, native_area_mm2: 0.281, native_model: { status: 'AVAILABLE', model_id: 'model-1', technology: '32nm' } },
  { topology: 'mesh4x4', family: 'MESH', injection_rate: 0.02, status: 'ok', endpoints: 16, routers: 16, native_power_w: 11.16, native_area_mm2: 0.281, native_model: { status: 'AVAILABLE', model_id: 'model-1', technology: '32nm' } },
  { topology: 'torus4x4', family: 'TORUS', injection_rate: 0.005, status: 'ok', endpoints: 16, routers: 16, native_power_w: 3.82, native_area_mm2: 0.281, native_model: { status: 'AVAILABLE', model_id: 'model-1', technology: '32nm' } },
  { topology: 'torus4x4', family: 'TORUS', injection_rate: 0.02, status: 'ok', endpoints: 16, routers: 16, native_power_w: 9.93, native_area_mm2: 0.281, native_model: { status: 'AVAILABLE', model_id: 'model-1', technology: '32nm' } },
  { topology: 'cmesh16', family: 'CONCENTRATED_MESH', injection_rate: 0.005, status: 'ok', endpoints: 16, routers: 4, native_power_w: 2.65, native_area_mm2: 0.158, native_model: { status: 'AVAILABLE', model_id: 'model-1', technology: '32nm' } },
  { topology: 'cmesh16', family: 'CONCENTRATED_MESH', injection_rate: 0.02, status: 'ok', endpoints: 16, routers: 4, native_power_w: 7.55, native_area_mm2: 0.158, native_model: { status: 'AVAILABLE', model_id: 'model-1', technology: '32nm' } },
];

const evidence: AdvisorEvidence = parseAdvisorEvidence(ablation);
const constraints = (patch: Partial<AdvisorConstraints> = {}): AdvisorConstraints => ({ ...emptyConstraints(), ...patch });
const arm = (topology: string): AdvisorArm => evidence.arms.find(item => item.topology === topology)!;

describe('workload evidence', () => {
  it('excludes failed cells and preserves support', () => {
    expect(evidence.skipped).toBe(1);
    expect(evidence.arms.map(item => item.topology)).toEqual(['mesh8x8', 'torus8x8', 'gec_mecs']);
    expect(arm('gec_mecs').support).toBe('research');
  });

  it('matches a project workload by name without confusing the MoE examples', () => {
    expect(matchWorkload(evidence.workloads, ['moe-8x7b', 'Mixtral 8x7B 64-tile dense demo'])).toBe('mixtral-8x7b-64tiles');
    expect(matchWorkload(evidence.workloads, ['qwen3-moe'])).toBe('moe');
  });

  it('snaps the measured demand to a common offered load', () => {
    const result = workloadReferenceLoad(evidence.arms);
    expect(result.median).toBeCloseTo(0.9384 / 64, 5);
    expect(result.load).toBe(0.01);
  });
});

describe('native-model screening', () => {
  it('keeps a per-endpoint reference instead of pretending it ran at 64 endpoints', () => {
    const models = fabricModels(sweep, 0.02);
    const mesh = models.get('MESH')!;
    expect(mesh.referenceEndpoints).toBe(16);
    expect(mesh.referenceLoad).toBe(0.02);
    expect(estimatePower(mesh, 64).value).toBeCloseTo(11.16 / 16 * 64, 5);
    expect(estimateArea(mesh, 64).value).toBeCloseTo(0.281 / 16 * 64, 5);
    expect(estimatePower(undefined, 64).value).toBeNull();
  });

  it('chooses the family reference nearest the requested load', () => {
    const models = fabricModels(sweep, 0.005);
    expect(models.get('TORUS')!.referenceLoad).toBe(0.005);
  });
});

describe('buffer depth', () => {
  it('uses measured depth variants and picks the fastest depth for latency', () => {
    const variants = selectDepth([
      { depth: 4, latencyMean: 510, latencyP95: 630, latencyP99: 710, throughput: 0.9340, completionCycles: 12100, storageFlits: 2560, measured: true, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: true, identityNote: null, source: 'depth 4' },
      { depth: 8, latencyMean: 500, latencyP95: 620, latencyP99: 700, throughput: 0.9345, completionCycles: 12000, storageFlits: 5120, measured: true, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: true, identityNote: null, source: 'depth 8' },
      { depth: 16, latencyMean: 450, latencyP95: 558, latencyP99: 640, throughput: 0.9360, completionCycles: 11700, storageFlits: 10240, measured: true, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: true, identityNote: null, source: 'depth 16' },
    ], 'latency', constraints());
    expect(variants.variant.depth).toBe(16);
    expect(variants.reason).toContain('measured');
  });

  it('keeps the shallowest measured depth that does not cost performance when power is the priority', () => {
    const selected = selectDepth([
      { depth: 4, latencyMean: 510, latencyP95: 630, latencyP99: 710, throughput: 0.9340, completionCycles: 12100, storageFlits: 2560, measured: true, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: true, identityNote: null, source: 'depth 4' },
      { depth: 8, latencyMean: 500, latencyP95: 620, latencyP99: 700, throughput: 0.9345, completionCycles: 12000, storageFlits: 5120, measured: true, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: true, identityNote: null, source: 'depth 8' },
      { depth: 16, latencyMean: 450, latencyP95: 558, latencyP99: 640, throughput: 0.9360, completionCycles: 11700, storageFlits: 10240, measured: true, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: true, identityNote: null, source: 'depth 16' },
    ], 'power', constraints());
    expect(selected.variant.depth).toBe(8);
  });

  it('does not invent a depth when the workload has no sweep', () => {
    const selected = selectDepth([
      { depth: 8, latencyMean: 1, latencyP95: 2, latencyP99: null, throughput: 3, completionCycles: 4, storageFlits: 5, measured: false, traceSha256: 'trace-a', binarySha256: 'bin-a', simulatorSeed: 1, identityVerified: false, identityNote: null, source: 'reference' },
    ], 'latency', constraints());
    expect(selected.variant.depth).toBe(8);
    expect(selected.reason).toContain('no depth sweep');
  });

  it('rejects a depth slice whose experiment identity changed', () => {
    const changed: SensitivityEvidence = {
      ...sensitivity,
      points: sensitivity.points.map(point => point.topology === 'mesh8x8' && point.depth === 16
        ? { ...point, traceSha256: 'different-trace' }
        : point),
    };
    const variants = depthVariants(arm('mesh8x8'), changed);
    expect(variants).toHaveLength(1);
    expect(variants[0].depth).toBe(8);
    expect(variants[0].identityVerified).toBe(false);
    expect(variants[0].identityNote).toContain('trace');
  });
});

describe('constrained recommendation', () => {
  it('ranks measured arms and keeps research arms behind an explicit switch', () => {
    const result = advise(evidence.arms, sweep, sensitivity, constraints(), 'latency');
    expect(result.ranked[0].arm.topology).toBe('mesh8x8');
    expect(result.ranked[0].depth).toBe(16);
    expect(result.ranked.some(candidate => candidate.arm.topology === 'gec_mecs')).toBe(false);
    const withResearch = advise(evidence.arms, sweep, sensitivity, constraints({ includeResearch: true }), 'latency');
    expect(withResearch.ranked[0].arm.topology).toBe('gec_mecs');
    expect(withResearch.ranked[0].powerW).toBeNull();
  });

  it('treats an unavailable modeled metric as a failed constraint, never as zero', () => {
    const result = advise(evidence.arms, sweep, sensitivity, constraints({ includeResearch: true, maxPowerW: 50 }), 'latency');
    const gec = result.candidates.find(candidate => candidate.arm.topology === 'gec_mecs')!;
    expect(gec.powerW).toBeNull();
    expect(gec.feasible).toBe(false);
    expect(gec.verdicts.find(verdict => verdict.key === 'maxPowerW')!.authority).toBe('UNAVAILABLE');
  });

  it('filters by latency and throughput before ranking', () => {
    const result = advise(evidence.arms, sweep, sensitivity, constraints({ maxLatencyP95: 600, minThroughput: 0.93 }), 'latency');
    expect(result.ranked.every(candidate => candidate.latencyP95 <= 600 && candidate.throughput >= 0.93)).toBe(true);
    expect(result.ranked[0].arm.topology).toBe('mesh8x8');
  });

  it('reports a measured flip threshold instead of extrapolating', () => {
    const result = advise(evidence.arms, sweep, sensitivity, constraints(), 'latency');
    const notes = sensitivityNotes(result.candidates, 'latency', constraints());
    expect(notes.length).toBeGreaterThan(0);
    const throughputNote = notes.find(note => note.key === 'minThroughput');
    expect(throughputNote?.threshold).toBe(0.9385);
    expect(throughputNote?.winnerLabel).toBe('8×8 torus at 16 flits/VC');
  });

  it('keeps a candidate table with an explicit depth choice', () => {
    const candidates = buildCandidates(evidence.arms, fabricModels(sweep, 0.005), sensitivity, constraints(), 'latency');
    const mesh = candidates.find(candidate => candidate.arm.topology === 'mesh8x8')!;
    expect(mesh.depth).toBe(16);
    expect(mesh.latencyP95).toBe(558);
    expect(mesh.powerW).not.toBeNull();
  });
});

describe('shipped evidence', () => {
  it('carries a measured depth slice for every product arm and workload', () => {
    const shipped = parseAdvisorEvidence(realWorkloads);
    const slice = parseSensitivity(realSensitivity);
    const productArms = shipped.arms.filter(arm => arm.support === 'product');
    expect(shipped.workloads).toHaveLength(11);
    expect(productArms).toHaveLength(55);
    for (const arm of productArms) {
      const depths = depthVariants(arm, slice).map(variant => variant.depth);
      expect(depths).toEqual([4, 8, 16]);
    }
    expect(slice.points).toHaveLength(242);
    expect(slice.skipped).toBe(0);
  });
});

describe('sensitivity parsing', () => {
  it('skips incomplete rows rather than filling them', () => {
    const parsed = parseSensitivity({
      scope: 'test',
      common: {},
      points: [
        { workload: 'a', topology: 'b', depth: 8, latency_mean: 1, latency_p95: 2, throughput: 3, status: 'ok' },
        { workload: 'a', topology: 'b', depth: 16, latency_mean: 1, latency_p95: null, throughput: 3, status: 'ok' },
      ],
    });
    expect(parsed.points).toHaveLength(1);
    expect(parsed.skipped).toBe(1);
  });
});
