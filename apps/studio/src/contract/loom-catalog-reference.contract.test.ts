import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject } from '../graph/project';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

describe('offline-safe IP catalog project reference', () => {
  const withCatalog = () => {
    const base = buildPreset('ring-8');
    return { ...base, nodes: base.nodes.map((node, i) => i === 0 ? {
      ...node, catalogRef: {
        catalogId: 'builtin', itemId: 'noc.router', version: '2.1.0',
        overrides: { radix: 5, vcs: 4 },
        fallbackMetadata: { displayName: 'Router IP', protocols: ['NoCLink'], offline: true },
      },
    } : node) };
  };
  it('round-trips stable item/version provenance, overrides and offline fallback metadata', () => {
    const p = withCatalog();
    expect(validateProject(p)).toEqual([]);
    expect(parseProject(serializeProject(p)).nodes[0].catalogRef).toEqual(p.nodes[0].catalogRef);
    expect(SCHEMA.$defs.catalogReference.required).toEqual(['catalogId', 'itemId', 'version', 'overrides', 'fallbackMetadata']);
  });
  it('refuses incomplete catalog provenance and non-object fallback/override data', () => {
    const p = withCatalog();
    const ref = p.nodes[0].catalogRef!;
    ref.version = ' ';
    ref.fallbackMetadata = null as unknown as typeof ref.fallbackMetadata;
    (ref as unknown as Record<string, unknown>).viewCache = { title: 'local-only' };
    expect(validateProject(p).map(x => x.path)).toEqual(expect.arrayContaining([
      '$.nodes[0].catalogRef.version', '$.nodes[0].catalogRef.fallbackMetadata', '$.nodes[0].catalogRef.viewCache',
    ]));
  });
});
