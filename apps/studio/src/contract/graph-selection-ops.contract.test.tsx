/** Predictable select-all / invert / clear (tracker M1-08).
 *
 *  Locks the pure selection algebra and the authoring shortcuts that drive it
 *  (Ctrl/Cmd+A and Escape), plus the explicit rail buttons.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { clearSelection, invertSelection, isSelected, selectAll } from '../graph/selectionOps';
import GraphLoom from '../pages/loom/GraphLoom';
import type { ReactElement } from 'react';

const mesh = buildPreset('mesh-4x4');

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('M1-08: selection algebra', () => {
  it('select all is every node and edge in document order', () => {
    const all = selectAll(mesh);
    expect(all.nodes).toEqual(mesh.nodes.map((n) => n.id));
    expect(all.edges).toEqual(mesh.edges.map((e) => e.id));
    expect(all.nodes).toHaveLength(16);
    expect(all.edges).toHaveLength(24);
  });

  it('invert is an involution and never invents ids', () => {
    const some = { nodes: [mesh.nodes[0].id, mesh.nodes[5].id], edges: [mesh.edges[0].id] };
    const inv = invertSelection(mesh, some);
    expect(inv.nodes).toHaveLength(14);
    expect(inv.edges).toHaveLength(23);
    expect(inv.nodes).not.toContain(mesh.nodes[0].id);
    expect(invertSelection(mesh, inv)).toEqual(some);
  });

  it('clear empties both sides', () => {
    expect(clearSelection()).toEqual({ nodes: [], edges: [] });
  });

  it('isSelected only reads the requested side', () => {
    const sel = { nodes: ['n1'], edges: ['e1'] };
    expect(isSelected(sel, 'node', 'n1')).toBe(true);
    expect(isSelected(sel, 'edge', 'n1')).toBe(false);
    expect(isSelected(sel, 'edge', 'e1')).toBe(true);
  });
});

function Editor(): ReactElement {
  return <GraphLoom projectId="project-sel" draftRequest={null} />;
}

describe('M1-08: authoring selection actions', () => {
  it('selects everything with Ctrl+A and clears with Escape', () => {
    render(<Editor />);
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');

    fireEvent.keyDown(window, { key: 'a', ctrlKey: true });
    expect(screen.getByTestId('selection-count').textContent).toBe('64 node(s), 112 link(s) selected');

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');
  });

  it('drives the same result from the rail buttons', () => {
    render(<Editor />);
    fireEvent.click(screen.getByRole('button', { name: 'select all' }));
    expect(screen.getByTestId('selection-count').textContent).toBe('64 node(s), 112 link(s) selected');

    fireEvent.click(screen.getByRole('button', { name: 'invert' }));
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');

    fireEvent.click(screen.getByRole('button', { name: 'clear' }));
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');
  });
});

describe('M1-12/M1-13: alignment and distribution actions', () => {
  it('gates on selection size, applies one undoable edit and undoes it', () => {
    render(<Editor />);
    const alignLeft = screen.getByRole('button', { name: 'align left' }) as HTMLButtonElement;
    const distributeH = screen.getByRole('button', { name: 'distribute horizontal' }) as HTMLButtonElement;
    const undo = screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement;

    // No selection: both tools are unavailable.
    expect(alignLeft.disabled).toBe(true);
    expect(distributeH.disabled).toBe(true);

    fireEvent.keyDown(window, { key: 'a', ctrlKey: true });
    expect(alignLeft.disabled).toBe(false);
    expect(distributeH.disabled).toBe(false);

    // A whole-selection alignment is one history step.
    expect(undo.disabled).toBe(true);
    fireEvent.click(alignLeft);
    expect(undo.disabled).toBe(false);

    fireEvent.click(undo);
    expect(undo.disabled).toBe(true);
  });
});
