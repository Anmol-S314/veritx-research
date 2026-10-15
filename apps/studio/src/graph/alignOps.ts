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
