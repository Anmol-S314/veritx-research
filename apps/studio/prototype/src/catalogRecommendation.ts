/** Measured-catalog recommendations, mirroring the reference catalog's four
 *  profile cards. Every number here comes from the campaign's own rows; a
 *  profile with no eligible row names why instead of inventing a winner.
 *  Network completion and system makespan are separate measurement scopes:
 *  they are shown side by side, never added into one score. */

export type CatalogRowLike = {
  topology_id: string;
  label: string;
  selectable?: boolean;
  requires_backend_ack?: boolean;
  requirements_pass?: boolean | null;
  reason?: string | null;
  objective_values?: Record<string, number | null> | null;
  analyses?: ({ question: string; status: string; normalized_metrics?: { key: string; value: number | null }[] | null } | null)[] | null;
};

export type CatalogFacts = {
  id: string;
  label: string;
  selectable: boolean;
  requiresBackendAck: boolean;
  requirementsPass: boolean | null;
  network: number | null;
  system: number | null;
  reason: string;
};

export type CatalogProfile = {
  id: 'network' | 'system' | 'balanced' | 'evidence';
  label: string;
  description: string;
  winner: CatalogFacts | null;
  /** True when the top rank is a tie inside the model's resolution band. */
  tie: boolean;
  eligible: CatalogFacts[];
  reason: string;
};

/** A 1.5% cycle band is the resolution this model has earned. Without it a
 *  10-cycle difference on an 8,000-cycle run becomes a false "winner". */
export const CATALOG_TIE_BAND = 0.015;

const measured = (row: CatalogRowLike, question: string, key: string): number | null => {
  const analysis = (row.analyses ?? []).find(item => item?.question === question);
  if (!analysis || analysis.status !== 'EVALUATED') return null;
  const metric = (analysis.normalized_metrics ?? []).find((item: { key: string } | null) => item?.key === key) as { value?: number | null } | undefined;
  const value = metric?.value ?? null;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
};

export function catalogFacts(rows: CatalogRowLike[]): CatalogFacts[] {
  return rows.map(row => ({
    id: row.topology_id,
    label: row.label || row.topology_id,
    selectable: row.selectable === true,
    requiresBackendAck: row.requires_backend_ack === true,
    requirementsPass: row.requirements_pass ?? null,
    network: measured(row, 'NETWORK_COMPLETION', 'completion_cycles'),
    system: measured(row, 'SYSTEM_MAKESPAN', 'system_makespan_cycles'),
    reason: row.reason ?? '',
  }));
}

/** Only evidence-verified rows that satisfy the declared requirements can win.
 *  A refusal never becomes a zero-valued result. */
const eligibleFor = (facts: CatalogFacts[], needs: ('network' | 'system')[]): CatalogFacts[] =>
  facts.filter(fact => fact.selectable && needs.every(key => fact[key] !== null));

const topBand = (rows: CatalogFacts[], key: 'network' | 'system'): CatalogFacts[] => {
  if (!rows.length) return [];
  const best = Math.min(...rows.map(row => row[key] as number));
  const band = best * CATALOG_TIE_BAND;
  return rows.filter(row => (row[key] as number) <= best + band);
};



/** Non-dominated set on the two measured scopes (lower is better). */
export function catalogFrontier(facts: CatalogFacts[]): CatalogFacts[] {
  const both = eligibleFor(facts, ['network', 'system']);
  return both.filter(row => !both.some(other => other !== row
    && (other.network as number) <= (row.network as number)
    && (other.system as number) <= (row.system as number)
    && ((other.network as number) < (row.network as number) || (other.system as number) < (row.system as number))));
}

