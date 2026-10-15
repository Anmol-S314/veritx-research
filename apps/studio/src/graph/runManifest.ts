import { PROVENANCE_STATES, type ProvenanceState } from './provenance';
import { serializeProject, type LoomProject } from './project';
import { validationIssue, type ValidationIssue } from './validation';

export interface RunArtifactV1 {
  path: string;
  sha256: string;
  sizeBytes: number;
  mediaType?: string;
}

export interface RunManifestV1 {
  schemaVersion: 1;
  runId: string;
  createdAt: string;
  projectFingerprint: string;
  projectSchemaVersion: number;
  compilerSemanticsVersion: number;
  engine: { name: string; version: string | null };
  uiVersion: string;
  backend: { id: string; version: string | null; provenance: ProvenanceState };
  /** Executable and arguments remain separate; never interpolate into a shell string. */
  command: string[];
  seed: number | null;
  inputs: Record<string, string | number | boolean | null>;
  artifacts: RunArtifactV1[];
}

export type RunManifestContext = Omit<RunManifestV1, 'schemaVersion' | 'projectFingerprint' | 'projectSchemaVersion' | 'compilerSemanticsVersion'>;

const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const sha256 = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const validDateTime = (value: unknown): value is string => {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match || !Number.isFinite(Date.parse(value))) return false;
  const [, y, mo, d, h, mi, s, , offsetHours, offsetMinutes] = match;
  const year = Number(y), month = Number(mo), day = Number(d);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]
    && Number(h) <= 23 && Number(mi) <= 59 && Number(s) <= 59
    && (offsetHours === undefined || (Number(offsetHours) <= 23 && Number(offsetMinutes) <= 59));
};

