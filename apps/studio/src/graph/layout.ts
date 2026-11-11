/** Pure layout operations for the authoring graph (tracker M1-12/13/19).
 *
 *  Every function here is a value transform over `{ id, x, y }` records. None
 *  of them touch React, history or the store: the caller decides how to apply
 *  the returned positions as an undoable command. Output is deterministic and
 *  ordered by document order, so the same selection always yields the same
 *  result. Coordinates are canvas units; the node footprint is the one the
 *  editor draws (76×48, centred on the node's x/y — see `GraphLoom`).
 *
 *  These are presentation helpers. They move authoring nodes on the canvas and
 *  make no claim about the compiled fabric, a physical route or placement.
 */
import type { GraphNode } from './project';

/** The drawn node extent, mirrored from the editor's `rect`. Kept here so the
 *  alignment/distribution math has one authority instead of two magic numbers. */
export const NODE_WIDTH = 76;
export const NODE_HEIGHT = 48;

export type NodePosition = Pick<GraphNode, 'id' | 'x' | 'y'>;

export type AlignMode =
  | 'left' | 'right' | 'top' | 'bottom' | 'center_x' | 'center_y';

export type DistributeAxis = 'horizontal' | 'vertical';

export interface PositionUpdate { id: string; x: number; y: number }

const clonePosition = (n: NodePosition): NodePosition => ({ id: n.id, x: n.x, y: n.y });

/** The subset of `nodes` whose ids are in `ids`, in document order. Unknown ids
 *  are ignored, so a stale selection cannot invent a node. */
function selectPositions(nodes: readonly NodePosition[], ids: Iterable<string>): NodePosition[] {
  const wanted = new Set(ids);
  return nodes.filter((n) => wanted.has(n.id)).map(clonePosition);
}

const boundsOf = (nodes: readonly NodePosition[]): {
  left: number; right: number; top: number; bottom: number; cx: number; cy: number;
} => {
  const lefts = nodes.map((n) => n.x - NODE_WIDTH / 2);
  const rights = nodes.map((n) => n.x + NODE_WIDTH / 2);
  const tops = nodes.map((n) => n.y - NODE_HEIGHT / 2);
  const bottoms = nodes.map((n) => n.y + NODE_HEIGHT / 2);
  const left = Math.min(...lefts);
  const right = Math.max(...rights);
  const top = Math.min(...tops);
  const bottom = Math.max(...bottoms);
  return { left, right, top, bottom, cx: (left + right) / 2, cy: (top + bottom) / 2 };
};

/** Return only the positions that actually change, so a no-op align adds no
 *  history entry and the caller can skip an empty batch. */
function changed(nodes: readonly NodePosition[], next: readonly NodePosition[]): PositionUpdate[] {
  const before = new Map(nodes.map((n) => [n.id, n]));
  return next.flatMap((n) => {
    const old = before.get(n.id);
    return !old || old.x !== n.x || old.y !== n.y ? [{ id: n.id, x: n.x, y: n.y }] : [];
  });
}

/** Align every selected node's matching edge (or centre line) to the selection
 *  bounding box. Fewer than two selected nodes is a no-op: there is nothing to
 *  align against. Returns the changed positions only. */
export function alignPositions(
  nodes: readonly NodePosition[],
  ids: Iterable<string>,
  mode: AlignMode,
): PositionUpdate[] {
  const selected = selectPositions(nodes, ids);
  if (selected.length < 2) return [];
  const b = boundsOf(selected);
  const next = selected.map((n) => {
    switch (mode) {
      case 'left': return { ...n, x: Math.round(b.left + NODE_WIDTH / 2) };
      case 'right': return { ...n, x: Math.round(b.right - NODE_WIDTH / 2) };
      case 'top': return { ...n, y: Math.round(b.top + NODE_HEIGHT / 2) };
      case 'bottom': return { ...n, y: Math.round(b.bottom - NODE_HEIGHT / 2) };
      case 'center_x': return { ...n, x: Math.round(b.cx) };
      case 'center_y': return { ...n, y: Math.round(b.cy) };
    }
  });
  return changed(selected, next);
}

/** Evenly space the selected node centres between the two extreme nodes on the
 *  chosen axis, preserving the outermost positions. Order on the axis comes
 *  from current coordinates with a stable id tie-break, so equal coordinates
 *  still distribute deterministically. Three or more nodes are required: two
 *  points are already evenly spaced. */
