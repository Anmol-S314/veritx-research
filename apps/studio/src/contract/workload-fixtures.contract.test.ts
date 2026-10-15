import { describe, expect, it } from 'vitest';
import dense from '../../fixtures/workloads/dense-supported.json';
import moe from '../../fixtures/workloads/moe-blocked-capacity.json';
import custom from '../../fixtures/workloads/custom-invalid.json';
import { buildWorkloadRunIntent, validateWorkload, type WorkloadBlock } from '../graph/workload';

type Fixture = { case: string; expected: string; nodeIds: string[]; workload: WorkloadBlock };
const GOLDENS = [dense, moe, custom] as Fixture[];

describe('golden dense/MoE/custom workload cases', () => {
  it.each(GOLDENS)('$case is classified only by workload validation evidence', (fixture) => {
    const issues = validateWorkload(fixture.workload, fixture.nodeIds.length, fixture.nodeIds).map((i) => i.message);
    const runIntent = buildWorkloadRunIntent(fixture.workload, fixture.nodeIds);
    if (fixture.expected === 'supported-intent') {
      expect(issues).toEqual([]);
      expect(runIntent.json).toBeTruthy();
      expect(runIntent.json).toBe(buildWorkloadRunIntent(fixture.workload, fixture.nodeIds).json);
      expect(JSON.parse(runIntent.json!).runIntentSchemaVersion).toBe(1);
    } else if (fixture.expected === 'blocked-capacity') {
      expect(issues).toEqual(expect.arrayContaining([expect.stringContaining('parallelism needs 16 nodes but the graph has 2')]));
      expect(runIntent.json).toBeNull();
      expect(runIntent.issues).toEqual(expect.arrayContaining([expect.stringContaining('parallelism needs 16 nodes but the graph has 2')]));
    } else {
      expect(issues).toEqual(expect.arrayContaining([
        expect.stringContaining('dimensionName: required'),
        expect.stringContaining('customName: required'),
        expect.stringContaining('payloadBytes: must be a positive integer'),
        expect.stringContaining('trafficClass: required'),
      ]));
      expect(runIntent.json).toBeNull();
      expect(runIntent.issues.length).toBeGreaterThan(0);
    }
  });
});
