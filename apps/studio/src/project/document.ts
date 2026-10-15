/** Unified versioned project document (tracker M0-01/M0-03/M0-04).
 *
 * This is the single `project.json` a Studio project reads and writes. It
 * composes the graph authoring document with the catalog references, agents,
 * domains, access, floorplan and workload sections plus project metadata, and
 * records the document schema version and the compiler semantics version the
 * project targets.
 *
 * Migration is delegated to the generic pipeline in `./migrate`: a document
 * with no `schema_version` is recognised as the legacy flat graph form (project
 * schema version 0), lifted into the envelope, and every generated run records
 * the same `compiler_semantics_version` so a result is never read under
 * mismatched semantics.
 */
import {
  canonicalizeJson,
  canonicalizeProject,
  errorIssues,
  stableHash,
  validateProject,
  type JsonValue,
  type LoomProject,
  type ProjectIssue,
} from '../graph/project';
import { deepCloneJson, migrateDocument, MigrationError, type MigrationStep } from './migrate';

export const PROJECT_DOCUMENT_SCHEMA_VERSION = 1;
export const PROJECT_COMPILER_SEMANTICS_VERSION = 1;

/** The legacy flat graph form is project schema version 0. */
export const LEGACY_PROJECT_SCHEMA_VERSION = 0;

