import { describe, expect, it } from 'vitest';
import { evidenceFamilyKey } from './finalEvidence';

const support = (kind: string | null, family: string | null = null) => ({ topology_kind: kind, topology_family: family } as never);

describe('evidenceFamilyKey', () => {
  it('resolves GEC hybrid and multidrop to their evidence family names', () => {
    expect(evidenceFamilyKey(support('gec'), { topology: { kind: 'gec', mode: 'HYBRID' } })).toBe('gec_hybrid');
    expect(evidenceFamilyKey(support('gec'), { topology: { kind: 'gec', mode: 'MULTIDROP' } })).toBe('gec_mecs');
  });

  it('keeps an already-specific family and returns null when nothing is known', () => {
    expect(evidenceFamilyKey(support('gec_hybrid'), {})).toBe('gec_hybrid');
    expect(evidenceFamilyKey(support('mesh'), {})).toBe('mesh');
    expect(evidenceFamilyKey(null, null)).toBeNull();
  });
});
