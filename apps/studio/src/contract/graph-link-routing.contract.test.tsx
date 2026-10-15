/** Link compatibility at pick time (M1-15), obstacle-avoiding routing (M1-17)
 *  and dangling catalog references (M1-26). */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import { linkCompatibilityProblem } from '../graph/linkOps';
import { manhattanAvoiding, manhattan, withLane, laneIndex, type RouteObstacle } from '../graph/routing';
import { validateProject, type GraphNode, type LoomProject } from '../graph/project';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const node = (id: string, ports = 5, interfaceRole?: GraphNode['interfaceRole']): GraphNode =>
  ({ id, x: 0, y: 0, role: 'compute_tile', ports, ...(interfaceRole ? { interfaceRole } : {}) });

describe('M1-15: link compatibility at pick time', () => {
  const project = (nodes: GraphNode[], edges: LoomProject['edges'] = []): Pick<LoomProject, 'nodes' | 'edges'> => ({ nodes, edges });

  it('accepts a compatible pair', () => {
    expect(linkCompatibilityProblem(project([node('a', 5, 'INITIATOR'), node('b', 5, 'TARGET')]), 'a', 'b')).toBeNull();
  });

  it('refuses an incompatible declared direction with a reason', () => {
    expect(linkCompatibilityProblem(project([node('a', 5, 'INITIATOR'), node('b', 5, 'INITIATOR')]), 'a', 'b'))
      .toMatch(/cannot pair/);
  });

  it('refuses duplicate links, self links and port exhaustion', () => {
    expect(linkCompatibilityProblem(project([node('a')], [{ id: 'e1', src: 'a', dst: 'a', width: 1, pipelineStages: 1, vcClass: 0 }]), 'a', 'a'))
      .toMatch(/distinct endpoints/);
    const dup = [{ id: 'e1', src: 'a', dst: 'b', width: 1, pipelineStages: 1, vcClass: 0 }];
    expect(linkCompatibilityProblem(project([node('a'), node('b')], dup), 'a', 'b')).toMatch(/duplicate directed link/);
    // a already spends its single egress port on c, so a -> b is out of ports.
    const spent = [{ id: 'e1', src: 'a', dst: 'c', width: 1, pipelineStages: 1, vcClass: 0 }];
    expect(linkCompatibilityProblem(project([node('a', 1), node('b'), node('c')], spent), 'a', 'b')).toMatch(/out of ports/);
  });

  it('refuses an unknown endpoint', () => {
    expect(linkCompatibilityProblem(project([node('a')]), 'a', 'ghost')).toMatch(/unknown target node/);
  });

  it('refuses the pick in the editor instead of creating an invalid edge', () => {
    localStorage.setItem('loom-graph-autosave-v1:link-compat-seed', JSON.stringify({
      schemaVersion: 1,
      compilerSemanticsVersion: 1,
      presetHint: null,
      nodes: [
        { id: 'a', x: 0, y: 0, role: 'compute_tile', ports: 5, interfaceRole: 'INITIATOR' },
        { id: 'b', x: 200, y: 0, role: 'compute_tile', ports: 5, interfaceRole: 'INITIATOR' },
      ],
      edges: [],
    }));
    render(<GraphLoom projectId="link-compat-seed" draftRequest={null} />);
    expect(screen.queryAllByTestId(/^link-e\d/)).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'link mode' }));
    fireEvent.click(screen.getByTestId('node-a'));
    fireEvent.click(screen.getByTestId('node-b'));

    expect(screen.getByTestId('link-error').textContent).toMatch(/cannot pair/);
    expect(screen.queryAllByTestId(/^link-e\d/)).toHaveLength(0);
  });
});

