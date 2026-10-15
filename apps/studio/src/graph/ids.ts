/** Stable node/edge identity rules for the authoring graph (tracker M0-02).
 *
 *  Rules (enforced by `graphIdProblem`, used by the project validator):
 *
 *  1. An id is a non-empty string of at most 64 characters from
 *     `[A-Za-z0-9_-]`, starting with a letter or digit. An id can never be
 *     empty, whitespace, a bare number-with-separator coordinate, or a label
 *     with spaces.
 *  2. An id is opaque and permanent: it is assigned once and survives save,
 *     load, copy/paste (remapped to a fresh unique id), and migration. An id
 *     is never derived from a node's position, role, label or array index, so
 *     moving a node (or reordering the arrays) never changes identity.
 *  3. Ids are unique within their kind (node ids unique among nodes, edge ids
 *     among edges) — the validator refuses a duplicate.
 *
 *  Fresh ids are minted deterministically from the document (`nextNodeId`,
 *  `nextEdgeId`) so the same starting graph always yields the same new id —
 *  no `Date.now()`, no randomness, no coordinate input.
 */
import type { GraphEdge, GraphNode, LoomProject } from './project';

/** See rule 1. Deliberately permissive enough for the seed presets (`n1`,`e1`)
 *  and the paste suffix form (`n1-c2`) while refusing whitespace and empty. */
export const GRAPH_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

export const isGraphId = (value: unknown): value is string =>
  typeof value === 'string' && GRAPH_ID_RE.test(value);

/** Return a refusal reason for a non-conforming id, or null when it is legal. */
export function graphIdProblem(value: unknown): string | null {
  if (typeof value !== 'string' || value.length === 0) return 'must be a non-empty string';
  if (value.length > 64) return 'must be at most 64 characters';
  if (!GRAPH_ID_RE.test(value)) {
    return 'must match [A-Za-z0-9_-] and start with a letter or digit';
  }
  return null;
}

const SUFFIX_OF = (prefix: 'n' | 'e') => new RegExp(`^${prefix}(\\d+)$`);

const nextSeq = (ids: string[], prefix: 'n' | 'e'): number => {
  const re = SUFFIX_OF(prefix);
  let max = 0;
  for (const id of ids) {
    const m = re.exec(id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return max + 1;
};

/** The next `n<number>` node id not implied by the current ids. Deterministic. */
export const nextNodeId = (nodes: Pick<GraphNode, 'id'>[]): string =>
  `n${nextSeq(nodes.map((n) => n.id), 'n')}`;

/** The next `e<number>` edge id not implied by the current ids. Deterministic. */
export const nextEdgeId = (edges: Pick<GraphEdge, 'id'>[]): string =>
  `e${nextSeq(edges.map((e) => e.id), 'e')}`;

/** A paste suffix token (`c1`, `c2`, ...) that no id in the document already
 *  carries, so remapped ids are unique and reproducible for a given document. */
export function nextPasteToken(nodes: Pick<GraphNode, 'id'>[], edges: Pick<GraphEdge, 'id'>[]): string {
  const all = [...nodes.map((n) => n.id), ...edges.map((e) => e.id)];
  let n = 1;
  while (all.some((id) => id.includes(`-c${n}`) || id.startsWith(`c${n}`))) n += 1;
  return `c${n}`;
}

export interface Clipboard {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** Remap a clipboard onto the document: every node gets a fresh unique id
 *  (`<id>-c<token>`), every internal edge is re-pointed at the new ids, and an
 *  offset is applied to positions. Edges whose endpoints are outside the
 *  clipboard are dropped (no dangling references). Pure: never mutates input. */
export function pasteClipboard(
  doc: LoomProject,
  clip: Clipboard,
  offset = { dx: 60, dy: 60 },
): Clipboard {
  const token = nextPasteToken(doc.nodes, doc.edges);
  const map = new Map<string, string>();
  const nodes = clip.nodes.map((n) => {
    const id = `${n.id}-c${token}`;
    map.set(n.id, id);
    return { ...n, id, x: n.x + offset.dx, y: n.y + offset.dy };
  });
  const edges = clip.edges
    .filter((e) => map.has(e.src) && map.has(e.dst))
    .map((e) => ({
      ...e,
      id: `${e.id}-c${token}`,
      src: map.get(e.src) as string,
      dst: map.get(e.dst) as string,
    }));
  return { nodes, edges };
}

/** Whether either endpoint of an edge is not present in `nodes` (dangling). */
export const hasDanglingEndpoints = (
  edge: Pick<GraphEdge, 'src' | 'dst'>,
  nodes: Pick<GraphNode, 'id'>[],
): boolean => {
  const ids = new Set(nodes.map((n) => n.id));
  return !ids.has(edge.src) || !ids.has(edge.dst);
};
