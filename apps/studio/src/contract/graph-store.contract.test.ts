import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useGraphStore } from '../graph/store';

afterEach(() => { cleanup(); localStorage.clear(); });

describe('Loom graph store mutations and derived selectors', () => {
  it('tracks preset/custom and dirty selectors across mutation, undo and redo', () => {
    const { result } = renderHook(() => useGraphStore('ring-8'));
    const initial = JSON.stringify(result.current.doc);
    expect(result.current.isCustom).toBe(false);
    expect(result.current.dirty).toBe(false);

    act(() => {
      expect(result.current.run({ type: 'update_node', id: 'n1', patch: { role: 'nic' } })).toBeNull();
    });
    expect(result.current.doc.nodes.find((n) => n.id === 'n1')?.role).toBe('nic');
    expect(result.current.isCustom).toBe(true);
    expect(result.current.dirty).toBe(true);
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(JSON.stringify(result.current.doc)).toBe(initial);
    expect(result.current.dirty).toBe(false);
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.redo());
    expect(result.current.doc.nodes.find((n) => n.id === 'n1')?.role).toBe('nic');
    expect(result.current.dirty).toBe(true);
  });

  it('keeps state and history unchanged when a mutation is refused', () => {
    const { result } = renderHook(() => useGraphStore('ring-8'));
    const initial = JSON.stringify(result.current.doc);

    act(() => {
      expect(result.current.run({ type: 'move_node', id: 'missing', x: 1, y: 2 })).toMatch(/unknown node/);
    });
    expect(JSON.stringify(result.current.doc)).toBe(initial);
    expect(result.current.dirty).toBe(false);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.error).toMatch(/unknown node/);
  });

  it('loads a valid serialized project as the clean current baseline', () => {
    const { result } = renderHook(() => useGraphStore('ring-8'));
    const project = { ...result.current.doc, presetHint: null, workload: { model: 'explicit-test' } };
    act(() => { expect(result.current.loadJson(JSON.stringify(project))).toBeNull(); });

    expect(result.current.doc.workload).toEqual({ model: 'explicit-test' });
    expect(result.current.isCustom).toBe(true);
    expect(result.current.dirty).toBe(false);
    expect(localStorage.getItem('loom-graph-autosave-v1:local')).toBe(JSON.stringify(project));
  });

  it('resets command history and dirty state when loading a preset', () => {
    const { result } = renderHook(() => useGraphStore('ring-8'));
    act(() => { result.current.run({ type: 'update_node', id: 'n1', patch: { role: 'nic' } }); });
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.loadPreset('mesh-4x4'));
    expect(result.current.doc.presetHint).toBe('mesh');
    expect(result.current.doc.nodes).toHaveLength(16);
    expect(result.current.isCustom).toBe(false);
    expect(result.current.dirty).toBe(false);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it('serializes the current document and marks that exact revision clean', () => {
    const { result } = renderHook(() => useGraphStore('ring-8'));
    act(() => { result.current.run({ type: 'update_node', id: 'n1', patch: { role: 'nic' } }); });

    let json = '';
    act(() => { json = result.current.serialize(); });
    expect(JSON.parse(json)).toEqual(result.current.doc);
    expect(result.current.dirty).toBe(false);
    expect(localStorage.getItem('loom-graph-autosave-v1:local')).toBeNull();
  });

  it('recovers the last saved browser autosave after store remount', () => {
    const first = renderHook(() => useGraphStore('ring-8'));
    act(() => { first.result.current.run({ type: 'update_node', id: 'n1', patch: { role: 'nic' } }); });
    const persisted = localStorage.getItem('loom-graph-autosave-v1:local');
    expect(persisted).not.toBeNull();
    first.unmount();

    const restored = renderHook(() => useGraphStore('ring-8'));
    expect(restored.result.current.doc.nodes.find((n) => n.id === 'n1')?.role).toBe('nic');
    expect(restored.result.current.dirty).toBe(false);
    expect(restored.result.current.canUndo).toBe(false);
  });
});
