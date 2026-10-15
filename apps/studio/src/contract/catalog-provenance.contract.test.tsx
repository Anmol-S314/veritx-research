/** Catalog provenance resolution, explicit rebind and override policy
 *  (M2-11 / M2-14 / M2-24). */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import { validateCatalogOverrides } from '../graph/catalog';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

interface Seeded { graph?: { nodes: { id: string; ports: number; catalogRef: { version: string; overrides: Record<string, unknown> } }[] }; nodes: { id: string; ports: number; catalogRef: { version: string; overrides: Record<string, unknown> } }[] }
const readDoc = (scope: string) => {
  const parsed = JSON.parse(localStorage.getItem(`loom-graph-autosave-v1:${scope}`)!) as Seeded;
  return parsed.graph ?? parsed;
};
const nodeOf = (scope: string, id: string) => readDoc(scope).nodes.find((n) => n.id === id)!;

const seed = (scope: string, version: string): void => {
  localStorage.setItem(`loom-graph-autosave-v1:${scope}`, JSON.stringify({
    schemaVersion: 1,
    compilerSemanticsVersion: 1,
    presetHint: null,
    nodes: [{
      id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 4,
      catalogRef: { catalogId: 'veritx.generic', itemId: 'compute.generic', version, overrides: {}, fallbackMetadata: {} },
    }],
    edges: [],
  }));
};

describe('M2-24: catalog override policy', () => {
  it('accepts allowed parameters inside range and refuses the rest with catalog-backed messages', () => {
    expect(validateCatalogOverrides('veritx.generic', { portCount: 8 })).toEqual([]);
    expect(validateCatalogOverrides('veritx.generic', { bogus: 1 })[0]).toContain('is not an allowed parameter');
    expect(validateCatalogOverrides('veritx.generic', { portCount: 999 })[0]).toContain('1..64');
    expect(validateCatalogOverrides('veritx.generic', { dataWidth: 0 })[0]).toContain('1..4096');
  });
});

describe('M2-14: catalog reference resolution', () => {
  it('marks an outdated reference and rebinds only on explicit action', () => {
    seed('catalog-outdated', '0.9.0');
    render(<GraphLoom projectId="catalog-outdated" draftRequest={null} />);
    expect(screen.getByTestId('resolution-n1').textContent).toBe('outdated');
    expect(screen.getByText(/differs from available/)).toBeTruthy();
    expect(nodeOf('catalog-outdated', 'n1').catalogRef.version).toBe('0.9.0');
    fireEvent.click(screen.getByRole('button', { name: 'rebind n1' }));
    expect(nodeOf('catalog-outdated', 'n1').catalogRef.version).toBe('1.0.0');
  });

  it('resolves a current reference without a rebind action', () => {
    seed('catalog-current', '1.0.0');
    render(<GraphLoom projectId="catalog-current" draftRequest={null} />);
    expect(screen.getByTestId('resolution-n1').textContent).toBe('resolved');
    expect(screen.queryByRole('button', { name: 'rebind n1' })).toBeNull();
  });
});

describe('M2-11: applying an allowed override', () => {
  it('writes the override and refuses an out-of-range value without changing the node', () => {
    seed('catalog-override', '1.0.0');
    render(<GraphLoom projectId="catalog-override" draftRequest={null} />);

    fireEvent.change(screen.getByLabelText('port override n1'), { target: { value: '999' } });
    fireEvent.click(screen.getByRole('button', { name: 'apply override n1' }));
    expect(screen.getByText(/must be an integer in 1\.\.64/)).toBeTruthy();
    expect(nodeOf('catalog-override', 'n1').ports).toBe(4);

    fireEvent.change(screen.getByLabelText('port override n1'), { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'apply override n1' }));
    expect(nodeOf('catalog-override', 'n1').ports).toBe(8);
    expect(nodeOf('catalog-override', 'n1').catalogRef.overrides.portCount).toBe(8);
  });
});
