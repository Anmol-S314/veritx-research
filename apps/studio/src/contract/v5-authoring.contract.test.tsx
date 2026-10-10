import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, type DesignViewV2 } from '../api';
import { baseDocument, editableDocument, withBaseDocument, assertExactJsonNumbers } from '../canonicalDraft';
import { applyCommand, DraftHistory } from '../pages/loom/draftCommands';
import { useDraftStore } from '../pages/loom/draftStore';
import { readAgents } from '../pages/loom/data';
import DesignViewV2Editor from '../components/DesignViewV2Editor';
import V5Declarations from '../components/V5Declarations';
import AbstractExperiment from '../components/AbstractExperiment';

const root = (): Record<string, unknown> => ({
  schema_version: 5, compiler_semantics_version: 5, design_hash: 'computed-root',
  base_v4: { schema_version: 4, design_hash: 'computed-base', guardrail_hash: 'computed-base',
    agents: [{ kind: 'compute_tile', count: 2, data_width: 64, addr_width: 64, protocol: 'AXI' }],
    workload: { tp: 1 }, requirements: [], topology: { kind: 'mesh', side_length: 2, concentration: 1 },
    noc_controls: { link_width: 64 } },
  agent_intents: [{ agent_group_index: 0, transaction_clock_domain: 'core' }],
  clock_sources: [{ id: 'pll', kind: 'PLL', frequency_hz: 1000000000 }],
  clock_domains: [{ id: 'core', source_id: 'pll', frequency_hz: 1000000000 }],
  crossings: [], reset_channels: [{ id: 'reset', retained: true }], power_domains: [],
  sideband_interfaces: [{ id: 'intent-only' }], sideband_connections: [], access_policy: null,
  migration_provenance: { source: 'owner declaration' },
});
const serverDraft = (request: Record<string, unknown>) => ({
  contract_version: 1 as const, project_id: 'p', workload_id: null, source: 'test', updated_at: 'now',
  design_hash: 'server-root', dirty: true, active_revision_id: null, latest_attempt_revision_id: null, request,
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('reads nested base agents and preserves all extensions with exact command inverse/undo/redo', () => {
  const doc = root();
  expect(readAgents(doc)[0].count).toBe(2);
  for (const value of ['new-clock', null]) {
    const outcome = applyCommand(doc, { type: 'set_agent_field', group: 0, field: 'clock_domain', value });
    expect(outcome.refused).toBeNull();
    expect(baseDocument(outcome.doc).agents).toEqual([{ ...(baseDocument(doc).agents as object[])[0], clock_domain: value }]);
    for (const key of Object.keys(doc).filter(k => k !== 'base_v4')) expect(outcome.doc[key]).toBe(doc[key]);
    const inverted = applyCommand(outcome.doc, outcome.inverse!);
    expect(inverted.refused).toBeNull();
    expect(JSON.stringify(inverted.doc)).toBe(JSON.stringify(doc));
    const history = new DraftHistory(doc);
    history.apply({ type: 'set_agent_field', group: 0, field: 'clock_domain', value });
    const edited = history.current();
    expect(history.undo()).toBe(doc);
    expect(history.redo()).toBe(edited);
  }
});

it('retains explicit null, rejects group deletion and refuses out-of-range immutable group indexes', () => {
  const doc = root();
  const base = baseDocument(doc);
  base.agents = [{ ...(base.agents as object[])[0], clock_domain: null }];
  const out = applyCommand(doc, { type: 'set_agent_field', group: 0, field: 'clock_domain', value: 'core' });
  expect(applyCommand(out.doc, out.inverse!).doc).toEqual(doc);
  expect(() => withBaseDocument(doc, { ...base, agents: [] })).toThrow(/cannot be added, removed or remapped/);
  expect(applyCommand(doc, { type: 'set_agent_kind', group: 7, value: 'nic' }).doc).toBe(doc);
});

it('saves full V5 root and strips only computed root/base hashes on explicit edit serialization', async () => {
  const doc = root();
  const put = vi.spyOn(api, 'putDraft').mockImplementation(async (_pid, request) => serverDraft(request));
  const { result } = renderHook(() => useDraftStore('p'));
  act(() => result.current.load(doc));
  act(() => result.current.run({ type: 'set_agent_field', group: 0, field: 'count', value: 3 }));
  await act(async () => { expect(await result.current.save()).toBe(true); });
  const submitted = put.mock.calls[0][1];
  expect(submitted).not.toHaveProperty('design_hash');
  expect(submitted.base_v4).not.toHaveProperty('design_hash');
  expect(submitted.base_v4).not.toHaveProperty('guardrail_hash');
  for (const key of Object.keys(doc).filter(k => !['base_v4', 'design_hash'].includes(k))) expect(submitted[key]).toBe(doc[key]);
  expect(doc.design_hash).toBe('computed-root');
  expect(result.current.dirty).toBe(false);
});

it('edits one explicit declaration only and retains migration/stage-unsupported records', () => {
  const doc = root(); const change = vi.fn();
  render(<V5Declarations doc={doc} onChange={change} />);
  fireEvent.change(screen.getByLabelText('crossings'), { target: { value: '[{"explicit":"pending server validation"}]' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply crossings declaration' }));
  const next = change.mock.calls[0][0];
  expect(next.crossings).toEqual([{ explicit: 'pending server validation' }]);
  expect(next.reset_channels).toBe(doc.reset_channels);
  expect(next.migration_provenance).toBe(doc.migration_provenance);
  expect(next).toEqual(editableDocument({ ...doc, crossings: next.crossings }));
  expect(screen.getAllByText(/refuses at COMPOSE/).length).toBe(2);
});

it('rejects malformed declaration JSON and unsafe integers without publishing edits', () => {
  const change = vi.fn(); render(<V5Declarations doc={root()} onChange={change} />);
  for (const value of ['{', '{"wrong":"object"}', '[9007199254740993]',
    '[{"id":"pll","frequency_hz":1000000000.00000001}]',
    '[{"id":"pll","frequency_hz":1.0000000000000001}]',
    '[{"id":"pll","frequency_hz":1,"frequency_hz":2}]']) {
    fireEvent.change(screen.getByLabelText('clock_sources'), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply clock_sources declaration' }));
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(change).not.toHaveBeenCalled();
  }
  expect(() => assertExactJsonNumbers({ nested: [Number.MAX_SAFE_INTEGER + 1] })).toThrow(/exact JavaScript range/);
});

const view: DesignViewV2 = {
  contract_version: 2, presentation: 'edit', draft_identity: { project_id: 'p', draft_design_hash: 'root' },
  parent_revision_ref: null, readiness: 'VALIDATED_DECLARATION', derived_summaries: [], validation_findings: [],
  capability_consequences: [], capability_semantics_version: '1',
  registry_versions: { capability_semantics_version: '1', capability_registry_version: 1, exposure_registry_version: 1 },
  completeness: { active_scientific_fields: [], represented_fields: [], non_active_fields: [], unrepresented_active_fields: [], invariant_holds: true, law: '' },
  sections: [{ id: 'agents', title: 'Agents', advanced_active_count: 0, blocking_count: 0, limitation_count: 0,
    entries: [{ field: 'Agent.count', label: 'Count', value: [2], semantic_class: 'DECLARED', exposure_class: '',
      disclosure_depth: 'GUIDED', source: null, active: true, capability_ref: null,
      ownership: { domain: 'SYSTEM', canonical_field: 'base_v4.Agent.count', scientific_name: null } }] }],
};
it('uses existing agent controls through a root-preserving lens and disables group identity changes', () => {
  const doc = root(); const change = vi.fn();
  render(<DesignViewV2Editor view={view} doc={doc} onDocChange={change} onGoToSection={vi.fn()}
    sectionId="agents" onSectionChange={vi.fn()} projectId="p" />);
  expect((screen.getByRole('button', { name: 'Remove agent group' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole('button', { name: 'Add agent group' })).toBeNull();
  fireEvent.change(screen.getByLabelText('Instance count'), { target: { value: '4' } });
  const next = change.mock.calls[0][0];
  expect((baseDocument(next).agents as Record<string, unknown>[])[0].count).toBe(4);
  expect(next.agent_intents).toBe(doc.agent_intents);
  expect(next.sideband_interfaces).toBe(doc.sideband_interfaces);
  expect(screen.getByText(/Generic evaluation unsupported/)).toBeTruthy();
});

it('requires explicit workload/placement and reports dedicated unqualified evidence, never native metrics', async () => {
  const call = vi.spyOn(api, 'abstractExperiment').mockResolvedValue({ status: 'DIAGNOSTIC_ABSTRACT', qualification: false });
  render(<AbstractExperiment projectId="p" revisionId="r" />);
  const run = screen.getByRole('button', { name: 'Run explicit abstract experiment' }) as HTMLButtonElement;
  expect(run.disabled).toBe(true);
  expect(call).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Explicit workload JSON'), { target: { value: '{"design_hash":"explicit"}' } });
  fireEvent.change(screen.getByLabelText('Explicit placement JSON'), { target: { value: '{"resource_graph_id":"explicit"}' } });
  fireEvent.click(run);
  await waitFor(() => expect(call).toHaveBeenCalledWith('p', 'r', { profile: 'ABSTRACT_DATA_MOVEMENT_V1',
    workload: { design_hash: 'explicit' }, placement: { resource_graph_id: 'explicit' } }));
  await waitFor(() => expect(screen.getByText(/DIAGNOSTIC_ABSTRACT · unqualified/)).toBeTruthy());
});

it.each([
  ['Explicit workload JSON', '{"operations":[{"service_cycles":1.0000000000000001}]}'],
  ['Explicit workload JSON', '{"operations":[{"service_cycles":1000000000.00000001}]}'],
  ['Explicit workload JSON', '{"operations":[],"operations":[{}]}'],
  ['Explicit placement JSON', '{"routers":[1.0000000000000001]}'],
  ['Explicit placement JSON', '{"resource_graph_id":"a","resource_graph_id":"b"}'],
])('refuses lossy or duplicate explicit experiment input in %s', async (field, text) => {
  const call = vi.spyOn(api, 'abstractExperiment').mockResolvedValue({ status: 'DIAGNOSTIC_ABSTRACT' });
  render(<AbstractExperiment projectId="p" revisionId="r" />);
  fireEvent.change(screen.getByLabelText('Explicit workload JSON'), { target: { value: '{}' } });
  fireEvent.change(screen.getByLabelText('Explicit placement JSON'), { target: { value: '{}' } });
  fireEvent.change(screen.getByLabelText(field), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Run explicit abstract experiment' }));
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  expect(call).not.toHaveBeenCalled();
  expect(screen.queryByText(/DIAGNOSTIC_ABSTRACT · unqualified/)).toBeNull();
});

it('does not publish an async response as evidence for a different revision', async () => {
  let resolve!: (value: Record<string, unknown>) => void;
  vi.spyOn(api, 'abstractExperiment').mockImplementation(() => new Promise(done => { resolve = done; }));
  const rendered = render(<AbstractExperiment projectId="p" revisionId="r1" />);
  fireEvent.change(screen.getByLabelText('Explicit workload JSON'), { target: { value: '{}' } });
  fireEvent.change(screen.getByLabelText('Explicit placement JSON'), { target: { value: '{}' } });
  fireEvent.click(screen.getByRole('button', { name: 'Run explicit abstract experiment' }));
  rendered.rerender(<AbstractExperiment projectId="p" revisionId="r2" />);
  await act(async () => resolve({ status: 'FOREIGN' }));
  expect(screen.queryByText(/DIAGNOSTIC_ABSTRACT · unqualified/)).toBeNull();
});

it('invalidates only the edited access policy hash, not untouched extension identities', () => {
  const doc: Record<string, unknown> = { ...root(), access_policy: { type: 'access-policy', rules: [], policy_hash: 'old' } };
  const changed = vi.fn(); render(<V5Declarations doc={doc} onChange={changed} />);
  fireEvent.change(screen.getByLabelText('access_policy'), { target: { value: '{"type":"access-policy","rules":[{"authored":true}],"policy_hash":"old"}' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply access_policy declaration' }));
  expect(changed.mock.calls[0][0].access_policy).not.toHaveProperty('policy_hash');
  expect(changed.mock.calls[0][0].sideband_interfaces).toBe(doc.sideband_interfaces);
});

it('refuses any V5 command on unsafe loaded integers without changing the working copy', () => {
  const doc = { ...root(), migration_provenance: { exact_integer: Number.MAX_SAFE_INTEGER + 1 } };
  const out = applyCommand(doc, { type: 'set_agent_field', group: 0, field: 'count', value: 3 });
  expect(out.doc).toBe(doc);
  expect(out.refused).toMatch(/exact JavaScript range/);
});
