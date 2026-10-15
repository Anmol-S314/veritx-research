/** Explicit, non-mutating Loom project migrations. Source strings are never rewritten. */
import { serializeProject, validateProject, type LoomProject } from './project';
import { validationIssue, type ValidationIssue } from './validation';

type RecordValue = Record<string, unknown>;
const record = (x: unknown): x is RecordValue => x !== null && typeof x === 'object' && !Array.isArray(x);

export interface MigrationChange {
  path: string;
  kind: 'added' | 'removed' | 'changed';
  before?: unknown;
  after?: unknown;
}

export interface MigrationPreview {
  sourceVersion: number;
  targetVersion: 1;
  migrated: LoomProject;
  before: string;
  after: string;
  changed: boolean;
  steps: string[];
  diff: MigrationChange[];
}
export type MigrationPreviewResult = { ok: true; preview: MigrationPreview } | { ok: false; issues: ValidationIssue[] };

class MigrationBlockedError extends Error {
  constructor(message: string, readonly issues: ValidationIssue[]) { super(message); }
}

function childPath(path: string, key: string | number): string {
  return typeof key === 'number' ? `${path}[${key}]` : /^[A-Za-z_$][\w$]*$/.test(key) ? `${path}.${key}` : `${path}[${JSON.stringify(key)}]`;
}

