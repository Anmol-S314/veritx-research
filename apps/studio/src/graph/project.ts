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

/** Canonical validation result model (tracker M0-16/M1-29): every validator
 *  returns a severity, a stable machine code, a human message, and the object
 *  it refers to. Warnings are authoring-legal; errors block every path. The
 *  single-component policy is a warning while editing and an error when the
 *  graph is compiled/run. */
export type IssueSeverity = 'error' | 'warning';

export interface ProjectIssue {
  path: string;
  message: string;
  severity: IssueSeverity;
  code: string;
  /** Stable reference to the object at fault, e.g. `$.nodes[id=n3]`. */
  objectRef?: string;
  /** Component membership, present only for `graph.disconnected`. */
  components?: string[][];
  /** Optional safe, mechanical fix a UI may offer. */
  quickFix?: { label: string; code: string };
}

export interface ValidationOptions {
  /** Escalate a disconnected document from a warning to an error. Compile and
   *  run pass `true`; the authoring editor omits it so a pasted subgraph can
   *  be held before it is wired in. */
  requireConnected?: boolean;
}

export const errorIssues = (issues: ProjectIssue[]): ProjectIssue[] =>
  issues.filter((i) => i.severity === 'error');

export const hasErrors = (issues: ProjectIssue[]): boolean =>
  issues.some((i) => i.severity === 'error');

import { graphIdProblem } from './ids';

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

/** Derive a stable machine code from a JSON path and message. Every issue built
 *  without an explicit code gets one, so a UI can key on codes, not prose. */
const codeFor = (path: string, message: string): string => {
  const base = path.replace(/^\$\.?/, '').replace(/\[[^\]]*\]/g, '').replace(/\.$/, '') || 'root';
  const slug = message.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
  return `${base}.${slug}`;
};

export interface IssueInit {
  path: string;
  message: string;
  severity?: IssueSeverity;
  /** Stable machine code; derived from path+message when omitted. */
  code?: string;
  /** Stable reference to the object at fault; defaults to `path`. */
  objectRef?: string;
  /** Component membership, for `graph.disconnected`. */
  components?: string[][];
  /** Optional safe, mechanical fix a UI may offer. */
  quickFix?: { label: string; code: string };
}

/** Canonical constructor for a validation result (tracker M0-16). Every
 *  validator builds issues through here so severity, code, message and object
 *  reference are always present, consistently derived, and the optional
 *  quick-fix/components metadata has one shape. */
export const makeIssue = (init: IssueInit): ProjectIssue => {
  const issue: ProjectIssue = {
    path: init.path,
    message: init.message,
    severity: init.severity ?? 'error',
    code: init.code ?? codeFor(init.path, init.message),
    objectRef: init.objectRef ?? init.path,
  };
  if (init.components) issue.components = init.components;
  if (init.quickFix) issue.quickFix = init.quickFix;
  return issue;
};

/** Validate identity, endpoint, degree and connectivity invariants before a
 *  graph document enters editor state or is serialized. */


