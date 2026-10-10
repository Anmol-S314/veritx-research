/** Versioned editable graph document for Loom. This is authoring data, not a
 * compiled fabric or execution claim. Keep the compiler adapter separate. */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface GraphNode {
  id: string;
  x: number;
  y: number;
  role: string;
  ports: number;
  clock?: string | null;
  vc?: { [key: string]: JsonValue };
}

export interface GraphEdge {
  id: string;
  src: string;
  dst: string;
  width: number;
  pipelineStages: number;
  vcClass: number;
}

export interface LoomProject {
  schemaVersion: 1;
  presetHint: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  firewall?: { [key: string]: JsonValue };
  workload?: { [key: string]: JsonValue };
}

export interface ProjectIssue { path: string; message: string }

const MAX_NODES = 256;
const MAX_EDGES = 512;
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const isPositiveInt = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const MAX_METADATA_DEPTH = 64;
const isJsonValue = (value: unknown, depth = 0): value is JsonValue => {
  if (depth > MAX_METADATA_DEPTH) return false;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((child) => isJsonValue(child, depth + 1));
  return isRecord(value) && Object.values(value).every((child) => isJsonValue(child, depth + 1));
};

/** Validate identity, endpoint, degree and connectivity invariants before a
 *  graph document enters editor state or is serialized. */
export function validateProject(value: unknown): ProjectIssue[] {
  const issues: ProjectIssue[] = [];
  const issue = (path: string, message: string): void => { issues.push({ path, message }); };
  if (!isRecord(value)) return [{ path: '$', message: 'must be an object' }];
  const allowed = new Set(['schemaVersion', 'presetHint', 'nodes', 'edges', 'firewall', 'workload']);
  for (const key of Object.keys(value)) if (!allowed.has(key)) issue(`$.${key}`, 'unknown field');
  if (value.schemaVersion !== 1) issue('$.schemaVersion', 'must equal 1');
  if (value.presetHint !== null && typeof value.presetHint !== 'string') issue('$.presetHint', 'must be a string or null');
  if (!Array.isArray(value.nodes)) issue('$.nodes', 'must be an array');
  if (!Array.isArray(value.edges)) issue('$.edges', 'must be an array');
  if (Array.isArray(value.nodes) && value.nodes.length > MAX_NODES) issue('$.nodes', `exceeds ${MAX_NODES}-node budget`);
  if (Array.isArray(value.edges) && value.edges.length > MAX_EDGES) issue('$.edges', `exceeds ${MAX_EDGES}-edge budget`);
  for (const key of ['firewall', 'workload'] as const) {
    if (value[key] !== undefined && (!isRecord(value[key]) || !isJsonValue(value[key]))) {
      issue(`$.${key}`, 'must be a JSON object');
    }
  }

  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  const edges = Array.isArray(value.edges) ? value.edges : [];
  const nodeIds = new Set<string>();
  const nodeById = new Map<string, Record<string, unknown>>();
  const degree = new Map<string, number>();
  nodes.forEach((raw, i) => {
    const path = `$.nodes[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'x', 'y', 'role', 'ports', 'clock', 'vc'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    if (typeof raw.id !== 'string' || raw.id.trim() === '') issue(`${path}.id`, 'must be a non-empty string');
    else if (nodeIds.has(raw.id)) issue(`${path}.id`, `duplicate node id ${raw.id}`);
    else { nodeIds.add(raw.id); nodeById.set(raw.id, raw); degree.set(raw.id, 0); }
    if (!isFiniteNumber(raw.x)) issue(`${path}.x`, 'must be finite');
    if (!isFiniteNumber(raw.y)) issue(`${path}.y`, 'must be finite');
    if (typeof raw.role !== 'string' || raw.role.trim() === '') issue(`${path}.role`, 'must be a non-empty string');
    if (!isPositiveInt(raw.ports)) issue(`${path}.ports`, 'must be a positive integer');
    if (raw.clock !== undefined && raw.clock !== null && (typeof raw.clock !== 'string' || raw.clock === '')) issue(`${path}.clock`, 'must be a non-empty string or null');
    if (raw.vc !== undefined && (!isRecord(raw.vc) || !isJsonValue(raw.vc))) issue(`${path}.vc`, 'must be a JSON object');
  });

  const edgeIds = new Set<string>();
  const adjacency = new Map([...nodeIds].map((id) => [id, new Set<string>()]));
  edges.forEach((raw, i) => {
    const path = `$.edges[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'src', 'dst', 'width', 'pipelineStages', 'vcClass'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    if (typeof raw.id !== 'string' || raw.id.trim() === '') issue(`${path}.id`, 'must be a non-empty string');
    else if (edgeIds.has(raw.id)) issue(`${path}.id`, `duplicate edge id ${raw.id}`);
    else edgeIds.add(raw.id);
    const src = typeof raw.src === 'string' ? raw.src : '';
    const dst = typeof raw.dst === 'string' ? raw.dst : '';
    if (!nodeIds.has(src)) issue(`${path}.src`, `unknown node ${src || '(empty)'}`);
    if (!nodeIds.has(dst)) issue(`${path}.dst`, `unknown node ${dst || '(empty)'}`);
    if (src && src === dst) issue(path, 'self-loops are not supported');
    if (isPositiveInt(raw.width) === false) issue(`${path}.width`, 'must be a positive integer');
    if (!isPositiveInt(raw.pipelineStages)) issue(`${path}.pipelineStages`, 'must be a positive integer');
    if (typeof raw.vcClass !== 'number' || !Number.isSafeInteger(raw.vcClass) || raw.vcClass < 0) issue(`${path}.vcClass`, 'must be a non-negative integer');
    if (nodeIds.has(src) && nodeIds.has(dst)) {
      degree.set(src, (degree.get(src) ?? 0) + 1);
      degree.set(dst, (degree.get(dst) ?? 0) + 1);
      adjacency.get(src)?.add(dst);
      adjacency.get(dst)?.add(src);
    }
  });

  for (const [id, used] of degree) {
    const ports = nodeById.get(id)?.ports;
    if (isPositiveInt(ports) && used > ports) issue(`$.nodes[id=${id}].ports`, `${used} incident edges exceed ${ports} ports`);
  }
  if (nodeIds.size > 1) {
    const seen = new Set<string>();
    const pending = [nodeIds.values().next().value as string];
    while (pending.length) {
      const id = pending.pop() as string;
      if (seen.has(id)) continue;
      seen.add(id);
      for (const next of adjacency.get(id) ?? []) if (!seen.has(next)) pending.push(next);
    }
    if (seen.size !== nodeIds.size) issue('$.nodes', 'graph is disconnected');
  }
  return issues;
}

export function parseProject(json: string): LoomProject {
  let value: unknown;
  try { value = JSON.parse(json); }
  catch (error) { throw new Error(`invalid project JSON: ${error instanceof Error ? error.message : String(error)}`); }
  const issues = validateProject(value);
  if (issues.length) throw new Error(issues.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return value as LoomProject;
}

export function serializeProject(project: LoomProject): string {
  const issues = validateProject(project);
  if (issues.length) throw new Error(issues.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return `${JSON.stringify(project, null, 2)}\n`;
}