function diffJson(before: unknown, after: unknown, path = '$', changes: MigrationChange[] = []): MigrationChange[] {
  if (record(before) && record(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
    for (const key of keys) {
      const had = Object.prototype.hasOwnProperty.call(before, key);
      const has = Object.prototype.hasOwnProperty.call(after, key);
      const at = childPath(path, key);
      if (!had) changes.push({ path: at, kind: 'added', after: after[key] });
      else if (!has) changes.push({ path: at, kind: 'removed', before: before[key] });
      else diffJson(before[key], after[key], at, changes);
    }
  } else if (Array.isArray(before) && Array.isArray(after)) {
    const length = Math.max(before.length, after.length);
    for (let i = 0; i < length; i++) {
      const at = childPath(path, i);
      if (i >= before.length) changes.push({ path: at, kind: 'added', after: after[i] });
      else if (i >= after.length) changes.push({ path: at, kind: 'removed', before: before[i] });
      else diffJson(before[i], after[i], at, changes);
    }
  } else if (!Object.is(before, after)) {
    changes.push({ path, kind: 'changed', before, after });
  }
  return changes;
}

function convertLegacyFirewall(firewall: unknown, nodes: unknown): RecordValue | null {
  if (!record(firewall) || Object.keys(firewall).some(key => key !== 'default' && key !== 'rules')) return null;
  if (firewall.default !== 'deny' || !Array.isArray(firewall.rules) || !Array.isArray(nodes)) return null;
  const nodeIds = new Set(nodes.filter(record).map(node => node.id).filter((id): id is string => typeof id === 'string'));
  const seenPairs = new Set<string>();
  const rules: RecordValue[] = [];
  for (const [index, raw] of firewall.rules.entries()) {
    if (!record(raw) || Object.keys(raw).some(key => key !== 'src' && key !== 'dst' && key !== 'perm')) return null;
    if (typeof raw.src !== 'string' || typeof raw.dst !== 'string' || !nodeIds.has(raw.src) || !nodeIds.has(raw.dst)) return null;
    if (raw.src === raw.dst || (raw.perm !== 'RO' && raw.perm !== 'RW')) return null;
    const pair = JSON.stringify([raw.src, raw.dst]);
    if (seenPairs.has(pair)) return null;
    seenPairs.add(pair);
    rules.push({
      id: `legacy-firewall-${index + 1}`,
      precedence: index,
      source: { nodeIds: [raw.src] },
      target: { nodeIds: [raw.dst] },
      policy: raw.perm === 'RO' ? 'read_only' : 'read_write',
    });
  }
  return { defaultPolicy: 'deny', rules };
}

function migrationError(path: string, reason: string): never {
  const message = `migration blocked at ${path}: ${reason}; source was not modified`;
  throw new MigrationBlockedError(message, [validationIssue('LOOM_MIGRATION_BLOCKED', path, message)]);
}

/** Migrate supported pre-contract v0 and early v1 projects one step at a time. */
export function previewProjectMigration(source: string): MigrationPreview {
  let parsed: unknown;
  try { parsed = JSON.parse(source); }
  catch (e) {
    const message = `invalid project JSON: ${e instanceof Error ? e.message : String(e)}`;
    throw new MigrationBlockedError(message, [validationIssue('LOOM_PROJECT_INVALID', '$', message)]);
  }
  if (!record(parsed)) migrationError('$', 'expected an object');
  const version = parsed.schemaVersion === undefined ? 0 : parsed.schemaVersion;
  if (version !== 0 && version !== 1) migrationError('$.schemaVersion', `unsupported version ${String(version)} (current version is 1)`);
  const project: RecordValue = structuredClone(parsed);
  const steps: string[] = [];
  if (version === 0) {
    if (!Array.isArray(project.nodes) || !Array.isArray(project.edges)) migrationError('$', 'v0 requires nodes and edges arrays');
    project.schemaVersion = 1;
    steps.push('v0→v1: record project schema version');
  }
  if (project.compilerSemanticsVersion === undefined) {
    project.compilerSemanticsVersion = 1;
    steps.push('v1: add compilerSemanticsVersion=1 (legacy project default)');
  } else if (project.compilerSemanticsVersion !== 1) {
    migrationError('$.compilerSemanticsVersion', `unsupported version ${String(project.compilerSemanticsVersion)}`);
  }
  // Historical side map is accepted only when it can be merged without ambiguity.
  if (project.pipelineStagesByEdge !== undefined) {
    const side = project.pipelineStagesByEdge;
    if (!record(side)) migrationError('$.pipelineStagesByEdge', 'expected an edge-id map');
    if (!Array.isArray(project.edges)) migrationError('$.edges', 'expected an array');
    const edges = project.edges.map((e, i) => {
      if (!record(e)) migrationError(`$.edges[${i}]`, 'expected an object');
      const mapped = side[e.id as string];
      if (mapped === undefined) return e;
      if (e.pipelineStages !== undefined && e.pipelineStages !== mapped) migrationError(`$.edges[${i}].pipelineStages`, 'conflicts with legacy side map');
      return { ...e, pipelineStages: mapped };
    });
    for (const key of Object.keys(side)) if (!project.edges.some((e) => record(e) && e.id === key)) migrationError(`$.pipelineStagesByEdge.${key}`, 'references an unknown edge');
    project.edges = edges;
    delete project.pipelineStagesByEdge;
    steps.push('v1: fold pipelineStagesByEdge into edges[].pipelineStages');
  }
  if (project.firewall !== undefined && project.access === undefined) {
    const converted = convertLegacyFirewall(project.firewall, project.nodes);
    if (converted) {
      project.access = converted;
      steps.push('v1: explicitly map supported legacy firewall rules to access (legacy field retained)');
    } else {
      steps.push('v1: retain legacy firewall unchanged; no semantics-safe access conversion available');
    }
  }
  if (project.presetHint === undefined) project.presetHint = null;
  const issues = validateProject(project);
  if (issues.length) {
    const message = `migration blocked; no data discarded and source was not modified:\n${issues.map(x => `${x.path}: ${x.message}`).join('\n')}`;
    throw new MigrationBlockedError(message, issues);
  }
  const migrated = project as unknown as LoomProject;
  const after = serializeProject(migrated);
  const normalized = JSON.parse(after) as LoomProject;
  return { sourceVersion: version, targetVersion: 1, migrated: normalized, before: source, after, changed: source !== after, steps, diff: diffJson(parsed, normalized) };
}

/** Non-throwing preview result with canonical findings; source text is never changed. */
export function previewProjectMigrationResult(source: string): MigrationPreviewResult {
  try { return { ok: true, preview: previewProjectMigration(source) }; }
  catch (error) {
    if (error instanceof MigrationBlockedError) return { ok: false, issues: error.issues };
    throw error;
  }
}

/** Explicit opt-in result; caller must save the returned text as a new file. */
export function migrateProject(source: string): LoomProject {
  return previewProjectMigration(source).migrated;
}
