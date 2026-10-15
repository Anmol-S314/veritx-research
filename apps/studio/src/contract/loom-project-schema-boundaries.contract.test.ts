import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject } from '../graph/project';
import schemaJson from '../../../../contracts/loom/v1/project.schema.json';

const withEveryOptionalBlock = () => ({
  ...buildPreset('mesh-4x4'),
  firewall: { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RO' }] },
  workload: { phases: [{ id: 'phase-1', kind: 'prefill', tokens: 128 }] },
});

describe('Loom project schema top-level contract', () => {
  it('pins every declared top-level block and round-trips a fixture containing optional blocks', () => {
    const schema = schemaJson as unknown as { properties: Record<string, unknown>; required: string[] };
    expect(Object.keys(schema.properties).sort()).toEqual([
      'edges', 'firewall', 'nodes', 'presetHint', 'schemaVersion', 'workload',
    ]);
    expect(schema.required).toEqual(['schemaVersion', 'presetHint', 'nodes', 'edges']);

    const fixture = withEveryOptionalBlock();
    expect(validateProject(fixture)).toEqual([]);
    const serialized = serializeProject(fixture);
    expect(parseProject(serialized)).toEqual(fixture);
    expect(serializeProject(parseProject(serialized))).toBe(serialized);
  });

  it.each([
    ['schemaVersion', { schemaVersion: 2 }, '$.schemaVersion'],
    ['presetHint', { presetHint: 7 }, '$.presetHint'],
    ['nodes', { nodes: null }, '$.nodes'],
    ['edges', { edges: {} }, '$.edges'],
    ['firewall', { firewall: [] }, '$.firewall'],
    ['workload', { workload: 'not an object' }, '$.workload'],
    ['unknown top-level block', { unexpected: true }, '$.unexpected'],
  ])('rejects invalid %s block with a stable schema path', (_name, patch, path) => {
    const invalid = { ...withEveryOptionalBlock(), ...patch };
    expect(validateProject(invalid).some((issue) => issue.path === path)).toBe(true);
    expect(() => parseProject(JSON.stringify(invalid))).toThrow(path);
  });

  it.each(['schemaVersion', 'presetHint', 'nodes', 'edges'])('rejects missing required top-level block %s', (key) => {
    const project: Record<string, unknown> = { ...buildPreset('mesh-4x4') };
    delete project[key];
    expect(validateProject(project).some((issue) => issue.path === `$.${key}`)).toBe(true);
  });
});
