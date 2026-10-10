import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentEditor, { AGENT_KINDS } from '../components/AgentEditor';

const doc = {
  schema_version: 4, topology: { kind: 'mesh', side_length: 4, concentration: 4 },
  agents: [
    { kind: 'compute_tile', count: 57, data_width: 128, addr_width: 32, protocol: 'CHI', clock_domain: 'core', power_domain: 'compute' },
    { kind: 'hbm_controller', count: 7, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null },
  ],
  workload: { tp: 8 }, noc_controls: { link_width: 64 }, requirements: [], dependencies: [{ authored: true }],
};
afterEach(cleanup);
function editor(props: { selectedAgent?: number; readOnly?: boolean; doc?: Record<string, unknown> } = {}): ReturnType<typeof vi.fn> {
  const changed = vi.fn(); render(<AgentEditor doc={doc} onChange={changed} {...props} />); return changed;
}

describe('choose agents and edit real group properties', () => {
  it('uses the closed five-kind picker, with no writes or invented defaults on mount', () => {
    const changed = editor();
    const select = screen.getByLabelText('Agent type') as HTMLSelectElement;
    expect([...select.options].map(option => option.value)).toEqual([...AGENT_KINDS]);
    expect(select.value).toBe('compute_tile');
    expect(screen.getByText(/not a GPU\/NPU performance model/)).toBeTruthy();
    expect(changed).not.toHaveBeenCalled();
  });

  it('changes the chosen kind without resetting its other authored properties', () => {
    const changed = editor();
    fireEvent.change(screen.getByLabelText('Agent type'), { target: { value: 'nic' } });
    expect(changed.mock.calls[0][0]).toEqual({ ...doc, agents: [{ ...doc.agents[0], kind: 'nic' }, doc.agents[1]] });
  });

  it('adds the type chosen by the human without resizing topology or parallelism', () => {
    const changed = editor();
    fireEvent.change(screen.getByLabelText('Agent type to add'), { target: { value: 'ucie_port' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add agent group' }));
    const next = changed.mock.calls[0][0];
    expect(next.agents[2]).toEqual({ kind: 'ucie_port', count: 1, data_width: 256, addr_width: 64,
      protocol: 'AXI', clock_domain: null, power_domain: null });
    for (const key of ['topology', 'workload', 'requirements', 'dependencies', 'noc_controls']) {
      expect(next[key]).toEqual(doc[key as keyof typeof doc]);
    }
  });

  it('lets canvas selection inspect and tune the selected group, not the first group', () => {
    const changed = editor({ selectedAgent: 1 });
    expect((screen.getByLabelText('Instance count') as HTMLInputElement).value).toBe('7');
    expect(screen.getByText(/HBM capacity, banks, channels/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Data width (bits)'), { target: { value: '512' } });
    expect(changed.mock.calls[0][0].agents).toEqual([doc.agents[0], { ...doc.agents[1], data_width: 512 }]);
    expect(changed.mock.calls[0][0].noc_controls.link_width).toBe(64);
  });

  it('preserves custom protocol/domain labels and exposes their support limits', () => {
    const changed = editor({ doc: { ...doc, agents: [{ ...doc.agents[0], protocol: 'private-stream' }] } });
    expect((screen.getByLabelText('Custom protocol label') as HTMLInputElement).value).toBe('private-stream');
    expect(screen.getByText(/do not establish transaction simulation/)).toBeTruthy();
    expect(screen.getByText(/not CDC, power gating/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Clock domain'), { target: { value: '' } });
    expect(changed.mock.calls[0][0].agents[0].clock_domain).toBeNull();
    expect(changed.mock.calls[0][0].agents[0].protocol).toBe('private-stream');
  });

  it('does not coerce imported unknown kinds to a supported role', () => {
    const changed = editor({ doc: { ...doc, agents: [{ ...doc.agents[0], kind: 'unknown-import' }] } });
    expect((screen.getByLabelText('Agent type') as HTMLSelectElement).value).toBe('unknown-import');
    expect(screen.getByText('Unsupported existing kind: unknown-import')).toBeTruthy();
    expect(changed).not.toHaveBeenCalled();
  });

  it('protects address-map targets from index-shifting deletion', () => {
    editor({ doc: { ...doc, address_map: { ranges: [{ target_agent_idx: 1, base: 0, size: 4096 }] } } });
    expect((screen.getByRole('button', { name: 'Remove agent group' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Group indexes are not remapped/)).toBeTruthy();
  });

  it('keeps Review read-only and lists unsupported per-instance tuning honestly', () => {
    const changed = editor({ readOnly: true });
    for (const label of ['Agent type', 'Instance count', 'Data width (bits)', 'Address width (bits)', 'Interface protocol', 'Clock domain', 'Power domain']) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(true);
    }
    expect(screen.queryByRole('button', { name: 'Add agent group' })).toBeNull();
    expect(screen.getByText(/Per-instance credits, outstanding transactions/)).toBeTruthy();
    expect(changed).not.toHaveBeenCalled();
  });
});