export function distributePositions(
  nodes: readonly NodePosition[],
  ids: Iterable<string>,
  axis: DistributeAxis,
): PositionUpdate[] {
  const selected = selectPositions(nodes, ids);
  if (selected.length < 3) return [];
  const key = axis === 'horizontal' ? 'x' : 'y';
  const sorted = [...selected].sort((a, b) => (a[key] - b[key])
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const first = sorted[0]!;
  const last = sorted[sorted.length - 1]!;
  const span = last[key] - first[key];
  const step = span / (sorted.length - 1);
  const placed = sorted.map((n, index) => ({
    ...n,
    [key]: Math.round(first[key] + step * index),
  })) as NodePosition[];
  return changed(selected, placed);
}

/** Round every selected node onto a grid of `step` canvas units. A non-positive
 *  step is a no-op (never a divide-by-zero or an invented position). */
export function snapPositions(
  nodes: readonly NodePosition[],
  ids: Iterable<string>,
  step: number,
): PositionUpdate[] {
  if (!Number.isFinite(step) || step <= 0) return [];
  const selected = selectPositions(nodes, ids);
  const next = selected.map((n) => ({
    ...n, x: Math.round(n.x / step) * step, y: Math.round(n.y / step) * step,
  }));
  return changed(selected, next);
}

const overlaps = (a: NodePosition, b: NodePosition, clearance: number): boolean =>
  Math.abs(a.x - b.x) < NODE_WIDTH + clearance
  && Math.abs(a.y - b.y) < NODE_HEIGHT + clearance;

/** Deterministically nudge overlapping nodes apart. Nodes are visited in
 *  document order; each node is pushed down, then right, just far enough to
 *  clear every earlier node, so the result is stable for a given input. The
 *  first node in the selection never moves. */
export function resolveOverlaps(
  nodes: readonly NodePosition[],
  ids: Iterable<string>,
  clearance = 12,
): PositionUpdate[] {
  const selected = selectPositions(nodes, ids);
  if (selected.length < 2) return [];
  const placed: NodePosition[] = [];
  for (const node of selected) {
    let candidate = node;
    let guard = 0;
    while (placed.some((other) => overlaps(candidate, other, clearance)) && guard < 10_000) {
      candidate = { ...candidate, y: candidate.y + NODE_HEIGHT + clearance };
      guard += 1;
    }
    placed.push(candidate);
  }
  return changed(selected, placed);
}

/** Snap to the grid, then separate any remaining overlaps. A single command
 *  the caller can offer as "tidy selection". */
export function cleanupLayout(
  nodes: readonly NodePosition[],
  ids: Iterable<string>,
  options: { gridStep?: number; clearance?: number } = {},
): PositionUpdate[] {
  const step = options.gridStep ?? 20;
  const clearance = options.clearance ?? 12;
  const afterSnap = applyPositions(nodes, snapPositions(nodes, ids, step));
  const afterSeparate = applyPositions(afterSnap, resolveOverlaps(afterSnap, ids, clearance));
  const wanted = new Set(ids);
  const before = nodes.filter((n) => wanted.has(n.id));
  const after = afterSeparate.filter((n) => wanted.has(n.id));
  return changed(before, after);
}

/** Arrange every node on a compact grid in document order. Guarantees a
 *  non-overlapping result for any graph shape, at the cost of discarding the
 *  authored positions — offered as an explicit "re-grid" action. */
export function arrangeGrid(
  nodes: readonly NodePosition[],
  options: { columns?: number; originX?: number; originY?: number; gapX?: number; gapY?: number } = {},
): PositionUpdate[] {
  if (nodes.length === 0) return [];
  const columns = Math.max(1, options.columns ?? Math.ceil(Math.sqrt(nodes.length)));
  const originX = options.originX ?? 80;
  const originY = options.originY ?? 80;
  const gapX = Math.max(NODE_WIDTH + 12, options.gapX ?? 120);
  const gapY = Math.max(NODE_HEIGHT + 12, options.gapY ?? 96);
  const next = nodes.map((n, index) => ({
    id: n.id,
    x: Math.round(originX + (index % columns) * gapX),
    y: Math.round(originY + Math.floor(index / columns) * gapY),
  }));
  return changed(nodes, next);
}

/** Apply a set of position updates to a node list without mutating the input. */
export function applyPositions<T extends NodePosition>(
  nodes: readonly T[],
  updates: readonly PositionUpdate[],
): T[] {
  if (updates.length === 0) return nodes.map((n) => ({ ...n }));
  const byId = new Map(updates.map((u) => [u.id, u]));
  return nodes.map((n) => {
    const update = byId.get(n.id);
    return update ? { ...n, x: update.x, y: update.y } : { ...n };
  });
}
