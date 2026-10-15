import { describe, expect, it } from 'vitest';
import { semanticProjectDiff } from './semanticDiff';
import type { LoomProject } from './project';
const node = (id: string, role = 'router') => ({ id, x: 0, y: 0, role, ports: 2 });
const base: LoomProject = { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: null, nodes: [node('n1'), node('n2')], edges: [{ id: 'e1', src: 'n1', dst: 'n2', width: 32, pipelineStages: 1, vcClass: 0 }] };

describe('stable-ID semantic project diff', () => {
  it('ignores collection ordering and reports a field change by stable ID', () => {
    const reordered: LoomProject = { ...base, nodes: [...base.nodes].reverse() };
    expect(semanticProjectDiff(base, reordered)).toEqual([]);
    const changed: LoomProject = { ...base, nodes: [node('n1', 'compute'), node('n2')] };
    expect(semanticProjectDiff(base, changed)).toContainEqual({ objectType: 'node', objectId: 'n1', path: 'role', before: 'router', after: 'compute' });
  });
  it('reports authored workload changes as project metadata', () => {
    const before: LoomProject = { ...base, workload: { phases: [{ id: 'p1', kind: 'decode', tokens: 16 }] } };
    const after: LoomProject = { ...base, workload: { phases: [{ id: 'p1', kind: 'decode', tokens: 32 }] } };
    expect(semanticProjectDiff(before, after)).toContainEqual({
      objectType: 'project', objectId: 'project', path: 'workload.phases[p1].tokens', before: 16, after: 32,
    });
  });
  it('diffs domain, access, and floorplan collections by stable identities', () => {
    const before: LoomProject = {
      ...base,
      domains: {
        clocks: [{ id: 'clkA', frequencyHz: 100 }, { id: 'clkB', frequencyHz: 200 }],
        resets: [], powers: [],
        portAssignments: [{ nodeId: 'n1', portId: 'p0', clockDomainId: 'clkA' }],
      },
      access: { defaultPolicy: 'deny', rules: [{ id: 'ruleA', precedence: 1, source: { nodeIds: ['n1'] }, target: { nodeIds: ['n2'] }, policy: 'read_only' }] },
      floorplan: { unit: 'um', placements: [{ nodeId: 'n1', x: 1, y: 2, width: 3, height: 4 }], timingConstraints: [{ edgeId: 'e1', targetDelayPs: 30 }] },
    };
    const after: LoomProject = {
      ...before,
      domains: {
        ...before.domains!,
        clocks: [{ id: 'clkB', frequencyHz: 200 }, { id: 'clkA', frequencyHz: 150 }],
        portAssignments: [{ nodeId: 'n1', portId: 'p0', clockDomainId: 'clkB' }],
      },
      access: { ...before.access!, rules: [{ ...before.access!.rules[0]!, policy: 'read_write' }] },
      floorplan: { ...before.floorplan!, placements: [{ nodeId: 'n1', x: 9, y: 2, width: 3, height: 4 }], timingConstraints: [{ edgeId: 'e1', targetDelayPs: 40 }] },
    };
    const changes = semanticProjectDiff(before, after);
    expect(changes).toContainEqual({ objectType: 'project', objectId: 'project', path: 'domains.clocks[clkA].frequencyHz', before: 100, after: 150 });
    expect(changes).toContainEqual({ objectType: 'project', objectId: 'project', path: 'domains.portAssignments[port:n1:p0].clockDomainId', before: 'clkA', after: 'clkB' });
    expect(changes).toContainEqual({ objectType: 'project', objectId: 'project', path: 'access.rules[ruleA].policy', before: 'read_only', after: 'read_write' });
    expect(changes).toContainEqual({ objectType: 'project', objectId: 'project', path: 'floorplan.placements[node:n1].x', before: 1, after: 9 });
    expect(changes).toContainEqual({ objectType: 'project', objectId: 'project', path: 'floorplan.timingConstraints[edge:e1].targetDelayPs', before: 30, after: 40 });
  });
  it('reports stable edge additions/removals without coordinate-derived identity', () => {
    const changed: LoomProject = { ...base, edges: [] };
    expect(semanticProjectDiff(base, changed)).toContainEqual({ objectType: 'edge', objectId: 'e1', path: '', before: base.edges[0], after: undefined });
  });
});
