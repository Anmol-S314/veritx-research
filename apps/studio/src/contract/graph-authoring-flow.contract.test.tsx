import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';

const renderGraph = (id = 'authoring-flow-test') => render(<GraphLoom projectId={id} draftRequest={null} />);
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('graph authoring UI persistence flow', () => {
  it('shows an actionable empty-node state and creates the first node', async () => {
    const scope = 'authoring-flow-empty';
    localStorage.setItem(`loom-graph-autosave-v1:${scope}`, JSON.stringify({
      schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: null, nodes: [], edges: [],
    }));
    renderGraph(scope);

    expect(screen.getByText('No nodes yet')).toBeTruthy();
    expect(screen.getByText('Create the first node to start building this graph.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'create first node' }));

    expect(await screen.findByRole('button', { name: 'n1 compute_tile' })).toBeTruthy();
    expect(screen.getByText('Validation', { selector: '.loom-strip-key' }).parentElement?.textContent).toContain('clean');
  });

  it('edits through the inspector, validates, and restores the edit after remount', async () => {
    const scope = 'authoring-flow-edit';
    localStorage.clear();
    const firstMount = renderGraph(scope);
    expect(screen.getByText('Validation', { selector: '.loom-strip-key' }).parentElement?.textContent).toContain('clean');
    fireEvent.click(screen.getByRole('button', { name: 'n1 compute_tile' }));
    fireEvent.click(screen.getByRole('button', { name: 'node (auto-wired)' }));
    const created = await screen.findByRole('button', { name: 'n65 compute_tile' });
    const createdName = created.getAttribute('aria-label') ?? created.textContent ?? '';
    expect(screen.getByText('Nodes', { selector: '.loom-strip-key' }).parentElement?.textContent).toContain('65');
    fireEvent.change(screen.getByRole('combobox', { name: 'inspector role' }), { target: { value: 'nic' } });

    const editedName = createdName.replace('compute_tile', 'nic');
    await waitFor(() => expect(screen.getByRole('button', { name: editedName })).toBeTruthy());
    expect((screen.getByLabelText('graph preset') as HTMLSelectElement).value).toBe('custom');
    expect(screen.getByText('Validation', { selector: '.loom-strip-key' }).parentElement?.textContent).toContain('clean');
    // HEAD's store autosaves eagerly, so no 'unsaved' marker is shown.
    expect(screen.queryByText('unsaved')).toBeNull();

    let downloaded: Blob | null = null;
    const previousCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
    const previousRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: (blob: Blob) => { downloaded = blob; return 'blob:graph-project'; } });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'save project.json' }));
    expect(downloaded).toBeInstanceOf(Blob);
    const savedText = await downloaded!.text();
    expect(JSON.parse(savedText).graph.nodes.some((node: { id: string; role: string }) => node.id === createdName.split(' ')[0] && node.role === 'nic')).toBe(true);
    firstMount.unmount();
    vi.clearAllTimers();
    vi.useRealTimers();

    // Remove autosave deliberately: recovery must now come from the saved file.
    localStorage.removeItem(`loom-graph-autosave-v1:${scope}`);
    if (previousCreate) Object.defineProperty(URL, 'createObjectURL', previousCreate);
    else Reflect.deleteProperty(URL, 'createObjectURL');
    if (previousRevoke) Object.defineProperty(URL, 'revokeObjectURL', previousRevoke);
    else Reflect.deleteProperty(URL, 'revokeObjectURL');

    renderGraph(scope);
    const file = new File([savedText], 'project.json', { type: 'application/json' });
    Object.defineProperty(file, 'text', { configurable: true, value: vi.fn(async () => savedText) });
    fireEvent.change(screen.getByLabelText('load project.json'), { target: { files: [file] } });
    expect(await screen.findByRole('button', { name: editedName })).toBeTruthy();
    expect((screen.getByLabelText('graph preset') as HTMLSelectElement).value).toBe('custom');
    expect(screen.getByText('Validation', { selector: '.loom-strip-key' }).parentElement?.textContent).toContain('clean');
  });
});
