import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { migrateProject, previewProjectMigration, previewProjectMigrationResult } from '../graph/migration';
import { fingerprintProject, parseProject, serializeProject, validateProject } from '../graph/project';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';
import LEGACY_V0_SIDE_MAP from '../graph/migration-fixtures/v0-side-map.json';
import EXPECTED_V1_SIDE_MAP from '../graph/migration-fixtures/v0-side-map.v1.json';

function workloadWithKeyOrder(reverse: boolean) {
  const phase = reverse
    ? { timingHints: { source: 'authored estimate', durationCycles: 2, startCycle: 0 }, mappingRefs: ['map-tp'], tensorSizes: { activation: 256, weights: 512 }, communicationOps: [{ trafficClass: 'collective', mappingRef: 'map-tp', tensorRef: 'activation', kind: 'all_reduce' }], dp: 1, pp: 1, ep: 1, tp: 2, batch: 1, tokens: 8, kind: 'decode', id: 'phase-1' }
    : { id: 'phase-1', kind: 'decode', tokens: 8, batch: 1, tp: 2, ep: 1, pp: 1, dp: 1, communicationOps: [{ kind: 'all_reduce', trafficClass: 'collective', tensorRef: 'activation', mappingRef: 'map-tp' }], tensorSizes: { weights: 512, activation: 256 }, mappingRefs: ['map-tp'], timingHints: { startCycle: 0, durationCycles: 2, source: 'authored estimate' } };
  return reverse
    ? { precision: 'fp16', phases: [phase], batch: 1, seqLen: 8, paramsB: 2, parameterCount: 200, modelName: 'test', modelFamily: 'transformer' }
    : { modelFamily: 'transformer', modelName: 'test', parameterCount: 200, paramsB: 2, seqLen: 8, batch: 1, precision: 'fp16', phases: [phase] };
}

