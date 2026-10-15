import { describe, expect, it } from 'vitest';
import PROVENANCE from '../../../../contracts/loom/v1/provenance.schema.json';
import { PROVENANCE_STATES } from '../graph/provenance';

describe('capability provenance v1', () => {
  it('defines all evidence states and explicit UI truth rules', () => {
    expect(PROVENANCE.enum).toEqual(['measured', 'simulated', 'estimated', 'mocked', 'unsupported', 'blocked']);
    expect(PROVENANCE_STATES).toEqual(PROVENANCE.enum);
    for (const state of PROVENANCE.enum as (keyof typeof PROVENANCE['x-ui-rules'])[]) expect(PROVENANCE['x-ui-rules'][state].length).toBeGreaterThan(10);
    expect(PROVENANCE['x-ui-rules'].mocked).toMatch(/never present as backend output/);
    expect(PROVENANCE['x-ui-rules'].unsupported).toMatch(/Do not show a numeric result/);
  });
});
