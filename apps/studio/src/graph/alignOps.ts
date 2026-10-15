/** Geometric alignment and distribution for a topology multi-selection
 *  (tracker M1-12 / M1-13).
 *
 *  Pure and deterministic: the operations read only node coordinates and the
 *  current selection, and return per-node patches that the caller applies as ONE
 *  command, so a whole alignment is a single undoable edit. They never change
 *  node identity, roles, ports or ordering semantics — only canvas x/y.
 */
import type { GraphNode } from './project';

export type AlignMode = 'left' | 'right' | 'top' | 'bottom' | 'center-x' | 'center-y';
export type DistributeAxis = 'horizontal' | 'vertical';

export interface NodePatch {
  id: string;
  patch: Partial<GraphNode>;
}

/** The drawn node box, in canvas units — the same 76×48 rectangle the editor
 *  renders around each node. Layout cleanup uses it to decide when two nodes
 *  visually collide; it is a spacing constant, not a physical footprint. */
export const LAYOUT_NODE_WIDTH = 76;
export const LAYOUT_NODE_HEIGHT = 48;

export interface CleanupOptions {
  /** Grid to snap onto; a non-positive step skips snapping. */
  gridStep?: number;
  /** Minimum gap left between two separated node boxes. */
  clearance?: number;
}

const finite = (value: number): boolean => Number.isFinite(value);

function takeSelected(nodes: readonly GraphNode[], ids: readonly string[]): GraphNode[] {
  const wanted = new Set(ids);
  return nodes.filter((node) => wanted.has(node.id));
}

/** Patch every selected node so the selection aligns on one edge or axis.
 *  Fewer than two selected nodes, or any non-finite coordinate, yields no
 *  patches (a refused no-op) rather than a partial move. */
export function alignNodes(nodes: readonly GraphNode[], ids: readonly string[], mode: AlignMode): NodePatch[] {
  const selected = takeSelected(nodes, ids);
  if (selected.length < 2) return [];
  if (selected.some((node) => !finite(node.x) || !finite(node.y))) return [];

  const xs = selected.map((node) => node.x);
  const ys = selected.map((node) => node.y);
  const left = Math.min(...xs);
  const right = Math.max(...xs);
  const top = Math.min(...ys);
  const bottom = Math.max(...ys);
  const midX = (left + right) / 2;
  const midY = (top + bottom) / 2;

  return selected.map((node) => {
    switch (mode) {
      case 'left': return { id: node.id, patch: { x: left } };
      case 'right': return { id: node.id, patch: { x: right } };
      case 'top': return { id: node.id, patch: { y: top } };
      case 'bottom': return { id: node.id, patch: { y: bottom } };
      case 'center-x': return { id: node.id, patch: { x: midX } };
      case 'center-y': return { id: node.id, patch: { y: midY } };
    }
  });
}

/** Evenly space the interior of a selection along one axis, keeping the two
 *  extreme nodes fixed. Ordering follows the current coordinate (document order
 *  breaks ties), so the result is deterministic. Fewer than three selected
 *  nodes yields no patches. */
export function distributeNodes(nodes: readonly GraphNode[], ids: readonly string[], axis: DistributeAxis): NodePatch[] {
  const selected = takeSelected(nodes, ids);
  if (selected.length < 3) return [];
  if (selected.some((node) => !finite(node.x) || !finite(node.y))) return [];

  const key = axis === 'horizontal' ? 'x' : 'y';
  const order = selected.slice();
  order.sort((a, b) => (a[key] === b[key] ? nodes.indexOf(a) - nodes.indexOf(b) : a[key] - b[key]));
  const first = order[0]!;
  const last = order[order.length - 1]!;
  const span = last[key] - first[key];
  const step = span / (order.length - 1);

  return order.map((node, index) => {
    const value = first[key] + step * index;
    return { id: node.id, patch: key === 'x' ? { x: value } : { y: value } };
  });
}

/** Tidy a selection: snap every node onto the grid, then push apart any boxes
 *  that still overlap. Nodes are visited in document order; the first node in
 *  the selection never moves, and each later node is pushed straight down just
 *  far enough to clear every earlier box. Deterministic for a given input, and
 *  expressed as patches the caller applies as ONE undoable edit.
 *
 *  This only changes canvas x/y. It never changes identity, roles, ports, edge
 *  endpoints or ordering, so it cannot alter the graph's meaning. */
export function cleanupNodes(
  nodes: readonly GraphNode[],
  ids: readonly string[],
  options: CleanupOptions = {},
): NodePatch[] {
  const selected = takeSelected(nodes, ids);
  if (selected.length < 2) return [];
  if (selected.some((node) => !finite(node.x) || !finite(node.y))) return [];
  const step = options.gridStep ?? 20;
  const clearance = Math.max(0, options.clearance ?? 12);

  const snapped = selected.map((node) => (step > 0
    ? { ...node, x: Math.round(node.x / step) * step, y: Math.round(node.y / step) * step }
    : node));

  const placed: GraphNode[] = [];
  for (const node of snapped) {
    let candidate = node;
    let guard = 0;
    while (placed.some((other) => Math.abs(other.x - candidate.x) < LAYOUT_NODE_WIDTH + clearance
      && Math.abs(other.y - candidate.y) < LAYOUT_NODE_HEIGHT + clearance) && guard < 10_000) {
      candidate = { ...candidate, y: candidate.y + LAYOUT_NODE_HEIGHT + clearance };
      guard += 1;
    }
    placed.push(candidate);
  }

  const before = new Map(selected.map((node) => [node.id, node]));
  return placed.flatMap((node) => {
    const previous = before.get(node.id)!;
    return previous.x !== node.x || previous.y !== node.y
      ? [{ id: node.id, patch: { x: node.x, y: node.y } }]
      : [];
  });
}