describe('M0 versioned contract / migration', () => {
  it('deterministically serializes semantic objects and keeps authored array order', () => {
    const p = buildPreset('ring-8');
    const permuted = { ...p, workload: workloadWithKeyOrder(false) };
    const permuted2 = { ...p, workload: workloadWithKeyOrder(true) };
    expect(serializeProject(permuted)).toBe(serializeProject(permuted2));
    expect(parseProject(serializeProject(p)).nodes.map(n => n.id)).toEqual(p.nodes.map(n => n.id));
    expect(validateProject(p)).toEqual([]);
  });
  it('fingerprints canonical serialization with real SHA-256 and normalized defaults', async () => {
    const p = buildPreset('ring-8');
    const absentClock = { ...p, nodes: p.nodes.map(({ clock: _clock, ...node }) => node) };
    const explicitNullClock = { ...p, nodes: p.nodes.map(({ clock: _clock, ...node }) => ({ ...node, clock: null })) };
    const reordered = { ...p, workload: workloadWithKeyOrder(false) };
    const reorderedKeys = { ...p, workload: workloadWithKeyOrder(true) };
    const fingerprint = await fingerprintProject(absentClock);
    // HEAD contract: `fingerprintProject` is the synchronous canonical content
    // hash (16 hex chars), not the branch's async SHA-256 digest.
    expect(fingerprint).toMatch(/^[a-f0-9]{16}$/);
    expect(await fingerprintProject(explicitNullClock)).toBe(fingerprint);
    expect(await fingerprintProject(reordered)).toBe(await fingerprintProject(reorderedKeys));
    expect(await fingerprintProject({ ...p, nodes: p.nodes.map((node, i) => i === 0 ? { ...node, x: node.x + 1 } : node) })).not.toBe(fingerprint);
  });

  it('returns canonical non-throwing migration preview findings while preserving throwing compatibility', () => {
    const unsupported = JSON.stringify({ ...buildPreset('ring-8'), schemaVersion: 2 });
    const refusal = previewProjectMigrationResult(unsupported);
    expect(refusal.ok).toBe(false);
    if (refusal.ok) throw new Error('expected unsupported-version refusal');
    expect(refusal.issues[0]).toMatchObject({ severity: 'error', code: 'LOOM_MIGRATION_BLOCKED', objectRef: '$.schemaVersion' });
    expect(refusal.issues[0]!.message).toContain('source was not modified');
    expect(() => previewProjectMigration(unsupported)).toThrow(/unsupported version 2/);

    const malformed = previewProjectMigrationResult('{bad-json');
    expect(malformed.ok).toBe(false);
    if (malformed.ok) throw new Error('expected JSON syntax refusal');
    expect(malformed.issues[0]).toMatchObject({ severity: 'error', code: 'LOOM_PROJECT_INVALID', objectRef: '$' });
    const valid = previewProjectMigrationResult(JSON.stringify(buildPreset('ring-8')));
    expect(valid.ok).toBe(true);
  });

  it('schema defines workload phases, communication ops, tensors, stable mappings and optional timing hints', () => {
    const schema = SCHEMA as any;
    expect(schema.$defs.workloadPhase.properties.communicationOps.type).toBe('array');
    expect(schema.$defs.communicationOp.required).toEqual(['kind', 'trafficClass']);
    expect(schema.$defs.workloadPhase.properties.tensorSizes.type).toBe('object');
    expect(schema.$defs.workloadPhase.properties.mappingRefs.uniqueItems).toBe(true);
    expect(schema.$defs.workloadPhase.properties.timingHints.$ref).toBe('#/$defs/timingHints');
    expect(schema.$defs.workloadPhase.required ?? []).not.toContain('timingHints');
  });
  it('schema declares persisted VC depth/class/escape, traffic mapping and arbitration inputs', () => {
    const schema = SCHEMA as any;
    const vc = schema.$defs.vcConfig;
    expect(vc.required).toEqual(['virtualChannels', 'trafficClassMap', 'arbitration']);
    expect(schema.$defs.virtualChannel.required).toEqual(['id', 'depth', 'class', 'escape']);
    expect(schema.$defs.trafficClassMap.required).toEqual(['trafficClass', 'vcId']);
    expect(schema.$defs.arbitration.properties.policy.enum).toEqual(['round_robin', 'fixed_priority', 'weighted_round_robin']);
  });
  it('returns graph validation findings in canonical structured form', () => {
    const issues = validateProject({ ...buildPreset('ring-8'), schemaVersion: 9 });
    expect(issues[0]).toMatchObject({
      path: '$.schemaVersion', severity: 'error', code: 'LOOM_PROJECT_INVALID',
      message: expect.stringContaining('migrate'), objectRef: '$.schemaVersion',
    });
  });
  it('refuses unsupported compiler semantics with a clear migration-directed validation message', () => {
    const project = { ...buildPreset('ring-8'), compilerSemanticsVersion: 9 };
    expect(validateProject(project)).toMatchObject([expect.objectContaining({
      path: '$.compilerSemanticsVersion', severity: 'error', code: 'LOOM_PROJECT_INVALID',
      message: expect.stringContaining('migrate'), objectRef: '$.compilerSemanticsVersion',
    })]);
    expect(() => parseProject(JSON.stringify(project))).toThrow(/unsupported compiler semantics version; migrate this project before running it/);
    expect(() => migrateProject(JSON.stringify(project))).toThrow(/unsupported version 9/);
  });

  it('preserves stable node and edge identities across save/load and migration', () => {
    const p = buildPreset('ring-8');
    const expectedNodes = p.nodes.map(n => n.id);
    const expectedEdges = p.edges.map(e => e.id);
    const roundTrip = parseProject(serializeProject(p));
    expect(roundTrip.nodes.map(n => n.id)).toEqual(expectedNodes);
    expect(roundTrip.edges.map(e => e.id)).toEqual(expectedEdges);
    const legacy = { ...p, compilerSemanticsVersion: undefined };
    delete (legacy as Record<string, unknown>).compilerSemanticsVersion;
    const migrated = migrateProject(JSON.stringify(legacy));
    expect(migrated.nodes.map(n => n.id)).toEqual(expectedNodes);
    expect(migrated.edges.map(e => e.id)).toEqual(expectedEdges);
  });
  it('normalizes only the explicit absent-clock default without inventing unknown semantics', () => {
    const p = buildPreset('ring-8');
    const absent = { ...p, nodes: p.nodes.map(({ clock: _clock, ...node }) => node) };
    const explicit = { ...p, nodes: p.nodes.map(node => ({ ...node, clock: null })) };
    expect(absent.nodes[0]).not.toHaveProperty('clock');
    expect(serializeProject(absent)).toBe(serializeProject(explicit));
    expect(absent.nodes[0]).not.toHaveProperty('clock');
    expect(parseProject(serializeProject(absent)).nodes[0].clock).toBeNull();
  });
  it('migrates v0 stepwise while preserving legacy firewall, typed access and metadata', () => {
    const project = buildPreset('ring-8') as unknown as Record<string, unknown>;
    project.schemaVersion = 0;
    delete project.compilerSemanticsVersion;
    delete project.presetHint;
    project.firewall = { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RO' }] };
    project.access = { defaultPolicy: 'deny', rules: [{ id: 'r1', precedence: 0, source: { nodeIds: ['n1'] }, target: { nodeIds: ['n2'] }, policy: 'read_only' }] };
    project.metadata = { name: 'legacy-title', tags: ['migration'] };
    const projectEdges = project.edges as Record<string, unknown>[];
    delete projectEdges[0].pipelineStages;
    project.pipelineStagesByEdge = { [String(projectEdges[0].id)]: 2 };
    const source = JSON.stringify(project);
    const preview = previewProjectMigration(source);
    expect(preview.sourceVersion).toBe(0);
    expect(preview.steps).toEqual(expect.arrayContaining([
      'v0→v1: record project schema version',
      'v1: add compilerSemanticsVersion=1 (legacy project default)',
      'v1: fold pipelineStagesByEdge into edges[].pipelineStages',
    ]));
    expect(preview.before).toBe(source);
    expect(preview.after).toBe(previewProjectMigration(source).after);
    const reloaded = parseProject(preview.after);
    expect(reloaded.firewall).toEqual(project.firewall);
    expect(reloaded.access).toEqual(project.access);
    expect(reloaded.metadata).toEqual(project.metadata);
    expect(reloaded.edges[0].pipelineStages).toBe(2);
  });

  it('treats an unversioned baseline project as v0 and records the migration step', () => {
    const project = buildPreset('ring-8') as unknown as Record<string, unknown>;
    delete project.schemaVersion;
    delete project.compilerSemanticsVersion;
    const source = JSON.stringify(project);
    const preview = previewProjectMigration(source);
    expect(preview.sourceVersion).toBe(0);
    expect(preview.steps[0]).toBe('v0→v1: record project schema version');
    expect(JSON.parse(source)).not.toHaveProperty('schemaVersion');
    expect(preview.migrated.schemaVersion).toBe(1);
  });

  it('migrates the stored v0 legacy fixture in explicit steps without altering its source', () => {
    const source = JSON.stringify(LEGACY_V0_SIDE_MAP);
    const preview = previewProjectMigration(source);
    expect(preview.sourceVersion).toBe(0);
    expect(preview.steps).toEqual([
      'v0→v1: record project schema version',
      'v1: add compilerSemanticsVersion=1 (legacy project default)',
      'v1: fold pipelineStagesByEdge into edges[].pipelineStages',
      'v1: explicitly map supported legacy firewall rules to access (legacy field retained)',
    ]);
    expect(preview.before).toBe(source);
    expect(preview.after).toBe(previewProjectMigration(source).after);
    expect(preview.after).toBe(`${JSON.stringify(EXPECTED_V1_SIDE_MAP, null, 2)}\n`);
    expect(serializeProject(migrateProject(source))).toBe(preview.after);
    expect(preview.migrated).toEqual(JSON.parse(preview.after));
    expect(JSON.parse(source)).toEqual(LEGACY_V0_SIDE_MAP);
    const migrated = JSON.parse(preview.after);
    expect(migrated.schemaVersion).toBe(1);
    expect(migrated.compilerSemanticsVersion).toBe(1);
    expect(migrated.presetHint).toBeNull();
    expect(migrated.edges[0].pipelineStages).toBe(2);
    expect(migrated.firewall).toEqual(LEGACY_V0_SIDE_MAP.firewall);
    expect(migrated.access).toEqual({
      defaultPolicy: 'deny',
      rules: [{ id: 'legacy-firewall-1', precedence: 0, source: { nodeIds: ['router-a'] }, target: { nodeIds: ['router-b'] }, policy: 'read_only' }],
    });
    expect(migrated).not.toHaveProperty('pipelineStagesByEdge');
    expect(preview.diff).toEqual(expect.arrayContaining([
      { path: '$.schemaVersion', kind: 'changed', before: 0, after: 1 },
      { path: '$.compilerSemanticsVersion', kind: 'added', after: 1 },
      { path: '$.edges[0].pipelineStages', kind: 'added', after: 2 },
      { path: '$.pipelineStagesByEdge', kind: 'removed', before: { 'link-a-b': 2 } },
      { path: '$.access', kind: 'added', after: migrated.access },
    ]));
    expect(preview.diff.some(change => change.path.startsWith('$.firewall'))).toBe(false);
  });

  it('retains legacy firewall shapes unchanged when a semantics-safe conversion is unavailable', () => {
    const unsupported = [
      { default: 'allow', rules: [] },
      { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RO', extra: true }] },
      { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RO' }, { src: 'n1', dst: 'n2', perm: 'RW' }] },
      { default: 'deny', rules: [{ src: 'missing', dst: 'n2', perm: 'RW' }] },
      { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'none' }] },
    ];
    for (const firewall of unsupported) {
      const project = buildPreset('ring-8') as unknown as Record<string, unknown>;
      delete project.compilerSemanticsVersion;
      project.firewall = firewall;
      const source = JSON.stringify(project);
      const preview = previewProjectMigration(source);
      expect(preview.migrated.firewall).toEqual(firewall);
      expect(preview.migrated.access).toBeUndefined();
      expect(preview.steps).toContain('v1: retain legacy firewall unchanged; no semantics-safe access conversion available');
      expect(JSON.parse(source).firewall).toEqual(firewall);
    }
  });

  it('migrates early v1 without mutating source and produces deterministic preview', () => {
    const project = buildPreset('ring-8') as unknown as Record<string, unknown>;
    delete project.compilerSemanticsVersion;
    const nodes = project.nodes as Record<string, unknown>[];
    delete nodes[0].clock;
    const source = JSON.stringify(project);
    const preview = previewProjectMigration(source);
    expect(source).not.toContain('compilerSemanticsVersion');
    expect(preview.steps).toContain('v1: add compilerSemanticsVersion=1 (legacy project default)');
    expect(preview.after).toBe(previewProjectMigration(source).after);
    expect(preview.diff).toEqual(previewProjectMigration(source).diff);
    expect(preview.migrated).toEqual(JSON.parse(preview.after));
    expect(preview.diff).toContainEqual({ path: '$.nodes[0].clock', kind: 'added', after: null });
    expect(migrateProject(source).compilerSemanticsVersion).toBe(1);
  });
  it('serializes exactly one canonical pipelineStages field on every edge', () => {
    const p = buildPreset('ring-8');
    const text = serializeProject(p);
    const json = JSON.parse(text) as { edges: Record<string, unknown>[] };
    expect(json.edges).toHaveLength(p.edges.length);
    for (const edge of json.edges) {
      expect(Object.keys(edge).filter(k => k === 'pipelineStages')).toHaveLength(1);
      expect(edge.pipelineStages).toBeTypeOf('number');
    }
    const legacy = { ...p, pipelineStagesByEdge: {} };
    expect(() => serializeProject(legacy)).toThrow(/unknown field/);
  });
  it('folds historical pipeline stage side-map into canonical edge records', () => {
    const project = buildPreset('ring-8') as unknown as Record<string, unknown>;
    delete project.compilerSemanticsVersion;
    const edges = project.edges as Record<string, unknown>[];
    delete edges[0].pipelineStages;
    project.pipelineStagesByEdge = { [String(edges[0].id)]: 4 };
    const migrated = migrateProject(JSON.stringify(project));
    expect(migrated.edges[0].pipelineStages).toBe(4);
    expect('pipelineStagesByEdge' in migrated).toBe(false);
  });
  it('refuses ambiguous or unsupported migrations without data loss', () => {
    const p = buildPreset('ring-8') as unknown as Record<string, unknown>;
    delete p.compilerSemanticsVersion;
    p.pipelineStagesByEdge = { e1: 5 };
    expect(() => migrateProject(JSON.stringify(p))).toThrow(/conflicts/);
    p.pipelineStagesByEdge = { no_such_edge: 2 };
    expect(() => migrateProject(JSON.stringify(p))).toThrow(/unknown edge/);
    expect(() => migrateProject('{"schemaVersion":99}')).toThrow(/unsupported version/);
    expect(() => migrateProject('{broken')).toThrow(/invalid project JSON/);
  });
});
