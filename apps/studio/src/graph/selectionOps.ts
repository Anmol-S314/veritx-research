/** Predictable selection actions over the authoring graph (tracker M1-08).
 *
 *  Select-all, invert and clear operate on the CURRENT document and the
 *  current selection and return a plain `{ nodes, edges }` set of ids. They are
 *  pure: the caller decides how to store the result. Ordering follows the
 *  document order, so the same graph always yields the same selection.
 */
import type { LoomProject } from './project';

export interface Selection {
  nodes: string[];
  edges: string[];
}

export const EMPTY_SELECTION: Selection = { nodes: [], edges: [] };

export const clearSelection = (): Selection => ({ nodes: [], edges: [] });

/** Every node and every edge, in document order. */
export const selectAll = (doc: LoomProject): Selection => ({
  nodes: doc.nodes.map((n) => n.id),
  edges: doc.edges.map((e) => e.id),
});

/** The complement of the current selection within the document, in document
 *  order. Inverting twice returns the original selection. */
export function invertSelection(doc: LoomProject, sel: Selection): Selection {
  const nodes = new Set(sel.nodes);
  const edges = new Set(sel.edges);
  return {
    nodes: doc.nodes.filter((n) => !nodes.has(n.id)).map((n) => n.id),
    edges: doc.edges.filter((e) => !edges.has(e.id)).map((e) => e.id),
  };
}

/** Whether an id is currently selected on either side. */
export const isSelected = (sel: Selection, kind: 'node' | 'edge', id: string): boolean =>
  (kind === 'node' ? sel.nodes : sel.edges).includes(id);
