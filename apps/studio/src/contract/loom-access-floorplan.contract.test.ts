import { describe, expect, it } from 'vitest';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject, type LoomProject } from '../graph/project';

describe('M0 firewall/access and floorplan contracts', () => {
  it('schema defines ordered access policy, explicit endpoint scope and default policy', () => {
    expect(SCHEMA.$defs.accessControl.required).toEqual(['defaultPolicy', 'rules']);
    expect(SCHEMA.$defs.legacyFirewallRule.required).toEqual(['src', 'dst', 'perm']);
    expect(SCHEMA.$defs.accessPolicy.enum).toEqual(['read_write', 'read_only', 'deny']);
    expect(SCHEMA.$defs.firewallRule.required).toEqual(['id', 'precedence', 'source', 'target', 'policy']);
    expect(SCHEMA.$defs.accessScope.required).toEqual(['nodeIds']);
    expect(SCHEMA.$defs.projectMetadata.properties).toHaveProperty('name');
  });

  it('serializes and round-trips firewall rules and physical floorplan metadata', () => {
    const project = buildPreset('ring-8');
    const enriched = {
      ...project,
      metadata: { name: 'fixture fabric', description: 'authored sample', tags: ['noc', 'contract'] },
      access: {
        defaultPolicy: 'deny' as const,
        rules: [
          { id: 'allow-rw', precedence: 0, source: { nodeIds: ['n1'] }, target: { nodeIds: ['n2'] }, policy: 'read_write' as const },
          { id: 'allow-ro', precedence: 1, source: { nodeIds: ['n2'] }, target: { nodeIds: ['n3'] }, policy: 'read_only' as const },
          { id: 'block', precedence: 2, source: { nodeIds: ['n3'] }, target: { nodeIds: ['n4'] }, policy: 'deny' as const },
        ],
      },
      floorplan: {
        units: 'um' as const,
        dieOutline: { x: 0, y: 0, width: 1000, height: 800 },
        placements: [{ nodeId: 'n1', bounds: { x: 10, y: 20, width: 40, height: 30 }, locked: true, hierarchyId: 'cluster-a' }],
        keepouts: [{ id: 'ko-1', bounds: { x: 100, y: 100, width: 20, height: 30 }, kind: 'routing' }],
        hierarchies: [{ id: 'cluster-a', parentId: null, nodeIds: ['n1', 'n2'] }],
      },
      edges: project.edges.map((edge, i) => i === 0 ? { ...edge, physical: { routeLength: 42.5, layer: 'M3', routeClass: 'local', locked: true } } : edge),
    };
    expect(validateProject(enriched)).toEqual([]);
    const encoded = serializeProject(enriched);
    const decoded = parseProject(encoded);
    expect(decoded.metadata).toEqual(enriched.metadata);
    expect(decoded.access).toEqual(enriched.access);
    expect(decoded.floorplan).toEqual(enriched.floorplan);
    expect(decoded.edges[0].physical).toEqual({ routeLength: 42.5, layer: 'M3', routeClass: 'local', locked: true });
    expect(serializeProject(decoded)).toBe(encoded);
  });

  it('rejects cyclic floorplan hierarchy parent links', () => {
    const project = buildPreset('ring-8');
    const invalid = {
      ...project,
      floorplan: {
        units: 'um' as const,
        dieOutline: { x: 0, y: 0, width: 100, height: 100 },
        placements: [], keepouts: [],
        hierarchies: [
          { id: 'cluster-a', parentId: 'cluster-b', nodeIds: ['n1'] },
          { id: 'cluster-b', parentId: 'cluster-a', nodeIds: ['n2'] },
        ],
      },
    };
    expect(validateProject(invalid).some(issue => issue.message.includes('must be acyclic'))).toBe(true);
  });

  it('rejects placement and keepout rectangles that extend beyond the die outline', () => {
    const project = buildPreset('ring-8');
    const invalid = {
      ...project,
      floorplan: {
        units: 'um' as const,
        dieOutline: { x: 0, y: 0, width: 100, height: 100 },
        placements: [{ nodeId: 'n1', bounds: { x: 99, y: 10, width: 2, height: 10 }, locked: false, hierarchyId: 'cluster' }],
        keepouts: [{ id: 'ko-outside', bounds: { x: -1, y: 0, width: 1, height: 1 }, kind: 'routing' }],
        hierarchies: [{ id: 'cluster', parentId: null, nodeIds: ['n2'] }],
      },
    };
    expect(validateProject(invalid).map(issue => issue.path)).toEqual(expect.arrayContaining([
      '$.floorplan.placements[0].bounds', '$.floorplan.placements[0].hierarchyId', '$.floorplan.keepouts[0].bounds',
    ]));
  });

  it('rejects ambiguous precedence, dangling scope IDs and malformed placement geometry', () => {
    const project = buildPreset('ring-8');
    const invalid = {
      ...project,
      metadata: { name: '', tags: ['same', 'same'] },
      access: {
        defaultPolicy: 'allow_all',
        rules: [
          { id: 'r1', precedence: 0, source: { nodeIds: ['unknown'] }, target: { nodeIds: ['n2'] }, policy: 'read_write' },
          { id: 'r2', precedence: 0, source: { nodeIds: ['n2', 'n2'] }, target: { nodeIds: ['n3'] }, policy: 'deny' },
        ],
      },
      floorplan: {
        units: 'um', dieOutline: { x: 0, y: 0, width: 100, height: 100 },
        placements: [{ nodeId: 'missing', bounds: { x: 0, y: 0, width: 0, height: 1 }, locked: false, hierarchyId: 'missing' }],
        keepouts: [], hierarchies: [],
      },
      edges: project.edges.map((edge, i) => i === 0 ? { ...edge, physical: { routeLength: -1 } } : edge),
    };
    const paths = validateProject(invalid).map(({ path }) => path);
    expect(paths).toEqual(expect.arrayContaining([
      '$.metadata.name', '$.metadata.tags', '$.access.defaultPolicy', '$.access.rules[0].source.nodeIds', '$.access.rules[1].precedence', '$.access.rules[1].source.nodeIds',
      '$.floorplan.placements[0].nodeId', '$.floorplan.placements[0].bounds', '$.floorplan.placements[0].hierarchyId',
      '$.edges[0].physical.routeLength',
    ]));
    expect(() => serializeProject(invalid as unknown as LoomProject)).toThrow(/unknown node missing/);
  });
});
