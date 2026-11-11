/** Layout algebra for graph authoring (tracker M1-12 alignment, M1-13
 *  distribution, M1-19 overlap cleanup). Pure functions only: no store, no
 *  history, no React. The UI test lane proves the wiring separately. */
import { describe, expect, it } from 'vitest';
import {
  alignPositions, applyPositions, arrangeGrid, cleanupLayout, distributePositions,
  NODE_HEIGHT, NODE_WIDTH, resolveOverlaps, snapPositions,
} from '../graph/layout';
import { buildPreset } from '../graph/presets';

const mesh = buildPreset('mesh-4x4');
const positions = mesh.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y }));
const at = (id: string): { x: number; y: number } => {
  const found = positions.find((n) => n.id === id);
  if (!found) throw new Error(`no node ${id}`);
  return { x: found.x, y: found.y };
};

describe('M1-12: alignment', () => {
  it('aligns the top row left to the selection bounding box', () => {
    const updates = alignPositions(positions, ['n1', 'n2', 'n3', 'n4'], 'left');
    // n1 is already the leftmost; the others move to x = 42 + 38 = 80.
    expect(updates.map((u) => u.id)).toEqual(['n2', 'n3', 'n4']);
    expect(updates.every((u) => u.x === 80)).toBe(true);
  });

  it('aligns to bottom and vertical centre', () => {
    const bottom = alignPositions(positions, ['n1', 'n5', 'n9', 'n13'], 'bottom');
    // Column 0 spans y = 80..440; bottom edge 464, centre y = 464 - 24 = 440.
    expect(bottom.find((u) => u.id === 'n1')!.y).toBe(440);
    expect(bottom.some((u) => u.id === 'n13')).toBe(false);
    expect(alignPositions(positions, ['n1', 'n5', 'n9', 'n13'], 'center_y')
      .every((u) => u.y === 260)).toBe(true);
  });

  it('is a no-op for a single node or an empty selection', () => {
    expect(alignPositions(positions, ['n1'], 'left')).toEqual([]);
    expect(alignPositions(positions, [], 'left')).toEqual([]);
  });

  it('never invents nodes for unknown ids', () => {
    expect(alignPositions(positions, ['n1', 'ghost'], 'left')).toEqual([]);
  });

  it('reports no change when everything is already aligned', () => {
    expect(alignPositions(positions, ['n1', 'n2', 'n3', 'n4'], 'top')).toEqual([]);
  });
});

describe('M1-13: distribution', () => {
  it('spaces three irregular centres evenly on the horizontal axis', () => {
    // n1 x=80, n6 x=200 (row 1), n4 x=440. Even centre spacing: 80, 260, 440.
    const updates = distributePositions(positions, ['n1', 'n4', 'n6'], 'horizontal');
    expect(updates.find((u) => u.id === 'n6')).toMatchObject({ x: 260 });
    // The extreme nodes keep their positions, so they are not in the diff.
    expect(updates.some((u) => u.id === 'n1')).toBe(false);
    expect(updates.some((u) => u.id === 'n4')).toBe(false);
  });

  it('preserves the outermost positions and ordering', () => {
    // y = 80, 80, 200 → even centre spacing 80, 140, 200; only n2 moves.
    const updates = distributePositions(positions, ['n5', 'n2', 'n1'], 'vertical');
    expect(updates).toEqual([{ id: 'n2', x: 200, y: 140 }]);
  });

  it('requires at least three nodes', () => {
    expect(distributePositions(positions, ['n1', 'n2'], 'horizontal')).toEqual([]);
    expect(distributePositions(positions, ['n1'], 'horizontal')).toEqual([]);
  });

  it('breaks coordinate ties by id, deterministically', () => {
    const tied = [{ id: 'b', x: 0, y: 0 }, { id: 'a', x: 0, y: 0 }, { id: 'c', x: 100, y: 0 }];
    const first = distributePositions(tied, ['a', 'b', 'c'], 'horizontal');
    const second = distributePositions([...tied].reverse(), ['c', 'a', 'b'], 'horizontal');
    expect(first).toEqual(second);
    // a is placed before b at the shared left edge; c is untouched.
    expect(first.find((u) => u.id === 'b')!.x).toBe(50);
  });
});

describe('M1-19: grid snap and overlap cleanup', () => {
  it('snaps to the grid and refuses a non-positive step', () => {
    expect(snapPositions(positions, ['n1'], 100)).toEqual([{ id: 'n1', x: 100, y: 100 }]);
    expect(snapPositions(positions, ['n1'], 0)).toEqual([]);
    expect(snapPositions(positions, ['n1'], Number.NaN)).toEqual([]);
  });

  it('pushes overlapping nodes apart deterministically', () => {
    const stacked = [
      { id: 'a', x: 100, y: 100 }, { id: 'b', x: 100, y: 100 }, { id: 'c', x: 100, y: 100 },
    ];
    const updates = resolveOverlaps(stacked, ['a', 'b', 'c']);
    // a stays; b and c are each pushed one footprint+clearance down.
    expect(updates).toEqual([
      { id: 'b', x: 100, y: 100 + NODE_HEIGHT + 12 },
      { id: 'c', x: 100, y: 100 + 2 * (NODE_HEIGHT + 12) },
    ]);
  });

  it('cleanup snaps then separates without inventing positions', () => {
    const updates = cleanupLayout(positions, ['n1', 'n2'], { gridStep: 100 });
    expect(updates.find((u) => u.id === 'n1')).toMatchObject({ x: 100, y: 100 });
    // n2 at (200,80) snaps to (200,100): same row, but far enough apart.
    expect(updates.find((u) => u.id === 'n2')).toMatchObject({ x: 200, y: 100 });
  });

  it('re-grid packs in document order with the node footprint respected', () => {
    const small = [{ id: 'a', x: 9, y: 9 }, { id: 'b', x: 9, y: 9 }, { id: 'c', x: 9, y: 9 }, { id: 'd', x: 9, y: 9 }];
    const updates = arrangeGrid(small, { columns: 2 });
    expect(updates).toEqual([
      { id: 'a', x: 80, y: 80 }, { id: 'b', x: 200, y: 80 },
      { id: 'c', x: 80, y: 176 }, { id: 'd', x: 200, y: 176 },
    ]);
    expect(arrangeGrid([], {})).toEqual([]);
  });
});

describe('layout: application is pure', () => {
  it('applyPositions returns copies and leaves the input untouched', () => {
    const input = [{ id: 'n1', x: 1, y: 2, role: 'compute_tile', ports: 5 }];
    const out = applyPositions(input, [{ id: 'n1', x: 10, y: 20 }]);
    expect(out[0]).toMatchObject({ id: 'n1', x: 10, y: 20 });
    expect(input[0]).toMatchObject({ x: 1, y: 2 });
    expect(out[0]).not.toBe(input[0]);
    expect(applyPositions(input, [])[0]).not.toBe(input[0]);
  });

  it('exposes the drawn node footprint the editor uses', () => {
    expect(NODE_WIDTH).toBe(76);
    expect(NODE_HEIGHT).toBe(48);
    expect(at('n1')).toEqual({ x: 80, y: 80 });
  });
});
