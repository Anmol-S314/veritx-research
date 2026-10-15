/** Local IP-catalog search and stamping (M2-08 / M2-09 / M2-26). */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import { BUILTIN_CATALOG_V1, searchCatalog } from '../graph/catalog';
import { catalogItemToNode, nextStampPosition } from '../graph/catalogStamp';
import { parseProject, serializeProject, validateProject, type LoomProject } from '../graph/project';

const item = (id: string) => BUILTIN_CATALOG_V1.items.find((i) => i.id === id)!;

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('M2-08: catalog search', () => {
  it('matches by name, class and tag', () => {
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'hbm').map((i) => i.id)).toContain('memory.hbm-controller.generic');
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'compute').map((i) => i.id)).toContain('compute.generic');
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'dma').map((i) => i.id)).toContain('dma.generic');
    expect(searchCatalog(BUILTIN_CATALOG_V1, 'nonsense-xyz')).toEqual([]);
  });
});

describe('M2-09: stamping a catalog item', () => {
  it('builds an authoring node with default ports, domains and provenance', () => {
    const node = catalogItemToNode(BUILTIN_CATALOG_V1, item('compute.generic'), { id: 'nX', x: 40, y: 60 });
    expect(node).toMatchObject({
      id: 'nX', x: 40, y: 60, role: 'compute_tile',
      clock: 'clk_core', resetDomain: 'rst_core', powerDomain: 'pwr_core',
    });
    expect(node.ports).toBeGreaterThanOrEqual(1);
    expect(node.catalogRef).toEqual({
      catalogId: 'veritx.generic', itemId: 'compute.generic', version: '1.0.0', overrides: {},
      fallbackMetadata: { name: 'Generic compute agent', class: 'compute', family: 'generic-compute', portCount: 1 },
    });
  });

  it('is deterministic and places the next stamp to the right of existing nodes', () => {
    const a = catalogItemToNode(BUILTIN_CATALOG_V1, item('compute.generic'), { id: 'nX', x: 0, y: 0 });
    const b = catalogItemToNode(BUILTIN_CATALOG_V1, item('compute.generic'), { id: 'nX', x: 0, y: 0 });
    expect(a).toEqual(b);
    expect(nextStampPosition([])).toEqual({ x: 200, y: 200 });
    expect(nextStampPosition([{ x: 10, y: 5 }, { x: 300, y: 40 }])).toEqual({ x: 440, y: 5 });
  });

  it('uses an editable compiler-vocabulary role per class', () => {
    for (const id of ['router.generic-5p', 'compute.generic', 'memory.hbm-controller.generic', 'bridge.protocol-domain.generic', 'peripheral.generic']) {
      const node = catalogItemToNode(BUILTIN_CATALOG_V1, item(id), { id: 'n', x: 0, y: 0 });
      expect(['compute_tile', 'hbm_controller', 'ucie_port', 'peripheral', 'nic']).toContain(node.role);
    }
  });

  it('preserves catalog provenance through save and reload', () => {
    const node = catalogItemToNode(BUILTIN_CATALOG_V1, item('memory.hbm-controller.generic'), { id: 'n1', x: 0, y: 0 });
    const project: LoomProject = { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: null, nodes: [node], edges: [] };
    const reloaded = parseProject(serializeProject(project));
    expect(reloaded.nodes[0]!.catalogRef).toEqual(node.catalogRef);
    expect(validateProject(reloaded, { knownCatalogItems: BUILTIN_CATALOG_V1.items.map((i) => i.id) }).filter((i) => i.severity === 'error')).toEqual([]);
  });
});

describe('M2-09/M2-26: stamping through the canvas UI', () => {
  it('stamps one node in a single undoable edit', () => {
    render(<GraphLoom projectId="catalog-stamp" draftRequest={null} />);
    const nodes = (): number => document.querySelectorAll('[data-node-id]').length;
    const before = nodes();

    fireEvent.change(screen.getByLabelText('catalog search'), { target: { value: 'hbm' } });
    expect(screen.getByTestId('catalog-count').textContent).toContain('item(s)');
    fireEvent.click(screen.getByRole('button', { name: 'stamp memory.hbm-controller.generic' }));
    expect(nodes()).toBe(before + 1);

    const undo = screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement;
    expect(undo.disabled).toBe(false);
    fireEvent.click(undo);
    expect(nodes()).toBe(before);
  });
});
