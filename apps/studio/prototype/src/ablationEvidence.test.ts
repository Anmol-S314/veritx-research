import { describe, expect, it } from 'vitest';
import { comparisonIssue } from './ablationEvidence';

const identity = { trace_sha256: 'sha256:trace', arm_sha256: 'sha256:arm', binary_sha256: 'sha256:binary', simulator_seed: 1 };

describe('ablation pairing', () => {
  it('accepts matching executed identities', () => expect(comparisonIssue(identity, { ...identity })).toBeNull());
  it('refuses legacy documents without hashes', () => expect(comparisonIssue({}, {})).toContain('missing'));
  it('refuses independently regenerated traffic', () => expect(comparisonIssue(identity, { ...identity, trace_sha256: 'sha256:other' })).toContain('Trace changed'));
  it('refuses changed fabric definitions and simulator builds', () => {
    expect(comparisonIssue(identity, { ...identity, arm_sha256: 'sha256:other' })).toContain('Fabric definition changed');
    expect(comparisonIssue(identity, { ...identity, binary_sha256: 'sha256:other' })).toContain('Simulator binary changed');
  });
  it('does not manufacture a seed for old results', () => expect(comparisonIssue({ ...identity, simulator_seed: undefined }, identity)).toContain('missing'));
  it('refuses different simulator seeds', () => expect(comparisonIssue(identity, { ...identity, simulator_seed: 2 })).toContain('seed changed'));
});
