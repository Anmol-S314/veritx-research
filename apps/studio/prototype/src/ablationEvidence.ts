// Shared pairing rule: a workload/arm label is not experimental identity.
export type AblationIdentity = {
  trace_sha256?: string;
  arm_sha256?: string;
  binary_sha256?: string;
  simulator_seed?: number;
};

export function comparisonIssue(before: AblationIdentity, after: AblationIdentity): string | null {
  for (const [key, label] of [
    ['trace_sha256', 'Trace'],
    ['arm_sha256', 'Fabric definition'],
    ['binary_sha256', 'Simulator binary'],
  ] as const) {
    if (!before[key] || !after[key]) return `${label} identity is missing; a paired delta is not verified.`;
    if (before[key] !== after[key]) return `${label} changed; this is not a matched-trace knob comparison.`;
  }
  if (before.simulator_seed === undefined || after.simulator_seed === undefined) {
    return 'Simulator seed is missing; a paired delta is not verified.';
  }
  if (before.simulator_seed !== after.simulator_seed) return 'Simulator seed changed; use matched seeds for a paired delta.';
  return null;
}
