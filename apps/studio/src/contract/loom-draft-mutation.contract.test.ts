/** Contract tests for the draft mutation seam (program §56–§57).
 *
 * These pin the behaviours that keep Loom honest while it edits:
 *  - a command touches only the seven canonical agent fields (+kind);
 *  - refusals are returned as reasons, never silent no-ops;
 *  - every applied command has an exact inverse (undo byte-equality);
 *  - identity: commands never reorder or renumber the agents array;
 *  - undo/redo stacks move documents, and a refusal does not pollute them.
 */
import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import { api } from '../api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  applyCommand, DraftHistory, type DraftCommand,
} from '../pages/loom/draftCommands';
import {
  useDraftStore, useServerDraftSync,
} from '../pages/loom/draftStore';

const serverDraft = (request: Record<string, unknown>) => ({
  contract_version: 1 as const,
  project_id: 'p1',
  workload_id: null,
  source: 'authored',
  updated_at: 'now',
  design_hash: 'hash',
  dirty: true,
  active_revision_id: null,
  latest_attempt_revision_id: null,
  request,
});

afterEach(() => vi.restoreAllMocks());

const DOC = (): Record<string, unknown> => ({
  schema_version: 4,
  workload: { model_family: 'dense' },
  agents: [
    { kind: 'compute_tile', count: 4, data_width: 256, addr_width: 64,
      protocol: 'AXI', clock_domain: null, power_domain: null },
    { kind: 'hbm_controller', count: 1, data_width: 256, addr_width: 64,
      protocol: 'AXI', clock_domain: 'clk_mem', power_domain: 'pd_1' },
  ],
  topology: { kind: 'mesh', side_length: 4, concentration: 1 },
});

describe('applyCommand writes only canonical fields', () => {
  it('sets a declared field and inverts exactly', () => {
    const doc = DOC();
    const out = applyCommand(doc, {
      type: 'set_agent_field', group: 0, field: 'clock_domain',
      value: 'clk_core',
    });
    expect(out.refused).toBeNull();
    const written = (out.doc.agents as Record<string, unknown>[])[0];
    expect(written.clock_domain).toBe('clk_core');
    // inverse restores byte-equality of the whole document
    expect(out.inverse).not.toBeNull();
    const back = applyCommand(out.doc, out.inverse as DraftCommand);
    expect(back.refused).toBeNull();
    expect(JSON.stringify(back.doc)).toBe(JSON.stringify(doc));
  });

  it('leaves every other part of the document untouched by reference-equal values', () => {
    const doc = DOC();
    const out = applyCommand(doc, {
      type: 'set_agent_field', group: 1, field: 'count', value: 2,
    });
    expect(out.refused).toBeNull();
    expect(out.doc.topology).toBe(doc.topology); // structural copy on write
    expect(out.doc.workload).toBe(doc.workload);
  });

  it('never reorders or renumbers the agents array', () => {
    const doc = DOC();
    const out = applyCommand(doc, {
      type: 'set_agent_field', group: 1, field: 'protocol', value: 'CHI',
    });
    const agents = out.doc.agents as Record<string, unknown>[];
    expect(agents).toHaveLength(2);
    expect(agents[0].kind).toBe('compute_tile');
    expect(agents[1].kind).toBe('hbm_controller');
  });
});

describe('topology editing writes only supported v2/v3 controls', () => {
  it('changes an explicitly declared mesh parameter and restores null exactly', () => {
    const doc = { ...DOC(), schema_version: 2, noc_config: {
      topology_family: 'mesh', radix: null, concentration: null,
    } };
    const out = applyCommand(doc, {
      type: 'set_topology_field', field: 'radix', value: 4,
    });
    expect(out.refused).toBeNull();
    expect((out.doc.noc_config as Record<string, unknown>).radix).toBe(4);
    const back = applyCommand(out.doc, out.inverse as DraftCommand);
    expect(back.refused).toBeNull();
    expect(JSON.stringify(back.doc)).toBe(JSON.stringify(doc));
  });

  it('refuses v4 and unsupported topology families without writing', () => {
    const v4 = { ...DOC(), schema_version: 4, topology: { kind: 'mesh' } };
    const v4out = applyCommand(v4, {
      type: 'set_topology_field', field: 'radix', value: 4,
    });
    expect(v4out.refused).toMatch(/v2\/v3/);
    expect(v4out.doc).toBe(v4);

    const other = { ...DOC(), schema_version: 2, noc_config: {
      topology_family: 'dragonfly', radix: null, concentration: null,
    } };
    const otherOut = applyCommand(other, {
      type: 'set_topology_field', field: 'radix', value: 4,
    });
    expect(otherOut.refused).toMatch(/only for mesh/);
    expect(otherOut.doc).toBe(other);
  });
});

