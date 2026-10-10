/** Trace schema keyed on node_id/edge_id (P6a) + mock-trace fallback.
 * Mock traces are labelled MOCK and must never be presented as measured. */
import type { LoomProject } from './project';

export interface TraceFrame {
  cycle: number;
  phase: string;
  nodeLoad: Record<string, number>;
  edgeUtil: Record<string, number>;
  stalls: Record<string, number>;
}

export interface MockTrace {
  origin: 'MOCK';
  frames: TraceFrame[];
  cyclesSampled: number;
}

export function buildMockTrace(project: LoomProject, phases: string[] = ['prefill', 'decode']): MockTrace {
  const frames: TraceFrame[] = [];
  const STEPS = 24;
  for (let s = 0; s < STEPS; s++) {
    const nodeLoad: Record<string, number> = {};
    const edgeUtil: Record<string, number> = {};
    const stalls: Record<string, number> = {};
    for (const n of project.nodes) {
      nodeLoad[n.id] = Math.round((50 + 40 * Math.sin(s / 3 + n.x / 200) + 10 * Math.cos(s / 2 + n.y / 200)) * 10) / 10;
    }
    for (const e of project.edges) {
      const hot = (s % 6 === 0 && e.vcClass === 0) ? 35 : 0;
      edgeUtil[e.id] = Math.round((30 + 25 * Math.sin(s / 4 + e.id.length) + hot) * 10) / 10;
      stalls[e.id] = Math.max(0, Math.round(edgeUtil[e.id] - 55));
    }
    frames.push({ cycle: s * 100, phase: phases[Math.min(phases.length - 1, Math.floor((s / STEPS) * phases.length))], nodeLoad, edgeUtil, stalls });
  }
  return { origin: 'MOCK', frames, cyclesSampled: STEPS };
}

export function topCongested(trace: MockTrace, frameIdx: number, n = 5): { edge: string; util: number }[] {
  const f = trace.frames[Math.min(frameIdx, trace.frames.length - 1)];
  if (!f) return [];
  return Object.entries(f.edgeUtil).sort((a, b) => b[1] - a[1]).slice(0, n).map(([edge, util]) => ({ edge, util }));
}
