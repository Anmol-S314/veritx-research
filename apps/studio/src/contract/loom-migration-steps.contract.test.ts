import { describe, expect, it } from 'vitest';
import { previewProjectMigration } from '../graph/migration';
import V0_INPUT from '../graph/migration-fixtures/steps/v0-version-and-semantics-default.before.json';
import V0_OUTPUT from '../graph/migration-fixtures/steps/v0-version-and-semantics-default.after.json';
import EARLY_V1_INPUT from '../graph/migration-fixtures/steps/early-v1-semantics-default.before.json';
import EARLY_V1_OUTPUT from '../graph/migration-fixtures/steps/early-v1-semantics-default.after.json';
import SIDE_MAP_INPUT from '../graph/migration-fixtures/steps/v1-edge-pipeline-side-map.before.json';
import SIDE_MAP_OUTPUT from '../graph/migration-fixtures/steps/v1-edge-pipeline-side-map.after.json';
import FIREWALL_INPUT from '../graph/migration-fixtures/steps/v1-supported-firewall-to-access.before.json';
import FIREWALL_OUTPUT from '../graph/migration-fixtures/steps/v1-supported-firewall-to-access.after.json';

const cases = [
  ['v0 version and semantics defaults', V0_INPUT, V0_OUTPUT, [
    'v0→v1: record project schema version',
    'v1: add compilerSemanticsVersion=1 (legacy project default)',
  ]],
  ['early-v1 semantics default', EARLY_V1_INPUT, EARLY_V1_OUTPUT, [
    'v1: add compilerSemanticsVersion=1 (legacy project default)',
  ]],
  ['legacy edge pipeline side-map fold', SIDE_MAP_INPUT, SIDE_MAP_OUTPUT, [
    'v1: fold pipelineStagesByEdge into edges[].pipelineStages',
  ]],
  ['supported legacy firewall mapping', FIREWALL_INPUT, FIREWALL_OUTPUT, [
    'v1: explicitly map supported legacy firewall rules to access (legacy field retained)',
  ]],
] as const;

describe('step-level project migration goldens', () => {
  it.each(cases)('%s matches before/after goldens and is idempotent', (_name, input, output, expectedSteps) => {
    const before = `${JSON.stringify(input, null, 2)}\n`;
    const expected = `${JSON.stringify(output, null, 2)}\n`;
    const preview = previewProjectMigration(before);
    expect(preview.before).toBe(before);
    expect(preview.steps).toEqual(expectedSteps);
    expect(preview.after).toBe(expected);

    const second = previewProjectMigration(preview.after);
    expect(second.after).toBe(preview.after);
    expect(second.changed).toBe(false);
    expect(second.steps).toEqual([]);
  });
});
