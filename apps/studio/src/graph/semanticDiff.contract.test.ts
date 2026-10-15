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
  it('reports stable edge additions/removals without coordinate-derived identity', () => {
    const changed: LoomProject = { ...base, edges: [] };
    expect(semanticProjectDiff(base, changed)).toContainEqual({ objectType: 'edge', objectId: 'e1', path: '', before: base.edges[0], after: undefined });
  });
});
