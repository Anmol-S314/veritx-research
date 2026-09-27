import type { Candidate } from './types';

/** Human identity for a design, derived from the DESIGN itself.
 *
 *  `cand_cf01ae…` is not something an engineer can reason about, and a hash is
 *  not a design. The label is the design: topology · link width · concentration.
 *  The immutable candidate id stays available in tooltips and in Engineering
 *  details — it just does not get to be the thing you read first.
 *
 *  Values not changed by the patch are read from the base design, so every
 *  candidate label describes a COMPLETE design, not only its diff.
 */
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

/** The GUIDED knobs this candidate CHANGED, as base → candidate pairs. */
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
