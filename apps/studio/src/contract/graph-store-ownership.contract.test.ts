import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useGraphStore } from '../graph/store';

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('project-scoped graph store ownership', () => {
  it('shares one live document and history between consumers in a project scope', () => {
    const a = renderHook(() => useGraphStore('ring-8', 'owner-shared'));
    const b = renderHook(() => useGraphStore('mesh-4x4', 'owner-shared'));
    const before = JSON.stringify(a.result.current.doc);
    const node = a.result.current.doc.nodes[0];
    act(() => { a.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    expect(b.result.current.doc.nodes[0]).toMatchObject({ id: node.id, x: 777, y: 888 });
    act(() => { b.result.current.undo(); });
    expect(JSON.stringify(a.result.current.doc)).toBe(before);
    expect(b.result.current.canUndo).toBe(false);
    act(() => { a.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, cancelable: true });
    act(() => { window.dispatchEvent(event); });
    expect(event.defaultPrevented).toBe(true);
    expect(JSON.stringify(a.result.current.doc)).toBe(before);
    expect(a.result.current.canUndo).toBe(false);
  });

  it('isolates project histories and handles one keyboard undo for the active scope', () => {
    const a = renderHook(() => useGraphStore('ring-8', 'owner-key-a'));
    const node = a.result.current.doc.nodes[0];
    act(() => { a.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    const b = renderHook(() => useGraphStore('ring-8', 'owner-key-b'));
    expect(b.result.current.doc.nodes[0].x).toBe(node.x);
    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
    act(() => { window.dispatchEvent(event); });
    expect(event.defaultPrevented).toBe(false);
    expect(a.result.current.doc.nodes[0].x).toBe(777);
    b.unmount();
    act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, cancelable: true })); });
    expect(a.result.current.doc.nodes[0].x).toBe(node.x);
    expect(b.result.current.doc.nodes[0].x).toBe(node.x);
  });

  it('keeps delayed callbacks scoped across project switches and remounts', () => {
    vi.useFakeTimers();
    const a = renderHook(() => useGraphStore('ring-8', 'owner-delay-a'));
    const node = a.result.current.doc.nodes[0];
    act(() => { a.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    a.unmount();
    const b = renderHook(() => useGraphStore('ring-8', 'owner-delay-b'));
    const bText = b.result.current.serialize();
    b.unmount();
    const restoredA = renderHook(() => useGraphStore('ring-8', 'owner-delay-a'));
    act(() => { vi.advanceTimersByTime(500); });
    expect(restoredA.result.current.doc.nodes[0]).toMatchObject({ id: node.id, x: 777, y: 888 });
    expect(JSON.parse(localStorage.getItem('loom-graph-autosave-v1:owner-delay-a')!).nodes[0].x).toBe(777);
    expect(localStorage.getItem('loom-graph-autosave-v1:owner-delay-b')).toBeNull();
    expect(JSON.parse(bText).nodes[0].x).toBe(node.x);
  });

  it('keeps recovery data and dirty status when immediate persistence fails; export is inert', () => {
    const scope = 'owner-failure';
    const key = `loom-graph-autosave-v1:${scope}`;
    const mount = renderHook(() => useGraphStore('ring-8', scope));
    const recoveryBefore = localStorage.getItem(key);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    const node = mount.result.current.doc.nodes[0];
    act(() => { mount.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    expect(mount.result.current.dirty).toBe(true);
    expect(mount.result.current.error).toMatch(/Could not save graph recovery data: quota/);
    expect(localStorage.getItem(key)).toBe(recoveryBefore);
    const exported = mount.result.current.serialize();
    expect(JSON.parse(exported).nodes[0]).toMatchObject({ id: node.id, x: 777, y: 888 });
    expect(mount.result.current.dirty).toBe(true);
    expect(localStorage.getItem(key)).toBe(recoveryBefore);
  });

  it('retries a failed immediate write after one of two consumers unmounts', () => {
    vi.useFakeTimers();
    const scope = 'owner-retry-survivor';
    const key = `loom-graph-autosave-v1:${scope}`;
    const first = renderHook(() => useGraphStore('ring-8', scope));
    const node = first.result.current.doc.nodes[0];
    act(() => { first.result.current.run({ type: 'move_node', id: node.id, x: 111, y: 222 }); });
    act(() => { vi.advanceTimersByTime(500); });
    const lastGood = localStorage.getItem(key);
    expect(lastGood).not.toBeNull();
    const second = renderHook(() => useGraphStore('mesh-4x4', scope));

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('temporary quota'); });
    act(() => { first.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    expect(first.result.current.dirty).toBe(true);
    expect(first.result.current.error).toMatch(/temporary quota/);
    expect(localStorage.getItem(key)).toBe(lastGood);

    first.unmount();
    setItem.mockRestore();
    act(() => { vi.advanceTimersByTime(500); });
    expect(localStorage.getItem(key)).not.toBe(lastGood);
    expect(JSON.parse(localStorage.getItem(key)!).nodes[0]).toMatchObject({ id: node.id, x: 777, y: 888 });
    expect(second.result.current.dirty).toBe(false);
    expect(second.result.current.error).toBeNull();
  });

  it('publishes a refusal error when the graph document is unchanged', () => {
    const mount = renderHook(() => useGraphStore('ring-8', 'owner-refusal-error'));
    const docBefore = mount.result.current.doc;
    act(() => {
      expect(mount.result.current.run({ type: 'move_node', id: 'missing-node', x: 1, y: 2 }))
        .toMatch(/unknown node missing-node/);
    });
    expect(mount.result.current.doc).toBe(docBefore);
    expect(mount.result.current.error).toEqual('unknown node missing-node');
  });

  it('does not clear dirty state when a delayed write fails', () => {
    vi.useFakeTimers();
    const scope = 'owner-delayed-failure';
    const mount = renderHook(() => useGraphStore('ring-8', scope));
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    const node = mount.result.current.doc.nodes[0];
    act(() => { mount.result.current.run({ type: 'move_node', id: node.id, x: 777, y: 888 }); });
    act(() => { vi.advanceTimersByTime(500); });
    expect(mount.result.current.dirty).toBe(true);
    expect(mount.result.current.error).toMatch(/blocked/);
  });
});
