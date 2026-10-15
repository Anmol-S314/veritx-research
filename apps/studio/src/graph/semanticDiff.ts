import type { LoomProject } from './project';

export interface SemanticChange {
  objectType: 'node' | 'edge' | 'project';
  objectId: string;
  path: string;
  before: unknown;
  after: unknown;
}
const json = (value: unknown): string => JSON.stringify(value);

function diffValue(before: unknown, after: unknown, path: string, objectType: SemanticChange['objectType'], objectId: string, out: SemanticChange[]): void {
  if (json(before) === json(after)) return;
  if (Array.isArray(before) && Array.isArray(after)) {
    const hasStableIds = (values: unknown[]): values is (Record<string, unknown> & { id: string })[] =>
      values.every(value => value !== null && typeof value === 'object' && !Array.isArray(value)
        && typeof (value as Record<string, unknown>).id === 'string')
      && new Set(values.map(value => (value as { id: string }).id)).size === values.length;
    if (hasStableIds(before) && hasStableIds(after)) {
      const left = new Map(before.map(value => [value.id, value]));
      const right = new Map(after.map(value => [value.id, value]));
      for (const id of [...new Set([...left.keys(), ...right.keys()])].sort()) {
        const a = left.get(id);
        const b = right.get(id);
        const itemPath = `${path}[${id}]`;
        if (a === undefined || b === undefined) out.push({ objectType, objectId, path: itemPath, before: a, after: b });
        else diffValue(a, b, itemPath, objectType, objectId, out);
      }
      return;
    }
  }
  if (before && after && typeof before === 'object' && typeof after === 'object' && !Array.isArray(before) && !Array.isArray(after)) {
    const left = before as Record<string, unknown>;
    const right = after as Record<string, unknown>;
    for (const key of [...new Set([...Object.keys(left), ...Object.keys(right)])].sort()) {
      diffValue(left[key], right[key], path ? `${path}.${key}` : key, objectType, objectId, out);
    }
    return;
  }
  out.push({ objectType, objectId, path, before, after });
}

/** Stable-ID graph diff. It deliberately reports only fields represented by
 * this current project contract; it cannot invent missing domains/floorplan. */
export function semanticProjectDiff(before: LoomProject, after: LoomProject): SemanticChange[] {
  const changes: SemanticChange[] = [];
  for (const collection of ['nodes', 'edges'] as const) {
    const kind = collection === 'nodes' ? 'node' : 'edge';
    const left = new Map(before[collection].map(item => [item.id, item]));
    const right = new Map(after[collection].map(item => [item.id, item]));
    for (const id of [...new Set([...left.keys(), ...right.keys()])].sort()) {
      const a = left.get(id);
      const b = right.get(id);
      if (a === undefined || b === undefined) changes.push({ objectType: kind, objectId: id, path: '', before: a, after: b });
      else diffValue(a, b, '', kind, id, changes);
    }
  }
  const { nodes: _beforeNodes, edges: _beforeEdges, ...beforeMetadata } = before;
  const { nodes: _afterNodes, edges: _afterEdges, ...afterMetadata } = after;
  diffValue(beforeMetadata, afterMetadata, '', 'project', 'project', changes);
  return changes.sort((a, b) => `${a.objectType}:${a.objectId}:${a.path}`.localeCompare(`${b.objectType}:${b.objectId}:${b.path}`));
}
