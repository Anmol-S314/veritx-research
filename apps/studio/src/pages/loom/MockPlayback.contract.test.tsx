import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildPreset } from '../../graph/presets';
import type { GraphStore } from '../../graph/store';
import { SimPlayback } from './authoring';

afterEach(() => { cleanup(); vi.useRealTimers(); });
describe('mock trace playback controls', () => {
  it('keeps mock provenance and supports deterministic single-step and speed selection', () => {
    const doc = buildPreset('mesh-4x4');
    const store = { doc } as GraphStore;
    render(<SimPlayback store={store} />);
    expect(screen.getByText(/MOCK trace/)).toBeTruthy();
    expect(screen.getByText(/cycle 0/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Step' }));
    expect(screen.getByText(/cycle 100/)).toBeTruthy();
    const speed = screen.getByRole('combobox', { name: 'playback speed' }) as HTMLSelectElement;
    fireEvent.change(speed, { target: { value: '2' } });
    expect(speed.value).toBe('2');
    fireEvent.click(screen.getByRole('button', { name: 'Inspect congested edge e1' }));
    expect(screen.getByRole('region', { name: 'Edge metric inspector' })).toBeTruthy();
  });
  it('imports and plays an explicitly unverified user trace', async () => {
    const store = { doc: buildPreset('mesh-4x4') } as GraphStore;
    const view = render(<SimPlayback store={store} />);
    const edgeId = store.doc.edges[0].id;
    const nodeId = store.doc.nodes[0].id;
    const record = JSON.stringify({ cycle: 0, phase: 'external-phase', nodeLoad: { [nodeId]: 3 }, edgeUtil: { [edgeId]: 12 }, stalls: { [edgeId]: 0 } });
    const nextRecord = JSON.stringify({ cycle: 10, phase: 'next-phase', nodeLoad: { [nodeId]: 4 }, edgeUtil: { [edgeId]: 40 }, stalls: { [edgeId]: 1 } });
    const contents = `${record}\n${nextRecord}\n`;
    const file = new File([contents], 'external.jsonl');
    Object.defineProperty(file, 'stream', { value: () => new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new TextEncoder().encode(contents)); c.close(); } }) });
    fireEvent.change(screen.getByLabelText('Import trace JSONL'), { target: { files: [file] } });
    expect(await screen.findByText(/USER-PROVIDED TRACE/)).toBeTruthy();
    expect(screen.getByText(/producer\/backend provenance is not verified/)).toBeTruthy();
    expect(screen.getByText(/external-phase/)).toBeTruthy();
    expect(screen.getAllByText(/12 \(unit unverified\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/trace-wide auto scale 0–40 \(unit unverified\)/)).toBeTruthy();
    const missingEdgeId = store.doc.edges.find(edge => edge.id !== edgeId)!.id;
    const missingBar = screen.getByRole('button', { name: `Inspect edge ${missingEdgeId}` });
    expect(missingBar.querySelector('rect')).toBeNull();
    expect(missingBar.textContent).toContain('—');
    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '1' } });
    expect(screen.getByText(/cycle 10/)).toBeTruthy();
    expect(screen.getByText(/next-phase/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: `Inspect edge ${edgeId}` }));
    const edgeInspector = screen.getByRole('region', { name: 'Edge metric inspector' });
    expect(edgeInspector.textContent).toContain('current 40 (unit unverified)');
    fireEvent.change(screen.getByRole('combobox', { name: 'metric' }), { target: { value: 'stalls' } });
    expect(screen.getByText(/trace-wide auto scale 0–1 \(unit unverified\)/)).toBeTruthy();
    expect(edgeInspector.textContent).toContain('metric stalls');
    expect(edgeInspector.textContent).toContain('current 1 (unit unverified)');
    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '0' } });
    expect(edgeInspector.textContent).toContain('current 0 (unit unverified)');
    fireEvent.change(screen.getByRole('combobox', { name: 'metric' }), { target: { value: 'utilization' } });
    expect(edgeInspector.textContent).toContain('current 12 (unit unverified)');
    fireEvent.change(screen.getByRole('combobox', { name: 'metric scale' }), { target: { value: 'fixed' } });
    expect(screen.getByText(/fixed scale 0–100 \(unit unverified\)/)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: 'metric scale' }), { target: { value: 'auto' } });
    fireEvent.click(screen.getByRole('button', { name: `Inspect edge ${edgeId}` }));
    const inspector = screen.getByRole('region', { name: 'Edge metric inspector' });
    expect(inspector.textContent).toContain('current 12 (unit unverified)');
    expect(inspector.textContent).toContain('min 12');
    expect(inspector.textContent).toContain('max 40');
    expect(inspector.textContent).toContain('avg 26.00 (unit unverified)');
    expect(inspector.textContent).toContain('USER-PROVIDED (producer unverified)');
    fireEvent.change(screen.getByRole('combobox', { name: 'Inspect node' }), { target: { value: nodeId } });
    const nodeInspector = screen.getByRole('region', { name: 'Node metric inspector' });
    expect(nodeInspector.textContent).toContain('current 3');
    expect(nodeInspector.textContent).toContain('min 3');
    expect(nodeInspector.textContent).toContain('max 4');
    expect(nodeInspector.textContent).toContain('avg 3.50');
    expect(nodeInspector.textContent).toContain('trace-declared unit not available');
    store.doc = { ...store.doc, nodes: store.doc.nodes.map((n, i) => i === 0 ? { ...n, role: 'compute' } : n) };
    view.rerender(<SimPlayback store={store} />);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('earlier project snapshot'));
    expect(screen.getByText(/MOCK trace/)).toBeTruthy();
    expect(screen.queryByText(/external-phase/)).toBeNull();
  });
  it('refuses foreign object IDs rather than drawing them on project objects', async () => {
    const store = { doc: buildPreset('mesh-4x4') } as GraphStore;
    render(<SimPlayback store={store} />);
    const foreign = JSON.stringify({ cycle: 0, phase: 'bad-ref', nodeLoad: { 'R0,0': 10 }, edgeUtil: {}, stalls: {} });
    const file = new File([`${foreign}\n`], 'foreign-id.jsonl');
    Object.defineProperty(file, 'stream', { value: () => new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new TextEncoder().encode(`${foreign}\n`)); c.close(); } }) });
    fireEvent.change(screen.getByLabelText('Import trace JSONL'), { target: { files: [file] } });
    expect((await screen.findByRole('alert')).textContent).toContain('unknown node_id R0,0');
    expect(screen.getByText(/MOCK trace/)).toBeTruthy();
    expect(screen.queryByText(/bad-ref/)).toBeNull();
  });
  it('reports trace-index progress while streaming a larger input', async () => {
    const store = { doc: buildPreset('mesh-4x4') } as GraphStore;
    render(<SimPlayback store={store} />);
    const edgeId = store.doc.edges[0].id;
    const nodeId = store.doc.nodes[0].id;
    const records = Array.from({ length: 100 }, (_, cycle) => JSON.stringify({
      cycle, phase: 'stream', nodeLoad: { [nodeId]: cycle }, edgeUtil: { [edgeId]: cycle }, stalls: { [edgeId]: 0 },
    }));
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const contents = `${records.join('\n')}\n`;
    const file = new File([contents], 'large.jsonl');
    Object.defineProperty(file, 'stream', { value: () => new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(new TextEncoder().encode(contents));
        await gate;
        controller.close();
      },
    }) });
    fireEvent.change(screen.getByLabelText('Import trace JSONL'), { target: { files: [file] } });
    expect(await screen.findByText('Indexing trace: 100 records indexed…')).toBeTruthy();
    await act(async () => { release(); await gate; });
    expect(await screen.findByText(/USER-PROVIDED TRACE/)).toBeTruthy();
    expect(screen.getByLabelText('scrub')).toBeTruthy();
  });
  it('surfaces corrupt line number and keeps the valid trace prefix', async () => {
    const store = { doc: buildPreset('mesh-4x4') } as GraphStore;
    render(<SimPlayback store={store} />);
    const edgeId = store.doc.edges[0].id;
    const nodeId = store.doc.nodes[0].id;
    const record = JSON.stringify({ cycle: 0, phase: 'prefix', nodeLoad: { [nodeId]: 1 }, edgeUtil: { [edgeId]: 5 }, stalls: { [edgeId]: 0 } });
    const file = new File([`${record}\n{broken`], 'corrupt.jsonl');
    Object.defineProperty(file, 'stream', { value: () => new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new TextEncoder().encode(`${record}\n{broken`)); c.close(); } }) });
    fireEvent.change(screen.getByLabelText('Import trace JSONL'), { target: { files: [file] } });
    const error = await screen.findByRole('alert');
    expect(error.textContent).toContain('trace line 2:');
    expect(error.textContent).toContain('1 valid frames retained');
    expect(screen.getByText(/USER-PROVIDED TRACE/)).toBeTruthy();
    expect(screen.getByText(/prefix/)).toBeTruthy();
  });
  it('aligns generated trace phase labels to authored workload cycle intervals', () => {
    const doc = buildPreset('mesh-4x4');
    doc.workload = {
      modelFamily: 'custom', seqLen: 1, batch: 1, precision: 'fp16',
      phases: [
        { id: 'p0', kind: 'prefill', tokens: 1, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1, name: 'warmup', startCycle: 0, durationCycles: 100 },
        { id: 'p1', kind: 'decode', tokens: 1, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1, name: 'steady', startCycle: 100, durationCycles: 100 },
      ],
    };
    render(<SimPlayback store={{ doc } as GraphStore} />);
    expect(screen.getByText(/cycle 0/).textContent).toContain('warmup');
    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '1' } });
    expect(screen.getByText(/cycle 100/).textContent).toContain('steady');
    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '2' } });
    expect(screen.getByText(/cycle 200/).textContent).toContain('unphased');
  });
  it('plays at the selected speed, keeps selected metrics in sync, and pauses cleanly', () => {
    vi.useFakeTimers();
    const store = { doc: buildPreset('mesh-4x4') } as GraphStore;
    render(<SimPlayback store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Inspect congested edge e1' }));
    const inspector = screen.getByRole('region', { name: 'Edge metric inspector' });
    const before = inspector.textContent;
    fireEvent.change(screen.getByRole('combobox', { name: 'playback speed' }), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    act(() => { vi.advanceTimersByTime(124); });
    expect(screen.getByText(/cycle 0/)).toBeTruthy();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.getByText(/cycle 100/)).toBeTruthy();
    expect(inspector.textContent).not.toBe(before);
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    const pausedAt = screen.getByText(/cycle 100/);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(pausedAt).toBeTruthy();
    expect(screen.getByText(/cycle 100/)).toBeTruthy();
    vi.useRealTimers();
  });
});