/** Validate a run manifest against the M0 v1 shape and return canonical findings. */
export function validateRunManifest(value: unknown): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const issue = (path: string, message: string): void => { issues.push(validationIssue('LOOM_RUN_MANIFEST_INVALID', path, message)); };
  if (!isRecord(value)) return [validationIssue('LOOM_RUN_MANIFEST_INVALID', '$', 'must be an object')];
  const allowed = ['schemaVersion', 'runId', 'createdAt', 'projectFingerprint', 'projectSchemaVersion', 'compilerSemanticsVersion', 'engine', 'uiVersion', 'backend', 'command', 'seed', 'inputs', 'artifacts'];
  for (const key of Object.keys(value)) if (!allowed.includes(key)) issue(`$.${key}`, 'unknown field');
  if (value.schemaVersion !== 1) issue('$.schemaVersion', 'must equal 1');
  if (!nonEmpty(value.runId)) issue('$.runId', 'must be a non-empty string');
  if (!validDateTime(value.createdAt)) issue('$.createdAt', 'must be an RFC 3339 date-time');
  if (!sha256(value.projectFingerprint)) issue('$.projectFingerprint', 'must be lowercase SHA-256 hex');
  for (const key of ['projectSchemaVersion', 'compilerSemanticsVersion']) if (!Number.isSafeInteger(value[key]) || (value[key] as number) < 1) issue(`$.${key}`, 'must be a positive integer');
  if (!isRecord(value.engine)) issue('$.engine', 'must be an object');
  else {
    for (const key of Object.keys(value.engine)) if (!['name', 'version'].includes(key)) issue(`$.engine.${key}`, 'unknown field');
    if (!nonEmpty(value.engine.name)) issue('$.engine.name', 'must be a non-empty string');
    if (value.engine.version !== null && typeof value.engine.version !== 'string') issue('$.engine.version', 'must be a string or null');
  }
  if (!nonEmpty(value.uiVersion)) issue('$.uiVersion', 'must be a non-empty string');
  if (!isRecord(value.backend)) issue('$.backend', 'must be an object');
  else {
    for (const key of Object.keys(value.backend)) if (!['id', 'version', 'provenance'].includes(key)) issue(`$.backend.${key}`, 'unknown field');
    if (!nonEmpty(value.backend.id)) issue('$.backend.id', 'must be a non-empty string');
    if (value.backend.version !== null && typeof value.backend.version !== 'string') issue('$.backend.version', 'must be a string or null');
    if (!PROVENANCE_STATES.includes(value.backend.provenance as ProvenanceState)) issue('$.backend.provenance', 'must be a supported provenance state');
  }
  if (!Array.isArray(value.command) || value.command.some(arg => typeof arg !== 'string')) issue('$.command', 'must be an argv array of strings');
  if (value.seed !== null && !Number.isSafeInteger(value.seed)) issue('$.seed', 'must be an integer or null');
  if (!isRecord(value.inputs)) issue('$.inputs', 'must be an object');
  else for (const [key, input] of Object.entries(value.inputs)) if (!(input === null || ['string', 'number', 'boolean'].includes(typeof input)) || (typeof input === 'number' && !Number.isFinite(input))) issue(`$.inputs.${key}`, 'must be a finite scalar or null');
  if (!Array.isArray(value.artifacts)) issue('$.artifacts', 'must be an array');
  else value.artifacts.forEach((artifact, index) => {
    const path = `$.artifacts[${index}]`;
    if (!isRecord(artifact)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(artifact)) if (!['path', 'sha256', 'sizeBytes', 'mediaType'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    if (!nonEmpty(artifact.path)) issue(`${path}.path`, 'must be a non-empty string');
    if (!sha256(artifact.sha256)) issue(`${path}.sha256`, 'must be lowercase SHA-256 hex');
    if (!Number.isSafeInteger(artifact.sizeBytes) || (artifact.sizeBytes as number) < 0) issue(`${path}.sizeBytes`, 'must be a non-negative integer');
    if (artifact.mediaType !== undefined && typeof artifact.mediaType !== 'string') issue(`${path}.mediaType`, 'must be a string');
  });
  return issues;
}

/** Build a reproducibility record from caller-supplied facts; no timestamps, versions, or seeds are invented. */
export async function createRunManifest(project: LoomProject, context: RunManifestContext): Promise<RunManifestV1> {
  // The manifest pins a full SHA-256 content identity of the canonical project
  // serialization (the editor's `fingerprintProject` is a short local hash).
  const canonical = serializeProject(project);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  const projectFingerprint = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  const manifest: RunManifestV1 = {
    schemaVersion: 1,
    runId: context.runId,
    createdAt: context.createdAt,
    projectFingerprint,
    projectSchemaVersion: project.schemaVersion,
    compilerSemanticsVersion: project.compilerSemanticsVersion,
    engine: { ...context.engine },
    uiVersion: context.uiVersion,
    backend: { ...context.backend },
    command: [...context.command],
    seed: context.seed,
    inputs: { ...context.inputs },
    artifacts: context.artifacts.map(artifact => ({ ...artifact })),
  };
  const issues = validateRunManifest(manifest);
  if (issues.length) throw new Error(issues.map(({ objectRef, message }) => `${objectRef}: ${message}`).join('\n'));
  return manifest;
}

function sortManifestJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortManifestJson);
  if (isRecord(value)) return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => [key, sortManifestJson(item)]));
  return value;
}

/** Deterministic manifest JSON; arrays such as argv/artifacts retain caller order. */
export function serializeRunManifest(manifest: RunManifestV1): string {
  const issues = validateRunManifest(manifest);
  if (issues.length) throw new Error(issues.map(({ objectRef, message }) => `${objectRef}: ${message}`).join('\n'));
  return `${JSON.stringify(sortManifestJson(manifest), null, 2)}\n`;
}

/** Hash already-produced artifact bytes. This helper performs no file I/O. */
export async function describeRunArtifact(path: string, bytes: Uint8Array, mediaType?: string): Promise<RunArtifactV1> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes.slice().buffer as ArrayBuffer);
  const sha256 = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return { path, sha256, sizeBytes: bytes.byteLength, ...(mediaType === undefined ? {} : { mediaType }) };
}
