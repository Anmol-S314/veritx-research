/** Node agents, ports, address windows and protocol compatibility
 *  (M2-15 / M2-16 / M2-18 / M2-19). */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import { isBridgeNode, nodeProtocols, protocolCompatibilityProblem } from '../graph/protocolCompat';
import type { LoomProject, ProjectAgent } from '../graph/project';

const agent = (nodeId: string, protocols: string[]): ProjectAgent => ({
  id: `agent-${nodeId}`, nodeId, role: 'initiator', protocol: protocols[0] ?? 'AXI4', capabilities: ['read'],
  ports: protocols.map((protocol, i) => ({ id: `p${i + 1}`, role: 'initiator', protocol, dataWidth: 256, capabilities: ['read'] })),
});

const project = (agents: ProjectAgent[], roles: Record<string, string> = {}): Pick<LoomProject, 'nodes' | 'agents'> => ({
  nodes: Object.keys(roles).map((id) => ({ id, x: 0, y: 0, role: roles[id]!, ports: 5 })),
  agents,
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const readAgents = (scope: string): ProjectAgent[] => {
  const parsed = JSON.parse(localStorage.getItem(`loom-graph-autosave-v1:${scope}`)!) as { graph?: { agents?: ProjectAgent[] }; agents?: ProjectAgent[] };
  return (parsed.graph ?? parsed).agents ?? [];
};

describe('M2-18: protocol compatibility', () => {
  it('reads declared protocols from agent ports', () => {
    expect(nodeProtocols({ agents: [agent('n1', ['AXI4', 'AXI4-Lite'])] }, 'n1')).toEqual(['AXI4', 'AXI4-Lite']);
    expect(nodeProtocols({ agents: [] }, 'n1')).toEqual([]);
  });

  it('allows a shared protocol or an unconstrained side', () => {
    const shared = project([agent('n1', ['AXI4']), agent('n2', ['AXI4'])]);
    expect(protocolCompatibilityProblem(shared, 'n1', 'n2')).toBeNull();
    const unconstrained = project([agent('n1', ['AXI4'])]);
    expect(protocolCompatibilityProblem(unconstrained, 'n1', 'n2')).toBeNull();
  });

  it('requires an explicit bridge when no protocol is shared', () => {
    const disjoint = project([agent('n1', ['AXI4']), agent('n2', ['AXI4-Lite'])], { n1: 'compute_tile', n2: 'compute_tile' });
    expect(protocolCompatibilityProblem(disjoint, 'n1', 'n2')).toMatch(/explicit bridge/);
    const bridged = { ...disjoint, nodes: [...disjoint.nodes, { id: 'n3', x: 0, y: 0, role: 'ucie_port', ports: 5 }] };
    expect(isBridgeNode(bridged, 'n3')).toBe(true);
    const withBridge = project([agent('n1', ['AXI4']), agent('n3', ['AXI4-Lite'])], { n1: 'compute_tile', n3: 'ucie_port' });
    expect(protocolCompatibilityProblem(withBridge, 'n1', 'n3')).toBeNull();
  });

  it('refuses an incompatible pick in the editor', () => {
    const scope = 'link-protocols';
    localStorage.setItem(`loom-graph-autosave-v1:${scope}`, JSON.stringify({
      schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: null,
      nodes: [
        { id: 'a', x: 0, y: 0, role: 'compute_tile', ports: 5 },
        { id: 'b', x: 200, y: 0, role: 'compute_tile', ports: 5 },
      ],
      edges: [],
      agents: [
        { id: 'agent-a', nodeId: 'a', role: 'initiator', protocol: 'AXI4', capabilities: ['read'], ports: [{ id: 'p1', role: 'initiator', protocol: 'AXI4', dataWidth: 256, capabilities: ['read'] }] },
        { id: 'agent-b', nodeId: 'b', role: 'initiator', protocol: 'AXI4-Lite', capabilities: ['read'], ports: [{ id: 'p1', role: 'initiator', protocol: 'AXI4-Lite', dataWidth: 32, capabilities: ['read'] }] },
      ],
    }));
    render(<GraphLoom projectId={scope} draftRequest={null} />);
    fireEvent.click(screen.getByRole('button', { name: 'link mode' }));
    fireEvent.click(screen.getByTestId('node-a'));
    fireEvent.click(screen.getByTestId('node-b'));
    expect(screen.getByTestId('link-error').textContent).toMatch(/no shared protocol/);
  });
});

describe('M2-15/M2-16/M2-19: agent, port and window editing', () => {
  it('authors an agent, a port and its address windows as undoable edits', () => {
    const scope = 'agents-edit';
    render(<GraphLoom projectId={scope} draftRequest={null} />);
    fireEvent.click(screen.getByTestId('node-n1'));
    fireEvent.click(screen.getByRole('button', { name: '+ Agent' }));
    expect(readAgents(scope)[0]).toMatchObject({ nodeId: 'n1', role: 'initiator', protocol: 'AXI4' });

    fireEvent.change(screen.getByLabelText('agent role agent-1'), { target: { value: 'target' } });
    fireEvent.click(screen.getByRole('button', { name: 'add port to agent-1' }));
    fireEvent.blur(screen.getByLabelText('port protocol agent-1 p1'), { target: { value: 'AXI4-Lite' } });
    fireEvent.click(screen.getByRole('button', { name: 'add window agent-1 p1' }));
    const saved = readAgents(scope)[0]!;
    expect(saved.role).toBe('target');
    expect(saved.ports[0]!.protocol).toBe('AXI4-Lite');
    expect(saved.ports[0]!.addressWindows).toEqual([{ base: '0x0', size: '0x1000', permissions: ['read', 'write'] }]);

    expect((screen.getByRole('button', { name: 'undo' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('places new address windows after the previous one and reports overlaps', () => {
    const scope = 'agents-window-overlap';
    render(<GraphLoom projectId={scope} draftRequest={null} />);
    fireEvent.click(screen.getByTestId('node-n1'));
    fireEvent.click(screen.getByRole('button', { name: '+ Agent' }));
    fireEvent.change(screen.getByLabelText('agent role agent-1'), { target: { value: 'target' } });
    fireEvent.click(screen.getByRole('button', { name: 'add port to agent-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'add window agent-1 p1' }));
    fireEvent.click(screen.getByRole('button', { name: 'add window agent-1 p1' }));
    // The second window is placed after the first, so no overlap and no issue.
    expect(readAgents(scope)[0]!.ports[0]!.addressWindows).toEqual([
      { base: '0x0', size: '0x1000', permissions: ['read', 'write'] },
      { base: '0x1000', size: '0x1000', permissions: ['read', 'write'] },
    ]);
    expect(screen.queryByTestId('agent-issues')).toBeNull();
    // Editing a base so the two windows overlap is refused by the validator.
    fireEvent.blur(screen.getByLabelText('window base agent-1 p1 0'), { target: { value: '0x1800' } });
    expect(readAgents(scope)[0]!.ports[0]!.addressWindows![0]!.base).toBe('0x0');
  });

  it('removes an agent', () => {
    const scope = 'agents-delete';
    render(<GraphLoom projectId={scope} draftRequest={null} />);
    fireEvent.click(screen.getByTestId('node-n2'));
    fireEvent.click(screen.getByRole('button', { name: '+ Agent' }));
    expect(readAgents(scope)).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'delete agent agent-1' }));
    expect(readAgents(scope)).toHaveLength(0);
  });
});
