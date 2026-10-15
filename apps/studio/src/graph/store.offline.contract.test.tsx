import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useGraphStore } from './store';

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('local graph editing without network access', () => {
  it('validates, edits, serializes, and reloads a graph without fetch', () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    const first = renderHook(() => useGraphStore('mesh-4x4', 'offline-source'));
    const originalNode = first.result.current.doc.nodes[0];

    act(() => {
      expect(first.result.current.run({
        type: 'move_node', id: originalNode.id, x: originalNode.x + 12, y: originalNode.y + 8,
      })).toBeNull();
    });
    // HEAD store persists eagerly, so a successful edit is immediately saved.
    expect(first.result.current.dirty).toBe(false);

    const saved = first.result.current.serialize();
    expect(saved).toContain('"schemaVersion": 1');
    const second = renderHook(() => useGraphStore('ring-8', 'offline-target'));
    act(() => {
      expect(second.result.current.loadJson(saved)).toBeNull();
    });

    expect(second.result.current.doc).toEqual(first.result.current.doc);
    expect(second.result.current.dirty).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
    first.unmount();
    second.unmount();
  });

  it('rejects an invalid project before mutating the open graph', () => {
    const store = renderHook(() => useGraphStore('mesh-4x4', 'invalid-open'));
    const before = structuredClone(store.result.current.doc);
    let error: string | null = null;
    act(() => { error = store.result.current.loadJson('{"schemaVersion":99}'); });
    expect(error).toMatch(/schemaVersion/);
    expect(store.result.current.doc).toEqual(before);
    store.unmount();
  });

  it('surfaces autosave storage failure without pretending the edit was saved', () => {
    const store = renderHook(() => useGraphStore('mesh-4x4', 'quota-failure'));
    const node = store.result.current.doc.nodes[0];
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota exceeded'); });
    act(() => {
      expect(store.result.current.run({ type: 'move_node', id: node.id, x: node.x + 3, y: node.y })).toBeNull();
    });
    expect(store.result.current.doc.nodes.find(item => item.id === node.id)?.x).toBe(node.x + 3);
    expect(store.result.current.error).toMatch(/Could not save graph recovery data.*quota exceeded/);
    store.unmount();
  });

  it('keeps one latest autosave snapshot for the project scope', () => {
    const key = 'loom-graph-autosave-v1:autosave-bound';
    const store = renderHook(() => useGraphStore('mesh-4x4', 'autosave-bound'));
    const node = store.result.current.doc.nodes[0];
    act(() => {
      expect(store.result.current.run({ type: 'move_node', id: node.id, x: node.x + 1, y: node.y })).toBeNull();
      expect(store.result.current.run({ type: 'move_node', id: node.id, x: node.x + 2, y: node.y })).toBeNull();
    });
    expect(Object.keys(localStorage).filter(item => item.startsWith('loom-graph-autosave-v1:'))).toEqual([key]);
    const snapshot = JSON.parse(localStorage.getItem(key) ?? 'null') as { nodes: { id: string; x: number }[] };
    expect(snapshot.nodes.find(item => item.id === node.id)?.x).toBe(node.x + 2);
    store.unmount();
  });
});
