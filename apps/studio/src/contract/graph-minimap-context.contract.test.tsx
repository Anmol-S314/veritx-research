/** Minimap navigation (M1-14) and contextual node/edge/canvas menus (M1-33). */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';

const renderGraph = (id: string): void => {
  render(<GraphLoom projectId={id} draftRequest={null} />);
};

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('M1-14: minimap', () => {
  it('renders every node and a viewport indicator', () => {
    renderGraph('minimap');
    const minimap = screen.getByTestId('graph-minimap');
    expect(minimap.querySelectorAll('circle')).toHaveLength(64);
    expect(screen.getByTestId('minimap-viewport')).toBeTruthy();
  });

  it('navigates the viewport when clicked', () => {
    renderGraph('minimap-nav');
    const before = screen.getByTestId('minimap-viewport').getAttribute('x');
    fireEvent.click(screen.getByLabelText('graph minimap'), { clientX: 20, clientY: 20 });
    const after = screen.getByTestId('minimap-viewport').getAttribute('x');
    expect(after).not.toBe(before);
  });
});

describe('M1-33: context menus', () => {
  it('offers node actions and deletes through them', () => {
    renderGraph('ctx-node');
    fireEvent.contextMenu(screen.getByTestId('node-n1'), { clientX: 40, clientY: 40 });
    const menu = screen.getByTestId('graph-context-menu');
    expect(within(menu).getByRole('button', { name: 'duplicate' })).toBeTruthy();
    expect(within(menu).getByRole('button', { name: 'link from here' })).toBeTruthy();
    fireEvent.click(within(menu).getByRole('button', { name: 'delete' }));
    expect(screen.queryByTestId('node-n1')).toBeNull();
    expect((screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('deletes a link through the edge menu', () => {
    renderGraph('ctx-edge');
    const before = screen.queryAllByTestId(/^link-e\d/).length;
    fireEvent.contextMenu(screen.queryAllByTestId(/^link-e\d/)[0]!, { clientX: 40, clientY: 40 });
    const menu = screen.getByTestId('graph-context-menu');
    fireEvent.click(within(menu).getByRole('button', { name: 'delete link' }));
    expect(screen.queryAllByTestId(/^link-e\d/)).toHaveLength(before - 1);
  });

  it('offers canvas actions', () => {
    renderGraph('ctx-canvas');
    fireEvent.contextMenu(screen.getByTestId('graph-canvas'), { clientX: 40, clientY: 40 });
    const menu = screen.getByTestId('graph-context-menu');
    fireEvent.click(within(menu).getByRole('button', { name: 'select all' }));
    expect(screen.getByTestId('selection-count').textContent).toBe('64 node(s), 112 link(s) selected');
    expect(screen.queryByTestId('graph-context-menu')).toBeNull();
  });

  it('closes the menu on Escape', () => {
    renderGraph('ctx-escape');
    fireEvent.contextMenu(screen.getByTestId('node-n2'), { clientX: 10, clientY: 10 });
    expect(screen.getByTestId('graph-context-menu')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('graph-context-menu')).toBeNull();
  });
});
