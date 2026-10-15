import { describe, expect, it } from 'vitest';
import { validateProject } from '../graph/project';
import WORKLOAD_BOUND from '../graph/fixtures/workload-bound-graph.json';

describe('VC/QoS project v1 contract', () => {
  it('accepts the typed workload-bound VC, traffic-class and arbitration example', () => {
    expect(validateProject(WORKLOAD_BOUND)).toEqual([]);
  });

  it('rejects dangling/duplicate VC and traffic-class references with canonical findings', () => {
    const project = structuredClone(WORKLOAD_BOUND);
    project.vcConfig.virtualChannels[1]!.id = project.vcConfig.virtualChannels[0]!.id;
    project.vcConfig.trafficClassMap[0]!.vcId = 'missing-vc';
    project.vcConfig.trafficClassMap[0]!.trafficClass = project.vcConfig.trafficClassMap[1]!.trafficClass;
    (project.vcConfig.arbitration.weightByTrafficClass as Record<string, number>).missing_class = 0;
    (project.vcConfig.virtualChannels[0] as Record<string, unknown>).viewOnlyDepth = 9;
    const issues = validateProject(project);
    expect(issues.map(issue => issue.path)).toEqual(expect.arrayContaining([
      '$.vcConfig.virtualChannels[1].id',
      '$.vcConfig.trafficClassMap[0].vcId',
      '$.vcConfig.trafficClassMap[1].trafficClass',
      '$.vcConfig.trafficClassMap[1].vcId',
      '$.vcConfig.arbitration.weightByTrafficClass.collective',
      '$.vcConfig.arbitration.weightByTrafficClass.missing_class',
      '$.vcConfig.virtualChannels[0].viewOnlyDepth',
    ]));
    expect(issues.every(issue => issue.severity === 'error' && issue.code === 'LOOM_PROJECT_INVALID' && issue.objectRef === issue.path)).toBe(true);
  });
});
