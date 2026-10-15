import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NodeEditor } from '../pages/loom/authoring';
import { useGraphStore } from '../graph/store';
import type { ReactElement } from 'react';
import { buildPreset } from '../graph/presets';
import { validateProject } from '../graph/project';

function Editor(): ReactElement {
  const store = useGraphStore('ring-8');
  return <NodeEditor store={store} />;
}

function EditorWithUndo(): ReactElement {
  const store = useGraphStore('ring-8');
  return <><NodeEditor store={store} /><button onClick={() => store.undo()}>Undo graph edit</button></>;
}

function EditorWithPortEdit(): ReactElement {
  const store = useGraphStore('ring-8');
  return <><NodeEditor store={store} /><button onClick={() => store.run({ type: 'update_node', id: 'n1', patch: { ports: 7 } })}>Set n1 ports to 7</button></>;
}

function EditorWithJsonLoad(): ReactElement {
  const store = useGraphStore('ring-8');
  return <>
    <NodeEditor store={store} />
    <button onClick={() => store.loadJson(JSON.stringify(buildPreset('star-8')))}>Import project JSON</button>
    <button onClick={() => store.undo()}>Undo graph edit</button>
  </>;
}

function EditorWithPresetLoad(): ReactElement {
  const store = useGraphStore('ring-8');
  return <>
    <NodeEditor store={store} />
    <button onClick={() => store.loadPreset('mesh-4x4')}>Load mesh preset</button>
    <button onClick={() => store.undo()}>Undo graph edit</button>
    <button onClick={() => store.redo()}>Redo graph edit</button>
  </>;
}

function EditorWithHistoryCommands(): ReactElement {
  const store = useGraphStore('ring-8');
  return <>
    <NodeEditor store={store} />
    <button onClick={() => store.run({ type: 'move_node', id: 'n1', x: 500, y: 500 })}>Move n1 directly</button>
    <button onClick={() => store.run({ type: 'delete_edge', id: 'e1' })}>Delete edge e1 directly</button>
    <button onClick={() => store.run({ type: 'update_node', id: 'n1', patch: { role: 'nic' } })}>Edit n1 role directly</button>
  </>;
}

afterEach(cleanup);

