/** Address map view (tracker M3-23 / M3-24).
 *
 *  Reads the local authoring graph: mapped windows, internal holes and unmapped
 *  initiator ports, plus the initiator toggle and the window inspector. Overlap
 *  detection is covered by the pure `address-map` suite — a document with
 *  overlapping target windows cannot load into the store (the validator refuses
 *  it), so the view asserts the empty-overlap confirmation instead. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import AddressLoom from '../pages/loom/AddressLoom';
import type { AgentCapability, AgentRole, AgentPort, LoomProject, ProjectAgent } from '../graph/project';

const key = (scope: string): string => `loom-graph-autosave-v1:${scope}`;
type Perm = 'read' | 'write';
const PERMS: Perm[] = ['read', 'write'];
const CAPS: AgentCapability[] = ['read', 'write'];

function port(id: string, role: AgentRole, windows: { base: string; size: string }[], addressWidth?: number): AgentPort {
  return {
    id, role, protocol: 'AXI4', dataWidth: 256, addressWidth, capabilities: [...CAPS],
    addressWindows: windows.map((w) => ({ ...w, permissions: [...PERMS] })),
  };
}
function agent(id: string, nodeId: string, role: AgentRole, ports: AgentPort[]): ProjectAgent {
  return { id, nodeId, role, protocol: 'AXI4', capabilities: [...CAPS], ports };
}

// A valid document: no overlapping target windows (the validator would refuse
// one), but two internal holes and an unmapped initiator port.
const seed: LoomProject = {
  schemaVersion: 1,
  compilerSemanticsVersion: 1,
  presetHint: null,
  nodes: [
    { id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 5 },
    { id: 'n2', x: 200, y: 0, role: 'hbm_controller', ports: 5 },
  ],
  edges: [],
  agents: [
    agent('a1', 'n1', 'initiator', [port('p1', 'initiator', [{ base: '0x0', size: '0x100' }])]),
    agent('a4', 'n1', 'initiator', [port('p1', 'initiator', [])]),
    agent('a2', 'n2', 'target', [port('p1', 'target', [{ base: '0x0', size: '0x1000' }, { base: '0x2000', size: '0x1000' }], 32)]),
    agent('a3', 'n2', 'target', [port('p2', 'target', [{ base: '0x4000', size: '0x1000' }], 32)]),
  ],
};

const renderView = (scope: string): ReturnType<typeof render> => render(<AddressLoom projectId={scope} />);

afterEach(() => { cleanup(); localStorage.clear(); });

describe('M3-23: address map view', () => {
  it('summarises mapped windows, holes and unmapped initiators', () => {
    localStorage.setItem(key('addr-map'), JSON.stringify(seed));
    renderView('addr-map');

    const cell = (k: string): string =>
      screen.getByText(k, { selector: '.loom-strip-key' }).parentElement?.textContent ?? '';
    expect(cell('Mapped windows')).toContain('3');
    expect(cell('Overlaps')).toContain('0');
    expect(cell('Holes')).toContain('2');
    expect(cell('Unmapped initiators')).toContain('1');
  });

  it('lists the internal holes and the unmapped port', () => {
    localStorage.setItem(key('addr-findings'), JSON.stringify(seed));
    renderView('addr-findings');

    const holes = screen.getByText('Internal holes').closest('section')?.textContent ?? '';
    expect(holes).toContain('0x1000');
    expect(holes).toContain('0x2000');
    expect(holes).toContain('0x3000');
    expect(holes).toContain('0x4000');
    expect(screen.getByText('Unmapped initiator ports').closest('section')?.textContent).toContain('a4/p1');
    expect(screen.getByText('Overlaps', { selector: '.loom-section-title' }).closest('section')?.textContent)
      .toContain('No two mapped windows overlap');
  });

  it('shows target windows by default and initiator windows only on request', () => {
    localStorage.setItem(key('addr-toggle'), JSON.stringify(seed));
    renderView('addr-toggle');

    expect(screen.queryAllByText('a1/p1')).toHaveLength(0);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.queryAllByText('a1/p1').length).toBeGreaterThan(0);
  });

  it('reads a selected window in the inspector', () => {
    localStorage.setItem(key('addr-inspector'), JSON.stringify(seed));
    renderView('addr-inspector');

    // 0x4000 is both the a3 window base and the end of the second hole; the
    // first match is the base cell in the mapped table, whose row is clickable.
    fireEvent.click(screen.getAllByText('0x4000')[0]!);
    expect(screen.getByText('Window inspector').closest('section')?.textContent).toContain('a3/p2');
  });

  it('asks for a window when none is authored', () => {
    localStorage.setItem(key('addr-empty'), JSON.stringify({ ...seed, agents: [] }));
    renderView('addr-empty');
    expect(screen.getByText('No authored address windows')).toBeTruthy();
  });
});
