import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import type { LoomProject } from '../graph/project';
import {
  PROJECT_COMPILER_SEMANTICS_VERSION,
  PROJECT_DOCUMENT_SCHEMA_VERSION,
  canonicalizeProjectDocument,
  fingerprintProjectDocument,
  graphFromDocument,
  migrateProjectDocument,
  parseProjectDocument,
  serializeProjectDocument,
  validateProjectDocument,
  wrapProjectDocument,
} from '../project/document';
import { deepCloneJson, MigrationError, migrateDocument, type MigrationStep } from '../project/migrate';

const graph = (): LoomProject => buildPreset('mesh-4x4');

describe('generic migration pipeline (M0-04)', () => {
  const step: MigrationStep = {
    from: 0, to: 1, code: 't.v0_to_v1',
    migrate: (doc) => ({ ...doc, schema_version: 1, touched: true }),
  };

  it('applies registered steps in order and reports them', () => {
    const report = migrateDocument({ schema_version: 0 }, { targetVersion: 1, steps: [step] });
    expect(report.fromVersion).toBe(0);
    expect(report.toVersion).toBe(1);
    expect(report.applied).toEqual([{ from: 0, to: 1, code: 't.v0_to_v1' }]);
    expect(report.doc).toMatchObject({ schema_version: 1, touched: true });
  });

  it('is non-mutating: the input is deep-cloned, never aliased', () => {
    const input = { schema_version: 0, nested: { keep: [1, 2, 3] } };
    const before = deepCloneJson(input);
    migrateDocument(input, { targetVersion: 1, steps: [step] });
    expect(input).toEqual(before);
  });

  it('refuses a document newer than the build, naming both versions', () => {
    expect(() => migrateDocument({ schema_version: 9 }, { targetVersion: 1, steps: [step] }))
      .toThrowError(/newer than this build supports \(1\)/);
  });

  it('refuses a version it has no path from, naming the version', () => {
    expect(() => migrateDocument({ schema_version: 0 }, { targetVersion: 3, steps: [step] }))
      .toThrowError(/no migration path from schema_version 1 to 3/);
  });

  it('refuses a malformed schema_version rather than guessing', () => {
    expect(() => migrateDocument({ schema_version: 'one' }, { targetVersion: 1, steps: [step] }))
      .toThrowError(MigrationError);
  });

  it('rejects a migration that does not move exactly one version', () => {
    const bad: MigrationStep = { from: 0, to: 2, code: 't.jump', migrate: (d) => d };
    expect(() => migrateDocument({ schema_version: 0 }, { targetVersion: 2, steps: [bad] }))
      .toThrowError(/exactly one version/);
  });
});

describe('unified project document (M0-01/M0-03)', () => {
  it('migrates the legacy flat graph form to the envelope, lifting annotations', () => {
    const legacy = { ...graph(), firewall: { default: 'deny' }, workload: { phases: [] } };
    const { doc, fromVersion, toVersion, applied } = migrateProjectDocument(legacy);
    expect(fromVersion).toBe(0);
    expect(toVersion).toBe(PROJECT_DOCUMENT_SCHEMA_VERSION);
    expect(applied.map((s) => s.code)).toEqual(['project.v0_to_v1']);
    expect(doc.schema_version).toBe(1);
    expect(doc.compiler_semantics_version).toBe(PROJECT_COMPILER_SEMANTICS_VERSION);
    expect(doc.access).toEqual({ default: 'deny' });
    expect(doc.workload).toEqual({ phases: [] });
    expect('firewall' in doc.graph).toBe(false);
    expect('workload' in doc.graph).toBe(false);
  });

  it('covers every named section and both versions', () => {
    const doc = wrapProjectDocument(graph(), { id: 'p1', name: 'demo' });
    expect(Object.keys(canonicalizeProjectDocument(doc)).sort()).toEqual([
      'access', 'agents', 'catalog_refs', 'compiler_semantics_version', 'domains',
      'floorplan', 'graph', 'metadata', 'schema_version', 'workload',
    ].sort());
    expect(validateProjectDocument(doc)).toEqual([]);
  });

  it('refuses a newer project document with a clear message', () => {
    const doc = wrapProjectDocument(graph());
    expect(() => parseProjectDocument(JSON.stringify({ ...doc, schema_version: 2 })))
      .toThrowError(/newer than this build supports/);
  });

  it('reports every unreadable field as an error, never silently', () => {
    const doc = wrapProjectDocument(graph());
    const broken = { ...doc, schema_version: 1, compiler_semantics_version: 0, agents: 7 };
    const codes = validateProjectDocument(broken).map((i) => i.code);
    expect(codes).toContain('document.compiler_semantics_version');
    expect(codes).toContain('document.section_shape');
  });

  it('round-trips a graph through save/load, preserving firewall and workload', () => {
    const withExtras: LoomProject = { ...graph(), firewall: { default: 'deny' }, workload: { phases: [{ id: 'p0' }] } };
    const text = serializeProjectDocument(wrapProjectDocument(withExtras));
    const back = graphFromDocument(parseProjectDocument(text));
    expect(back.firewall).toEqual({ default: 'deny' });
    expect(back.workload).toEqual({ phases: [{ id: 'p0' }] });
    expect(back.nodes).toHaveLength(withExtras.nodes.length);
    expect(back.edges).toHaveLength(withExtras.edges.length);
  });

  it('accepts the legacy flat form through the file parser too', () => {
    const doc = parseProjectDocument(JSON.stringify(graph()));
    expect(doc.schema_version).toBe(1);
    expect(graphFromDocument(doc).nodes).toHaveLength(graph().nodes.length);
  });

  it('serializes deterministically and fingerprints stably', () => {
    const a = wrapProjectDocument(graph(), { name: 'x' });
    const b = wrapProjectDocument(graph(), { name: 'x' });
    expect(serializeProjectDocument(a)).toBe(serializeProjectDocument(b));
    expect(fingerprintProjectDocument(a)).toBe(fingerprintProjectDocument(b));
    const shuffled = { ...a, metadata: { name: 'x' } };
    expect(serializeProjectDocument(shuffled)).toBe(serializeProjectDocument(a));
  });
});
