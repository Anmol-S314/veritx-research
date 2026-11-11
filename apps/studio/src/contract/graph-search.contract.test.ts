/** Topology-wide search over the authoring graph (tracker M1-31). */
import { describe, expect, it } from 'vitest';
import { matchedNodeIds, searchGraph } from '../graph/search';
import { buildPreset } from '../graph/presets';

const mesh = buildPreset('mesh-4x4');

describe('M1-31: graph search', () => {
  it('returns nothing for an empty or whitespace query', () => {
    expect(searchGraph(mesh, '')).toEqual([]);
    expect(searchGraph(mesh, '   ')).toEqual([]);
  });

  it('finds nodes by role', () => {
    const matches = searchGraph(mesh, 'hbm_controller');
    const ids = matchedNodeIds(matches);
    // i % 5 === 4 → indices 4, 9, 14.
    expect(ids).toEqual(['n5', 'n10', 'n15']);
    expect(matches.every((m) => m.kind === 'node' && m.field === 'role')).toBe(true);
  });

  it('ranks an exact id above everything else', () => {
    const matches = searchGraph(mesh, 'n1');
    expect(matches[0]).toMatchObject({ kind: 'node', id: 'n1', field: 'id', score: 0 });
  });

  it('is case-insensitive and searches edges by endpoint too', () => {
    expect(searchGraph(mesh, 'HBM_CONTROLLER').length).toBeGreaterThan(0);
    const byEdge = searchGraph(mesh, 'e1');
    expect(byEdge.some((m) => m.kind === 'edge' && m.id === 'e1')).toBe(true);
    // An edge is reachable by its source node id via the `src` field.
    expect(searchGraph(mesh, 'n16').some((m) => m.kind === 'edge')).toBe(true);
  });

  it('matches non-string fields by their text form', () => {
    const matches = searchGraph(mesh, '0');
    expect(matches.some((m) => m.kind === 'edge' && m.field === 'vcClass')).toBe(true);
  });

  it('honours the result limit and stays deterministic', () => {
    const limited = searchGraph(mesh, 'n', 3);
    expect(limited).toHaveLength(3);
    expect(searchGraph(mesh, 'n', 3)).toEqual(limited);
  });

  it('deduplicates node ids a result set points at', () => {
    const matches = searchGraph(mesh, 'compute_tile');
    const ids = matchedNodeIds(matches);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain('n1');
    expect(ids).not.toContain('n5');
  });
});