describe('refusals carry reasons and write nothing', () => {
  it('refuses an unknown field at runtime casts', () => {
    const doc = DOC();
    const evil = {
      type: 'set_agent_field', group: 0,
      field: 'max_outstanding', value: 64,
    } as unknown as DraftCommand;
    const out = applyCommand(doc, evil);
    expect(out.refused).toMatch(/not one of the seven/);
    expect(out.doc).toBe(doc);
    expect(out.inverse).toBeNull();
  });

  it('refuses a group that does not exist', () => {
    const doc = DOC();
    const out = applyCommand(doc, {
      type: 'set_agent_field', group: 5, field: 'count', value: 2,
    });
    expect(out.refused).toMatch(/no agent group 5/);
    expect(out.doc).toBe(doc);
  });

  it('refuses an illegal count rather than writing it', () => {
    const doc = DOC();
    for (const value of [0, -1, 2.5, '4' as unknown as number]) {
      const out = applyCommand(doc, {
        type: 'set_agent_field', group: 0, field: 'count', value,
      });
      expect(out.refused).toMatch(/positive integer/);
      expect(out.doc).toBe(doc);
    }
  });

  it('refuses a no-op command instead of stacking history noise', () => {
    const doc = DOC();
    const out = applyCommand(doc, {
      type: 'set_agent_field', group: 0, field: 'protocol', value: 'AXI',
    });
    expect(out.refused).toMatch(/already carries/);
    expect(out.doc).toBe(doc);
  });

  it('refuses an empty document without agents', () => {
    const out = applyCommand({ schema_version: 4 }, {
      type: 'set_agent_field', group: 0, field: 'count', value: 2,
    });
    expect(out.refused).toMatch(/no agents block/);
  });
});

describe('DraftStore re-anchors the exact submitted snapshot', () => {
  it('keeps edits made while the save request is in flight dirty', async () => {
    let finish!: (saved: Awaited<ReturnType<typeof api.putDraft>>) => void;
    const response = new Promise<Awaited<ReturnType<typeof api.putDraft>>>(
      (resolve) => { finish = resolve; },
    );
    const put = vi.spyOn(api, 'putDraft').mockReturnValue(response);
    const { result } = renderHook(() => useDraftStore('p1'));
    const initial = DOC();
    act(() => result.current.load(initial));

    let saving!: Promise<boolean>;
    act(() => { saving = result.current.save(); });
    const submitted = put.mock.calls[0][1];
    expect(submitted).toBe(initial);

    act(() => {
      result.current.run({
        type: 'set_agent_field', group: 0, field: 'count', value: 8,
      });
    });
    expect(result.current.dirty).toBe(true);

    await act(async () => {
      finish(serverDraft(submitted));
      expect(await saving).toBe(true);
    });

    expect((result.current.doc?.agents as Record<string, unknown>[])[0].count)
      .toBe(8);
    expect(result.current.dirty).toBe(true);
    expect(result.current.canUndo).toBe(true);
  });

  it('adopts the server-canonical document when no later edits exist', async () => {
    const local = DOC();
    const canonical = { ...local, design_hash: 'server-owned' };
    const put = vi.spyOn(api, 'putDraft')
      .mockResolvedValue(serverDraft(canonical));
    const { result } = renderHook(() => useDraftStore('p1'));
    act(() => result.current.load(local));
    act(() => {
      result.current.run({
        type: 'set_agent_field', group: 0, field: 'count', value: 8,
      });
    });

    await act(async () => { expect(await result.current.save()).toBe(true); });

    expect(put).toHaveBeenCalledOnce();
    expect(result.current.doc).toEqual(canonical);
    expect(result.current.dirty).toBe(false);
    expect(result.current.canUndo).toBe(false);
  });
});