describe('graph authoring keyboard access', () => {
  it('selects a canvas node with Enter and exposes its selected state', () => {
    localStorage.clear();
    render(<Editor />);
    const node = screen.getByRole('button', { name: 'n1 compute_tile' });
    expect(node.getAttribute('aria-pressed')).toBe('false');
    node.focus();
    fireEvent.keyDown(node, { key: 'Enter' });
    expect(node.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByLabelText('node x')).toBeTruthy();
  });

  it('renders exposed ports from project state and updates without a reload', () => {
    localStorage.clear();
    render(<EditorWithPortEdit />);
    expect(screen.getAllByTestId(/^port-n1-/)).toHaveLength(5);
    fireEvent.click(screen.getByRole('button', { name: 'Set n1 ports to 7' }));
    expect(screen.getAllByTestId(/^port-n1-/)).toHaveLength(7);
    expect(screen.getByLabelText('n1 port 7')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'n1 compute_tile' })).toBeTruthy();
  });

  it('uses Ctrl+Z/Ctrl+Shift+Z to undo and redo node, edge and property edits', async () => {
    localStorage.clear();
    render(<EditorWithHistoryCommands />);
    const original = buildPreset('ring-8');
    const readSaved = (): ReturnType<typeof buildPreset> => JSON.parse(
      localStorage.getItem('loom-graph-autosave-v1:local')!,
    ) as ReturnType<typeof buildPreset>;
    const undo = (): void => { fireEvent.keyDown(document.body, { key: 'z', ctrlKey: true, bubbles: true }); };
    const redo = (): void => { fireEvent.keyDown(document.body, { key: 'z', ctrlKey: true, shiftKey: true, bubbles: true }); };

    fireEvent.click(screen.getByRole('button', { name: 'Move n1 directly' }));
    const moved = readSaved();
    expect(moved.nodes.find((node) => node.id === 'n1')).toMatchObject({ x: 500, y: 500 });
    undo();
    await waitFor(() => expect(readSaved()).toEqual(original));
    redo();
    await waitFor(() => expect(readSaved()).toEqual(moved));
    undo();
    await waitFor(() => expect(readSaved()).toEqual(original));

    fireEvent.click(screen.getByRole('button', { name: 'Delete edge e1 directly' }));
    expect(readSaved().edges).toHaveLength(original.edges.length - 1);
    undo();
    await waitFor(() => expect(readSaved()).toEqual(original));

    fireEvent.click(screen.getByRole('button', { name: 'Edit n1 role directly' }));
    const roleEdited = readSaved();
    expect(roleEdited.nodes.find((node) => node.id === 'n1')?.role).toBe('nic');
    undo();
    await waitFor(() => expect(readSaved()).toEqual(original));
    redo();
    await waitFor(() => expect(readSaved()).toEqual(roleEdited));
  });

  it('selects a canvas node with Space', () => {
    localStorage.clear();
    render(<Editor />);
    const node = screen.getByRole('button', { name: 'n2 compute_tile' });
    node.focus();
    fireEvent.keyDown(node, { key: ' ' });
    expect(node.getAttribute('aria-pressed')).toBe('true');
  });

  it('Shift-click toggles a node cleanly without leaving stale delete selection', () => {
    localStorage.clear();
    render(<Editor />);
    const node = screen.getByRole('button', { name: 'n1 compute_tile' });
    fireEvent.click(node);
    expect(node.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(node, { shiftKey: true });
    expect(node.getAttribute('aria-pressed')).toBe('false');
    expect(screen.queryByLabelText('node x')).toBeNull();
    expect(screen.getByRole('button', { name: 'Delete' }).hasAttribute('disabled')).toBe(true);
  });

  it('Shift-click multiselects and toggles edges without losing the active inspector', () => {
    localStorage.clear();
    render(<Editor />);
    const e1 = screen.getByRole('button', { name: 'edge e1 n1 to n2' });
    const e2 = screen.getByRole('button', { name: 'edge e2 n2 to n3' });
    fireEvent.click(e1);
    fireEvent.click(e2, { shiftKey: true });
    expect(e1.getAttribute('aria-pressed')).toBe('true');
    expect(e2.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByLabelText('edge width e2')).toBeTruthy();
    fireEvent.click(e2, { shiftKey: true });
    expect(e1.getAttribute('aria-pressed')).toBe('true');
    expect(e2.getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByLabelText('edge width e1')).toBeTruthy();
  });

  it('marquee-selects graph nodes and edges while keeping active inspectors', () => {
    localStorage.clear();
    render(<Editor />);
    const canvas = screen.getByTestId('authoring-canvas');
    const bounds = vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 300,
      width: 600, height: 300, toJSON: () => ({}),
    } as DOMRect);
    fireEvent.mouseDown(canvas, { button: 0, clientX: 0, clientY: 0 });
    fireEvent.mouseMove(canvas, { clientX: 600, clientY: 300 });
    expect(screen.getByTestId('selection-marquee')).toBeTruthy();
    fireEvent.mouseUp(canvas, { clientX: 600, clientY: 300 });
    for (let i = 1; i <= 8; i++) {
      expect(screen.getByRole('button', { name: `n${i} compute_tile` }).getAttribute('aria-pressed')).toBe('true');
    }
    expect(screen.getByRole('button', { name: 'edge e1 n1 to n2' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'edge e8 n8 to n1' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByLabelText('node x')).toBeTruthy();
    expect(screen.getByLabelText('edge width e8')).toBeTruthy();
    bounds.mockRestore();
  });

  it('marquee-selects an edge segment without selecting endpoint nodes', () => {
    localStorage.clear();
    render(<Editor />);
    const canvas = screen.getByTestId('authoring-canvas');
    const bounds = vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 300,
      width: 600, height: 300, toJSON: () => ({}),
    } as DOMRect);
    const view = canvas.getAttribute('viewBox')!.split(' ').map(Number);
    const toClientX = (x: number): number => (x - view[0]) * 600 / view[2];
    const toClientY = (y: number): number => (y - view[1]) * 300 / view[3];
    fireEvent.mouseDown(canvas, { button: 0, clientX: toClientX(510), clientY: toClientY(258) });
    fireEvent.mouseMove(canvas, { clientX: toClientX(500), clientY: toClientY(262) });
    fireEvent.mouseUp(canvas, { clientX: toClientX(500), clientY: toClientY(262) });
    expect(screen.getByRole('button', { name: 'edge e1 n1 to n2' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'n1 compute_tile' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByLabelText('edge width e1')).toBeTruthy();
    bounds.mockRestore();
  });

  it('pans, zooms around the pointer, fits content and resets the view', () => {
    localStorage.clear();
    render(<Editor />);
    const canvas = screen.getByTestId('authoring-canvas');
    const bounds = vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 300,
      width: 600, height: 300, toJSON: () => ({}),
    } as DOMRect);
    const readView = (): number[] => canvas.getAttribute('viewBox')!.split(' ').map(Number);
    const initial = readView();

    fireEvent.wheel(canvas, { ctrlKey: true, deltaY: -1, clientX: 300, clientY: 150 });
    const zoomed = readView();
    expect(zoomed[2]).toBeCloseTo(initial[2] * 0.9);
    expect(zoomed[3]).toBeCloseTo(initial[3] * 0.9);
    expect(zoomed[0] + zoomed[2] / 2).toBeCloseTo(initial[0] + initial[2] / 2);
    expect(zoomed[1] + zoomed[3] / 2).toBeCloseTo(initial[1] + initial[3] / 2);

    fireEvent.wheel(canvas, { deltaX: 10, deltaY: 5, clientX: 300, clientY: 150 });
    const scrolled = readView();
    expect(scrolled[0]).toBeGreaterThan(zoomed[0]);
    expect(scrolled[1]).toBeGreaterThan(zoomed[1]);

    fireEvent.click(screen.getByRole('button', { name: 'Pan canvas: off' }));
    fireEvent.mouseDown(canvas, { button: 0, clientX: 100, clientY: 100 });
    fireEvent.mouseMove(canvas, { clientX: 130, clientY: 140 });
    fireEvent.mouseUp(canvas);
    const panned = readView();
    expect(panned[0]).toBeLessThan(scrolled[0]);
    expect(panned[1]).toBeLessThan(scrolled[1]);

    fireEvent.click(screen.getByRole('button', { name: 'Fit to content' }));
    expect(readView()).toEqual(initial);
    fireEvent.wheel(canvas, { ctrlKey: true, deltaY: -1, clientX: 300, clientY: 150 });
    fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
    expect(readView()).toEqual(initial);
    bounds.mockRestore();
  });

  it('drags a node with optional grid snap as one undoable edit', () => {
    localStorage.clear();
    render(<EditorWithUndo />);
    const original = buildPreset('ring-8').nodes.find((node) => node.id === 'n1')!;
    const canvas = screen.getByTestId('authoring-canvas');
    const bounds = vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 600,
      width: 600, height: 600, toJSON: () => ({}),
    } as DOMRect);

    fireEvent.mouseDown(screen.getByRole('button', { name: 'n1 compute_tile' }), { button: 0 });
    fireEvent.mouseMove(canvas, { clientX: 33, clientY: 69 });
    fireEvent.mouseUp(canvas);
    const snapped = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    const snappedNode = snapped.nodes.find((node) => node.id === 'n1')!;
    expect(snappedNode.x % 20).toBe(0);
    expect(snappedNode.y % 20).toBe(0);
    expect(snappedNode).not.toMatchObject({ x: original.x, y: original.y });
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)
      .nodes.find((node: { id: string }) => node.id === 'n1')).toMatchObject(original);

    fireEvent.click(screen.getByRole('button', { name: 'Snap to grid: on' }));
    const baseViewBox = canvas.getAttribute('viewBox')!.split(' ').map(Number);
    fireEvent.mouseDown(screen.getByRole('button', { name: 'n1 compute_tile' }), { button: 0 });
    fireEvent.mouseMove(canvas, { clientX: 33, clientY: 69 });
    fireEvent.mouseUp(canvas);
    const unsnapped = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    const unsnappedNode = unsnapped.nodes.find((node) => node.id === 'n1')!;
    expect(unsnappedNode).toMatchObject({ x: baseViewBox[0] + 33, y: baseViewBox[1] + 69 });
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)
      .nodes.find((node: { id: string }) => node.id === 'n1')).toMatchObject(original);
    bounds.mockRestore();
  });

  it('previews a node deletion before one undoable removal of its dependent edges', () => {
    localStorage.clear();
    render(<EditorWithUndo />);
    const original = buildPreset('ring-8');
    fireEvent.click(screen.getByRole('button', { name: 'n1 compute_tile' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const preview = screen.getByRole('dialog', { name: 'Confirm node deletion' });
    expect(preview.textContent).toContain('e1');
    expect(preview.textContent).toContain('e8');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete node' }));
    const deleted = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(deleted.nodes.some((node) => node.id === 'n1')).toBe(false);
    expect(deleted.edges.some((edge) => edge.src === 'n1' || edge.dst === 'n1')).toBe(false);
    expect(validateProject(deleted)).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    const restored = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(restored).toEqual(original);
  });

  it('imports project JSON as one undoable command', () => {
    localStorage.clear();
    render(<EditorWithJsonLoad />);
    const original = buildPreset('ring-8');
    const imported = buildPreset('star-8');
    fireEvent.click(screen.getByRole('button', { name: 'Import project JSON' }));
    const loaded = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(loaded.presetHint).toBe('star');
    expect(loaded.nodes.map((node) => node.id)).toEqual(imported.nodes.map((node) => node.id));
    expect(loaded.edges).toEqual(imported.edges);
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)).toEqual(original);
  });

  it('loads a preset as one undoable and redoable history step', () => {
    localStorage.clear();
    render(<EditorWithPresetLoad />);
    const original = buildPreset('ring-8');
    fireEvent.click(screen.getByRole('button', { name: 'Load mesh preset' }));
    const loaded = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(loaded).toEqual(buildPreset('mesh-4x4'));
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)).toEqual(original);
    fireEvent.click(screen.getByRole('button', { name: 'Redo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)).toEqual(loaded);
  });

  it('applies a multi-node role edit as one undoable batch command', () => {
    localStorage.clear();
    render(<EditorWithUndo />);
    const original = buildPreset('ring-8');
    fireEvent.click(screen.getByRole('button', { name: 'n1 compute_tile' }));
    fireEvent.click(screen.getByRole('button', { name: 'n2 compute_tile' }), { shiftKey: true });
    fireEvent.change(screen.getByLabelText('Batch role'), { target: { value: 'nic' } });
    const edited = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(edited.nodes.find((node) => node.id === 'n1')?.role).toBe('nic');
    expect(edited.nodes.find((node) => node.id === 'n2')?.role).toBe('nic');
    expect(validateProject(edited)).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)).toEqual(original);
  });

  it('deletes a Shift-selected node batch as one undoable graph command', () => {
    localStorage.clear();
    render(<EditorWithUndo />);
    const original = buildPreset('ring-8');
    fireEvent.click(screen.getByRole('button', { name: 'n1 compute_tile' }));
    fireEvent.click(screen.getByRole('button', { name: 'n2 compute_tile' }), { shiftKey: true });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const preview = screen.getByRole('dialog', { name: 'Confirm node deletion' });
    expect(preview.textContent).toContain('e1');
    expect(preview.textContent).toContain('e2');
    expect(preview.textContent).toContain('e8');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete node' }));
    const deleted = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(deleted.nodes.some((node) => node.id === 'n1' || node.id === 'n2')).toBe(false);
    expect(deleted.edges.some((edge) => edge.src === 'n1' || edge.dst === 'n1' || edge.src === 'n2' || edge.dst === 'n2')).toBe(false);
    expect(validateProject(deleted)).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!)).toEqual(original);
  });

  it('adds, wires, edits, autosaves and reopens a topology without changing IDs/endpoints', () => {
    localStorage.clear();
    render(<Editor />);
    const originalNodes = buildPreset('ring-8').nodes;
    fireEvent.click(screen.getByRole('button', { name: '+ node (wired)' }));
    let saved = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    const newNode = saved.nodes.find((node) => !originalNodes.some((base) => base.id === node.id))!;
    expect(newNode).toBeTruthy();
    const bridge = saved.edges[saved.edges.length - 1];
    fireEvent.change(screen.getByLabelText('edge source'), { target: { value: 'n2' } });
    fireEvent.change(screen.getByLabelText('edge target'), { target: { value: newNode.id } });
    fireEvent.click(screen.getByRole('button', { name: 'Wire link' }));
    saved = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    const wired = saved.edges.find((edge) => edge.id !== bridge.id && edge.src === 'n2' && edge.dst === newNode.id)!;
    expect(wired).toBeTruthy();
    fireEvent.click(screen.getByTestId(`edge-hit-${wired.id}`));
    const width = screen.getByLabelText(`edge width ${wired.id}`) as HTMLInputElement;
    fireEvent.change(width, { target: { value: '256' } });
    fireEvent.blur(width);
    saved = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(saved.edges.find((edge) => edge.id === wired.id)?.width).toBe(256);
    const expectedNodeIds = saved.nodes.map((node) => node.id);
    const expectedLinks = saved.edges.map(({ id, src, dst }) => [id, src, dst]);

    cleanup();
    render(<Editor />);
    const reopened = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(reopened.nodes.map((node) => node.id)).toEqual(expectedNodeIds);
    expect(reopened.edges.map(({ id, src, dst }) => [id, src, dst])).toEqual(expectedLinks);
    expect(validateProject(reopened)).toEqual([]);
    expect(screen.getByRole('button', { name: `${newNode.id} compute_tile` })).toBeTruthy();
  });

  it('selects, inspects, deletes and undoes an edge independently', () => {
    localStorage.clear();
    render(<EditorWithUndo />);
    const original = buildPreset('ring-8');
    fireEvent.click(screen.getByTestId('edge-hit-e1'));
    expect(screen.getByLabelText('edge width e1')).toBeTruthy();
    expect(screen.queryByLabelText('node x')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'delete link' }));
    const deleted = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(deleted.edges.some((edge) => edge.id === 'e1')).toBe(false);
    expect(validateProject(deleted)).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    const restored = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(restored.edges).toEqual(original.edges);
    expect(validateProject(restored)).toEqual([]);
  });

  it('copies and pastes selected nodes with remapped internal edges and relative placement', () => {
    localStorage.clear();
    render(<EditorWithUndo />);
    const original = buildPreset('ring-8');
    fireEvent.click(screen.getByRole('button', { name: 'n1 compute_tile' }));
    fireEvent.click(screen.getByRole('button', { name: 'n2 compute_tile' }), { shiftKey: true });
    const copy = screen.getByRole('button', { name: 'Copy' });
    const paste = screen.getByRole('button', { name: 'Paste' });
    expect(copy.hasAttribute('disabled')).toBe(false);
    expect(paste.hasAttribute('disabled')).toBe(true);
    fireEvent.click(copy);
    expect(paste.hasAttribute('disabled')).toBe(false);
    fireEvent.click(paste);

    const saved = localStorage.getItem('loom-graph-autosave-v1:local');
    expect(saved).not.toBeNull();
    const project = JSON.parse(saved!) as ReturnType<typeof buildPreset>;
    expect(project.presetHint).toBeNull();
    const a = project.nodes.find((node) => node.id === 'n1-copy1')!;
    const b = project.nodes.find((node) => node.id === 'n2-copy1')!;
    const oldA = original.nodes.find((node) => node.id === 'n1')!;
    const oldB = original.nodes.find((node) => node.id === 'n2')!;
    expect(a.x - b.x).toBe(oldA.x - oldB.x);
    expect(a.y - b.y).toBe(oldA.y - oldB.y);
    const internal = project.edges.find((edge) => edge.src === a.id && edge.dst === b.id);
    expect(internal).toMatchObject({ id: 'e1-copy1', width: 512, pipelineStages: 1, vcClass: 0 });
    expect(project.edges).toContainEqual(expect.objectContaining({ src: 'n2', dst: 'n1-copy1' }));
    expect(validateProject(project)).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Undo graph edit' }));
    const undone = JSON.parse(localStorage.getItem('loom-graph-autosave-v1:local')!) as ReturnType<typeof buildPreset>;
    expect(undone).toEqual(original);
  });
});
