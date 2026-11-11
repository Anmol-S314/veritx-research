import { describe, expect, it } from 'vitest';
import { workloadIssues, type WorkloadForm } from './WorkloadStudio';

const form = (over: Partial<WorkloadForm> = {}): WorkloadForm => ({
  model_name: 'test workload',
  model_family: 'dense_transformer',
  tp: '8',
  dp: '1',
  ep: '1',
  pp: '1',
  collectives: [],
  profiles: [],
  stages: [],
  ...over,
});

const collective = (kind: string, dimension: string): WorkloadForm['collectives'][number] => ({
  kind,
  dimension,
  payload_bytes: '4096',
  traffic_class: 'tp_collective',
  source_rank: '',
});

describe('workload intent editor validation', () => {
  it('refuses a TP collective when TP is one rank', () => {
    const issues = workloadIssues(form({
      tp: '1',
      dp: '2',
      collectives: [collective('reducescatter', 'TP')],
    }));
    expect(issues.join(' ')).toMatch(/reducescatter over TP needs at least 2 participants; TP is 1/);
  });

  it('accepts the same collective once TP has peers', () => {
    const issues = workloadIssues(form({
      tp: '8',
      collectives: [collective('reducescatter', 'TP')],
    }));
    expect(issues).toEqual([]);
  });

  it('refuses a PP-dimension collective before the gateway does', () => {
    const issues = workloadIssues(form({
      collectives: [collective('allreduce', 'PP')],
    }));
    expect(issues.join(' ')).toMatch(/PP-dimension collectives are not supported/);
  });

  it('refuses a GLOBAL collective in a one-rank world', () => {
    const issues = workloadIssues(form({
      tp: '1',
      dp: '1',
      ep: '1',
      pp: '1',
      collectives: [collective('allreduce', 'GLOBAL')],
    }));
    expect(issues.join(' ')).toMatch(/allreduce over GLOBAL needs at least 2 participants/);
  });
});
