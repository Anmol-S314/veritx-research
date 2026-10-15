/** Generic versioned migration pipeline (tracker M0-04).
 *
 * A versioned document carries an integer `schema_version`. Migrations are
 * registered one step at a time (`from` -> `to`) and are applied in order until
 * the document reaches the version this build implements. The pipeline is
 * deterministic, refuses to mutate its input (it deep-clones first), refuses a
 * document newer than this build, and refuses a version it has no path from —
 * always with a message that names the versions, never a silent guess.
 */

export interface MigrationStep {
  /** Source schema version. */
  from: number;
  /** Target schema version; must equal `from + 1`. */
  to: number;
  /** Stable identifier, e.g. `project.v0_to_v1`. */
  code: string;
  /** Pure transform: given the doc at `from`, return an equivalent doc at `to`. */
  migrate: (doc: Record<string, unknown>) => Record<string, unknown>;
}

export type MigrateReport = {
  /** Document at the target version. */
  doc: Record<string, unknown>;
  /** Version the document started at. */
  fromVersion: number;
  /** Version the document ended at. */
  toVersion: number;
  /** Ordered steps applied (empty when already current). */
  applied: { from: number; to: number; code: string }[];
};

export class MigrationError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message);
    this.name = 'MigrationError';
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

/** Deep clone a JSON value so a migration can never alias its input. */
export const deepCloneJson = <T>(value: T): T => {
  if (Array.isArray(value)) return value.map((child) => deepCloneJson(child)) as unknown as T;
  if (isRecord(value)) {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value)) out[key] = deepCloneJson(value[key]);
    return out as unknown as T;
  }
  return value;
};

export interface MigrateOptions {
  /** The version this build implements (the pipeline target). */
  targetVersion: number;
  /** Registered steps; unique by `from`. */
  steps: readonly MigrationStep[];
  /** Optional detector for a document with no `schema_version` field. */
  detectVersion?: (doc: Record<string, unknown>) => number | null;
}

const indexSteps = (steps: readonly MigrationStep[]): Map<number, MigrationStep> => {
  const byFrom = new Map<number, MigrationStep>();
  for (const step of steps) {
    if (step.to !== step.from + 1) {
      throw new MigrationError(
        `migration ${step.code} must move exactly one version (${step.from} -> ${step.from + 1})`, 'migration.bad_step');
    }
    if (byFrom.has(step.from)) {
      throw new MigrationError(`two migrations start at schema_version ${step.from}`, 'migration.duplicate_step');
    }
    byFrom.set(step.from, step);
  }
  return byFrom;
};

const versionOf = (doc: Record<string, unknown>, options: MigrateOptions): number => {
  const raw = doc.schema_version;
  if (typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= 0) return raw;
  if (raw !== undefined) {
    throw new MigrationError(
      `schema_version must be a non-negative integer, got ${JSON.stringify(raw)}`, 'migration.bad_version');
  }
  const detected = options.detectVersion?.(doc);
  if (detected !== null && detected !== undefined) return detected;
  throw new MigrationError(
    'document has no schema_version and is not a recognised legacy form', 'migration.missing_version');
};

export function migrateDocument(value: unknown, options: MigrateOptions): MigrateReport {
  if (!isRecord(value)) {
    throw new MigrationError('document must be an object', 'migration.not_object');
  }
  const byFrom = indexSteps(options.steps);
  const target = options.targetVersion;
  const fromVersion = versionOf(value, options);
  if (fromVersion > target) {
    throw new MigrationError(
      `document schema_version ${fromVersion} is newer than this build supports (${target}); upgrade the application`,
      'migration.future_version');
  }
  let doc = deepCloneJson(value);
  const applied: MigrateReport['applied'] = [];
  let version = fromVersion;
  // Bounded by the number of registered steps; a cycle can never spin forever.
  for (let guard = 0; version < target; guard += 1) {
    if (guard > options.steps.length + 1) {
      throw new MigrationError(`no migration path from schema_version ${fromVersion}`, 'migration.no_path');
    }
    const step = byFrom.get(version);
    if (!step) {
      throw new MigrationError(
        `no migration path from schema_version ${version} to ${target}`,
        'migration.no_path');
    }
    doc = step.migrate(doc);
    if (!isRecord(doc)) {
      throw new MigrationError(`migration ${step.code} did not return an object`, 'migration.bad_output');
    }
    version = step.to;
    applied.push({ from: step.from, to: step.to, code: step.code });
  }
  return { doc, fromVersion, toVersion: version, applied };
}
