/** Topology alignment and distribution (tracker M1-12 / M1-13).
 *
 *  Pure geometry over canvas coordinates: deterministic, identity-preserving,
 *  and expressed as per-node patches the caller applies as one undoable edit. */
import { describe, expect, it } from 'vitest';
import { alignNodes, cleanupNodes, distributeNodes, LAYOUT_NODE_HEIGHT, LAYOUT_NODE_WIDTH } from '../graph/alignOps';
import type { GraphNode } from '../graph/project';

const node = (id: string, x: number, y: number): GraphNode => ({ id, x, y, role: 'compute_tile', ports: 5 });
const nodes: GraphNode[] = [node('a', 0, 0), node('b', 10, 40), node('c', 30, 20), node('d', 100, 90)];
const apply = (patches: { id: string; patch: Partial<GraphNode> }[]): GraphNode[] =>
  nodes.map((n) => {
    const p = patches.find((x) => x.id === n.id);
    return p ? { ...n, ...p.patch } : n;
  });

describe('M1-12: alignment', () => {
  it('refuses to align fewer than two nodes', () => {
    expect(alignNodes(nodes, ['a'], 'left')).toEqual([]);
    expect(alignNodes(nodes, [], 'left')).toEqual([]);
  });

  it('aligns left/right on x and top/bottom on y', () => {
    const xs = (mode: Parameters<typeof alignNodes>[2]): number[] => apply(alignNodes(nodes, ['a', 'b', 'c'], mode)).slice(0, 3).map((n) => n.x);
    const ys = (mode: Parameters<typeof alignNodes>[2]): number[] => apply(alignNodes(nodes, ['a', 'b', 'c'], mode)).slice(0, 3).map((n) => n.y);
    expect(xs('left')).toEqual([0, 0, 0]);
    expect(xs('right')).toEqual([30, 30, 30]);
    expect(ys('top')).toEqual([0, 0, 0]);
    expect(ys('bottom')).toEqual([40, 40, 40]);
  });

  it('centers on the selection bounding box', () => {
    expect(apply(alignNodes(nodes, ['a', 'b', 'c'], 'center-x')).slice(0, 3).map((n) => n.x)).toEqual([15, 15, 15]);
    expect(apply(alignNodes(nodes, ['a', 'b', 'c'], 'center-y')).slice(0, 3).map((n) => n.y)).toEqual([20, 20, 20]);
  });

  it('does not touch nodes outside the selection', () => {
    const applied = apply(alignNodes(nodes, ['a', 'b'], 'left'));
    expect(applied.find((n) => n.id === 'd')!.x).toBe(100);
  });

  it('refuses a non-finite coordinate instead of moving partially', () => {
    const bad = [node('a', Number.NaN, 0), node('b', 10, 10)];
    expect(alignNodes(bad, ['a', 'b'], 'left')).toEqual([]);
  });

  it('is deterministic', () => {
    expect(alignNodes(nodes, ['a', 'b', 'c'], 'center-x')).toEqual(alignNodes(nodes, ['a', 'b', 'c'], 'center-x'));
  });
});

describe('M1-13: distribution', () => {
  it('refuses to distribute fewer than three nodes', () => {
    expect(distributeNodes(nodes, ['a', 'b'], 'horizontal')).toEqual([]);
  });

  it('spaces the interior evenly and keeps the extremes fixed', () => {
    const distributed = apply(distributeNodes(nodes, ['a', 'b', 'c', 'd'], 'horizontal'));
    const xs = Object.fromEntries(distributed.map((n) => [n.id, n.x]));
    expect(xs.a).toBe(0);
    expect(xs.d).toBe(100);
    expect(xs.b).toBeCloseTo(100 / 3);
    expect(xs.c).toBeCloseTo(200 / 3);
  });

  it('distributes vertically by y', () => {
    const distributed = apply(distributeNodes(nodes, ['a', 'b', 'c', 'd'], 'vertical'));
    const ys = Object.fromEntries(distributed.map((n) => [n.id, n.y]));
    // Ordered by y: a(0), c(20), b(40), d(90) -> 0, 30, 60, 90.
    expect(ys.a).toBe(0);
    expect(ys.d).toBe(90);
    expect(ys.c).toBeCloseTo(30);
    expect(ys.b).toBeCloseTo(60);
  });

  it('preserves ordering by current coordinate, deterministically', () => {
    const shuffled = [nodes[2]!, nodes[0]!, nodes[3]!, nodes[1]!];
    expect(distributeNodes(shuffled, ['a', 'b', 'c', 'd'], 'horizontal'))
      .toEqual(distributeNodes(nodes, ['a', 'b', 'c', 'd'], 'horizontal'));
  });
});

describe('M1-19: node layout cleanup (tidy)', () => {
  it('refuses fewer than two nodes or a non-finite coordinate', () => {
    expect(cleanupNodes(nodes, ['a'])).toEqual([]);
    expect(cleanupNodes(nodes, [])).toEqual([]);
    expect(cleanupNodes([node('a', Number.NaN, 0), node('b', 0, 0)], ['a', 'b'])).toEqual([]);
  });

  it('snaps onto the grid and returns only the nodes that actually moved', () => {
    const scattered = [node('a', 13, 7), node('b', 200, 0)];
    expect(cleanupNodes(scattered, ['a', 'b'], { gridStep: 20 }))
      .toEqual([{ id: 'a', patch: { x: 20, y: 0 } }]);
  });

  it('separates exactly overlapping boxes by one footprint plus clearance', () => {
    const stacked = [node('a', 0, 0), node('b', 0, 0)];
    expect(cleanupNodes(stacked, ['a', 'b'], { gridStep: 20, clearance: 12 }))
      .toEqual([{ id: 'b', patch: { x: 0, y: LAYOUT_NODE_HEIGHT + 12 } }]);
  });

  it('leaves no two selected boxes overlapping, and touches nothing else', () => {
    const cleaned = apply(cleanupNodes(nodes, ['a', 'b', 'c'], { gridStep: 20, clearance: 12 }));
    const selected = cleaned.filter((n) => ['a', 'b', 'c'].includes(n.id));
    for (let i = 0; i < selected.length; i++) for (let j = i + 1; j < selected.length; j++) {
      const overlap = Math.abs(selected[i]!.x - selected[j]!.x) < LAYOUT_NODE_WIDTH
        && Math.abs(selected[i]!.y - selected[j]!.y) < LAYOUT_NODE_HEIGHT;
      expect(overlap).toBe(false);
    }
    expect(cleaned.find((n) => n.id === 'd')!.x).toBe(100);
    expect(cleaned.find((n) => n.id === 'd')!.y).toBe(90);
  });

  it('is deterministic', () => {
    expect(cleanupNodes(nodes, ['a', 'b', 'c', 'd'], { gridStep: 20 }))
      .toEqual(cleanupNodes(nodes, ['a', 'b', 'c', 'd'], { gridStep: 20 }));
  });
});

