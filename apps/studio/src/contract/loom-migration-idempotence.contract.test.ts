import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { previewProjectMigration } from '../graph/migration';
import { serializeProject } from '../graph/project';
import LEGACY_V0 from '../graph/migration-fixtures/v0-side-map.json';
import EXPECTED_V1 from '../graph/migration-fixtures/v0-side-map.v1.json';

const migrationInputs = [
  ['v0 golden (version, semantics, side-map, supported firewall)', JSON.stringify(LEGACY_V0)],
  ['unversioned v0', (() => {
    const value = { ...buildPreset('mesh-4x4') } as unknown as Record<string, unknown>;
    delete value.schemaVersion;
    delete value.compilerSemanticsVersion;
    return JSON.stringify(value);
  })()],
  ['early v1 missing compiler-semantics version', (() => {
    const value = { ...buildPreset('ring-8') } as unknown as Record<string, unknown>;
    delete value.compilerSemanticsVersion;
    return JSON.stringify(value);
  })()],
] as const;

describe('project migration golden and idempotence contract', () => {
  it('keeps the checked-in v0 before/after golden pair and explicit migration steps', () => {
    const preview = previewProjectMigration(JSON.stringify(LEGACY_V0));
    expect(preview.after).toBe(`${JSON.stringify(EXPECTED_V1, null, 2)}\n`);
    expect(preview.steps).toEqual([
      'v0→v1: record project schema version',
      'v1: add compilerSemanticsVersion=1 (legacy project default)',
      'v1: fold pipelineStagesByEdge into edges[].pipelineStages',
      'v1: explicitly map supported legacy firewall rules to access (legacy field retained)',
    ]);
  });

  it.each(migrationInputs)('%s migrates deterministically and is idempotent', (_label, source) => {
    const untouchedSource = source;
    const migrated = previewProjectMigration(source);
    expect(source).toBe(untouchedSource);
    expect(migrated.after).toBe(serializeProject(migrated.migrated));

    const again = previewProjectMigration(migrated.after);
    expect(again.after).toBe(migrated.after);
    expect(again.changed).toBe(false);
    expect(again.steps).toEqual([]);
  });
});
