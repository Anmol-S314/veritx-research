/** Topology search (M1-31) and the keyboard shortcut layer (M1-32). */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';

const renderGraph = (id: string): ReturnType<typeof render> => render(<GraphLoom projectId={id} draftRequest={null} />);

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('M1-31: topology search', () => {
  it('matches nodes by id and selects the result', () => {
    renderGraph('search-by-id');
    fireEvent.change(screen.getByLabelText('search topology'), { target: { value: 'n1' } });
    expect(screen.getByTestId('search-count').textContent).toContain('match');
    fireEvent.click(screen.getByRole('button', { name: 'find next' }));
    expect(screen.getByTestId('selection-count').textContent).toBe('1 node(s), 0 link(s) selected');
  });

  it('matches nodes by role', () => {
    renderGraph('search-by-role');
    fireEvent.change(screen.getByLabelText('search topology'), { target: { value: 'hbm_controller' } });
    expect(screen.getByTestId('search-count').textContent).toContain('match');
  });

  it('reports no match for an unknown query', () => {
    renderGraph('search-none');
    fireEvent.change(screen.getByLabelText('search topology'), { target: { value: 'zzz-no-such-node' } });
    expect(screen.getByTestId('search-count').textContent).toContain('0 match');
  });
});

describe('M1-32: keyboard shortcut layer', () => {
  it('focuses the search box with Ctrl/Cmd+F', () => {
    renderGraph('sc-find');
    fireEvent.keyDown(window, { key: 'f', ctrlKey: true });
    expect(document.activeElement).toBe(screen.getByLabelText('search topology'));
  });

  it('duplicates the selection with Ctrl/Cmd+D as one undoable edit', () => {
    renderGraph('sc-duplicate');
    fireEvent.keyDown(window, { key: 'a', ctrlKey: true });
    fireEvent.keyDown(window, { key: 'd', ctrlKey: true });
    expect(screen.getByTestId('selection-count').textContent).toBe('64 node(s), 0 link(s) selected');
    expect((screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('copies and pastes with Ctrl/Cmd+C and Ctrl/Cmd+V', () => {
    renderGraph('sc-copy-paste');
    fireEvent.keyDown(window, { key: 'a', ctrlKey: true });
    fireEvent.keyDown(window, { key: 'c', ctrlKey: true });
    fireEvent.keyDown(window, { key: 'v', ctrlKey: true });
    expect(screen.getByTestId('selection-count').textContent).toBe('64 node(s), 0 link(s) selected');
  });

  it('deletes the selection with Delete and is undoable', () => {
    renderGraph('sc-delete');
    fireEvent.keyDown(window, { key: 'a', ctrlKey: true });
    fireEvent.keyDown(window, { key: 'Delete' });
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');
    const undo = screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement;
    expect(undo.disabled).toBe(false);
    fireEvent.click(undo);
    expect(undo.disabled).toBe(true);
  });

  it('fits the view with Ctrl/Cmd+0 without changing the graph', () => {
    renderGraph('sc-fit');
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');
    fireEvent.keyDown(window, { key: '0', ctrlKey: true });
    expect(screen.getByTestId('graph-canvas')).toBeTruthy();
    expect(screen.getByTestId('selection-count').textContent).toBe('0 node(s), 0 link(s) selected');
  });

  it('documents the shortcuts in the rail', () => {
    renderGraph('sc-docs');
    expect(screen.getByText('Ctrl/Cmd+0 fit · Ctrl/Cmd+F search')).toBeTruthy();
    expect(screen.getByText('Delete/Backspace delete · Ctrl/Cmd+D duplicate')).toBeTruthy();
  });
});