export interface ProjectMetadata {
  id?: string | null;
  name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProjectDocument {
  schema_version: number;
  compiler_semantics_version: number;
  metadata: ProjectMetadata;
  graph: LoomProject;
  catalog_refs: JsonValue | null;
  agents: JsonValue | null;
  domains: JsonValue | null;
  access: JsonValue | null;
  floorplan: JsonValue | null;
  workload: JsonValue | null;
}

const DOCUMENT_SECTIONS = ['catalog_refs', 'agents', 'domains', 'access', 'floorplan', 'workload'] as const;
const METADATA_KEYS = ['id', 'name', 'created_at', 'updated_at'] as const;
const DOCUMENT_KEYS = new Set([
  'schema_version', 'compiler_semantics_version', 'metadata', 'graph', ...DOCUMENT_SECTIONS,
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const isJsonSection = (value: unknown): boolean => value === null || Array.isArray(value) || isRecord(value);

/** A document with no `schema_version` but the graph form's fields is the
 *  legacy flat graph document, project schema version 0. */
const detectLegacyGraph = (doc: Record<string, unknown>): number | null => {
  if (!('schema_version' in doc) && ('schemaVersion' in doc || ('nodes' in doc && 'edges' in doc))) {
    return LEGACY_PROJECT_SCHEMA_VERSION;
  }
  return null;
};

/** v0 (legacy flat graph) -> v1 (unified envelope). Lifts the graph-local
 *  `firewall`/`workload` annotations into the top-level `access`/`workload`
 *  sections and leaves a pure graph document. Deterministic and non-mutating. */
export const migrateV0ToV1: MigrationStep = {
  from: 0,
  to: 1,
  code: 'project.v0_to_v1',
  migrate: (doc) => {
    const graph: Record<string, unknown> = { ...doc };
    const access = isRecord(doc.firewall) ? doc.firewall : null;
    const workload = isRecord(doc.workload) ? doc.workload : null;
    delete graph.firewall;
    delete graph.workload;
    return {
      schema_version: 1,
      compiler_semantics_version: PROJECT_COMPILER_SEMANTICS_VERSION,
      metadata: {},
      graph,
      catalog_refs: null,
      agents: null,
      domains: null,
      access,
      floorplan: null,
      workload,
    };
  },
};

export const PROJECT_MIGRATIONS: readonly MigrationStep[] = [migrateV0ToV1];

export type ProjectMigrationReport = {
  doc: ProjectDocument;
  fromVersion: number;
  toVersion: number;
  applied: { from: number; to: number; code: string }[];
};

/** Migrate any recognised project form to the current document version. */
export function migrateProjectDocument(value: unknown): ProjectMigrationReport {
  const report = migrateDocument(value, {
    targetVersion: PROJECT_DOCUMENT_SCHEMA_VERSION,
    steps: PROJECT_MIGRATIONS,
    detectVersion: detectLegacyGraph,
  });
  return { ...report, doc: report.doc as unknown as ProjectDocument };
}

/** Validate the unified document: versions, metadata, every named section and
 *  the embedded graph. Graph issue paths are re-rooted under `$.graph`. */
export function validateProjectDocument(value: unknown): ProjectIssue[] {
  const issues: ProjectIssue[] = [];
  const issue = (path: string, message: string, code?: string): void => {
    issues.push({ path, message, severity: 'error', code: code ?? `${path.replace(/^\$\.?/, '').replace(/\.$/, '') || 'root'}.invalid`, objectRef: path });
  };
  if (!isRecord(value)) return [{ path: '$.root', message: 'must be an object', severity: 'error', code: 'root.must_be_an_object', objectRef: '$' }];
  for (const key of Object.keys(value)) if (!DOCUMENT_KEYS.has(key)) issue(`$.${key}`, 'unknown field');
  if (value.schema_version !== PROJECT_DOCUMENT_SCHEMA_VERSION) {
    issue('$.schema_version', `must equal ${PROJECT_DOCUMENT_SCHEMA_VERSION}`, 'document.schema_version');
  }
  const semver = value.compiler_semantics_version;
  if (typeof semver !== 'number' || !Number.isSafeInteger(semver) || semver < 1) {
    issue('$.compiler_semantics_version', 'must be a positive integer', 'document.compiler_semantics_version');
  }
  if (!isRecord(value.metadata)) {
    issue('$.metadata', 'must be an object', 'document.metadata');
  } else {
    for (const key of Object.keys(value.metadata)) {
      if (!(METADATA_KEYS as readonly string[]).includes(key)) issue(`$.metadata.${key}`, 'unknown field');
    }
    for (const key of METADATA_KEYS) {
      const field = value.metadata[key];
      if (field !== undefined && field !== null && typeof field !== 'string') {
        issue(`$.metadata.${key}`, 'must be a string or null');
      }
    }
  }
  for (const section of DOCUMENT_SECTIONS) {
    if (!(section in value)) issue(`$.${section}`, 'section must be present (use null when empty)', `document.section_missing`);
    else if (!isJsonSection(value[section])) issue(`$.${section}`, 'must be an object, array or null', 'document.section_shape');
  }
  if (!('graph' in value)) {
    issue('$.graph', 'must be present', 'document.graph_missing');
  } else {
    for (const inner of validateProject(value.graph)) {
      issues.push({ ...inner, path: inner.path === '$' ? '$.graph' : `$.graph${inner.path.slice(1)}` });
    }
  }
  return issues;
}

const canonicalMetadata = (metadata: ProjectMetadata): Record<string, unknown> => {
  const out: Record<string, unknown> = {};
  for (const key of METADATA_KEYS) if (metadata[key] !== undefined) out[key] = metadata[key];
  return out;
};

/** Canonical project document: fixed top-level order, canonical graph, and
 *  key-sorted open sections. Equal documents serialize identically (M0-19). */
export function canonicalizeProjectDocument(doc: ProjectDocument): Record<string, unknown> {
  const out: Record<string, unknown> = {
    schema_version: doc.schema_version,
    compiler_semantics_version: doc.compiler_semantics_version,
    metadata: canonicalMetadata(doc.metadata ?? {}),
    graph: canonicalizeProject(doc.graph),
  };
  for (const section of DOCUMENT_SECTIONS) {
    out[section] = doc[section] === null || doc[section] === undefined ? null : canonicalizeJson(doc[section]);
  }
  return out;
}

export function fingerprintProjectDocument(doc: ProjectDocument): string {
  return stableHash(JSON.stringify(canonicalizeProjectDocument(doc)));
}

/** The graph sub-document of a project (authoring state is graph-scoped). */
export const graphOf = (doc: ProjectDocument): LoomProject => doc.graph;

/** Wrap a graph document (and optional metadata) into a current envelope. The
 *  graph-local `firewall`/`workload` annotations are lifted into the top-level
 *  `access`/`workload` sections so the envelope is the single home for them. */
export function wrapProjectDocument(graph: LoomProject, metadata: ProjectMetadata = {}): ProjectDocument {
  const copy = deepCloneJson(graph) as LoomProject & { firewall?: JsonValue; workload?: JsonValue };
  const access = copy.firewall ?? null;
  const workload = copy.workload ?? null;
  delete copy.firewall;
  delete copy.workload;
  return {
    schema_version: PROJECT_DOCUMENT_SCHEMA_VERSION,
    compiler_semantics_version: PROJECT_COMPILER_SEMANTICS_VERSION,
    metadata,
    graph: copy,
    catalog_refs: null, agents: null, domains: null, access, floorplan: null, workload,
  };
}

/** Fold a project document back into the graph-scoped authoring state the
 *  editor uses: the `access`/`workload` sections return to the graph-local
 *  `firewall`/`workload` fields so the access and workload editors keep them. */
export function graphFromDocument(doc: ProjectDocument): LoomProject {
  const graph = deepCloneJson(doc.graph) as LoomProject & { firewall?: JsonValue; workload?: JsonValue };
  if (doc.access !== null && doc.access !== undefined && graph.firewall === undefined) {
    graph.firewall = doc.access as { [key: string]: JsonValue };
  }
  if (doc.workload !== null && doc.workload !== undefined && graph.workload === undefined) {
    graph.workload = doc.workload as { [key: string]: JsonValue };
  }
  return graph;
}

/** Parse, migrate and validate a `project.json` text. Accepts both the legacy
 *  flat graph form and the unified envelope; refuses newer versions and errors
 *  with the offending version named. */
export function parseProjectDocument(json: string): ProjectDocument {
  let value: unknown;
  try { value = JSON.parse(json); }
  catch (error) { throw new Error(`invalid project JSON: ${error instanceof Error ? error.message : String(error)}`); }
  let doc: ProjectDocument;
  try {
    doc = migrateProjectDocument(value).doc;
  } catch (error) {
    if (error instanceof MigrationError) throw new Error(`${error.message} (${error.code})`);
    throw error;
  }
  const errors = errorIssues(validateProjectDocument(doc));
  if (errors.length) throw new Error(errors.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return doc;
}

export function serializeProjectDocument(doc: ProjectDocument): string {
  const errors = errorIssues(validateProjectDocument(doc));
  if (errors.length) throw new Error(errors.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return `${JSON.stringify(canonicalizeProjectDocument(doc), null, 2)}\n`;
}
