import { describe, expect, it } from 'vitest';
import { parseTraceLines, parseTraceStream, TraceParseError } from './traceParser';
import type { LoomProject } from './project';

const project: LoomProject = {
  schemaVersion: 1, presetHint: null,
  nodes: [
    { id: 'node-a', x: 0, y: 0, role: 'router', ports: 1 },
    { id: 'node-b', x: 1, y: 0, role: 'router', ports: 1 },
  ],
  edges: [{ id: 'edge-ab', src: 'node-a', dst: 'node-b', width: 1, pipelineStages: 1, vcClass: 0 }],
};
const frame = (cycle: number) => JSON.stringify({ cycle, phase: 'decode', nodeLoad: { 'node-a': 12 }, edgeUtil: { 'edge-ab': 42 }, stalls: { 'edge-ab': 2 } });

describe('strict JSONL trace parser', () => {
  it('indexes valid records by cycle, node, and edge', () => {
    const parsed = parseTraceLines([frame(0), '', frame(5)], project);
    expect(parsed.index.byCycle.get(5)).toBe(1);
    expect(parsed.index.byNode.get('node-a')).toEqual([0, 1]);
    expect(parsed.index.byEdge.get('edge-ab')).toEqual([0, 1]);
    expect(parsed.index.byMetric.get('edgeUtil')).toEqual([0, 1]);
    expect(parsed.index.byMetric.get('stalls')).toEqual([0, 1]);
    expect(parsed.frames[1].phase).toBe('decode');
  });
  it('rejects empty traces rather than rendering an empty completed artifact', () => {
    expect(() => parseTraceLines([], project)).toThrow(/line 1: trace contains no records/);
  });
  it('reports exact malformed source line', () => {
    expect(() => parseTraceLines([frame(0), '{bad'], project)).toThrowError(TraceParseError);
    try { parseTraceLines([frame(0), '{bad'], project); } catch (e) { expect((e as Error).message).toMatch(/^trace line 2:/); }
  });
  it('rejects non-monotonic cycles and unknown stable IDs', () => {
    expect(() => parseTraceLines([frame(4), frame(4)], project)).toThrow(/line 2: cycle 4/);
    const unknown = JSON.stringify({ cycle: 1, phase: 'decode', nodeLoad: { 'R0,0': 1 }, edgeUtil: {}, stalls: {} });
    expect(() => parseTraceLines([unknown], project)).toThrow(/unknown node_id R0,0/);
    const warned = parseTraceLines([unknown], project, { unknownReferences: 'warn' });
    expect(warned.warnings).toHaveLength(1);
    expect(warned.frames[0].nodeLoad).not.toHaveProperty('R0,0');
  });
  it('indexes a long trace without losing per-object frame references', () => {
    const records = Array.from({ length: 4096 }, (_, cycle) => frame(cycle));
    const parsed = parseTraceLines(records, project);
    expect(parsed.frames).toHaveLength(4096);
    expect(parsed.index.byNode.get('node-a')).toHaveLength(4096);
    const edgeFrames = parsed.index.byEdge.get('edge-ab') ?? [];
    expect(edgeFrames[edgeFrames.length - 1]).toBe(4095);
  });
  it('streams 10k records, reports progress, and pinpoints a corrupt final line', async () => {
    const lineCount = 10_000;
    const records = Array.from({ length: lineCount }, (_, cycle) => frame(cycle));
    records.push('{bad');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < records.length; i += 128) {
          controller.enqueue(new TextEncoder().encode(`${records.slice(i, i + 128).join('\n')}\n`));
        }
        controller.close();
      },
    });
    let validFrames = 0;
    let latestProgress = 0;
    await expect(parseTraceStream(stream, project, {
      onFrame: () => { validFrames += 1; },
      onProgress: progress => { latestProgress = progress.recordsIndexed; },
    })).rejects.toThrow(`trace line ${lineCount + 1}:`);
    expect(validFrames).toBe(lineCount);
    expect(latestProgress).toBe(lineCount);
  });
  it('rejects invalid metric values', () => {
    const invalid = JSON.stringify({ cycle: 1, phase: 'decode', nodeLoad: { 'node-a': -1 }, edgeUtil: {}, stalls: {} });
    expect(() => parseTraceLines([invalid], project)).toThrow(/finite non-negative number/);
  });
  it('parses split byte chunks incrementally and reports original line on stream errors', async () => {
    const bytes = new TextEncoder().encode(`${frame(0)}\n${frame(7)}\n`);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(bytes.slice(0, 19)); controller.enqueue(bytes.slice(19)); controller.close(); },
    });
    const progress: number[] = [];
    const parsed = await parseTraceStream(stream, project, { onProgress: p => progress.push(p.recordsIndexed) });
    expect(progress).toEqual([1, 2]);
    expect(parsed.index.byCycle.get(7)).toBe(1);

    const validPrefix: number[] = [];
    const broken = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode(`${frame(0)}\n{bad`)); controller.close(); },
    });
    await expect(parseTraceStream(broken, project, { onFrame: (_item, index) => validPrefix.push(index) })).rejects.toThrow('trace line 2:');
    expect(validPrefix).toEqual([0]);
  });
});
