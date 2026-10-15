/** Domain editor (tracker M3-11/M3-12, M2-20).
 *
 *  Declares clock/reset/power domains and assigns them at node and port level,
 *  one undoable command per edit. Reads the local authoring graph. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { DomainsEditor } from '../pages/loom/DomainsEditor';
import { useGraphStore } from '../graph/store';
import type { LoomProject } from '../graph/project';

const key = (scope: string): string => `loom-graph-autosave-v1:${scope}`;
const seed: LoomProject = {
  schemaVersion: 1,
  compilerSemanticsVersion: 1,
  presetHint: null,
  nodes: [
    { id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 5 },
    { id: 'n2', x: 200, y: 0, role: 'hbm_controller', ports: 5 },
  ],
  edges: [],
  agents: [{
    id: 'a1', nodeId: 'n1', role: 'initiator', protocol: 'AXI4', capabilities: ['read'],
    ports: [{ id: 'p1', role: 'initiator', protocol: 'AXI4', dataWidth: 256, capabilities: ['read'] }],
  }],
};

const read = (scope: string): LoomProject => {
  const parsed = JSON.parse(localStorage.getItem(key(scope))!) as { graph?: LoomProject };
  return (parsed.graph ?? parsed) as LoomProject;
};

function Harness({ scope }: { scope: string }): ReactElement {
  const store = useGraphStore('mesh-8x8', scope);
  return (
    <>
      <DomainsEditor store={store} />
      <button type="button" onClick={() => store.undo()}>Undo domain edit</button>
    </>
  );
}

const mount = (scope: string): ReturnType<typeof render> => render(<Harness scope={scope} />);

afterEach(() => { cleanup(); localStorage.clear(); });

describe('M3-11/M3-12: declaring domains', () => {
  it('adds clock, reset and power domains', () => {
    localStorage.setItem(key('dom-add'), JSON.stringify(seed));
    mount('dom-add');

    fireEvent.click(screen.getByRole('button', { name: '+ clock domain' }));
    fireEvent.click(screen.getByRole('button', { name: '+ reset domain' }));
    fireEvent.click(screen.getByRole('button', { name: '+ power domain' }));

    const saved = read('dom-add');
    expect(saved.domains?.clocks.map((c) => c.id)).toEqual(['clk_1']);
    expect(saved.domains?.resets.map((r) => r.id)).toEqual(['rst_1']);
    expect(saved.domains?.powers.map((p) => p.id)).toEqual(['pd_1']);
  });

  it('edits a clock frequency and a reset polarity', () => {
    localStorage.setItem(key('dom-edit'), JSON.stringify(seed));
    mount('dom-edit');
    fireEvent.click(screen.getByRole('button', { name: '+ clock domain' }));
    fireEvent.blur(screen.getByLabelText('clock frequency clk_1'), { target: { value: '1200000000' } });
    expect(read('dom-edit').domains?.clocks[0]!.frequencyHz).toBe(1_200_000_000);

    fireEvent.click(screen.getByRole('button', { name: '+ reset domain' }));
    fireEvent.change(screen.getByLabelText('reset polarity rst_1'), { target: { value: 'active_high' } });
    fireEvent.click(screen.getByLabelText('reset asynchronous rst_1'));
    expect(read('dom-edit').domains?.resets[0]).toMatchObject({ polarity: 'active_high', asynchronous: false });
  });
});

describe('M2-20: node and port assignment', () => {
  it('assigns a node-level clock domain', () => {
    localStorage.setItem(key('dom-node'), JSON.stringify(seed));
    mount('dom-node');
    fireEvent.click(screen.getByRole('button', { name: '+ clock domain' }));
    fireEvent.change(screen.getByLabelText('node clock domain'), { target: { value: 'clk_1' } });
    expect(read('dom-node').nodes.find((n) => n.id === 'n1')?.clock).toBe('clk_1');
  });

  it('records a port override and clears it back to inherit', () => {
    localStorage.setItem(key('dom-port'), JSON.stringify(seed));
    mount('dom-port');
    fireEvent.click(screen.getByRole('button', { name: '+ clock domain' }));

    const select = screen.getByLabelText('port p1 clock domain');
    fireEvent.change(select, { target: { value: 'clk_1' } });
    expect(read('dom-port').domains?.portAssignments).toEqual([{ nodeId: 'n1', portId: 'p1', clockDomainId: 'clk_1' }]);

    fireEvent.change(screen.getByLabelText('port p1 clock domain'), { target: { value: '' } });
    expect(read('dom-port').domains?.portAssignments).toEqual([]);
  });

  it('removing a referenced clock clears the node default and the domain', () => {
    localStorage.setItem(key('dom-remove'), JSON.stringify(seed));
    mount('dom-remove');
    fireEvent.click(screen.getByRole('button', { name: '+ clock domain' }));
    fireEvent.change(screen.getByLabelText('node clock domain'), { target: { value: 'clk_1' } });

    fireEvent.click(screen.getByRole('button', { name: 'remove clock domain clk_1' }));
    const saved = read('dom-remove');
    expect(saved.domains?.clocks).toEqual([]);
    expect(saved.nodes.find((n) => n.id === 'n1')?.clock ?? null).toBeNull();
  });

  it('is undoable as one edit per command', () => {
    localStorage.setItem(key('dom-undo'), JSON.stringify(seed));
    mount('dom-undo');
    fireEvent.click(screen.getByRole('button', { name: '+ clock domain' }));
    expect(read('dom-undo').domains?.clocks).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Undo domain edit' }));
    expect(read('dom-undo').domains?.clocks ?? []).toHaveLength(0);
  });
});
