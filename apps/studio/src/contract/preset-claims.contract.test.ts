/** Preset generators and claim revalidation (tracker M1-21 / M1-22 / M1-24 / M1-30). */
import { describe, expect, it } from 'vitest';
import { buildPreset, buildRingPreset, buildTorusPreset, buildTreePreset, presetClaimStatus } from '../graph/presets';
import { validateProject } from '../graph/project';

describe('M1-21: torus preset', () => {
  it('adds explicit wrap links and validates', () => {
    const torus = buildTorusPreset(4, 4);
    expect(validateProject(torus)).toEqual([]);
    expect(buildPreset('torus-4x4')).toEqual(torus);
    // 4x4 mesh (24 links) + 4 row wraps + 4 column wraps.
    expect(torus.edges).toHaveLength(32);
    expect(torus.presetHint).toBe('torus');
  });

  it('refuses dimensions that would duplicate a wrap link', () => {
    expect(() => buildTorusPreset(2, 4)).toThrow(/≥ 3/);
    expect(() => buildTorusPreset(4, 2)).toThrow(/≥ 3/);
  });
});

describe('M1-22: ring preset options', () => {
  it('supports size and direction and validates', () => {
    expect(buildRingPreset(8).edges).toHaveLength(8);
    expect(buildRingPreset(8, { direction: 'ccw' }).edges).toHaveLength(8);
    expect(buildRingPreset(8, { direction: 'bidirectional' }).edges).toHaveLength(16);
    expect(buildRingPreset(12).nodes).toHaveLength(12);
    expect(validateProject(buildRingPreset(12)).filter((i) => i.severity === 'error')).toEqual([]);
    expect(buildPreset('ring-8')).toEqual(buildRingPreset(8));
  });

  it('refuses an invalid size', () => {
    expect(() => buildRingPreset(2)).toThrow(/3\.\.256/);
  });
});

describe('M1-24: tree preset options', () => {
  it('supports branch factor and depth and validates', () => {
    const binary = buildTreePreset(2, 3);
    expect(binary.nodes).toHaveLength(15);
    expect(binary.edges).toHaveLength(14);
    expect(buildPreset('tree-15')).toEqual(binary);

    const ternary = buildTreePreset(3, 2);
    expect(ternary.nodes).toHaveLength(13);
    expect(ternary.edges).toHaveLength(12);
    expect(validateProject(ternary).filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('refuses an invalid branch factor or depth', () => {
    expect(() => buildTreePreset(1, 3)).toThrow(/branch factor/);
    expect(() => buildTreePreset(2, 0)).toThrow(/depth/);
  });
});

describe('M1-30: preset claim revalidation', () => {
  it('holds for untouched presets', () => {
    expect(presetClaimStatus(buildPreset('mesh-4x4'))).toMatchObject({ claim: 'mesh', holds: true });
    expect(presetClaimStatus(buildPreset('torus-4x4'))).toMatchObject({ claim: 'torus', holds: true });
    expect(presetClaimStatus(buildRingPreset(12))).toMatchObject({ claim: 'ring', holds: true });
    expect(presetClaimStatus(buildRingPreset(8, { direction: 'bidirectional' }))).toMatchObject({ claim: 'ring', holds: true });
    expect(presetClaimStatus(buildTreePreset(3, 2))).toMatchObject({ claim: 'tree', holds: true });
    expect(presetClaimStatus(buildPreset('star-8'))).toMatchObject({ claim: 'star', holds: true });
  });

  it('reports a diverged claim as custom', () => {
    const diverged = { ...buildPreset('mesh-4x4'), edges: buildPreset('mesh-4x4').edges.slice(0, -1) };
    expect(presetClaimStatus(diverged)).toMatchObject({ claim: 'custom', holds: false });
  });

  it('reports an unclaimed graph as custom', () => {
    const { presetHint, ...rest } = buildPreset('mesh-4x4');
    expect(presetHint).toBe('mesh');
    expect(presetClaimStatus({ ...rest, presetHint: null })).toMatchObject({ claim: 'custom', holds: false });
  });
});