describe('M1-17: obstacle-avoiding Manhattan routing', () => {
  const crosses = (p: { x: number; y: number }, q: { x: number; y: number }, r: RouteObstacle): boolean => {
    if (p.x === q.x) {
      if (p.x <= r.x || p.x >= r.x + r.width) return false;
      return Math.max(p.y, q.y) > r.y && Math.min(p.y, q.y) < r.y + r.height;
    }
    if (p.y === q.y) {
      if (p.y <= r.y || p.y >= r.y + r.height) return false;
      return Math.max(p.x, q.x) > r.x && Math.min(p.x, q.x) < r.x + r.width;
    }
    return true;
  };

  it('routes around an obstacle blocking the direct line', () => {
    const obstacle: RouteObstacle = { x: 80, y: -40, width: 40, height: 80 };
    const path = manhattanAvoiding({ x: 0, y: 0 }, { x: 200, y: 0 }, [obstacle], 4);
    expect(path.length).toBeGreaterThan(2);
    for (let i = 1; i < path.length; i++) {
      expect(crosses(path[i - 1]!, path[i]!, obstacle)).toBe(false);
    }
  });

  it('stays direct when nothing is in the way', () => {
    const path = manhattanAvoiding({ x: 0, y: 0 }, { x: 200, y: 0 }, [{ x: 500, y: 500, width: 10, height: 10 }], 4);
    expect(path).toHaveLength(2);
  });
});

describe('M1-19: stable routing lanes', () => {
  it('assigns a deterministic lane per source, in document order', () => {
    const edges = [
      { id: 'e1', src: 'a' }, { id: 'e2', src: 'b' }, { id: 'e3', src: 'a' }, { id: 'e4', src: 'a' },
    ];
    expect(laneIndex(edges, 'e1')).toBe(0);
    expect(laneIndex(edges, 'e2')).toBe(0);
    expect(laneIndex(edges, 'e3')).toBe(1);
    expect(laneIndex(edges, 'e4')).toBe(2);
    expect(laneIndex(edges, 'e1')).toBe(laneIndex(edges, 'e1'));
  });

  it('keeps endpoints fixed and offsets the interior into the lane', () => {
    const base = manhattan({ x: 0, y: 0 }, { x: 100, y: 60 });
    expect(withLane(base, 0)).toBe(base);
    const lane1 = withLane(base, 1, 10);
    expect(lane1[0]).toEqual(base[0]);
    expect(lane1[lane1.length - 1]).toEqual(base[base.length - 1]);
    expect(lane1.length).toBeGreaterThan(base.length);
    expect(lane1[1]).toEqual({ x: base[0]!.x, y: base[0]!.y + 10 });
  });

  it('separates links that share a source instead of overlapping exactly', () => {
    const edges = [{ id: 'e1', src: 'a' }, { id: 'e2', src: 'a' }];
    const p = manhattan({ x: 0, y: 0 }, { x: 50, y: 50 });
    const first = withLane(p, laneIndex(edges, 'e1'));
    const second = withLane(p, laneIndex(edges, 'e2'));
    expect(first).not.toEqual(second);
  });
});

describe('M1-26: dangling catalog references', () => {
  const withCatalog = (): LoomProject => ({
    schemaVersion: 1,
    compilerSemanticsVersion: 1,
    presetHint: null,
    nodes: [
      { id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 5, catalogRef: { catalogId: 'veritx.generic', itemId: 'compute.generic', version: '1.0.0', overrides: {}, fallbackMetadata: {} } },
      { id: 'n2', x: 200, y: 0, role: 'compute_tile', ports: 5, catalogRef: { catalogId: 'veritx.generic', itemId: 'compute.missing', version: '1.0.0', overrides: {}, fallbackMetadata: {} } },
    ],
    edges: [{ id: 'e1', src: 'n1', dst: 'n2', width: 512, pipelineStages: 1, vcClass: 0 }],
  });

  it('reports a missing item with the node at fault when a catalog is supplied', () => {
    const issues = validateProject(withCatalog(), { knownCatalogItems: ['compute.generic'] });
    const missing = issues.filter((i) => i.code === 'node.catalog_ref_missing');
    expect(missing).toHaveLength(1);
    expect(missing[0]!.objectRef).toBe('$.nodes[id=n2]');
    expect(missing[0]!.message).toContain('compute.missing');
  });

  it('does not invent a catalog problem when no catalog context is supplied', () => {
    expect(validateProject(withCatalog()).filter((i) => i.code === 'node.catalog_ref_missing')).toEqual([]);
  });

  it('accepts a reference that resolves', () => {
    expect(validateProject(withCatalog(), { knownCatalogItems: ['compute.generic', 'compute.missing'] })
      .filter((i) => i.code === 'node.catalog_ref_missing')).toEqual([]);
  });
});
