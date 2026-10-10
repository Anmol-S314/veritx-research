import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type DesignViewV2, type FabricPresetCatalogView, type LoomCapabilityView } from '../api';
import TopologyIntentEditor from '../components/TopologyIntentEditor';
import DesignViewV2Editor from '../components/DesignViewV2Editor';

const families = ['mesh', 'concentrated_mesh', 'torus', 'explicit', 'flatfly',
  'fattree', 'fat_tree', 'dragonfly', 'flattened_butterfly', 'qtree', 'tree4',
  'gec_mesh', 'gec_express', 'gec_multidrop', 'gec_hybrid', 'srota'];
const caps: LoomCapabilityView = {
  schema_version: 1, type: 'capabilities', statuses: ['READY', 'BLOCKED'],
  note: '', readiness_note: '', capabilities: [], by_status: {},
  topology: { probed: true, families: families.map((family) => ({
    family, status: 'READY', qualification: 'profile-from-server', stopped_at: null,
    reason: 'supported probe configuration',
  })) },
};
const catalog: FabricPresetCatalogView = {
  contract_version: 1, presets: families.map((family) => ({
    preset_id: family, name: family, description: `${family} preset`, family,
    dependencies: family === 'torus' ? [
      { source: 'X', target: 'Y', kind: 'blocking' },
      { source: 'Y', target: 'X', kind: 'blocking' },
    ] : [],
    topology: family === 'dragonfly' ? { kind: 'structured', family, params: { radix: 2, groups: 2 } }
      : family === 'torus' ? { kind: 'torus', side_length: 5, concentration: 1 }
      : family === 'explicit' ? { kind: 'explicit', graph: { nodes: 16, links: [[0, 1]] } }
      : { kind: family, side_length: 4, concentration: 1 },
  })),
};
const doc = {
  schema_version: 4, compiler_semantics_version: 4,
  workload: { tp: 2 }, agents: [{ kind: 'compute_tile', count: 16 }],
  requirements: [{ binding: true }], dependencies: [],
  topology: { kind: 'explicit', graph: { nodes: 16, links: [[0, 1]] } },
  noc_controls: { link_width: 128, arbitration: 'round_robin', output_formats: ['systemverilog'] },
};
beforeEach(() => {
  vi.spyOn(api, 'loomCapabilities').mockResolvedValue(structuredClone(caps));
  vi.spyOn(api, 'fabricPresets').mockResolvedValue(structuredClone(catalog));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function loaded(): Promise<HTMLSelectElement> {
  const selector = screen.getByRole('combobox', { name: 'Topology' }) as HTMLSelectElement;
  await waitFor(() => expect(selector.disabled).toBe(false));
  return selector;
}

describe('typed topology editor', () => {
  it('shows the actual custom graph and all 16 probed families', async () => {
    render(<TopologyIntentEditor doc={doc} onChange={vi.fn()} readOnly={false} projectId="p" />);
    const select = await loaded();
    expect(select.value).toBe('explicit');
    expect(select.options.length).toBe(16);
    expect(select.textContent).not.toMatch(/Experimental|Research/);
    expect(api.loomCapabilities).toHaveBeenCalledWith(true);
  });

  it('switches to structured intent without altering the rest of the draft', async () => {
    const changed = vi.fn();
    render(<TopologyIntentEditor doc={doc} onChange={changed} readOnly={false} projectId="p" />);
    fireEvent.change(await loaded(), { target: { value: 'dragonfly' } });
    expect(changed).toHaveBeenCalledWith({ ...doc,
      topology: { kind: 'structured', family: 'dragonfly', params: { radix: 2, groups: 2 } },
    });
    expect(changed.mock.calls[0][0]).not.toHaveProperty('noc_config');
  });

  it('renders a blocked server verdict and disables that family', async () => {
    const blocked = structuredClone(caps);
    blocked.topology.families!.find((row) => row.family === 'srota')!.status = 'BLOCKED';
    vi.mocked(api.loomCapabilities).mockResolvedValue(blocked);
    render(<TopologyIntentEditor doc={doc} onChange={vi.fn()} readOnly={false} projectId="p" />);
    await loaded();
    const option = screen.getByRole('option', { name: 'SROTA — BLOCKED' }) as HTMLOptionElement;
    expect(option.disabled).toBe(true);
  });

  it('fails closed when the capability request fails', async () => {
    vi.mocked(api.loomCapabilities).mockRejectedValue(new Error('registry unavailable'));
    render(<TopologyIntentEditor doc={doc} onChange={vi.fn()} readOnly={false} projectId="p" />);
    await screen.findByText('registry unavailable');
    expect((screen.getByRole('combobox', { name: 'Topology' }) as HTMLSelectElement).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Retry topology catalog' })).toBeTruthy();
  });

  it('keeps an invalid legacy draft unchanged on migration refusal', async () => {
    vi.spyOn(api, 'previewTopology').mockRejectedValue(new Error('explicit collective payload required'));
    const changed = vi.fn();
    const legacy = { schema_version: 2, noc_config: { topology_family: 'mesh' }, workload: {} };
    render(<TopologyIntentEditor doc={legacy} onChange={changed} readOnly={false} projectId="p" />);
    fireEvent.change(await loaded(), { target: { value: 'dragonfly' } });
    await screen.findByText('explicit collective payload required');
    expect(changed).not.toHaveBeenCalled();
  });

  it('adds torus dependencies only on the explicit action', async () => {
    const changed = vi.fn();
    render(<TopologyIntentEditor doc={{ ...doc, topology: { kind: 'torus', side_length: 5, concentration: 1 } }}
      onChange={changed} readOnly={false} projectId="p" />);
    await loaded();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Add torus X/Y dependencies' }));
    expect(changed.mock.calls[0][0].dependencies).toEqual(catalog.presets.find((p) => p.family === 'torus')!.dependencies);
  });

  it('exposes optional router controls without changing the draft on mount', async () => {
    const changed = vi.fn();
    render(<TopologyIntentEditor doc={doc} onChange={changed} readOnly={false} projectId="p" />);
    await loaded();
    expect(changed).not.toHaveBeenCalled();
    const input = screen.getByLabelText('Input buffer (flits per VC)') as HTMLInputElement;
    expect(input.value).toBe('');
    expect(input.min).toBe('1');
    expect(input.max).toBe('64');
    fireEvent.change(input, { target: { value: '4' } });
    expect(changed.mock.calls[0][0]).toEqual({ ...doc,
      noc_controls: { ...doc.noc_controls, input_buffer_depth_flits_per_vc: 4 },
    });
    expect(screen.getByLabelText('Credit return (cycles)').getAttribute('min')).toBe('0');
    expect(screen.getByLabelText('Allocator iterations')).toBeTruthy();
    expect(screen.getByLabelText('Route compute (cycles)')).toBeTruthy();
    expect(screen.getByLabelText('VC allocation (cycles)')).toBeTruthy();
    expect(screen.getByLabelText('Switch allocation (cycles)')).toBeTruthy();
    expect(screen.getByLabelText('Switch traversal (cycles)')).toBeTruthy();
  });

  it('clears overrides without inventing null fields or dropping other intent', async () => {
    const changed = vi.fn();
    render(<TopologyIntentEditor doc={{ ...doc,
      noc_controls: { ...doc.noc_controls, allocator_iterations: 2 },
    }} onChange={changed} readOnly={false} projectId="p" />);
    await loaded();
    fireEvent.change(screen.getByLabelText('Allocator iterations'), { target: { value: '' } });
    expect(changed.mock.calls[0][0]).toEqual(doc);
  });

  it('shows authored controls read-only in Review', async () => {
    const changed = vi.fn();
    render(<TopologyIntentEditor doc={{ ...doc,
      noc_controls: { ...doc.noc_controls, credit_return_latency_cycles: 0 },
    }} onChange={changed} readOnly />);
    const input = screen.getByLabelText('Credit return (cycles)') as HTMLInputElement;
    expect(input.value).toBe('0');
    expect(input.disabled).toBe(true);
    expect(input.closest('details')?.open).toBe(true);
    expect(changed).not.toHaveBeenCalled();
  });

  it('never exposes v4 router overrides on legacy drafts', async () => {
    render(<TopologyIntentEditor doc={{ schema_version: 3, noc_config: {} }}
      onChange={vi.fn()} readOnly={false} projectId="p" />);
    await loaded();
    expect(screen.queryByLabelText('Allocator iterations')).toBeNull();
  });

  it('never writes edits in review mode', async () => {
    const changed = vi.fn();
    render(<TopologyIntentEditor doc={doc} onChange={changed} readOnly={true} />);
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(16));
    expect((screen.getByRole('combobox', { name: 'Topology' }) as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: 'Apply graph json' })).toBeNull();
    expect(changed).not.toHaveBeenCalled();
  });
});

it('link-width editing reads/writes noc_controls on v4, never a phantom noc_config', async () => {
  const view: DesignViewV2 = {
    contract_version: 2, presentation: 'edit', draft_identity: { project_id: 'p', draft_design_hash: null },
    parent_revision_ref: null, readiness: 'READY', derived_summaries: [], validation_findings: [],
    capability_consequences: [], capability_semantics_version: '1',
    registry_versions: { capability_semantics_version: '1', capability_registry_version: 1, exposure_registry_version: 1 },
    completeness: { active_scientific_fields: [], represented_fields: [], non_active_fields: [],
      unrepresented_active_fields: [], invariant_holds: true, law: '' },
    sections: [{ id: 'fabric', title: 'Fabric', advanced_active_count: 0, blocking_count: 0, limitation_count: 0,
      entries: [{ field: 'NocConfig.link_width', label: 'Link width (bits)', value: 128,
        semantic_class: 'DECLARED', exposure_class: '', disclosure_depth: 'GUIDED', source: null,
        active: true, capability_ref: null, ownership: { domain: 'FABRIC', canonical_field: 'NocConfig.link_width', scientific_name: null } }] }],
  };
  const changed = vi.fn();
  render(<DesignViewV2Editor view={view} doc={doc} onDocChange={changed} onGoToSection={vi.fn()}
    sectionId="fabric" onSectionChange={vi.fn()} projectId="p" />);
  await loaded();
  const input = screen.getByLabelText('Link width (bits)') as HTMLInputElement;
  expect(input.value).toBe('128');
  fireEvent.change(input, { target: { value: '64' } });
  expect(changed.mock.calls[0][0].noc_controls.link_width).toBe(64);
  expect(changed.mock.calls[0][0]).not.toHaveProperty('noc_config');
});

it('keeps address-map controls read-only until PF-D1', () => {
  const view: DesignViewV2 = {
    contract_version: 2, presentation: 'edit', draft_identity: { project_id: 'p', draft_design_hash: null },
    parent_revision_ref: null, readiness: 'READY', derived_summaries: [], validation_findings: [],
    capability_consequences: [], capability_semantics_version: '1',
    registry_versions: { capability_semantics_version: '1', capability_registry_version: 1, exposure_registry_version: 1 },
    completeness: { active_scientific_fields: [], represented_fields: [], non_active_fields: [],
      unrepresented_active_fields: [], invariant_holds: true, law: '' },
    sections: [{ id: 'memory_addressing', title: 'Memory Addressing', advanced_active_count: 0,
      blocking_count: 0, limitation_count: 0, entries: [] }],
  };
  const changed = vi.fn();
  render(<DesignViewV2Editor view={view}
    doc={{ ...doc, address_map: { ranges: [{ name: 'hbm', base: 0, size: 4096, target_agent_idx: 1 }] } }}
    onDocChange={changed} onGoToSection={vi.fn()} sectionId="memory_addressing"
    onSectionChange={vi.fn()} projectId="p" />);
  expect(screen.queryByLabelText('Range name')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Add range' })).toBeNull();
  expect(changed).not.toHaveBeenCalled();
});
