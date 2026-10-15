/** Contract for deterministic project serialization + fingerprints (M0-19),
 *  duplicate directed-link refusal (M1-27) and issue object links (M1-26). */
import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import {
  canonicalizeProject, fingerprintProject, parseProject, serializeProject, validateProject,
  type LoomProject,
} from '../graph/project';

describe('deterministic serialization', () => {
  const p = buildPreset('mesh-4x4');

  it('is byte-identical across repeated calls', () => {
    expect(serializeProject(p)).toBe(serializeProject(p));
  });

  it('is independent of object key insertion order', () => {
    const shuffled = {
      edges: p.edges.map((e) => ({ vcClass: e.vcClass, pipelineStages: e.pipelineStages, width: e.width, dst: e.dst, src: e.src, id: e.id })),
      nodes: p.nodes.map((n) => ({ vc: n.vc, clock: n.clock, ports: n.ports, role: n.role, y: n.y, x: n.x, id: n.id })),
      presetHint: p.presetHint,
      schemaVersion: p.schemaVersion,
    } as unknown as LoomProject;
    expect(serializeProject(shuffled)).toBe(serializeProject(p));
    expect(fingerprintProject(shuffled)).toBe(fingerprintProject(p));
  });

  it('drops optional empties so a defaulted node is canonical', () => {
    const bare: LoomProject = { schemaVersion: 1, presetHint: null, nodes: [
      { id: 'n1', x: 0, y: 0, role: 'nic', ports: 4 },
      { id: 'n2', x: 1, y: 0, role: 'nic', ports: 4, vc: {} },
    ], edges: [] };
    const withEmptyVc = canonicalizeProject(bare) as { nodes: Record<string, unknown>[] };
    expect('vc' in withEmptyVc.nodes[1]).toBe(false);
    expect(fingerprintProject(bare)).toBe(fingerprintProject({ ...bare, nodes: [
      { id: 'n1', x: 0, y: 0, role: 'nic', ports: 4 },
      { id: 'n2', x: 1, y: 0, role: 'nic', ports: 4 },
    ] }));
  });

  it('round-trips to the canonical form', () => {
    expect(JSON.parse(serializeProject(p))).toEqual(canonicalizeProject(p));
    expect(parseProject(serializeProject(p)).nodes).toHaveLength(p.nodes.length);
  });

  it('fingerprints are stable and change with content', () => {
    expect(fingerprintProject(p)).toBe(fingerprintProject(p));
    expect(fingerprintProject(buildPreset('ring-8'))).not.toBe(fingerprintProject(p));
    const edited = { ...p, edges: p.edges.map((e, i) => i === 0 ? { ...e, width: 1024 } : e) };
    expect(fingerprintProject(edited)).not.toBe(fingerprintProject(p));
  });
});

describe('validator: duplicate directed links (M1-27)', () => {
  const p = buildPreset('mesh-4x4');

  it('flags two edges with the same src->dst and blocks save', () => {
    const duplicate = {
      ...p,
      edges: [...p.edges, { id: 'dup', src: 'n1', dst: 'n2', width: 512, pipelineStages: 1, vcClass: 0 }],
    };
    const issues = validateProject(duplicate);
    const found = issues.find((i) => i.code === 'edge.duplicate_directed_link');
    expect(found?.severity).toBe('error');
    expect(found?.objectRef).toBe('$.edges[id=dup]');
    expect(() => serializeProject(duplicate)).toThrow(/duplicate directed link/);
    expect(() => parseProject(JSON.stringify(duplicate))).toThrow(/duplicate directed link/);
  });

  it('allows the opposite direction as a distinct link', () => {
    const reversed = {
      ...p,
      edges: [...p.edges, { id: 'rev', src: 'n2', dst: 'n1', width: 512, pipelineStages: 1, vcClass: 0 }],
    };
    expect(validateProject(reversed).some((i) => i.code === 'edge.duplicate_directed_link')).toBe(false);
  });

  it('links every issue to the object at fault', () => {
    const broken = { ...p, edges: [...p.edges, { id: 'bad', src: 'n1', dst: 'ghost', width: 512, pipelineStages: 1, vcClass: 0 }] };
    const issues = validateProject(broken);
    expect(issues.length).toBeGreaterThan(0);
    expect(issues.every((i) => typeof i.objectRef === 'string' && i.objectRef.length > 0)).toBe(true);
    expect(issues.every((i) => typeof i.code === 'string' && i.code.length > 0)).toBe(true);
  });
});
