import { describe, expect, it } from 'vitest';
import { discoverFabricDomain, fabricComparisonFamilies, fabricGrid, rankMeasured, type FabricParameter } from './recommendation';
import type { OptimizationStudyCandidate } from './gateway';
const candidate = (id: string, value: number): OptimizationStudyCandidate => ({ candidate_id: id, evaluation_status: 'EVALUATED', evaluation_authority: 'certified-backend', pareto_eligible: true, objective_values: { completion_cycles: value }, objective_availability: { completion_cycles: 'MEASURED' }, constraint_verdicts: { completion_cycles: 'SATISFIED' } });
describe('fabric shortlist', () => {
  it('retains the executable baseline within the four-candidate budget', () => {
    expect(fabricComparisonFamilies(['MESH', 'TORUS', 'RING', 'TREE', 'SROTA', 'MESH'], 'srota')).toEqual(['SROTA', 'MESH', 'TORUS', 'RING']);
  });
  it('excludes unsupported typed family conversions from the submitted shortlist', () => {
    expect(fabricComparisonFamilies(['mesh', 'srota', 'torus', 'concentrated_mesh'], 'mesh', true)).toEqual(['mesh', 'torus', 'concentrated_mesh']);
    expect(fabricComparisonFamilies(['mesh', 'srota'], 'srota', true)).toEqual([]);
  });
  it('does not invent support for an unavailable baseline or missing families', () => {
    expect(fabricComparisonFamilies(['MESH', 'TORUS'], 'custom')).toEqual(['MESH', 'TORUS']);
    expect(fabricComparisonFamilies([], 'mesh')).toEqual([]);
  });
});
describe('bounded multi-knob discovery', () => {
  const parameters: FabricParameter[] = [
    { name: 'topology_family', kind: 'enum', executable: true, qualified_for_certified_optimization: true, executable_values: ['mesh', 'torus', 'srota'] },
    ...['link_width', 'concentration', 'radix'].map(name => ({ name, kind: 'int', executable: true, qualified_for_certified_optimization: true })),
  ];
  const request = { topology: { kind: 'mesh', side_length: 4, concentration: 1 }, noc_controls: { link_width: 64 } };
  it('proposes two independent knobs, four combinations, and the authored baseline', () => {
    const domain = discoverFabricDomain(parameters, request);
    expect(domain).toEqual([{ name: 'topology_family', values: ['mesh', 'torus'] }, { name: 'link_width', values: [64, 128] }]);
    expect(fabricGrid(domain)).toEqual([
      { topology_family: 'mesh', link_width: 64 }, { topology_family: 'mesh', link_width: 128 },
      { topology_family: 'torus', link_width: 64 }, { topology_family: 'torus', link_width: 128 },
    ]);
  });
  it('falls back to authored numeric knobs when a family switch is unavailable', () => {
    expect(discoverFabricDomain(parameters.filter(p => p.kind === 'int'), request)).toEqual([
      { name: 'link_width', values: [64, 128] }, { name: 'concentration', values: [1, 2] },
    ]);
  });
  it('refuses unknown typed conversions, missing baselines, unqualified knobs, and overflow', () => {
    expect(discoverFabricDomain(parameters, { topology: { kind: 'srota' }, noc_controls: { link_width: 64 } })).toEqual([]);
    expect(discoverFabricDomain(parameters, { topology: { kind: 'custom' } })).toEqual([]);
    expect(discoverFabricDomain(parameters.map(p => ({ ...p, executable: false })), request)).toEqual([]);
    expect(discoverFabricDomain(parameters.filter(p => p.name !== 'topology_family' && p.name !== 'radix'), { ...request, noc_controls: { link_width: Number.MAX_SAFE_INTEGER } })).toEqual([]);
  });
});
describe('measured recommendation eligibility', () => {
  it('ranks only certified measured constraint-passing candidates', () => {
    const good = candidate('good', 20);
    const failed = { ...candidate('failed', 1), constraint_verdicts: { completion_cycles: 'VIOLATED' } };
    const unknown = { ...candidate('unknown', 2), constraint_verdicts: {} };
    const modeled = { ...candidate('modeled', 3), evaluation_authority: 'modeled' };
    expect(rankMeasured([failed, unknown, modeled, good], 'completion_cycles', 'MIN', ['completion_cycles']).map(row => row.candidate_id)).toEqual(['good']);
  });
  it('respects direction and refuses nonfinite or missing objective evidence', () => {
    const low = candidate('low', 10), high = candidate('high', 20);
    const missing = { ...candidate('missing', 30), objective_availability: {} };
    expect(rankMeasured([low, high, missing, candidate('nan', NaN)], 'completion_cycles', 'MAX', []).map(row => row.candidate_id)).toEqual(['high', 'low']);
  });
});