export function catalogProfiles(facts: CatalogFacts[]): CatalogProfile[] {
  const both = eligibleFor(facts, ['network', 'system']);
  const networkRows = eligibleFor(facts, ['network']);
  const systemRows = eligibleFor(facts, ['system']);
  const evidenceRows = facts.filter(fact => fact.selectable && !fact.requiresBackendAck);

  const networkTop = topBand(networkRows, 'network');
  const systemTop = topBand(systemRows, 'system');
  const evidenceTop = topBand(evidenceRows.filter(fact => fact.network !== null), 'network');
  const networkWinner = networkTop.length === 1 ? networkTop[0] : null;
  const systemWinner = systemTop.length === 1 ? systemTop[0] : null;
  const evidenceWinner = evidenceTop.length === 1 ? evidenceTop[0] : null;
  const frontier = catalogFrontier(facts);
  // Balanced ranks each scope separately and picks the lowest rank sum. It is a
  // deterministic tie-break over two named objectives, not a fused score.
  const byNetwork = [...both].sort((a, b) => (a.network as number) - (b.network as number) || a.id.localeCompare(b.id));
  const bySystem = [...both].sort((a, b) => (a.system as number) - (b.system as number) || a.id.localeCompare(b.id));
  const balancedWinner = both.length
    ? [...both].sort((a, b) => (byNetwork.indexOf(a) + bySystem.indexOf(a)) - (byNetwork.indexOf(b) + bySystem.indexOf(b)) || a.id.localeCompare(b.id))[0]
    : null;

  const why = (top: CatalogFacts[], winner: CatalogFacts | null, empty: string, hint: string) => {
    if (winner) return hint;
    if (top.length > 1) return `${top.map(fact => fact.label).join(', ')} tie within ${(CATALOG_TIE_BAND * 100).toFixed(1)}%`;
    return empty;
  };
  return [
    { id: 'network', label: 'Network', description: 'Lowest measured network completion in BookSim. It excludes compute and memory.', winner: networkWinner, tie: networkTop.length > 1, eligible: networkRows,
      reason: why(networkTop, networkWinner, `No fabric carries a measured network completion. ${facts.length} candidate${facts.length === 1 ? '' : 's'} ran.`, 'Ranked on network completion cycles alone.') },
    { id: 'system', label: 'System', description: 'Lowest measured system makespan in ASTRA-SIM, including declared compute stages.', winner: systemWinner, tie: systemTop.length > 1, eligible: systemRows,
      reason: why(systemTop, systemWinner, 'No fabric carries a measured system makespan. Declare compute stages and check the ASTRA verdicts.', 'Ranked on system makespan cycles alone.') },
    { id: 'balanced', label: 'Balanced', description: 'Non-dominated on both scopes; ranks are summed, no fused score is invented.', winner: balancedWinner, tie: false, eligible: frontier,
      reason: why(balancedWinner ? [balancedWinner] : [], balancedWinner, 'No fabric has both measurements, so the scopes cannot be compared row by row.', `${frontier.length} fabric${frontier.length === 1 ? '' : 's'} on the network/system frontier.`) },
    { id: 'evidence', label: 'Best evidenced', description: 'Both backends measured and requirements satisfied, then fastest network.', winner: evidenceWinner, tie: evidenceTop.length > 1, eligible: evidenceRows,
      reason: why(evidenceTop, evidenceWinner, 'No fabric completed both backends with every requirement satisfied.', 'Prefers complete evidence over speed; a missing backend is not a zero.') },
  ];
}

export type CatalogScatterPoint = { id: string; label: string; x: number; y: number; front: boolean };

/** Only fabrics that satisfy the declared requirements and carry both
 *  measurements are plotted. The shared scatter legend calls every point
 *  "eligible", so an ineligible row would be mislabelled; refusals and unmet
 *  requirements stay visible in the measured table instead. */
export function catalogTradeoffPoints(facts: CatalogFacts[]): CatalogScatterPoint[] {
  const frontier = new Set(catalogFrontier(facts).map(fact => fact.id));
  return facts
    .filter(fact => fact.selectable && fact.network !== null && fact.system !== null)
    .map(fact => ({ id: fact.id, label: fact.label, x: fact.network as number, y: fact.system as number, front: frontier.has(fact.id) }));
}

/** Relative bar for one measured scope. Lower is better, so the smallest
 *  measured value fills the bar. A missing value draws nothing rather than an
 *  invented position. */
export function catalogBarWidth(value: number | null, values: (number | null)[]): number {
  if (value === null || !Number.isFinite(value)) return 0;
  const finite = values.filter((item): item is number => item !== null && Number.isFinite(item));
  if (finite.length < 2) return finite.length === 1 ? 100 : 0;
  const low = Math.min(...finite), high = Math.max(...finite);
  if (high === low) return 100;
  return Math.max(6, Math.min(100, ((high - value) / (high - low)) * 100));
}

export function catalogTradeoff(winner: CatalogFacts | null, reference: CatalogFacts | null): string {
  if (!winner || !reference || winner.id === reference.id) return 'Reference configuration for this profile.';
  const network = winner.network !== null && reference.network !== null ? reference.network - winner.network : null;
  const system = winner.system !== null && reference.system !== null ? reference.system - winner.system : null;
  const delta = (value: number | null, unit: string) => value === null ? null
    : value === 0 ? `same ${unit}`
      : `${value > 0 ? '−' : '+'}${Math.abs(value).toLocaleString()} ${unit}`;
  const parts = [delta(network, 'network cycles'), delta(system, 'makespan cycles')].filter(Boolean);
  return parts.length ? `Versus Balanced: ${parts.join(' · ')}.` : 'No comparable pair with Balanced.';
}