describe('server draft refresh synchronization', () => {
  it('does not replace a saved draft with the stale pre-refresh query result', () => {
    const stale = { value: 'before-save' };
    const saved = { value: 'saved-locally' };
    const refreshed = { value: 'server-refreshed' };
    const { result, rerender } = renderHook((props: {
      source: string;
      serverDoc: Record<string, unknown>;
      dirty: boolean;
    }) => {
      const [doc, setDoc] = useState(props.serverDoc);
      useServerDraftSync(
        props.source, props.serverDoc, props.dirty, setDoc,
      );
      return { doc, setDoc };
    }, {
      initialProps: {
        source: 'p1:hash-before:time-before',
        serverDoc: stale,
        dirty: false,
      },
    });
    expect(result.current.doc).toEqual(stale);

    act(() => result.current.setDoc(saved));
    rerender({
      source: 'p1:hash-before:time-before', serverDoc: stale, dirty: true,
    });
    rerender({
      source: 'p1:hash-before:time-before', serverDoc: stale, dirty: false,
    });
    expect(result.current.doc).toEqual(saved);

    rerender({
      source: 'p1:hash-after:time-after', serverDoc: refreshed, dirty: false,
    });
    expect(result.current.doc).toEqual(refreshed);
  });
});

describe('DraftHistory moves documents on undo/redo', () => {
  it('undo restores the exact prior document; redo re-applies', () => {
    const doc = DOC();
    const h = new DraftHistory(doc);
    expect(h.current()).toBe(doc);

    h.apply({ type: 'set_agent_field', group: 0,
              field: 'clock_domain', value: 'clk_a' });
    const after1 = JSON.stringify(h.current());
    h.apply({ type: 'set_agent_field', group: 0,
              field: 'clock_domain', value: 'clk_b' });
    const after2 = JSON.stringify(h.current());
    expect(after1).not.toBe(after2);

    h.undo();
    expect(JSON.stringify(h.current())).toBe(after1);
    h.undo();
    expect(JSON.stringify(h.current())).toBe(JSON.stringify(doc));
    expect(h.canUndo()).toBe(false);

    h.redo();
    expect(JSON.stringify(h.current())).toBe(after1);
    h.redo();
    expect(JSON.stringify(h.current())).toBe(after2);
    expect(h.canRedo()).toBe(false);
  });

  it('a refused command does not enter history', () => {
    const h = new DraftHistory(DOC());
    const out = h.apply({
      type: 'set_agent_field', group: 9, field: 'count', value: 2,
    });
    expect(out.refused).not.toBeNull();
    expect(h.canUndo()).toBe(false);
  });

  it('a new command after undo clears the redo stack', () => {
    const h = new DraftHistory(DOC());
    h.apply({ type: 'set_agent_field', group: 0,
              field: 'count', value: 8 });
    h.undo();
    expect(h.canRedo()).toBe(true);
    h.apply({ type: 'set_agent_field', group: 0, field: 'addr_width',
              value: 32 });
    expect(h.canRedo()).toBe(false);
  });

  it('reset adopts a server document and drops stale stacks', () => {
    const h = new DraftHistory(DOC());
    h.apply({ type: 'set_agent_field', group: 0, field: 'count', value: 8 });
    const server = DOC();
    h.reset(server);
    expect(h.current()).toBe(server);
    expect(h.canUndo()).toBe(false);
    expect(h.canRedo()).toBe(false);
  });

  it('set_agent_kind inverts to the prior kind', () => {
    const doc = DOC();
    const out = applyCommand(doc, {
      type: 'set_agent_kind', group: 1, value: 'nic',
    });
    expect(out.refused).toBeNull();
    const back = applyCommand(out.doc, out.inverse as DraftCommand);
    expect(back.refused).toBeNull();
    expect(JSON.stringify(back.doc)).toBe(JSON.stringify(doc));
  });
});
