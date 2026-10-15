/** Versioned provenance vocabulary; MOCK and other origins remain explicit. */
export const PROVENANCE_STATES = ['measured', 'simulated', 'estimated', 'mocked', 'unsupported', 'blocked'] as const;
export type ProvenanceState = typeof PROVENANCE_STATES[number];
