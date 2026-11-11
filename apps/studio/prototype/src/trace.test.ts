import { describe, expect, it } from 'vitest';
import { isInjectionTraceArtifact, scanInjectionTrace, selectInjectionTrace } from './trace';

describe('injection trace artifact selection', () => {
  it('prefers the network workload trace over Ramulator internal traces', () => {
    expect(selectInjectionTrace([
      'analyses/dram_timing/ramulator/run/empty.trace',
      'analyses/network_completion/run/workload.trace',
    ])).toBe('analyses/network_completion/run/workload.trace');
  });

  it('does not treat a Ramulator empty trace as requested injections', () => {
    const path = 'analyses/dram_timing/ramulator/run/empty.trace';
    expect(isInjectionTraceArtifact(path)).toBe(false);
    expect(selectInjectionTrace([path])).toBeUndefined();
  });

  it('reads the first and last requested injection from either dialect', () => {
    const csv = scanInjectionTrace([
      'timestamp,source,destination,class,flits',
      '0,0,1,0,4',
      '12,2,3,1,2',
      '7,1,0,0,5',
    ].join('\n'));
    expect(csv).toMatchObject({
      total: 3, firstCycle: 0, lastCycle: 12, flits: 11,
      sources: 3, destinations: 3, dialect: 'CSV',
    });
    const whitespace = scanInjectionTrace('3 0 1 0 4\n9 2 3 1 2\n');
    expect(whitespace).toMatchObject({
      total: 2, firstCycle: 3, lastCycle: 9, flits: 6, dialect: 'Whitespace',
    });
  });
});