export function validateProject(value: unknown, options: ValidationOptions = {}): ProjectIssue[] {
  const issues: ProjectIssue[] = [];
  const issue = (path: string, message: string, extra: Partial<ProjectIssue> = {}): void => {
    // Every issue links to the object at fault; `path` is the JSON pointer and
    // `objectRef` is the stable id form when the caller knows one.
    issues.push(makeIssue({ path, message, ...extra }));
  };
  if (!isRecord(value)) return [makeIssue({ path: '$', message: 'must be an object', code: 'root.must_be_an_object' })];
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
    const nodeIdProblem = graphIdProblem(raw.id);
    if (nodeIdProblem) issue(`${path}.id`, nodeIdProblem, { code: 'node.id_format', objectRef: `${path}.id` });
    else if (nodeIds.has(raw.id as string)) issue(`${path}.id`, `duplicate node id ${raw.id}`);
    else { nodeIds.add(raw.id as string); nodeById.set(raw.id as string, raw); degree.set(raw.id as string, 0); }
    if (!isFiniteNumber(raw.x)) issue(`${path}.x`, 'must be finite');
    if (!isFiniteNumber(raw.y)) issue(`${path}.y`, 'must be finite');
    if (typeof raw.role !== 'string' || raw.role.trim() === '') issue(`${path}.role`, 'must be a non-empty string');
    if (!isPositiveInt(raw.ports)) issue(`${path}.ports`, 'must be a positive integer');
    if (raw.clock !== undefined && raw.clock !== null && (typeof raw.clock !== 'string' || raw.clock === '')) issue(`${path}.clock`, 'must be a non-empty string or null');
    if (raw.vc !== undefined && (!isRecord(raw.vc) || !isJsonValue(raw.vc))) issue(`${path}.vc`, 'must be a JSON object');
  });

  const edgeIds = new Set<string>();
  const directedPairs = new Map<string, string>();
  const adjacency = new Map([...nodeIds].map((id) => [id, new Set<string>()]));
  edges.forEach((raw, i) => {
    const path = `$.edges[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'src', 'dst', 'width', 'pipelineStages', 'vcClass'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    const edgeIdProblem = graphIdProblem(raw.id);
    if (edgeIdProblem) issue(`${path}.id`, edgeIdProblem, { code: 'edge.id_format', objectRef: `${path}.id` });
    else if (edgeIds.has(raw.id as string)) issue(`${path}.id`, `duplicate edge id ${raw.id}`);
    else edgeIds.add(raw.id as string);
    const src = typeof raw.src === 'string' ? raw.src : '';
    const dst = typeof raw.dst === 'string' ? raw.dst : '';
    if (!nodeIds.has(src)) issue(`${path}.src`, `unknown node ${src || '(empty)'}`);
    if (!nodeIds.has(dst)) issue(`${path}.dst`, `unknown node ${dst || '(empty)'}`);
    if (src && src === dst) issue(path, 'self-loops are not supported');
    if (nodeIds.has(src) && nodeIds.has(dst) && src !== dst) {
      const pair = `${src}\u0000${dst}`;
      const first = directedPairs.get(pair);
      if (first !== undefined) {
        issue(path, `duplicate directed link ${src} -> ${dst} (also ${first})`, {
          code: 'edge.duplicate_directed_link',
          objectRef: `$.edges[id=${typeof raw.id === 'string' ? raw.id : i}]`,
        });
      } else {
        directedPairs.set(pair, typeof raw.id === 'string' ? raw.id : path);
      }
    }
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
    const components: string[][] = [];
    for (const root of nodeIds) {
      if (seen.has(root)) continue;
      const component: string[] = [];
      const pending = [root];
      while (pending.length) {
        const id = pending.pop() as string;
        if (seen.has(id)) continue;
        seen.add(id);
        component.push(id);
        for (const next of adjacency.get(id) ?? []) if (!seen.has(next)) pending.push(next);
      }
      components.push(component.sort());
    }
    if (components.length > 1) {
      issue('$.nodes', `graph is disconnected (${components.length} components)`, {
        severity: options.requireConnected ? 'error' : 'warning',
        code: 'graph.disconnected',
        objectRef: '$.nodes',
        components,
        quickFix: { label: 'Select a component to attach', code: 'graph.attach_component' },
      });
    }
  }
  return issues;
}

/** Recursively sort object keys so equal JSON values serialize identically
 *  regardless of the order they were assigned. Arrays keep their order. */
export const canonicalizeJson = (value: JsonValue): JsonValue => {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value !== null && typeof value === 'object') {
    const out: { [key: string]: JsonValue } = {};
    for (const key of Object.keys(value).sort()) out[key] = canonicalizeJson(value[key]);
    return out;
  }
  return value;
};

/** Normalize a project into a canonical shape: fixed field ordering per node
 *  and edge, optional empties dropped, and unordered metadata key-sorted. Two
 *  semantically equal projects produce byte-identical output (M0-19). */
export function canonicalizeProject(project: LoomProject): Record<string, unknown> {
  const nodes = project.nodes.map((n) => {
    const out: Record<string, unknown> = {
      id: n.id, x: n.x, y: n.y, role: n.role, ports: n.ports,
    };
    if (n.clock !== undefined) out.clock = n.clock;
    if (n.vc !== undefined && Object.keys(n.vc).length > 0) out.vc = canonicalizeJson(n.vc);
    return out;
  });
  const edges = project.edges.map((e) => ({
    id: e.id, src: e.src, dst: e.dst, width: e.width,
    pipelineStages: e.pipelineStages, vcClass: e.vcClass,
  }));
  const out: Record<string, unknown> = {
    schemaVersion: project.schemaVersion, presetHint: project.presetHint, nodes, edges,
  };
  if (project.firewall !== undefined) out.firewall = canonicalizeJson(project.firewall);
  if (project.workload !== undefined) out.workload = canonicalizeJson(project.workload);
  return out;
}

/** cyrb53 — a small deterministic, non-cryptographic string hash. Used to give
 *  a project a stable fingerprint for diffs and run manifests. */
export const stableHash = (input: string): string => {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16).padStart(16, '0');
};

/** Stable content fingerprint of a project's canonical form. Equal projects
 *  hash equal; any edit changes the hash. */
export function fingerprintProject(project: LoomProject): string {
  return stableHash(JSON.stringify(canonicalizeProject(project)));
}

export function parseProject(json: string): LoomProject {
  let value: unknown;
  try { value = JSON.parse(json); }
  catch (error) { throw new Error(`invalid project JSON: ${error instanceof Error ? error.message : String(error)}`); }
  const errors = errorIssues(validateProject(value));
  if (errors.length) throw new Error(errors.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return value as LoomProject;
}

export function serializeProject(project: LoomProject): string {
  const errors = errorIssues(validateProject(project));
  if (errors.length) throw new Error(errors.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return `${JSON.stringify(canonicalizeProject(project), null, 2)}\n`;
}
