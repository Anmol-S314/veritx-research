import type { Candidate } from './types';

export function candidateLabel(
  candidate: Pick<Candidate, 'guided_patch'>,
  base: Record<string, unknown> | null | undefined,
): string {
  const patch = (candidate.guided_patch ?? {}) as Record<string, unknown>;
  const val = (k: string): unknown =>
    patch[k] !== undefined ? patch[k] : base?.[k];
  const parts: string[] = [];
  const fam = val('topology_family');
  if (fam !== undefined && fam !== null && fam !== '') {
    parts.push(String(fam));
  }
  const width = val('link_width');
  if (width !== undefined && width !== null && width !== '') {
    parts.push(`${width}b`);
  }
  const conc = val('concentration');
  if (conc !== undefined && conc !== null && conc !== '') {
    parts.push(`c${conc}`);
  }
  return parts.join(' · ') || 'base design';
}

export function guidedDelta(
  candidate: Pick<Candidate, 'guided_patch'>,
  base: Record<string, unknown> | null | undefined,
): { name: string; from: string; to: string }[] {
  const patch = (candidate.guided_patch ?? {}) as Record<string, unknown>;
  const out: { name: string; from: string; to: string }[] = [];
  for (const key of Object.keys(patch).sort()) {
    const to = patch[key];
    const from = base?.[key];
    out.push({
      name: HUMAN_KNOB[key] ?? key,
      from: from === undefined || from === null ? '—' : String(from),
      to: to === undefined || to === null ? '—' : String(to),
    });
  }
  return out;
}

const HUMAN_KNOB: Record<string, string> = {
  link_width: 'Link width',
  topology_family: 'Topology',
  concentration: 'Concentration',
  radix: 'Radix',
  rcu_enabled: 'RCU',
  arbitration: 'Arbitration',
  mcast_groups: 'Multicast groups',
  mcast_setup_cycles: 'Multicast setup',
};
