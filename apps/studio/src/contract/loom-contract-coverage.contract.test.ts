import { describe, expect, it } from 'vitest';
import PROJECT_SCHEMA from '../../../../contracts/loom/v1/project.schema.json';
import { buildPreset } from '../graph/presets';
import { validateProject } from '../graph/project';

const topLevel = [
  'access', 'agents', 'compilerSemanticsVersion', 'domains', 'edges', 'firewall',
  'floorplan', 'metadata', 'nodes', 'presetHint', 'routing', 'schemaVersion',
  'vcConfig', 'workload',
];

describe('project v1 contract coverage', () => {
  it('declares every top-level block and pins required version fields', () => {
    expect(Object.keys(PROJECT_SCHEMA.properties).sort()).toEqual([...topLevel].sort());
    expect(PROJECT_SCHEMA.required).toEqual(['schemaVersion', 'compilerSemanticsVersion', 'presetHint', 'nodes', 'edges']);
    expect(PROJECT_SCHEMA.properties.schemaVersion.const).toBe(1);
    expect(PROJECT_SCHEMA.properties.compilerSemanticsVersion.const).toBe(1);
  });

  it.each([
    ['routing', { policy: 'unknown' }, '$.routing.policy'],
    ['firewall', [], '$.firewall'],
    ['workload', 'invalid', '$.workload'],
    ['vcConfig', 'invalid', '$.vcConfig'],
    ['domains', [], '$.domains'],
    ['agents', {}, '$.agents'],
    ['floorplan', [], '$.floorplan'],
    ['metadata', [], '$.metadata'],
    ['access', [], '$.access'],
    ['schemaVersion', 2, '$.schemaVersion'],
    ['compilerSemanticsVersion', 2, '$.compilerSemanticsVersion'],
  ])('rejects invalid top-level %s fixture at %s', (_key, value, path) => {
    const project = { ...buildPreset('ring-8'), [_key]: value };
    expect(validateProject(project).some(issue => issue.path === path)).toBe(true);
  });
});
