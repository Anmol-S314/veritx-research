import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { useGraphStore } from '../graph/store';
import GraphLoom from '../pages/loom/GraphLoom';
import { GraphStatus } from '../pages/loom/authoring';
import type { ReactElement } from 'react';

const v5Draft: Record<string, unknown> = {
  schema_version: 5,
  compiler_semantics_version: 5,
  base_v4: {
    schema_version: 4,
    compiler_semantics_version: 4,
    agents: [{ kind: 'compute_tile', count: 2, data_width: 128, addr_width: 40, protocol: 'CHI' }],
    topology: { kind: 'mesh', side_length: 2, concentration: 1 },
    noc_controls: { allocator_iterations: 3 },
    address_map: { ranges: [{ base: 4096, size: 4096, target_agent_idx: 0 }] },
  },
  agent_intents: [{ agent_group_index: 0, transaction_clock_domain: 'core' }],
  access_policy: { rules: [{ permission: 'DENY' }] },
  migration_provenance: { source: 'authored-test', preserved: true },
};

function StatusEditor(): ReactElement {
  const store = useGraphStore('ring-8', 'graph-apply-contract');
  return <GraphStatus store={store} projectId="project-1" draftRequest={v5Draft} />;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('graph apply contract', () => {
  it('saves the V5 graph topology and preserves its canonical root intent', async () => {
    const putDraft = vi.spyOn(api, 'putDraft').mockResolvedValue({
      contract_version: 1, project_id: 'project-1', design_hash: 'saved-hash',
      dirty: true, workload_id: null, source: null, updated_at: null,
      active_revision_id: null, latest_attempt_revision_id: null, request: null,
    });
    localStorage.clear();
    render(<GraphLoom projectId="project-1" draftRequest={v5Draft} />);

    const save = screen.getByRole('button', { name: 'save to draft' });
    expect((save as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(save);
    await screen.findByText(/Draft saved · design/);
    const submitted = putDraft.mock.calls[0][1];
    expect(submitted.schema_version).toBe(5);
    expect((submitted.base_v4 as Record<string, unknown>).topology)
      .toMatchObject({ kind: 'explicit', graph: { kind: 'custom', nodes: 64 } });
    expect(submitted.agent_intents).toEqual(v5Draft.agent_intents);
    expect(submitted.access_policy).toEqual(v5Draft.access_policy);
    expect(submitted.migration_provenance).toEqual(v5Draft.migration_provenance);
  });

  it('saves then submits the V4 topology to compile', async () => {
    vi.spyOn(api, 'putDraft').mockResolvedValue({
      contract_version: 1, project_id: 'project-1', design_hash: 'saved-hash',
      dirty: true, workload_id: null, source: null, updated_at: null,
      active_revision_id: null, latest_attempt_revision_id: null, request: null,
    });
    const compileJob = vi.spyOn(api, 'compileJob').mockResolvedValue({
      contract_version: 1, job_id: 'compile-1', project_id: 'project-1', kind: 'COMPILE',
      state: 'QUEUED', revision_id: null, submitted_at: '', updated_at: '',
      error_code: null, error_message: null, result: null,
    });
    vi.spyOn(api, 'job').mockResolvedValue({
      contract_version: 1, job_id: 'compile-1', project_id: 'project-1', kind: 'COMPILE',
      state: 'COMPLETED', revision_id: null, submitted_at: '', updated_at: '',
      error_code: null, error_message: null, result: null,
    });
    const v4 = { ...v5Draft.base_v4 as Record<string, unknown> };
    render(<GraphLoom projectId="project-1" draftRequest={v4} />);
    fireEvent.click(screen.getByRole('button', { name: 'save + compile' }));
    await waitFor(() => expect(compileJob).toHaveBeenCalledWith('project-1', 'saved-hash'));
    await screen.findByText('Draft saved · compile COMPLETED', {}, { timeout: 3000 });
  });

  it('recovers only the current project’s local graph after switching projects', () => {
    const a = renderHook(() => useGraphStore('ring-8', 'project-a'));
    const original = a.result.current.doc.nodes[0];
    act(() => { expect(a.result.current.run({
      type: 'move_node', id: original.id, x: 999, y: 999,
    })).toBeNull(); });
    expect(a.result.current.doc.nodes[0].x).toBe(999);
    a.unmount();

    const b = renderHook(() => useGraphStore('ring-8', 'project-b'));
    expect(b.result.current.doc.nodes[0].x).toBe(original.x);
    b.unmount();

    const restored = renderHook(() => useGraphStore('ring-8', 'project-a'));
    expect(restored.result.current.doc.nodes[0].x).toBe(999);
  });

  it('applies the topology from GraphStatus without replacing the V5 root', async () => {
    vi.spyOn(api, 'projectJobs').mockResolvedValue({ contract_version: 1, jobs: [] });
    vi.spyOn(api, 'fabricPresets').mockResolvedValue({ contract_version: 1, presets: [] });
    const putDraft = vi.spyOn(api, 'putDraft').mockResolvedValue({
      contract_version: 1, project_id: 'project-1', design_hash: 'saved-hash',
      dirty: true, workload_id: null, source: null, updated_at: null,
      active_revision_id: null, latest_attempt_revision_id: null, request: null,
    });
    render(<StatusEditor />);

    const save = screen.getByRole('button', { name: 'Apply graph to draft' });
    expect((save as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(putDraft).toHaveBeenCalled());
    const submitted = putDraft.mock.calls[0][1];
    expect((submitted.base_v4 as Record<string, unknown>).topology)
      .toMatchObject({ kind: 'explicit', graph: { kind: 'custom' } });
    expect(submitted.agent_intents).toEqual(v5Draft.agent_intents);
    expect(submitted.access_policy).toEqual(v5Draft.access_policy);
  });
});
