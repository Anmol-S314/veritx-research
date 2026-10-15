import { describe, expect, it } from 'vitest';
import MANIFEST from '../../../../contracts/loom/v1/run-manifest.schema.json';
import PROVENANCE from '../../../../contracts/loom/v1/provenance.schema.json';
import { PROVENANCE_STATES } from '../graph/provenance';
import { buildPreset } from '../graph/presets';
import { createRunManifest, describeRunArtifact, serializeRunManifest, validateRunManifest } from '../graph/runManifest';

describe('run manifest v1 contract', () => {
  it('requires project/compiler fingerprints, engine/UI/backend, argv, seed, inputs and hashed artifacts', () => {
    expect(MANIFEST.required).toEqual(expect.arrayContaining(['projectFingerprint', 'projectSchemaVersion', 'compilerSemanticsVersion', 'engine', 'uiVersion', 'backend', 'command', 'seed', 'inputs', 'artifacts']));
    expect(MANIFEST.properties.projectFingerprint.pattern).toMatch(/64/);
    expect(MANIFEST.properties.command.type).toBe('array');
    expect(MANIFEST.properties.artifacts.items.required).toEqual(expect.arrayContaining(['path', 'sha256', 'sizeBytes']));
    expect(MANIFEST.properties.backend.properties.provenance.enum).toEqual(PROVENANCE.enum);
    expect(MANIFEST.properties.backend.properties.provenance.enum).toEqual(PROVENANCE_STATES);
  });

  it('constructs a manifest only from caller-supplied run facts and project versions', async () => {
    const project = buildPreset('ring-8');
    const manifest = await createRunManifest(project, {
      runId: 'run-17', createdAt: '2026-10-15T00:00:00Z',
      engine: { name: 'loom-reference', version: null }, uiVersion: '1.2.3',
      backend: { id: 'mock-demo', version: null, provenance: 'mocked' },
      command: ['loom-runner', '--mode', 'dry-run'], seed: null,
      inputs: { workload: 'fixture', deterministic: true }, artifacts: [],
    });
    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.projectSchemaVersion).toBe(project.schemaVersion);
    expect(manifest.compilerSemanticsVersion).toBe(project.compilerSemanticsVersion);
    expect(manifest.command).toEqual(['loom-runner', '--mode', 'dry-run']);
    expect(manifest.seed).toBeNull();
    expect(manifest.backend.provenance).toBe('mocked');
    expect(manifest.projectFingerprint).toMatch(/^[a-f0-9]{64}$/);
    expect(manifest.createdAt).toBe('2026-10-15T00:00:00Z');
    expect(validateRunManifest(manifest)).toEqual([]);
    const reordered = { ...manifest, inputs: { deterministic: true, workload: 'fixture' } };
    expect(serializeRunManifest(manifest)).toBe(serializeRunManifest(reordered));
    expect(JSON.parse(serializeRunManifest(manifest))).toEqual(manifest);
    const findings = validateRunManifest({ ...manifest, createdAt: '2026-02-30T00:00:00Z', projectFingerprint: 'not-a-hash', backend: { ...manifest.backend, provenance: 'guaranteed' } });
    expect(findings).toMatchObject([
      { code: 'LOOM_RUN_MANIFEST_INVALID', objectRef: { path: '$.createdAt' } },
      { code: 'LOOM_RUN_MANIFEST_INVALID', objectRef: { path: '$.projectFingerprint' } },
      { code: 'LOOM_RUN_MANIFEST_INVALID', objectRef: { path: '$.backend.provenance' } },
    ]);
  });

  it('hashes artifact bytes with SHA-256 without reading files', async () => {
    const artifact = await describeRunArtifact('trace.jsonl', new TextEncoder().encode('abc'), 'application/x-ndjson');
    expect(artifact).toEqual({
      path: 'trace.jsonl',
      sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
      sizeBytes: 3,
      mediaType: 'application/x-ndjson',
    });
  });
});
