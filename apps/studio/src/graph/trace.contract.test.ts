import { describe, expect, it } from 'vitest';
import { buildMockTrace } from './trace';
import type { LoomProject } from './project';

const project: LoomProject = {
  schemaVersion: 1, presetHint: null,
  nodes: [{ id: 'node-x', x: 0, y: 0, role: 'router', ports: 1 }],
  edges: [],
};

describe('mock trace truth boundary', () => {
  it('retains MOCK origin and stable project IDs; does not imply measured results', () => {
    const trace = buildMockTrace(project, ['warmup']);
    expect(trace.origin).toBe('MOCK');
    expect(trace.frames.length).toBe(trace.cyclesSampled);
    expect(trace.frames.every(frame => Object.keys(frame.nodeLoad).every(id => id === 'node-x'))).toBe(true);
    expect(trace.frames.every(frame => Object.keys(frame.edgeUtil).length === 0 && Object.keys(frame.stalls).length === 0)).toBe(true);
    expect(new Set(trace.frames.map(frame => frame.cycle)).size).toBe(trace.frames.length);
    expect(trace.frames.every(frame => frame.phase === 'warmup')).toBe(true);
  });
});
