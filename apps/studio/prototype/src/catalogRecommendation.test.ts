import { describe, expect, test } from 'vitest';
import { catalogBarWidth, catalogFacts, catalogFrontier, catalogProfiles, catalogTradeoff, catalogTradeoffPoints, type CatalogRowLike } from './catalogRecommendation';

const evaluated = (completion: number | null, makespan: number | null) => [
  ...(completion === null ? [] : [{ question: 'NETWORK_COMPLETION', status: 'EVALUATED', normalized_metrics: [{ key: 'completion_cycles', value: completion }] }]),
  ...(makespan === null ? [] : [{ question: 'SYSTEM_MAKESPAN', status: 'EVALUATED', normalized_metrics: [{ key: 'system_makespan_cycles', value: makespan }] }]),
];

const row = (id: string, completion: number | null, makespan: number | null, extra: Partial<CatalogRowLike> = {}): CatalogRowLike => ({
  topology_id: id, label: id, selectable: true, requires_backend_ack: false, requirements_pass: true,
  analyses: evaluated(completion, makespan) as CatalogRowLike['analyses'], ...extra,
});

const rows: CatalogRowLike[] = [
  // Fast network, slow system: a real trade-off, not a single winner.
  row('mesh', 1000, 5000),
  row('fattree', 1100, 4000),
  // Refused by every backend: no measurement, so it cannot win anything.
  { topology_id: 'torus', label: 'torus', selectable: false, requires_backend_ack: true, analyses: [{ question: 'NETWORK_COMPLETION', status: 'UNSUPPORTED' }], reason: 'deadlock certificate failed' },
  // Network only: plottable on one axis only.
  row('ring_native', 900, null, { requires_backend_ack: true }),
  // Fast on both but fails a declared requirement: measured, not eligible.
  row('flatfly', 500, 3000, { selectable: false, requirements_pass: false }),
];

describe('catalog recommendations', () => {
  test('a refusal or an unmet requirement never becomes a winner', () => {
    const profiles = catalogProfiles(catalogFacts(rows));
    const winners = profiles.map(profile => profile.winner?.id);
    expect(winners).not.toContain('torus');
    expect(winners).not.toContain('flatfly');
  });

  test('network and system profiles rank their own measured scope only', () => {
    const [network, system] = catalogProfiles(catalogFacts(rows));
    expect(network.winner?.id).toBe('ring_native');
    expect(system.winner?.id).toBe('fattree');
  });

  test('balanced keeps only fabrics with both scopes and prefers the non-dominated pair', () => {
    const facts = catalogFacts(rows);
    expect(catalogFrontier(facts).map(fact => fact.id).sort()).toEqual(['fattree', 'mesh']);
    const balanced = catalogProfiles(facts).find(profile => profile.id === 'balanced')!;
    // mesh: rank0 network + rank1 system; fattree: rank1 + rank0 — a deterministic tie.
    expect(['mesh', 'fattree']).toContain(balanced.winner?.id);
    expect(balanced.eligible.every(fact => fact.network !== null && fact.system !== null)).toBe(true);
  });

  test('the evidence profile requires both backends, not merely a fast number', () => {
    const evidence = catalogProfiles(catalogFacts(rows)).find(profile => profile.id === 'evidence')!;
    expect(evidence.eligible.map(fact => fact.id).sort()).toEqual(['fattree', 'mesh']);
    expect(evidence.winner?.id).toBe('mesh');
  });

  test('a sub-resolution gap is a tie, not a winner', () => {
    const facts = catalogFacts([
      row('mesh', 1000, 5000),
      row('torus', 1005, 5000),
    ]);
    const [network] = catalogProfiles(facts);
    expect(network.winner).toBeNull();
    expect(network.tie).toBe(true);
    expect(network.reason).toContain('tie within 1.5%');
  });

  test('a gap above the band still names a winner', () => {
    const facts = catalogFacts([
      row('mesh', 1000, 5000),
      row('torus', 1200, 5000),
    ]);
    const [network] = catalogProfiles(facts);
    expect(network.winner?.id).toBe('mesh');
    expect(network.tie).toBe(false);
  });

  test('a missing scope is never plotted or silently substituted', () => {
    const points = catalogTradeoffPoints(catalogFacts(rows));
    expect(points.map(point => point.id).sort()).toEqual(['fattree', 'mesh']);
    expect(points.find(point => point.id === 'mesh')?.front).toBe(true);
  });

  test('an empty campaign states why instead of inventing a winner', () => {
    const profiles = catalogProfiles([]);
    expect(profiles.every(profile => profile.winner === null && profile.reason.length > 0)).toBe(true);
    expect(catalogTradeoffPoints([])).toEqual([]);
  });

  test('trade-off copy compares two measured scopes without fusing them', () => {    const facts = catalogFacts(rows);
    const mesh = facts.find(fact => fact.id === 'mesh')!;
    const fattree = facts.find(fact => fact.id === 'fattree')!;
    expect(catalogTradeoff(mesh, fattree)).toContain('network cycles');
    expect(catalogTradeoff(mesh, fattree)).toContain('makespan cycles');
    expect(catalogTradeoff(mesh, mesh)).toContain('Reference configuration');
    // Identical scope values are named, not printed as "−0".
    expect(catalogTradeoff(facts.find(f => f.id === 'mesh')!, { ...facts.find(f => f.id === 'mesh')!, id: 'other' })).toContain('same network cycles');
  });

  test('a relative bar is full for the best value and empty for a missing one', () => {
    expect(catalogBarWidth(100, [100, 200, 400])).toBe(100);
    expect(catalogBarWidth(400, [100, 200, 400])).toBe(6);
    expect(catalogBarWidth(null, [100, 200])).toBe(0);
    expect(catalogBarWidth(100, [100])).toBe(100);
    expect(catalogBarWidth(100, [])).toBe(0);
  });
});
