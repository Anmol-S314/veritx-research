import { describe, expect, it } from 'vitest';
import { BUILTIN_CATALOG_V1, parseLocalCatalog, resolveCatalogReference, searchCatalog, serializeLocalCatalog, validateLocalCatalog } from '../graph/catalog';
import { validateProject } from '../graph/project';
import { buildPreset } from '../graph/presets';

describe('offline authoring catalog v1', () => {
  it('ships stable generic router, compute, HBM, DDR and bridge interface templates', () => {
    expect(validateLocalCatalog(BUILTIN_CATALOG_V1)).toEqual([]);
    expect(BUILTIN_CATALOG_V1.schemaVersion).toBe(1);
    const ids = BUILTIN_CATALOG_V1.items.map(item => item.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ['router.generic-5p','compute.generic','memory.hbm-controller.generic','memory.ddr-controller.generic','bridge.protocol-domain.generic','peripheral.generic','dma.generic']) expect(ids).toContain(id);
    expect(BUILTIN_CATALOG_V1.items.every(item => item.vendor === null && item.description.trim().length > 0)).toBe(true);
    expect(BUILTIN_CATALOG_V1.items.find(item => item.id === 'bridge.protocol-domain.generic')?.description).toContain('not implemented or simulated');
  });

  it('parses validated catalogs and serializes deterministically without reordering entries', () => {
    const serialized = serializeLocalCatalog(BUILTIN_CATALOG_V1);
    expect(parseLocalCatalog(serialized)).toEqual(BUILTIN_CATALOG_V1);
    expect(serializeLocalCatalog(parseLocalCatalog(serialized))).toBe(serialized);
    expect(() => parseLocalCatalog('{')).toThrow('invalid catalog JSON');
    expect(() => parseLocalCatalog('{"schemaVersion":2,"catalogId":"x","version":"1","items":[]}')).toThrow('schemaVersion: must equal 1');
  });

  it('filters local entries by words across stable metadata and optional class', () => {
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'hbm controller')).toHaveLength(1);
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'AXI', 'memory').map(item => item.id)).toContain('memory.ddr-controller.generic');
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'nonexistent')).toEqual([]);
  });

  it('detects missing/outdated references without silently replacing their fallback', () => {
    const fallbackMetadata = { class: 'memory', note: 'authored offline' };
    const missing = resolveCatalogReference(BUILTIN_CATALOG_V1, { catalogId: 'other.catalog', itemId: 'custom.hbm', version: '2', fallbackMetadata });
    expect(missing).toMatchObject({ state: 'missing', item: null, fallbackMetadata, requiredAction: 'explicit-rebind' });
    expect(missing.warning).toContain('inspection data only');
    const outdated = resolveCatalogReference(BUILTIN_CATALOG_V1, { catalogId: BUILTIN_CATALOG_V1.catalogId, itemId: 'compute.generic', version: '0.9.0', fallbackMetadata });
    expect(outdated).toMatchObject({ state: 'outdated', item: null, fallbackMetadata, requiredAction: 'explicit-rebind' });
    expect(outdated.warning).toContain('replacement requires explicit action');
    const exact = resolveCatalogReference(BUILTIN_CATALOG_V1, { catalogId: BUILTIN_CATALOG_V1.catalogId, itemId: 'compute.generic', version: '1.0.0', fallbackMetadata });
    expect(exact).toMatchObject({ state: 'resolved', item: expect.objectContaining({ id: 'compute.generic' }), requiredAction: 'none', warning: null });
  });

  it('reports malformed catalog metadata and duplicate item identities', () => {
    const bad = structuredClone(BUILTIN_CATALOG_V1);
    bad.items[1]!.id = bad.items[0]!.id;
    bad.items[1]!.ports[0]!.dataWidth = 0;
    expect(validateLocalCatalog(bad)).toEqual(expect.arrayContaining([
      expect.stringContaining('duplicate catalog item ID'),
      expect.stringContaining('dataWidth: must be a positive integer'),
    ]));
  });

  it('does not claim catalog templates are compiler-supported project references', () => {
    const project = buildPreset('mesh-4x4');
    project.nodes[0]!.catalogRef = { catalogId: BUILTIN_CATALOG_V1.catalogId, itemId: 'compute.generic', version: '1.0.0', overrides: {}, fallbackMetadata: {} };
    expect(validateProject(project)).toEqual([]);
  });
});
