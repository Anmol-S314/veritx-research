import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { validateProject } from '../graph/project';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

const sampleWorkload = () => ({
  modelFamily: 'transformer', modelName: 'fixture-model', parameterCount: 12000000,
  paramsB: 0.012, hiddenSize: 1024, layers: 12, seqLen: 128, batch: 2, precision: 'bf16',
  phases: [{
    id: 'phase-prefill', kind: 'prefill', tokens: 128, batch: 2, tp: 2, ep: 1, pp: 1, dp: 1,
    communicationOps: [{ kind: 'all_reduce', trafficClass: 'collective', tensorRef: 'activation', mappingRef: 'map-tp' }],
    tensorSizes: { activation: 512 }, mappingRefs: ['map-tp'],
    timingHints: { startCycle: 0, durationCycles: 100, source: 'authored estimate' },
  }],
});

describe('workload.phases project v1 contract', () => {
  it('validates optional workload phase, communication, tensor, mapping and timing fields', () => {
    const project = { ...buildPreset('ring-8'), workload: sampleWorkload() };
    expect(validateProject(project)).toEqual([]);
    const defs = SCHEMA.$defs as Record<string, any>;
    expect(defs.workloadPhase.properties.communicationOps.type).toBe('array');
    expect(defs.workloadPhase.properties.tensorSizes.type).toBe('object');
    expect(defs.workloadPhase.properties.mappingRefs.uniqueItems).toBe(true);
    expect(defs.workloadPhase.properties.timingHints.$ref).toBe('#/$defs/timingHints');
    const withoutHints = sampleWorkload();
    delete (withoutHints.phases[0] as Record<string, unknown>).timingHints;
    expect(validateProject({ ...buildPreset('ring-8'), workload: withoutHints })).toEqual([]);
  });

  it('returns canonical findings for malformed workload semantics and unknown nested fields', () => {
    const workload = sampleWorkload();
    workload.phases[0]!.tensorSizes.activation = -1;
    workload.phases[0]!.mappingRefs.push('map-tp');
    workload.phases[0]!.timingHints.startCycle = -1;
    workload.phases[0]!.communicationOps[0]!.trafficClass = '';
    workload.phases[0]!.communicationOps[0]!.mappingRef = 'missing-map';
    workload.phases[0]!.communicationOps[0]!.tensorRef = 'missing-tensor';
    (workload.phases[0] as Record<string, unknown>).mockCycleBoundary = 100;
    const issues = validateProject({ ...buildPreset('ring-8'), workload });
    expect(issues.map(issue => issue.path)).toEqual(expect.arrayContaining([
      '$.workload.phases[0].tensorSizes.activation',
      '$.workload.phases[0].mappingRefs',
      '$.workload.phases[0].timingHints.startCycle',
      '$.workload.phases[0].communicationOps[0].trafficClass',
      '$.workload.phases[0].communicationOps[0].mappingRef',
      '$.workload.phases[0].communicationOps[0].tensorRef',
      '$.workload.phases[0].mockCycleBoundary',
    ]));
    expect(issues.every(issue => issue.severity === 'error' && issue.code === 'LOOM_PROJECT_INVALID' && issue.objectRef === issue.path)).toBe(true);
  });
});
