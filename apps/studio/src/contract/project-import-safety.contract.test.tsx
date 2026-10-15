import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import { MAX_PROJECT_JSON_BYTES } from '../graph/project';

const renderGraph = () => render(<GraphLoom projectId="import-safety-test" draftRequest={null} />);
afterEach(() => { cleanup(); localStorage.clear(); });

describe('Loom project file import safety', () => {
  it('rejects an oversized project before reading it and keeps the current graph', async () => {
    localStorage.clear();
    renderGraph();
    const original = screen.getByRole('button', { name: 'n1 compute_tile' });
    const text = vi.fn(async () => '{"not":"read"}');
    const file = new File(['placeholder'], 'oversized.json', { type: 'application/json' });
    Object.defineProperties(file, {
      size: { configurable: true, value: MAX_PROJECT_JSON_BYTES + 1 },
      text: { configurable: true, value: text },
    });
    fireEvent.change(screen.getByLabelText('load project.json'), { target: { files: [file] } });
    expect((await screen.findByRole('alert')).textContent).toContain(`project file exceeds ${MAX_PROJECT_JSON_BYTES} byte limit`);
    expect(text).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'n1 compute_tile' })).toBe(original);
  });

  it('shows malformed-project recovery error without replacing the in-memory graph', async () => {
    localStorage.clear();
    renderGraph();
    const original = screen.getByRole('button', { name: 'n1 compute_tile' });
    const file = new File(['placeholder'], 'malformed.json', { type: 'application/json' });
    Object.defineProperty(file, 'text', { configurable: true, value: vi.fn(async () => '{ malformed') });
    fireEvent.change(screen.getByLabelText('load project.json'), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/invalid project JSON/));
    expect(screen.getByRole('button', { name: 'n1 compute_tile' })).toBe(original);
  });

  it.each([
    ['unsupported schema version', JSON.stringify({ schemaVersion: 2, presetHint: null, nodes: [], edges: [] }), '$.schemaVersion'],
    ['missing required edge list', JSON.stringify({ schemaVersion: 1, presetHint: null, nodes: [] }), '$.edges'],
  ])('rejects %s and preserves the existing graph', async (_case, source, expectedIssue) => {
    localStorage.clear();
    renderGraph();
    const original = screen.getByRole('button', { name: 'n1 compute_tile' });
    const file = new File(['placeholder'], 'invalid-project.json', { type: 'application/json' });
    Object.defineProperty(file, 'text', { configurable: true, value: vi.fn(async () => source) });
    fireEvent.change(screen.getByLabelText('load project.json'), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain(expectedIssue));
    expect(screen.getByRole('button', { name: 'n1 compute_tile' })).toBe(original);
  });
});
