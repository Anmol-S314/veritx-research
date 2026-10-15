/** Node layout cleanup (tidy) and port-drag link refusal (M1-19 / M1-15).
 *
 *  Tidy is a pure patch over the selection applied as one undoable edit; the
 *  port drag uses the SAME compatibility authority as the click-to-link path,
 *  so a bad drop is refused with a reason instead of creating a dead edge. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import type { LoomProject } from '../graph/project';

const autosaveKey = (scope: string): string => `loom-graph-autosave-v1:${scope}`;
const seed: LoomProject = {
  schemaVersion: 1,
  compilerSemanticsVersion: 1,
  presetHint: null,
  nodes: [
    { id: 'a', x: 13, y: 7, role: 'compute_tile', ports: 5 },
    { id: 'b', x: 0, y: 0, role: 'compute_tile', ports: 5 },
  ],
  edges: [],
};

const read = (scope: string): LoomProject => JSON.parse(localStorage.getItem(autosaveKey(scope))!) as LoomProject;

afterEach(() => { cleanup(); localStorage.clear(); });

describe('M1-19: node layout cleanup', () => {
  it('tidies the selection as one undoable edit', () => {
    localStorage.setItem(autosaveKey('tidy-ui'), JSON.stringify(seed));
    render(<GraphLoom projectId="tidy-ui" draftRequest={null} />);
    fireEvent.click(screen.getByTestId('node-a'));
    fireEvent.click(screen.getByTestId('node-b'), { shiftKey: true });
    expect(screen.getByTestId('selection-count').textContent).toBe('2 node(s), 0 link(s) selected');

    fireEvent.click(screen.getByRole('button', { name: 'tidy selection' }));
    const saved = read('tidy-ui');
    const a = saved.nodes.find((n) => n.id === 'a')!;
    const b = saved.nodes.find((n) => n.id === 'b')!;
    // Both snapped to the 20-unit grid and no longer inside each other's box.
    expect(a.x % 20).toBe(0);
    expect((a.x === b.x && a.y === b.y)).toBe(false);
    expect(Math.abs(a.x - b.x) >= 76 || Math.abs(a.y - b.y) >= 48).toBe(true);
    expect((screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('tidies the whole graph from one button', () => {
    localStorage.setItem(autosaveKey('tidy-all'), JSON.stringify(seed));
    render(<GraphLoom projectId="tidy-all" draftRequest={null} />);
    fireEvent.click(screen.getByRole('button', { name: 'tidy graph' }));
    const saved = read('tidy-all');
    expect(saved.nodes.map((n) => n.id).sort()).toEqual(['a', 'b']);
    expect(validateNoOverlap(saved)).toBe(true);
  });
});

function validateNoOverlap(project: LoomProject): boolean {
  for (let i = 0; i < project.nodes.length; i++) for (let j = i + 1; j < project.nodes.length; j++) {
    const a = project.nodes[i]!;
    const b = project.nodes[j]!;
    if (Math.abs(a.x - b.x) < 76 && Math.abs(a.y - b.y) < 48) return false;
  }
  return true;
}

describe('M1-15: port drag uses the same pick-time refusal', () => {
  it('refuses an incompatible drag with a reason and creates no edge', () => {
    const incompatible: LoomProject = {
      ...seed,
      nodes: [
        { id: 'a', x: 0, y: 0, role: 'compute_tile', ports: 5, interfaceRole: 'INITIATOR' },
        { id: 'b', x: 200, y: 0, role: 'compute_tile', ports: 5, interfaceRole: 'INITIATOR' },
      ],
    };
    localStorage.setItem(autosaveKey('drag-refusal'), JSON.stringify(incompatible));
    render(<GraphLoom projectId="drag-refusal" draftRequest={null} />);

    fireEvent.mouseDown(screen.getByTestId('port-a-e'), { button: 0 });
    fireEvent.mouseUp(screen.getByTestId('node-b'), { clientX: 200, clientY: 0 });

    expect(screen.getByTestId('link-error').textContent).toMatch(/cannot pair/);
    expect(read('drag-refusal').edges).toHaveLength(0);
  });

  it('creates the edge on a compatible drag', () => {
    const compatible: LoomProject = {
      ...seed,
      nodes: [
        { id: 'a', x: 0, y: 0, role: 'compute_tile', ports: 5, interfaceRole: 'INITIATOR' },
        { id: 'b', x: 200, y: 0, role: 'compute_tile', ports: 5, interfaceRole: 'TARGET' },
      ],
    };
    localStorage.setItem(autosaveKey('drag-ok'), JSON.stringify(compatible));
    render(<GraphLoom projectId="drag-ok" draftRequest={null} />);

    fireEvent.mouseDown(screen.getByTestId('port-a-e'), { button: 0 });
    fireEvent.mouseUp(screen.getByTestId('node-b'), { clientX: 200, clientY: 0 });

    const saved = read('drag-ok');
    expect(saved.edges).toHaveLength(1);
    expect(saved.edges[0]).toMatchObject({ src: 'a', dst: 'b' });
    expect(screen.queryByTestId('link-error')).toBeNull();
  });
});
