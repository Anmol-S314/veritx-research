/** Topology-wide search over the authoring graph (tracker M1-31).
 *
 *  `searchGraph` is a pure substring matcher over node and edge fields. It has
 *  no notion of a route, a compiler artifact or a measured value: it only finds
 *  authored objects so a UI can select and centre them. Results are ranked and
 *  stable — identical input yields an identical ordering — so the caller can
 *  render them without re-sorting.
 */
import type { GraphEdge, GraphNode, LoomProject } from './project';

export type GraphMatchKind = 'node' | 'edge';

export interface GraphMatch {
  kind: GraphMatchKind;
  id: string;
  /** Human label of the object, e.g. `n3 · compute_tile`. */
  label: string;
  /** The field the query matched, e.g. `role`, `clock`, `src`. */
  field: string;
  /** The matched value, verbatim (stringified for non-strings). */
  value: string;
  /** Lower is better; used only for ordering within a result set. */
  score: number;
}

const MAX_RESULTS = 200;

const asText = (value: unknown): string =>
  value === null || value === undefined ? '' : String(value);

interface Candidate { kind: GraphMatchKind; id: string; label: string; field: string; value: string }

function nodeCandidates(node: GraphNode): Candidate[] {
  const label = `${node.id} · ${node.role}`;
  const entries: [string, unknown][] = [
    ['id', node.id],
    ['role', node.role],
    ['clock', node.clock],
    ['resetDomain', node.resetDomain],
    ['powerDomain', node.powerDomain],
    ['interfaceRole', node.interfaceRole],
    ['catalog', node.catalogRef?.itemId],
    ['catalog', node.catalogRef?.catalogId],
  ];
  return entries.flatMap(([field, value]) => {
    const text = asText(value);
    return text === '' ? [] : [{ kind: 'node' as const, id: node.id, label, field, value: text }];
  });
}

function edgeCandidates(edge: GraphEdge): Candidate[] {
  const label = `${edge.src} → ${edge.dst}`;
  const entries: [string, unknown][] = [
    ['id', edge.id],
    ['src', edge.src],
    ['dst', edge.dst],
    ['vcClass', edge.vcClass],
    ['width', edge.width],
  ];
  return entries.map(([field, value]) => ({
    kind: 'edge' as const, id: edge.id, label, field, value: asText(value),
  }));
}

/** Rank a candidate for a lower-cased query. Exact id beats an id prefix, an
 *  id substring, then any other field match; ties keep document order through
 *  the caller's stable sort. */
function scoreOf(candidate: Candidate, query: string): number {
  const value = candidate.value.toLowerCase();
  const id = candidate.id.toLowerCase();
  if (candidate.field === 'id' && value === query) return 0;
  if (candidate.field === 'id' && id.startsWith(query)) return 1;
  if (candidate.field === 'id') return 2;
  if (value === query) return 3;
  if (value.startsWith(query)) return 4;
  return 5;
}

/** All authored objects whose id or a searchable field contains `query`
 *  (case-insensitive). An empty or whitespace-only query returns no matches:
 *  the caller keeps its own selection instead of being handed the whole graph.
 *  At most one row per (object, field) pair survives. */
export function searchGraph(doc: LoomProject, query: string, limit = MAX_RESULTS): GraphMatch[] {
  const needle = query.trim().toLowerCase();
  if (needle === '') return [];
  const candidates: Candidate[] = [
    ...doc.nodes.flatMap(nodeCandidates),
    ...doc.edges.flatMap(edgeCandidates),
  ].filter((candidate) => candidate.value.toLowerCase().includes(needle));
  const ranked: GraphMatch[] = candidates
    .map((candidate) => ({
      kind: candidate.kind,
      id: candidate.id,
      label: candidate.label,
      field: candidate.field,
      value: candidate.value,
      score: scoreOf(candidate, needle),
    }))
    // Equal scores keep the candidates' document order (Array.sort is stable):
    // nodes in node order, then edges in edge order. No id tie-break, so a
    // heap of similarly-scored ids reads in the order the author sees them.
    .sort((a, b) => a.score - b.score
      || (a.kind === b.kind ? 0 : a.kind === 'node' ? -1 : 1));
  return ranked.slice(0, Math.max(0, limit));
}

/** The distinct node ids a result set points at, in result order — what a
 *  click-to-select consumer applies to the canvas. */
export const matchedNodeIds = (matches: readonly GraphMatch[]): string[] =>
  [...new Set(matches.filter((m) => m.kind === 'node').map((m) => m.id))];
