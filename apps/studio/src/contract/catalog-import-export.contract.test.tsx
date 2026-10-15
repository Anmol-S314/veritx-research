/** Project-local catalog import/export and use (M2-12 / M2-13). */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import { BUILTIN_CATALOG_V1, parseLocalCatalog, serializeLocalCatalog, type LocalCatalogV1 } from '../graph/catalog';
import { effectiveCatalog, hasLocalCatalog } from '../graph/catalogStore';
import { GraphHistory } from '../graph/history';
import { buildPreset } from '../graph/presets';
import { validateProject, type LoomProject } from '../graph/project';

const localCatalog: LocalCatalogV1 = {
  schemaVersion: 1,
  catalogId: 'acme.local',
  version: '2.1.0',
  items: [{
    id: 'custom.router.x', name: 'Acme router X', vendor: null, family: 'custom-router', version: '2.1.0',
    class: 'router', tags: ['router', 'custom'], clocks: ['clk_core'], resets: ['rst_core'], powers: ['pwr_core'],
    ports: [{ id: 'p0', role: 'bidirectional', protocol: 'generic-flit', dataWidth: 256, capabilities: ['read', 'write'] }],
    description: 'Authored local entry; not a vendor model.',
  }],
};

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('M2-13: catalog serialization round-trip', () => {
  it('re-imports an exported catalog losslessly', () => {
    expect(parseLocalCatalog(serializeLocalCatalog(localCatalog))).toEqual(localCatalog);
  });

  it('rejects a malformed catalog', () => {
    expect(() => parseLocalCatalog(JSON.stringify({ ...localCatalog, items: 'nope' }))).toThrow(/invalid catalog/);
  });
});

describe('M2-12: project-local catalog', () => {
  it('falls back to the built-in catalog until one is embedded', () => {
    expect(effectiveCatalog({})).toBe(BUILTIN_CATALOG_V1);
    expect(hasLocalCatalog({})).toBe(false);
    const withLocal = { metadata: { localCatalog } };
    expect(effectiveCatalog(withLocal)).toEqual(localCatalog);
    expect(hasLocalCatalog(withLocal)).toBe(true);
  });

  it('rejects a malformed embedded catalog during validation', () => {
    const project = {
      ...buildPreset('mesh-4x4'),
      metadata: { localCatalog: { schemaVersion: 1, catalogId: 'x', version: '1', items: 'nope' } },
    } as unknown as LoomProject;
    expect(validateProject(project).some((i) => i.path.startsWith('$.metadata.localCatalog'))).toBe(true);
  });

  it('records the local catalog as one undoable edit', () => {
    const history = new GraphHistory(buildPreset('ring-8'));
    expect(history.apply({ type: 'set_metadata', metadata: { localCatalog } }).refused).toBeNull();
    expect((history.current().metadata as { localCatalog?: LocalCatalogV1 }).localCatalog).toEqual(localCatalog);
    expect(history.undo()).toBe(true);
    expect(history.current().metadata).toBeUndefined();
  });

  it('searches and stamps from the embedded local catalog in the UI', () => {
    const scope = 'catalog-local';
    localStorage.setItem(`loom-graph-autosave-v1:${scope}`, JSON.stringify({
      schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'mesh', nodes: [], edges: [], metadata: { localCatalog },
    }));
    render(<GraphLoom projectId={scope} draftRequest={null} />);
    fireEvent.change(screen.getByLabelText('catalog search'), { target: { value: 'custom' } });
    expect(screen.getByTestId('catalog-count').textContent).toContain('1 item');
    fireEvent.click(screen.getByRole('button', { name: 'stamp custom.router.x' }));
    expect(document.querySelectorAll('[data-node-id]').length).toBe(1);
  });
});
